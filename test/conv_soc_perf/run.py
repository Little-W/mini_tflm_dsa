#!/usr/bin/env python3
"""Run real RV32IM firmware on the production CPU + NPU + AXI RAM SoC.

No host C function drives the accelerator. The host only builds firmware,
loads immutable memory images, launches a cold SoC simulation, and checks the
CPU-written result plus observer counters. Timing values are RTL/CSR cycles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NN = ROOT / "drivers/tflm/NMSIS/NN"
SOC_C = ROOT / "veri/soc_csrc"
sys.path.insert(0, str(ROOT / "test/conv_models"))
from generate_vectors import generate_layers, DEFAULT_SEED
LAYERS = ["mnist_cnn_sg0_op0", "mnist_cnn_sg0_op2", "justure_detect_sg0_op7",
          "justure_detect_sg0_op16", "mobilenet_v2_sg0_op52"]
REGIONS = {"input": 0x10000, "weight": 0x20000, "params": 0x30000,
           "output": 0x40000, "scratch": 0x60000}
GOLDEN_BASE = 0x80000
CONFIG_BASE = 0xA0000
RAM_WORDS = 524288
RESULT_FIELDS = ["magic", "version", "complete", "mode", "compiled_dataflow", "case_id",
                 "nmsis_status", "error", "start_cycle", "end_cycle", "total_call_cycles",
                 "npu_cycles_last", "conv_caps", "input_bytes", "filter_bytes", "output_bytes",
                 "scratch_bytes", "compared_outputs", "mismatches", "first_mismatch",
                 "first_expected", "first_actual", "output_fnv1a", "guard_errors"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(paths) -> dict[str, str]:
    return {str(path.resolve().relative_to(ROOT)): digest(path)
            for path in sorted(set(paths))}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def command(args, log: Path, *, cwd=ROOT, timeout=1800) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    args = [str(v) for v in args]
    with log.open("w") as stream:
        stream.write("COMMAND: " + shlex.join(args) + "\n")
        stream.flush()
        try:
            return subprocess.run(args, cwd=cwd, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            stream.write("\nHOST_RUNNER_TIMEOUT (not a cycle measurement)\n")
            return 124


def filelist_sources(path: Path, cwd: Path) -> list[Path]:
    result = [path]
    tokens = shlex.split(path.read_text(), comments=True)
    pos = 0
    while pos < len(tokens):
        token = tokens[pos]
        if token == "-f":
            pos += 1
            result.extend(filelist_sources((cwd / tokens[pos]).resolve(), cwd))
        elif not token.startswith(("+", "-")):
            result.append((cwd / token).resolve())
        pos += 1
    return result


def verify_sources(manifest: dict) -> None:
    for name, expected in manifest["source_sha256"].items():
        if digest(ROOT / name) != expected:
            raise RuntimeError(f"source changed since build: {name}; rebuild into a new evidence directory")


def build_sim(out: Path, verilator: str, jobs: int, *, skip=False, icache=0, reuse=None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "build.json"
    binary = out / "obj/Vtb_conv_soc_perf"
    cwd = ROOT / "veri/sim"
    filelist = ROOT / "veri/flist/dut_axi_soc.f"
    sources = filelist_sources(filelist, cwd) + [HERE / "tb_conv_soc_perf.sv"]
    # Include macros used by the production GEMPACT files in the source audit.
    sources += list((ROOT / "rtl/npu/gempact").glob("*.svh"))
    before = source_hashes(sources)
    if skip or reuse is not None:
        previous_root = Path(reuse).resolve() if reuse is not None else out
        previous_manifest = previous_root / 'build.json'
        manifest = json.loads(previous_manifest.read_text())
        previous_binary = previous_root / 'obj/Vtb_conv_soc_perf'
        expected = {'cpu_icache': icache, 'size': 16, 'ram_words': RAM_WORDS,
                    'ia_cache_blocks': 4, 'ps_frame_count': 16,
                    'conv_cache_sets': 32, 'conv_cache_ways': 2,
                    'conv_line_bytes': 16, 'conv_cache_policy': 2}
        if (manifest.get('returncode') != 0 or not manifest.get('sources_unchanged_during_build') or
                manifest['source_sha256'] != before or
                any(manifest.get(key) != value for key, value in expected.items()) or
                digest(previous_binary) != manifest['binary_sha256']):
            raise RuntimeError('simulation source inventory, parameters or binary differs; rebuild')
        if reuse is not None:
            binary.parent.mkdir(parents=True, exist_ok=True)
            if previous_binary.resolve() != binary.resolve():
                shutil.copy2(previous_binary, binary)
            manifest = {**manifest, 'build_mode': 'reuse_exact_rtl_source_hashes',
                        'reused_from': str(previous_root),
                        'original_manifest_sha256': digest(previous_manifest),
                        'current_source_files_matched': len(before),
                        'current_source_match': True}
            write_json(manifest_path, manifest)
            (out/'reuse.log').write_text('Reused existing pure RTL simulator after exact full source inventory, profile and binary hash checks.\n')
        return binary
    args = [verilator, "--binary", "--timing", "--assert", "-sv", "--top-module",
            "tb_conv_soc_perf", "-Wno-fatal", "--Mdir", out / "obj", "-j", jobs,
            "-CFLAGS", "-std=c++20 -O2", "-MAKEFLAGS", "OPT_FAST=-O2 OPT_SLOW=-O0",
            f"-DSOC_PERF_ICACHE={icache}", "-f", filelist, HERE / "tb_conv_soc_perf.sv"]
    rc = command(args, out / "compile.log", cwd=cwd)
    after = source_hashes(sources)
    log = (out / "compile.log").read_text()
    manifest = {
        "build_mode": "fresh_verilator_build",
        "returncode": rc, "command": [str(v) for v in args],
        "verilator": subprocess.check_output([verilator, "--version"], text=True).strip(),
        "source_sha256": before, "sources_unchanged_during_build": before == after,
        "cpu": "production picorv32", "cpu_isa": "RV32IM, no compressed ISA, 32-bit rdcycle",
        "cpu_icache": icache, "ram_words": RAM_WORDS, "size": 16,
        "ia_cache_blocks": 4, "ps_frame_count": 16,
        "conv_cache_sets": 32, "conv_cache_ways": 2, "conv_line_bytes": 16, "conv_cache_policy": 2,
        "axi_read_outstanding": 4, "axi_write_outstanding": 4,
        "cpu_axi_read_timing_buffer": 1, "cpu_axi_write_timing_buffer": 1,
        "npu_axi_timing_buffer": 1, "bypass_ram_pingpong": 1, "ram_write_timing_buffer": 1,
        "warnings": {w: log.count("%Warning-" + w + ":")
                     for w in sorted(set(re.findall(r"%Warning-([^:]+):", log)))},
        "picorv32_commit": subprocess.check_output(["git", "-C", ROOT / "picorv32", "rev-parse", "HEAD"], text=True).strip(),
    }
    if rc == 0 and before == after:
        manifest["binary_sha256"] = digest(binary)
    write_json(manifest_path, manifest)
    if rc or before != after:
        raise RuntimeError(f"SoC build failed/changed sources: {out / 'compile.log'}\n{log[-5000:]}")
    return binary


def nn_sources() -> list[Path]:
    files = [NN / "Source/ExtraAccFunctions" / f"{name}.c" for name in
             ["dsa_accel", "riscv_conv_acc", "riscv_nn_mat_mult_acc"]]
    files += [NN / "Source/ConvolutionFunctions" / f"{name}.c" for name in [
        "riscv_convolve_s8", "riscv_convolve_wrapper_s8", "riscv_convolve_1x1_s8",
        "riscv_convolve_1x1_s8_fast", "riscv_convolve_1_x_n_s8",
        "riscv_convolve_get_buffer_sizes_s8", "riscv_nn_mat_mult_kernel_s8_s16",
        "riscv_nn_mat_mult_kernel_row_offset_s8_s16"]]
    files += [NN / "Source/NNSupportFunctions" / f"{name}.c" for name in
              ["riscv_nn_mat_mult_nt_t_s8", "riscv_q7_to_q15_with_offset"]]
    return files


def compiler_sibling(gcc: str, name: str) -> str:
    resolved = shutil.which(gcc) or gcc
    if not resolved.endswith("gcc"):
        raise ValueError("--gcc must name the GCC executable ending in gcc")
    return resolved[:-3] + name


def build_firmware(out: Path, gcc: str, *, dataflow=0, smoke=False, skip=False,
                   newlib_include: Path | None = None, runtime_lib: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "firmware.json"
    if skip:
        manifest = json.loads(manifest_path.read_text())
        verify_sources(manifest)
        if manifest["compiled_dataflow"] != dataflow or manifest["smoke"] != smoke:
            raise RuntimeError("firmware profile mismatch")
        if digest(out / "cpu.elf") != manifest["elf_sha256"]:
            raise RuntimeError("firmware ELF hash mismatch")
        return manifest
    if smoke:
        files = [SOC_C / "start.S", SOC_C / "soc_reg_directed_main.c",
                 SOC_C / "picosoc_bsp.c", SOC_C / "dsa_accel_mmio.c", ROOT / "drivers/dsa_accel.c"]
    else:
        files = [SOC_C / "start.S", HERE / "benchmark.c", HERE / "benchmark_baseline.c"] + nn_sources()
    dependencies = files + [SOC_C / "link.ld", HERE / "benchmark.h", HERE / "benchmark_baseline_e8.c"]
    dependencies += list((ROOT / "drivers").glob("*.h")) + list((NN / "Include").glob("*.h"))
    dependencies += list((NN.parent / "Core/Include").glob("*.h"))
    before = source_hashes(dependencies)
    args = [gcc, "-march=rv32im_zicsr", "-mabi=ilp32", "-std=c11", "-O3",
            "-ffreestanding", "-fno-builtin", "-fdata-sections", "-ffunction-sections",
            "-nostdlib", "-nostartfiles", "-DDSA_TILE_SIZE=16", "-DDSA_IA_CACHE_BLOCKS=4",
            "-DDSA_PS_FRAME_COUNT=16", f"-DDSA_NN_CONV_DATAFLOW_MODE={dataflow}",
            "-I", NN / "Include", "-I", NN.parent / "Core/Include",
            "-I", ROOT / "drivers", "-I", SOC_C, "-I", HERE,
            "-T", SOC_C / "link.ld", "-Wl,--build-id=none", "-Wl,--gc-sections",
            f"-Wl,--defsym=__ram_length={RAM_WORDS * 4}", f"-Wl,-Map={out / 'cpu.map'}",
            *files]
    if newlib_include is not None:
        args += ["-isystem", newlib_include]
    args += ["-Wl,--start-group"]
    if not smoke:
        args += [runtime_lib if runtime_lib is not None else "-lc"]
    args += ["-lgcc", "-Wl,--end-group", "-o", out / "cpu.elf"]
    rc = command(args, out / "compile.log", timeout=300)
    after = source_hashes(dependencies)
    manifest = {"returncode": rc, "command": [str(v) for v in args], "smoke": smoke,
                "source_sha256": before, "sources_unchanged_during_build": before == after,
                "compiled_dataflow": dataflow, "ram_bytes": RAM_WORDS * 4,
                "newlib_include": str(newlib_include) if newlib_include is not None else None,
                "runtime_lib": str(runtime_lib) if runtime_lib is not None else (None if smoke else "compiler default -lc"),
                "runtime_lib_sha256": digest(runtime_lib) if runtime_lib is not None else None,
                "compiler": subprocess.check_output([gcc, "--version"], text=True).splitlines()[0],
                "compiler_sha256": digest(Path(shutil.which(gcc) or gcc))}
    write_json(manifest_path, manifest)
    if rc or before != after:
        raise RuntimeError(f"firmware build failed/changed sources: {out / 'compile.log'}\n" +
                           (out / "compile.log").read_text()[-7000:])
    nm_output = subprocess.check_output([compiler_sibling(gcc, "nm"), "-n", out / "cpu.elf"], text=True)
    (out / "cpu.nm").write_text(nm_output)
    symbols = {line.split()[2]: int(line.split()[0], 16) for line in nm_output.splitlines()
               if re.match(r"^[0-9a-fA-F]+ [A-Za-z] \S+$", line)}
    if symbols["_end"] >= REGIONS["input"] - 16:
        raise RuntimeError("firmware code/data overlaps fixed tensor arena")
    rc = command([compiler_sibling(gcc, "objcopy"), "-O", "binary", out / "cpu.elf", out / "cpu.bin"], out / "objcopy.log")
    if rc:
        raise RuntimeError("firmware objcopy failed")
    image = (out / "cpu.bin").read_bytes()
    image += b"\0" * (-len(image) % 4)
    (out / "cpu.mem").write_text("".join(f"{word:08x}\n" for (word,) in struct.iter_unpack("<I", image)))
    manifest.update(elf_sha256=digest(out / "cpu.elf"), mem_sha256=digest(out / "cpu.mem"),
                    symbols=symbols, image_bytes=len(image), end_address=symbols["_end"])
    write_json(manifest_path, manifest)
    return manifest


def write_sparse(path: Path, spans: list[tuple[int, bytes]]) -> None:
    words = {}
    for base, payload in spans:
        for i, value in enumerate(payload):
            address = base + i
            index, lane = divmod(address, 4)
            words[index] = (words.get(index, 0) & ~(255 << (lane * 8))) | (value << (lane * 8))
    with path.open("w") as stream:
        previous = -2
        for index, value in sorted(words.items()):
            if index != previous + 1:
                stream.write(f"@{index:08x}\n")
            stream.write(f"{value:08x}\n")
            previous = index


def prepare_case(out: Path, slug: str, mode: int, source: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    source = source.resolve()
    original = json.loads((source / "case.json").read_text())
    h, w, c, gc, go, kh, kw, oh, ow, co, sh, sw, dh, dw, ph, pw, io, oo, amin, amax = original["parameters"]
    if gc != c or go != 0:
        raise ValueError("this old-API baseline comparison requires ungrouped shapes")
    payloads = {name: (source / f"{name}.bin").read_bytes()
                for name in ["input", "filter", "bias", "multiplier", "shift", "output"]}
    expected_lengths = {"input": h * w * c, "filter": co * kh * kw * gc,
                        "bias": 4 * co, "multiplier": 4 * co, "shift": 4 * co, "output": oh * ow * co}
    assert all(len(payloads[name]) == size for name, size in expected_lengths.items())
    scratch_bytes = 32 * ((kh * kw * gc + 3) // 4 * 4)
    # The historical 1x1 wrapper submits one ordinary GEMM per output image row;
    # its generic spatial path submits at most 32 im2col rows per command.
    legacy_starts = oh if kh == kw == 1 else (oh * ow + 31) // 32
    expected_starts = legacy_starts if mode == 0 else 1
    bias_base, mult_base, shift_base = 0x30000, 0x31000, 0x32000
    config = [0x43565046, 1, mode, LAYERS.index(slug), 1, h, w, c, kh, kw, gc,
              oh, ow, co, sh, sw, dh, dw, ph, pw, io, oo, amin, amax,
              REGIONS["input"], REGIONS["weight"], bias_base, mult_base, shift_base,
              REGIONS["output"], REGIONS["scratch"], GOLDEN_BASE,
              len(payloads["input"]), len(payloads["filter"]), len(payloads["output"]),
              scratch_bytes, expected_starts, 0]
    assert len(config) == 38
    spans = [(REGIONS["input"], payloads["input"]), (REGIONS["weight"], payloads["filter"]),
             (bias_base, payloads["bias"]), (mult_base, payloads["multiplier"]),
             (shift_base, payloads["shift"]), (GOLDEN_BASE, payloads["output"]),
             (CONFIG_BASE, struct.pack("<38I", *(v & 0xffffffff for v in config)))]
    write_sparse(out / "data.mem", spans)
    sizes = {"input": len(payloads["input"]), "weight": len(payloads["filter"]),
             "scratch": scratch_bytes, "output": len(payloads["output"]),
             "params": shift_base + 4 * co - bias_base}
    meta = {"layer": slug, "layer_id": original["layer_id"], "mode": mode,
            "case_id": LAYERS.index(slug), "parameters": original["parameters"],
            "config_words": config, "expected_starts": expected_starts,
            "regions": {name: {"base": base, "bytes": sizes[name]} for name, base in REGIONS.items()},
            "golden_base": GOLDEN_BASE, "config_base": CONFIG_BASE,
            "source_case": os.path.relpath(source, out.resolve()),
            "source_case_relative_to": "case_directory",
            "vector_sha256": {"case.json": digest(source / "case.json"),
                              **{f"{name}.bin": digest(source / f"{name}.bin") for name in payloads}},
            "data_mem_sha256": digest(out / "data.mem"),
            "data_policy": "Exact model geometry freshly extracted from bundled TFLite; deterministic generated synthetic tensors/quantization and direct-C golden. Not full-model inference."}
    write_json(out / "case.json", meta)
    return meta


def parse_counters(log: str) -> tuple[dict, dict]:
    counters, regions = {}, {}
    for line in log.splitlines():
        if line.startswith("SOC_PERF_COUNTER "):
            fields = dict(re.findall(r"(\w+)=([\w]+)", line))
            scope = fields.pop("scope")
            counters[scope] = {name: int(value) for name, value in fields.items()}
        elif line.startswith("SOC_PERF_OWNER "):
            fields = dict(re.findall(r"(\w+)=([\w]+)", line))
            scope = fields.pop("scope")
            counters.setdefault(scope, {}).update({name: int(value) for name, value in fields.items()})
        elif line.startswith("SOC_PERF_REGION "):
            fields = dict(re.findall(r"(\w+)=([\w]+)", line))
            name = fields.pop("name")
            regions[name] = {key: int(value) for key, value in fields.items()}
    return counters, regions


def run_benchmark(binary: Path, firmware: Path, firmware_manifest: dict, case_dir: Path,
                  meta: dict, *, latency=0, max_cycles=300000000) -> dict:
    symbols = firmware_manifest["symbols"]
    args = [binary, f"+SOC_CPU_MEM={firmware / 'cpu.mem'}", f"+SOC_DATA_MEM={case_dir / 'data.mem'}",
            f"+RESULT_ADDR={symbols['benchmark_result']:x}", "+RESULT_WORDS=24",
            f"+RESULT_FILE={case_dir / 'result.mem'}", f"+GOLDEN_BASE={GOLDEN_BASE:x}",
            f"+TIMEOUT_CYCLES={max_cycles}", f"+RAM_FIXED_LAT={latency}"]
    for name, region in meta["regions"].items():
        args.extend([f"+PERF_{name}_BASE={region['base']:x}", f"+PERF_{name}_BYTES={region['bytes']}"])
    rc = command(args, case_dir / "run.log", timeout=1800)
    log = (case_dir / "run.log").read_text()
    counters, regions = parse_counters(log)
    result = dict(layer=meta["layer"], mode=meta["mode"], fixed_response_latency=latency,
                  returncode=rc, command=[str(v) for v in args], counters=counters, regions=regions,
                  simulation_binary_sha256=digest(binary), firmware_elf_sha256=firmware_manifest["elf_sha256"],
                  case_mem_sha256=meta["data_mem_sha256"])
    values = [int(value, 16) for value in (case_dir / "result.mem").read_text().split()] if (case_dir / "result.mem").exists() else []
    errors = []
    if len(values) != 24:
        errors.append("CPU result is missing/incomplete")
    else:
        cpu = dict(zip(RESULT_FIELDS, values))
        for name in ["nmsis_status", "first_expected", "first_actual"]:
            if cpu[name] & 0x80000000:
                cpu[name] -= 1 << 32
        result["cpu_result"] = cpu
        if (cpu["magic"] != 0x43565052 or cpu["version"] != 1 or cpu["complete"] != 1 or
                cpu["mode"] != meta["mode"] or cpu["case_id"] != meta["case_id"]):
            errors.append("CPU result ABI/config mismatch")
        if any(cpu[name] for name in ["nmsis_status", "error", "mismatches", "guard_errors"]):
            errors.append("CPU reported an execution/output failure")
        if cpu["compared_outputs"] != meta["regions"]["output"]["bytes"]:
            errors.append("CPU did not compare every output")
        if ((cpu["end_cycle"] - cpu["start_cycle"]) & 0xffffffff) != cpu["total_call_cycles"]:
            errors.append("CSR cycle subtraction mismatch")
    window = counters.get("call_window", {})
    if window.get("jobs") != meta["expected_starts"]:
        errors.append("actual START count differs from original scheduling contract")
    expected_conv = int(meta["mode"] != 0)
    if window.get("conv_jobs") != expected_conv or window.get("is_jobs") != int(meta["mode"] == 2):
        errors.append("observed NPU command kind/dataflow mismatch (fallback forbidden)")
    if window.get("done_jobs") != meta["expected_starts"]:
        errors.append("NPU completion count mismatch")
    ia_blocks, kernel_blocks = window.get("ia_im2col_blocks", 0), window.get("kernel_im2col_blocks", 0)
    if ((meta["mode"] == 0 and (ia_blocks or kernel_blocks)) or
            (meta["mode"] == 1 and (not ia_blocks or kernel_blocks)) or
            (meta["mode"] == 2 and (ia_blocks or not kernel_blocks))):
        errors.append("im2col DMA block owner does not match the requested dataflow")
    if rc != 0 or "SOC_PERF_PASS" not in log:
        errors.append("SoC did not finish successfully")
    result["errors"] = errors
    result["passed"] = not errors
    if not errors:
        result["non_npu_busy_call_cycles"] = result["cpu_result"]["total_call_cycles"] - window["npu_busy_cycles"]
    write_json(case_dir / "result.json", result)
    print(meta["layer"], "legacy" if meta["mode"] == 0 else "hardware", "PASS" if not errors else "FAIL",
          result.get("cpu_result", {}).get("total_call_cycles"), errors, flush=True)
    if errors:
        print(log[-6000:], flush=True)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / 'build/conv_soc_perf')
    ap.add_argument("--stage", choices=["build", "smoke", "benchmark"], default="benchmark")
    ap.add_argument("--verilator", default="verilator")
    ap.add_argument("--gcc", default="riscv64-unknown-elf-gcc")
    ap.add_argument("--newlib-include", type=Path, help="Optional standard newlib headers for a locally unpacked GCC")
    ap.add_argument("--runtime-lib", type=Path, help="Optional official target C runtime archive; otherwise use -lc")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--reuse-sim", type=Path, help="Existing simulator directory; reused only after exact source, parameter and binary SHA checks")
    ap.add_argument("--skip-firmware", action="store_true")
    ap.add_argument("--icache", type=int, choices=[0, 1], default=0)
    ap.add_argument("--dataflow", type=int, choices=[0, 1], default=0)
    ap.add_argument("--layers", nargs="+", choices=LAYERS, default=LAYERS)
    ap.add_argument("--modes", nargs="+", type=int, choices=[0, 1, 2], default=[0, 1])
    ap.add_argument("--latency", type=int, default=0)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--max-cycles", type=int, default=300000000)
    ap.add_argument("--summary-name", default="summary.json", help="Separate report name for optional IS/latency runs")
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if Path(args.summary_name).name != args.summary_name or not args.summary_name.endswith('.json'):
        ap.error('--summary-name must be a simple JSON filename')
    if args.skip_build and args.reuse_sim:
        ap.error('choose --skip-build or --reuse-sim')
    binary = build_sim(out / "sim", args.verilator, args.jobs, skip=args.skip_build,
                       icache=args.icache, reuse=args.reuse_sim)
    if args.stage == "build":
        print(binary)
        return 0
    firmware = out / ("firmware_smoke" if args.stage == "smoke" else f"firmware_df{args.dataflow}")
    manifest = build_firmware(firmware, args.gcc, dataflow=args.dataflow,
                              smoke=args.stage == "smoke", skip=args.skip_firmware,
                              newlib_include=args.newlib_include, runtime_lib=args.runtime_lib)
    if args.stage == "smoke":
        cmd = [binary, f"+SOC_CPU_MEM={firmware / 'cpu.mem'}", "+EXPECTED_STATUS=1", "+TIMEOUT_CYCLES=10000000"]
        rc = command(cmd, out / "smoke.log", timeout=300)
        log = (out / "smoke.log").read_text()
        status = {"passed": rc == 0 and "SOC_PERF_PASS" in log, "returncode": rc,
                  "command": [str(v) for v in cmd], "firmware_elf_sha256": manifest["elf_sha256"]}
        write_json(out / "smoke.json", status)
        print(log[-5000:])
        return 0 if status["passed"] else 1
    vector_out = out / ('vectors_' + Path(args.summary_name).stem)
    vectors = generate_layers(vector_out, args.layers, seed=args.seed)
    summary = {"verification_level": "real production PicoRV32 CPU executes RV32 firmware on soc_top with NPU and production AXI RAM",
               "vector_generation": {"manifest": str((vector_out/'manifest.json').relative_to(out)),
                                     "manifest_sha256": digest(vector_out/'manifest.json'),
                                     "seed": args.seed, "historical_vectors_used": False},
               "timing_source": "CPU rdcycle around the complete NMSIS call; host wall time is never a performance metric",
               "counter_window": "progress BEGIN/END markers bracket CSR readings and are slightly wider than the CSR call interval",
               "cpu_data_read_units": "accepted native bus word reads times 4, not decoded C-load byte width",
               "npu_read_units": "AXI addressed bytes of accepted AR commands, excluding inactive lanes of an unaligned first beat",
               "non_npu_busy_meaning": "CSR call cycles minus all observed NPU busy cycles; includes CPU preparation, validation, MMIO submission and polling, not pure im2col",
               "cold_reset_per_case": True, "same_elf_for_legacy_and_ws": args.dataflow == 0,
               "cpu_icache": args.icache, "fixed_response_latency": args.latency, "results": []}
    for layer in args.layers:
        for mode in args.modes:
            case_dir = out / "cases" / f"{layer}_mode{mode}_lat{args.latency}"
            meta = prepare_case(case_dir, layer, mode, vectors['cases'][layer])
            result = run_benchmark(binary, firmware, manifest, case_dir, meta,
                                   latency=args.latency, max_cycles=args.max_cycles)
            summary["results"].append(result)
            write_json(out / args.summary_name, summary)
            if not result["passed"]:
                return 1
    summary["passed"] = True
    write_json(out / args.summary_name, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
