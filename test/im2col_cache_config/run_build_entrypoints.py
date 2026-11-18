#!/usr/bin/env python3
"""Elaborate production simulator commands with a nondefault im2col cache."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import elaboration


class CapturedCommand(Exception):
    def __init__(self, command, cwd, environment):
        super().__init__("Verilator command captured")
        self.command = [str(item) for item in command]
        self.cwd = str(cwd)
        self.environment = environment


def load_entrypoint(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_soc(folder, verilator, picorv32, capacity, environment):
    entrypoint = ROOT / "test/model_benchmark/build_sim.py"
    module = load_entrypoint(entrypoint, "im2col_soc_builder")
    arguments = [str(entrypoint), "--build-dir", str(folder / "build"), "--build-only",
                 "--verilator", verilator, "--picorv32", str(picorv32),
                 "--bus-width", "64", "--shared-bank-bytes", "2048",
                 "--shared-bank-count", "7", "--ps-pool-bytes", "12288",
                 "--im2col-cache-bytes", str(capacity)]

    def capture(command, log, *, cwd=ROOT, timeout=1800):
        raise CapturedCommand(command, cwd, dict(os.environ))

    with patch.dict(os.environ, environment, clear=True), patch.object(sys, "argv", arguments), \
            patch.object(module, "command", capture):
        try:
            module.main()
        except CapturedCommand as captured:
            files, _ = module.filelist_sources(ROOT / "veri/flist/dut_axi_soc.f",
                                                ROOT / "veri/sim", picorv32)
            return arguments, captured, files
    raise RuntimeError("SoC entrypoint did not produce a Verilator command")


def capture_backend(folder, verilator, capacity, environment):
    entrypoint = ROOT / "veri/python_model/build_backend.py"
    module = load_entrypoint(entrypoint, "im2col_python_builder")
    arguments = [str(entrypoint), "--config", str(ROOT / "config/npu.mk"),
                 "--output-root", str(folder / "build"), "--verilator", verilator,
                 "--bus-width", "64", "--shared-bank-bytes", "2048", "--shared-bank-count", "7",
                 "--size", "16", "--cache", "4", "--ps", "16", "--ps-compress",
                 "--ps-pool-bytes", "12288", "--im2col-cache-bytes", str(capacity)]

    def capture(command, **kwargs):
        raise CapturedCommand(command, kwargs.get("cwd", Path.cwd()),
                              kwargs.get("env", dict(os.environ)))

    with patch.dict(os.environ, environment, clear=True), patch.object(sys, "argv", arguments), \
            patch.object(module.subprocess, "run", capture):
        try:
            module.main()
        except CapturedCommand as captured:
            return arguments, captured, []
    raise RuntimeError("Python backend entrypoint did not produce a Verilator command")


def inspect_command(name, folder, arguments, captured, extra_files, capacity):
    folder.mkdir(parents=True, exist_ok=True)
    tree_path = folder / "elaborated.tree.json"
    # Keep the generated RTL sources, defines, parameters and include paths.
    # JSON elaboration replaces the C++ code generation and executable phases.
    command = [item for item in captured.command
               if item not in ("--cc", "--exe") and not item.endswith(".cpp")]
    command += ["--json-only", "--json-only-output", str(tree_path)]
    files = {Path(item).resolve() for item in captured.command
             if Path(item).suffix in (".sv", ".v", ".cpp") and Path(item).is_file()}
    files.update(extra_files)
    files.update((ROOT / "rtl/npu").rglob("*.svh"))
    files.update((Path(arguments[0]), Path(__file__).resolve(), ROOT / "config/npu.mk",
                  ROOT / "scripts/capacity/config.py", ROOT / "scripts/capacity/elaboration.py"))
    hashes = {str(path): elaboration.digest(path) for path in sorted(files)}
    (folder / "commands.json").write_text(json.dumps({
        "entrypoint_arguments": arguments, "generated_command": captured.command,
        "elaboration_command": command, "cwd": captured.cwd,
    }, indent=2) + "\n")
    started = time.monotonic()
    with (folder / "elaboration.log").open("w") as log:
        log.write("COMMAND: " + shlex.join(command) + "\n")
        log.flush()
        subprocess.run(command, cwd=captured.cwd, env=captured.environment,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    tree = json.loads(tree_path.read_text())
    state = elaboration.inventory(tree)
    cache_keys = ("IM2COL_CACHE_BYTES", "CONV_CACHE_SETS", "CONV_CACHE_WAYS", "CONV_LINE_BYTES")
    parameters = {"npu_top": elaboration.constant_parameters(tree, "npu_top", cache_keys),
                  "conv_im2col_frontend": elaboration.constant_parameters(
                      tree, "conv_im2col_frontend", ("CACHE_SETS", "CACHE_WAYS", "LINE_BYTES", "BUS_WIDTH")),
                  "conv_sdp_ram": elaboration.constant_parameters(
                      tree, "conv_sdp_ram", ("DEPTH", "WRITE_WIDTH"))}
    expected_top = dict(IM2COL_CACHE_BYTES=capacity, CONV_CACHE_SETS=capacity // 32,
                        CONV_CACHE_WAYS=2, CONV_LINE_BYTES=16)
    checks = {
        "entrypoint_capacity_argument": arguments[arguments.index("--im2col-cache-bytes") + 1] == str(capacity),
        "npu_top_parameters": parameters["npu_top"] == expected_top,
        "frontend_parameters": parameters["conv_im2col_frontend"] ==
            dict(CACHE_SETS=capacity // 32, CACHE_WAYS=2, LINE_BYTES=16, BUS_WIDTH=64),
        "ram_parameters": parameters["conv_sdp_ram"] == dict(DEPTH=capacity // 4, WRITE_WIDTH=64),
        "data_array_bits": state["buffer_arrays_bits"].get("conv_data_cache") == capacity * 8,
        "metadata_array_bits": state["buffer_arrays_bits"].get("conv_cache_metadata") == (capacity // 16) * 322,
        "single_input_cache": state["module_instances"].get("conv_sdp_ram") == 1,
    }
    if name == "soc":
        parameters["soc_top"] = elaboration.constant_parameters(tree, "soc_top", ("IM2COL_CACHE_BYTES",))
        parameters["npu_axil_top"] = elaboration.constant_parameters(tree, "npu_axil_top", cache_keys)
        parameters["npu_axil_reg_if"] = elaboration.constant_parameters(tree, "npu_axil_reg_if", ("CONV_CACHE_BYTES",))
        checks.update(
            generated_capacity_define=f"-DSOC_NETWORK_IM2COL_CACHE_BYTES={capacity}" in captured.command,
            soc_top_parameter=parameters["soc_top"] == dict(IM2COL_CACHE_BYTES=capacity),
            npu_axil_top_parameters=parameters["npu_axil_top"] == expected_top,
            capability_bytes=parameters["npu_axil_reg_if"] == dict(CONV_CACHE_BYTES=capacity))
    else:
        checks["generated_capacity_define"] = f"-DTB_IM2COL_CACHE_BYTES={capacity}" in captured.command
    checks["sources_unchanged"] = all(elaboration.digest(path) == value for path, value in hashes.items())
    report = {
        "name": name, "passed": all(checks.values()), "checks": checks,
        "cache_bytes": capacity, "parameters": parameters,
        "data_array_bits": state["buffer_arrays_bits"].get("conv_data_cache"),
        "metadata_array_bits": state["buffer_arrays_bits"].get("conv_cache_metadata"),
        "cache_declarations": [row for row in state["sequential_declarations"]
                               if row["buffer_category"] in ("conv_data_cache", "conv_cache_metadata")],
        "source_sha256": hashes, "elapsed_seconds": time.monotonic() - started,
        "entrypoint_arguments": arguments, "generated_command": captured.command,
        "elaboration_command": command, "cwd": captured.cwd,
        "verilator": subprocess.check_output([captured.command[0], "--version"], text=True).strip(),
    }
    (folder / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    tree_path.unlink()
    print(json.dumps({key: report[key] for key in
                      ("name", "passed", "cache_bytes", "data_array_bits", "metadata_array_bits")}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/im2col_config/build_entrypoints")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--picorv32", type=Path, default=Path(os.environ.get(
        "PICORV32_ROOT", ROOT / "picorv32")))
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    verilator = shutil.which(args.verilator) or args.verilator
    environment = {key: value for key, value in os.environ.items() if key not in
                   ("NPU_CONFIG", "NPU_AXI_DATA_WIDTH", "IM2COL_CACHE_BYTES", "SHARED_BANK_BYTES", "SHARED_BANK_COUNT")}
    environment["NPU_CONFIG"] = str(ROOT / "config/npu.mk")
    capacity = 8192
    profiles = []
    arguments, command, files = capture_soc(output / "soc", verilator, args.picorv32.resolve(), capacity, environment)
    profiles.append(inspect_command("soc", output / "soc", arguments, command, files, capacity))
    arguments, command, files = capture_backend(output / "python_backend", verilator, capacity, environment)
    profiles.append(inspect_command("python_backend", output / "python_backend", arguments, command, files, capacity))
    sources_unchanged = all(elaboration.digest(path) == value for profile in profiles
                            for path, value in profile["source_sha256"].items())
    summary = dict(passed=sources_unchanged and all(profile["passed"] for profile in profiles),
                   scope="Actual production CLI command generation and Verilator JSON elaboration",
                   cache_bytes=capacity, sources_unchanged=sources_unchanged, profiles=profiles)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(dict(passed=summary["passed"], profiles=len(profiles),
                          report=str(output / "summary.json"))), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
