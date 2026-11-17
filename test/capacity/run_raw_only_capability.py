#!/usr/bin/env python3
"""Check hardware RAW_ONLY reporting and both public software interfaces."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import elaboration
from scripts.capacity.config import axi_data_width


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_logged(command, path, timeout=180):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as log:
        log.write(shlex.join(command) + "\n")
        log.flush()
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {path}\n" + path.read_text()[-8000:])


def result_json(text):
    records = [json.loads(line) for line in text.splitlines() if line.startswith('{"passed":')]
    if len(records) != 1 or not records[0].get("passed"):
        raise ValueError("Expected one successful JSON test result")
    return records[0]


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def parameter(module, name):
    declarations = [node for node in walk(module)
                    if node.get("type") == "VAR" and node.get("name") == name and node.get("isParam")]
    if len(declarations) != 1:
        raise ValueError(f"Expected one elaborated {name} parameter")
    values = declarations[0].get("valuep", [])
    if len(values) != 1 or values[0].get("type") != "CONST":
        raise ValueError(f"Elaborated {name} is not a constant")
    match = re.fullmatch(r"\d+'s?([hodb])([0-9a-fA-F]+)", values[0]["name"])
    if match is None:
        raise ValueError("Unsupported Verilator constant: " + values[0]["name"])
    return int(match[2], {"h": 16, "o": 8, "d": 10, "b": 2}[match[1]])


def module(tree, original):
    found = [item for item in tree["modulesp"] if item.get("origName", item.get("name")) == original]
    if len(found) != 1:
        raise ValueError(f"Expected one elaborated {original} module")
    return found[0]


def software_checks(args, out):
    reports = []
    source = ROOT / "test/capacity/test_raw_only_capability.c"
    for api in ("root", "nmsis"):
        directory = out / "software" / api
        directory.mkdir(parents=True, exist_ok=True)
        include = ROOT / ("drivers" if api == "root" else "drivers/tflm/NMSIS/NN/Include")
        driver = ROOT / ("drivers/dsa_accel.c" if api == "root" else
                         "drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/dsa_accel.c")
        binary = directory / "test_raw_only"
        flags = [args.cc, "-std=c11", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all", "-DDSA_MMIO_CUSTOM=1",
                 "-DDSA_PS_COMPRESS=1", "-DDSA_PS_FORCE_RAW=0", "-DDSA_PS_ADAPTIVE_W=1",
                 "-DDSA_DEFAULT_DATAFLOW=2", "-DDSA_ENABLE_IS_MODE=1", "-DDSA_WEIGHT_WIDTH=16",
                 "-DDSA_TILE_SIZE=16", "-DDSA_IA_CACHE_BLOCKS=4", "-DDSA_PS_FRAME_COUNT=16",
                 "-DDSA_PS_POOL_BYTES=12288", "-I", str(include), "-I", str(ROOT / "drivers")]
        if api == "nmsis":
            flags.append("-DPOINTER_API=1")
        dependencies = subprocess.check_output([*flags, "-MM", str(source), str(driver)], cwd=ROOT, text=True)
        paths = {Path(__file__).resolve()}
        for line in dependencies.replace("\\\n", " ").splitlines():
            paths.update(Path(name).resolve() for name in line.split(":", 1)[1].split())
        before = {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}
        command = [*flags, str(source), str(driver), "-o", str(binary)]
        run_logged(command, directory / "build.log")
        run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=60)
        (directory / "run.log").write_text(run.stdout + run.stderr)
        if run.returncode:
            raise RuntimeError(f"Software capability check failed: {directory}\n{run.stdout}{run.stderr}")
        report = result_json(run.stdout)
        after = {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}
        if before != after:
            raise RuntimeError("Software capability sources changed during the test")
        report.update(api=api, undefined_behavior_sanitizer=True, compile_command=command,
                      run_command=[str(binary)], source_sha256=before, sources_unchanged=True,
                      binary_sha256=digest(binary))
        (directory / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        reports.append(report)
    return reports


def hardware_checks(args, out):
    profiles = (("adaptive", [], 0), ("gemmora_raw", ["-DGEMMORA_PS_FORCE_RAW=1"], 1),
                ("legacy_raw", ["-DPS_FORCE_RAW=1"], 1))
    sources = elaboration.source_files()
    dependencies = set(sources)
    dependencies.update((ROOT / "rtl/npu").rglob("*.svh"))
    dependencies.update((Path(__file__).resolve(), ROOT / "scripts/capacity/elaboration.py",
                         ROOT / "scripts/capacity/model.py", ROOT / "scripts/capacity/config.py",
                         ROOT / "veri/flist/dut_axil.f", ROOT / "test/capacity/tb_raw_only_caps.sv"))
    before = {str(p.relative_to(ROOT)): digest(p) for p in sorted(dependencies)}
    reports = []
    for name, defines, raw in profiles:
        directory = out / "hardware" / name
        directory.mkdir(parents=True, exist_ok=True)
        tree_path = directory / "elaborated.tree.json"
        command = [args.verilator, "--json-only", "--assert", "-DSYNTHESIS", "-DASIC_SYNTHESIS",
                   "-Wno-fatal", "--top-module", "npu_axil_top", "--json-only-output", str(tree_path),
                   "--Mdir", str(directory / "obj"), "-GDATA_WIDTH=16", "-GWEIGHT_WIDTH=16",
                   f"-GBUS_WIDTH={args.bus_width}", "-GSHARED_BANK_BYTES=2048", "-GSHARED_BANK_COUNT=7",
                   "-GSIZE=16", "-GIA_CACHE_BLOCKS=4", "-GPS_FRAME_COUNT=16", "-GAXI_READ_OUTSTANDING=4",
                   "-GENABLE_VECTOR_ENGINE=1", "-GVECTOR_PE_COUNT=8", "-DGEMPACT_PS_COMPRESS=1",
                   "-DGEMMORA_PS_POOL_BYTES=12288", "-I" + str(ROOT / "rtl/npu/gempact"),
                   *defines, *map(str, sources)]
        run_logged(command, directory / "elaboration.log")
        tree = json.loads(tree_path.read_text())
        top = module(tree, "npu_axil_top")
        registers = module(tree, "npu_axil_reg_if")
        core = module(tree, "npu_top")
        caps = parameter(top, "PS_CAPS")
        register_caps = parameter(registers, "PS_CAPS")
        pool = parameter(registers, "PS_POOL_BYTES")
        ia = parameter(registers, "IA_CACHE_BYTES")
        shared_total = parameter(registers, "SHARED_TOTAL_BYTES")
        shared_bank = parameter(registers, "SHARED_BANK_BYTES")
        shared_mask = parameter(registers, "SHARED_IA_BANK_MASK")
        directory_rows = parameter(registers, "PS_DIRECTORY_ROWS")
        required_raw = parameter(core, "PS_REQUIRE_RAW_CAPACITY")
        if (caps != (0x01100037 | (raw << 3)) or register_caps != caps or
                parameter(top, "PS_RAW_ONLY") != raw or required_raw != raw or
                parameter(top, "BUS_WIDTH") != args.bus_width or
                parameter(core, "BUS_WIDTH") != args.bus_width or
                parameter(registers, "AXI_DATA_BITS") != args.bus_width or
                parameter(registers, "DMA_MAX_BYTES") != 256 * (args.bus_width // 8) or
                pool != 12288 or ia != 2048 or shared_total != 14336 or
                shared_bank != 2048 or shared_mask != 0x16 or directory_rows != 1024):
            raise ValueError(f"Hardware capability mismatch: {name}")
        inventory = elaboration.inventory(tree)
        counts = inventory["module_instances"]
        if counts.get("compute_core") != 1 or counts.get("ws_systolic_array") != 1:
            raise ValueError("Expected one shared compute array")
        report = dict(passed=True, profile=name, bus_width=args.bus_width,
                      ps_caps=caps, ps_caps_hex=f"0x{caps:08x}",
                      register_ps_caps=register_caps, ps_require_raw_capacity=required_raw,
                      pool_bytes=pool, ia_bytes=ia, command=command,
                      shared_total_bytes=shared_total, shared_bank_bytes=shared_bank,
                      shared_ia_bank_mask=shared_mask, ps_directory_rows=directory_rows,
                      elaborated_tree_sha256=digest(tree_path), module_instances=counts,
                      total_sequential_bits=inventory["total_bits"])
        (directory / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        reports.append(report)
        del tree, inventory
        if not args.keep_tree:
            tree_path.unlink()

    directory = out / "hardware" / "register_reads"
    directory.mkdir(parents=True, exist_ok=True)
    command = [args.verilator, "--cc", "--exe", "--main", "--timing", "--assert", "-Wno-fatal",
               "-Wno-PINMISSING", "--top-module", "tb_raw_only_caps", "--Mdir", str(directory / "obj"),
               "--output-groups", "0", "-CFLAGS",
               "-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096",
               f'-GCAP_NORMAL={reports[0]["ps_caps"]}', f'-GCAP_GEMMORA_RAW={reports[1]["ps_caps"]}',
               f'-GCAP_LEGACY_RAW={reports[2]["ps_caps"]}',
               f'-GAXI_DATA_BITS={args.bus_width}',
               str(ROOT / "rtl/npu/conv/00_conv_im2col_pkg.sv"),
               str(ROOT / "rtl/axi_top/npu_axil_reg_if.sv"),
               str(ROOT / "test/capacity/tb_raw_only_caps.sv")]
    run_logged(command, directory / "verilator.log")
    make_command = ["make", "-C", str(directory / "obj"), "-f", "Vtb_raw_only_caps.mk", "-j", "1",
                    "OPT_FAST=-O0", "OPT_SLOW=-O0", "OPT_GLOBAL=-O0", "VK_PCH_I_FAST=",
                    "VK_PCH_I_SLOW=", "CFG_CXXFLAGS_PCH=-E"]
    run_logged(make_command, directory / "build.log")
    binary = directory / "obj/Vtb_raw_only_caps"
    run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    (directory / "run.log").write_text(run.stdout + run.stderr)
    if run.returncode:
        raise RuntimeError(f"Capability register reads failed: {run.stdout}{run.stderr}")
    read_report = result_json(run.stdout)
    after = {str(p.relative_to(ROOT)): digest(p) for p in sorted(dependencies)}
    if before != after:
        raise RuntimeError("Hardware capability sources changed during the test")
    read_report.update(verilator_command=command, make_command=make_command,
                       run_command=[str(binary)], binary_sha256=digest(binary),
                       capability_values_from_elaboration=[row["ps_caps"] for row in reports])
    return dict(passed=True, profiles=reports, register_reads=read_report,
                source_sha256=before, sources_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/capacity/raw_only_capability")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--bus-width", type=int, choices=(32, 64))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--keep-tree", action="store_true")
    args = parser.parse_args()
    args.cc = shutil.which(args.cc) or args.cc
    args.verilator = shutil.which(args.verilator) or args.verilator
    args.bus_width = axi_data_width(args.bus_width, args.config)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    software = software_checks(args, out)
    hardware = hardware_checks(args, out)
    report = dict(passed=True, bus_width=args.bus_width, software=software, hardware=hardware,
                  configurations=sum(row["configurations"] for row in software),
                  submissions=sum(row["submissions"] for row in software),
                  plan_comparisons=sum(row["plan_comparisons"] for row in software),
                  elapsed_seconds=time.monotonic() - start,
                  native_compiler=subprocess.check_output([args.cc, "--version"], text=True).splitlines()[0],
                  verilator=subprocess.check_output([args.verilator, "--version"], text=True).strip())
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: report[name] for name in
                      ("passed", "configurations", "submissions", "plan_comparisons", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
