#!/usr/bin/env python3
"""Run common quantized GEMM cases on an explicitly selected mini_tflm_dsa tree."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "veri/top_regression"))
from host_schedule import default_config, plan_schedule, schedule_key
from host_tiling import plan_capacity


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runner(repository: Path):
    path = repository / "test/conv_npu/run.py"
    spec = importlib.util.spec_from_file_location("selected_npu_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payload(directory: Path, tensor: dict) -> bytes:
    path = directory / tensor["path"]
    value = path.read_bytes()
    if len(value) != tensor["bytes"] or hashlib.sha256(value).hexdigest() != tensor["sha256"]:
        raise ValueError("Shared workload tensor does not match its manifest")
    return value


def build_comparison(runner, repository: Path, out: Path, args,
                     testbench: Path | None = None, top_module: str = "tb_conv_npu") -> Path:
    npu = repository / "rtl/npu"
    package = npu / "conv/00_conv_im2col_pkg.sv"
    sources = [package] + [path for path in sorted(npu.rglob("*.sv")) if path != package]
    sources += sorted(npu.rglob("*.v"))
    sources += [repository / "rtl/common/pseudo_dual_port_ram.v", repository / "test/conv_npu/axi_memory.sv"]
    if testbench is None:
        sources.append(repository / "test/conv_npu/tb_conv_npu.sv")
    monitor = Path(__file__).resolve().with_name("axi_monitor.sv")
    comparison_sources = [monitor] + ([testbench] if testbench is not None else [])
    comparison_defines = []
    if getattr(args, "windowed", False):
        comparison_defines.append("-DCOMMON_WINDOWED_INPUT")
    if getattr(args, "prefetch", False):
        comparison_defines.append("-DCOMMON_PREFETCH_INPUT")
    command = [args.verilator, "--binary", "--timing", "--assert", "-sv", "--top-module", top_module,
               "-Wno-fatal", f"-I{npu / 'gempact'}", "-DTB_SIZE=16", f"-DCOMMON_MONITOR_TOP={top_module}",
               f"-DTB_IA_CACHE_BLOCKS={getattr(args, 'ia_cache_blocks', 4)}",
               f"-DTB_PS_FRAME_COUNT={getattr(args, 'ps_frames', 16)}",
               f"-DTB_PS_STORAGE_ROWS={getattr(args, 'ps_storage_rows', 0)}",
               f"-DTB_OA_S16_FIFO_BANKS_MAX={getattr(args, 's16_output_banks', 0)}",
               f"-DTB_CONV_CACHE_SETS={args.cache_sets}", f"-DTB_CONV_CACHE_POLICY={args.cache_policy}",
               f"-DTB_BUS_WIDTH={args.bus_width}", f"-DTB_DMA_MAX_BYTES={args.dma_max_bytes}",
               f"-DTB_READ_BEAT_CYCLES={args.read_beat_cycles}",
               f"-DTB_READ_FIRST_LATENCY={args.first_read_latency}",
               f"-DTB_PIPELINED_READ={int(args.memory_timing == 'pipelined')}",
               "--Mdir", out / "obj", "-j", args.jobs, "-CFLAGS", "-std=c++20 -O1",
               "-MAKEFLAGS", "OPT_FAST=-O1 OPT_SLOW=-O0", *comparison_defines, *sources, *comparison_sources]
    before = {str(path.relative_to(repository)): sha256(path) for path in sources}
    comparison_before = {str(path): sha256(path) for path in comparison_sources}
    monitor_digest = sha256(monitor)
    returncode = runner.command(command, out / "compile.log", timeout=1200)
    log = (out / "compile.log").read_text()
    after = {str(path.relative_to(repository)): sha256(path) for path in sources}
    build = {"returncode": returncode, "size": 16, "cache_sets": args.cache_sets,
             "dma_max_bytes": args.dma_max_bytes, "bus_width": args.bus_width,
             "read_beat_cycles": args.read_beat_cycles,
             "first_read_latency": args.first_read_latency, "memory_timing": args.memory_timing,
             "ia_cache_blocks": getattr(args, "ia_cache_blocks", 4), "ps_frames": getattr(args, "ps_frames", 16),
             "ps_storage_rows": getattr(args, "ps_storage_rows", 0),
             "s16_output_banks_max": getattr(args, "s16_output_banks", 0),
             "cache_ways": 2, "cache_line_bytes": 16, "cache_policy": args.cache_policy,
             "command": [str(value) for value in command], "source_sha256": before,
             "top_module": top_module, "comparison_source_sha256": comparison_before,
             "comparison_defines": comparison_defines,
             "monitor_sha256": monitor_digest, "sources_unchanged_during_build": before == after,
             "warnings": {name: log.count("%Warning-" + name + ":")
                          for name in sorted(set(re.findall(r"%Warning-([^:]+):", log)))}}
    (out / "build.json").write_text(json.dumps(build, indent=2) + "\n")
    if returncode:
        raise RuntimeError(log[-6000:])
    if before != after or comparison_before != {str(path): sha256(path) for path in comparison_sources}:
        raise RuntimeError("RTL sources changed during compilation")
    return out / ("obj/V" + top_module)


def records(log: str, prefix: str) -> list[dict]:
    return [{key: int(value) for key, value in re.findall(r"(\w+)=(-?\d+)", line)}
            for line in log.splitlines() if line.startswith(prefix)]


def memory_profile(args) -> dict:
    pipelined = args.memory_timing == "pipelined"
    return {"implementation": "test/conv_npu/axi_memory.sv", "random_wait": False,
            "read_request_queue": 16, "read_first_beat_latency_idle": args.first_read_latency,
            "read_beat_interval_cycles": args.read_beat_cycles,
            "read_burst_transition_interval_min": 1 if pipelined else 3,
            "read_latency_semantics": "per_request_from_ar_handshake" if pipelined else "queued_service",
            "read_latency_overlap": pipelined, "registered_synchronous_read": True,
            "write_active_transactions_max": 1, "write_first_beat_after_aw_min": 1,
            "write_beat_interval_min": 1, "write_response_after_last_w_min": 1,
            "read_write_independent": True}


def pack_matrix(data: bytes, rows: int, depth: int, element_bytes: int = 1) -> bytes:
    if len(data) != rows * depth * element_bytes:
        raise ValueError("Physical source does not match its logical matrix shape")
    output = bytearray(((rows + 15) // 16) * ((depth + 15) // 16) * 256 * element_bytes)
    offset = 0
    for rt in range((rows + 15) // 16):
        for kt in range((depth + 15) // 16):
            for r in range(16):
                count = max(0, min(16, depth - kt * 16)) * element_bytes
                if rt * 16 + r < rows and count:
                    source = ((rt * 16 + r) * depth + kt * 16) * element_bytes
                    output[offset:offset + count] = data[source:source + count]
                offset += 16 * element_bytes
    return bytes(output)


def prepare_case(runner, source: Path, out: Path, ia_cache_blocks: int = 4,
                 ps_frames: int = 16, ps_storage_rows: int = 0, *,
                 schedule_mode: str = "legacy", dataflow: str = "auto",
                 layout: str = "row-major", requested_r: int = 0, requested_w: int = 0,
                 s16_output_banks: int = 0, dma_max_bytes: int = 2048, bus_width: int = 64,
                 read_beat_cycles: int = 1) -> dict:
    description = json.loads((source / "case.json").read_text())
    m, n, k = (description[key] for key in ("m", "n", "k"))
    data = {name: payload(source, tensor) for name, tensor in description["tensors"].items()}
    requested_layout = layout
    if layout == "auto" and schedule_mode != "auto":
        raise ValueError("Automatic layout requires automatic schedule selection")
    layouts = ("row-major", "lhs-packed", "rhs-packed", "both-packed") if layout == "auto" else (layout,)
    choices = []
    for candidate_layout in layouts:
        physical = {key: data[key] for key in ("a", "b_transposed", "bias")}
        lhs_packed = candidate_layout in ("lhs-packed", "both-packed")
        rhs_packed = candidate_layout in ("rhs-packed", "both-packed")
        if lhs_packed:
            physical["a"] = pack_matrix(data["a"], m, k)
        if rhs_packed:
            physical["b_transposed"] = pack_matrix(data["b_transposed"], n, k)
        addresses, base = {}, 4096
        for key in ("a", "b_transposed", "bias"):
            addresses[key] = base
            base = (base + len(physical[key]) + 127) & ~63
        addresses["c"] = base
        planning = default_config(m, k, n, ia_blocks=ia_cache_blocks, ps_frames=ps_frames,
            ps_storage_rows=ps_storage_rows, flow={"ws": 0, "is": 1, "auto": 2}[dataflow],
            requested_r=requested_r, requested_w=requested_w, has_bias=1,
            lhs_address=addresses["a"], rhs_address=addresses["b_transposed"], output_address=addresses["c"],
            lhs_tile_packed=int(lhs_packed), rhs_tile_packed=int(rhs_packed),
            output_banks_s16=s16_output_banks, dma_max_bytes=dma_max_bytes, axi_data_bits=bus_width,
            read_beat_cycles=read_beat_cycles)
        schedule = plan_schedule(planning) if schedule_mode == "auto" else None
        choices.append(dict(layout=candidate_layout, physical=physical, addresses=addresses,
                            planning=planning, schedule=schedule))
    chosen = min(choices, key=lambda x: schedule_key(x["schedule"])) if layout == "auto" else choices[0]
    layout, physical, addresses, planning, schedule = (chosen[key] for key in
        ("layout", "physical", "addresses", "planning", "schedule"))
    lhs_packed, rhs_packed = planning["lhs_tile_packed"], planning["rhs_tile_packed"]
    image = bytearray(runner.SENTINEL * runner.WORDS)
    if addresses["c"] + len(data["c_s8"]) + 64 > len(image):
        raise ValueError("GEMM case exceeds the comparison memory")
    for key, value in physical.items():
        image[addresses[key]:addresses[key] + len(value)] = value
    golden = bytearray(image)
    golden[addresses["c"]:addresses["c"] + len(data["c_s8"])] = data["c_s8"]
    if schedule_mode == "legacy":
        selected_mode = int(dataflow == "is")
        tiling, _ = plan_capacity(m, n, 16, ia_cache_blocks, ps_frames,
            requested_r, requested_w, bool(selected_mode), False, ps_storage_rows * 64 if k > 16 else 0)
    else:
        tiling, selected_mode = schedule["tiling"], schedule["dataflow_mode"]
    cfg = [0] * 64
    fields = {0: 0x4E505531, 1: 16, 2: ia_cache_blocks, 3: m, 4: k, 5: n,
              6: tiling["ia_reuse"], 7: tiling["w_reuse"], 8: selected_mode, 9: ps_frames,
              10: runner.WORDS, 11: runner.WORDS, 12: 0, 13: 0,
              14: addresses["a"], 15: addresses["b_transposed"], 16: addresses["bias"],
              17: addresses["c"], 18: k, 19: k, 20: n,
              21: 0, 22: 0, 23: 0, 24: description["npu_quant_multiplier"],
              25: description["npu_quant_shift"], 26: -128, 27: 127,
              29: int(lhs_packed) | (int(rhs_packed) << 1),
              30: tiling["row_groups"] | tiling["col_groups"] << 16,
              31: tiling["row_tail_tiles"] | tiling["col_tail_tiles"] << 16}
    for index, value in fields.items():
        cfg[index] = value & 0xFFFFFFFF
    out.mkdir(parents=True, exist_ok=True)
    runner.sparse_mem(out / "init.mem", image)
    runner.sparse_mem(out / "golden.mem", golden)
    (out / "config.mem").write_text("".join(f"{value:08x}\n" for value in cfg))
    (out / "required.mem").write_text("@00000000\n0\n")
    record = {"name": description["name"], "m": m, "n": n, "k": k,
              "dense_macs": description["dense_macs"],
              "workload_manifest_sha256": sha256(source / "case.json"),
              "output_sha256": description["tensors"]["c_s8"]["sha256"],
              "input_tensor_sha256": {key: value["sha256"] for key, value in description["tensors"].items()},
              "requested_layout": requested_layout,
              "layout_candidates": [{"layout": choice["layout"], "schedule": choice["schedule"],
                                     "configuration": choice["planning"]} for choice in choices],
              "physical_layout": layout, "dataflow": "is" if selected_mode else "ws",
              "physical_payload": {key: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                                   for key, value in physical.items()},
              "schedule_mode": schedule_mode, "schedule_configuration": planning, "schedule": schedule,
              "addresses": addresses, "tiling": tiling,
              "files": {filename: sha256(out / filename) for filename in ("init.mem", "golden.mem", "config.mem")}}
    (out / "case.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--cache-sets", type=int, default=128)
    parser.add_argument("--cache-policy", type=int, default=3)
    parser.add_argument("--ia-cache-blocks", type=int, default=8)
    parser.add_argument("--ps-frames", type=int, default=16)
    parser.add_argument("--ps-storage-rows", type=int, default=799)
    parser.add_argument("--s16-output-banks", type=int, default=4)
    parser.add_argument("--bus-width", type=int, choices=(32, 64), default=64)
    parser.add_argument("--read-beat-cycles", type=int, choices=(1, 2), default=1,
                        help="Cycles between consecutive read beats within one burst")
    parser.add_argument("--memory-timing", choices=("pipelined", "legacy"), default="pipelined")
    parser.add_argument("--first-read-latency", "--read-latency-cycles", type=int,
                        help="AR-to-first-R latency; defaults to 8 for pipelined memory and 3 for legacy memory")
    parser.add_argument("--dma-max-bytes", type=int, help="Optional physical burst limit; default: 256 bus beats")
    parser.add_argument("--layout", choices=("auto", "row-major", "lhs-packed", "rhs-packed", "both-packed"), default="auto")
    parser.add_argument("--schedule", choices=("auto", "legacy"), default="auto")
    parser.add_argument("--dataflow", choices=("auto", "ws", "is"), default="auto")
    parser.add_argument("--ia-reuse", type=int, default=0)
    parser.add_argument("--w-reuse", type=int, default=0)
    args = parser.parse_args()
    if args.first_read_latency is None:
        args.first_read_latency = 8 if args.memory_timing == "pipelined" else 3
    if args.first_read_latency < 1 or (args.memory_timing == "legacy" and args.first_read_latency != 3):
        parser.error("Pipelined latency must be at least one cycle; legacy memory has three cycles")
    if args.dma_max_bytes is None:
        args.dma_max_bytes = 256 * (args.bus_width // 8)
    if (args.dma_max_bytes < args.bus_width // 8 or args.dma_max_bytes > 256 * (args.bus_width // 8)
        or args.dma_max_bytes & (args.dma_max_bytes - 1)):
        parser.error("DMA limit must be 1 through 256 complete bus beats with a power-of-two byte length")
    repository, workloads, out = args.repo.resolve(), args.workloads.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    runner = load_runner(repository)
    catalog = json.loads((workloads / "workloads.json").read_text())
    selected = [row for row in catalog["cases"] if args.cases is None or row["name"] in args.cases]
    if not selected or (args.cases and {row["name"] for row in selected} != set(args.cases)):
        raise ValueError("Requested workload case is absent")
    cases = []
    for row in selected:
        manifest_path = workloads / row["manifest"]
        if sha256(manifest_path) != row["manifest_sha256"]:
            raise ValueError("Shared case manifest changed")
        cases.append(prepare_case(runner, manifest_path.parent, out / "cases" / row["name"],
            args.ia_cache_blocks, args.ps_frames, args.ps_storage_rows, schedule_mode=args.schedule,
            dataflow=args.dataflow, layout=args.layout, requested_r=args.ia_reuse, requested_w=args.w_reuse,
            s16_output_banks=args.s16_output_banks, dma_max_bytes=args.dma_max_bytes, bus_width=args.bus_width,
            read_beat_cycles=args.read_beat_cycles))
    build_dir = out / "sim"
    build_dir.mkdir(exist_ok=True)
    if args.skip_build:
        build = json.loads((build_dir / "build.json").read_text())
        if (build["size"] != 16 or build["cache_sets"] != args.cache_sets or
                build["cache_policy"] != args.cache_policy or build["returncode"]):
            raise ValueError("Compiled NPU profile differs from requested profile")
        if build.get("dma_max_bytes", 1024) != args.dma_max_bytes or build.get("bus_width", 32) != args.bus_width:
            raise ValueError("Compiled DMA transaction limit differs from requested limit")
        if build.get("read_beat_cycles", 2) != args.read_beat_cycles:
            raise ValueError("Compiled memory read throughput differs from requested throughput")
        if (build.get("first_read_latency", 3) != args.first_read_latency or
                build.get("memory_timing", "legacy") != args.memory_timing):
            raise ValueError("Compiled memory latency differs from requested latency")
        if (build.get("ia_cache_blocks", 4) != args.ia_cache_blocks or
                build.get("ps_frames", 16) != args.ps_frames):
            raise ValueError("Compiled operand/partial-sum capacities differ")
        if build.get("ps_storage_rows", 0) != args.ps_storage_rows:
            raise ValueError("Compiled partial-sum physical storage differs")
        if build.get("s16_output_banks_max", 0) != args.s16_output_banks:
            raise ValueError("Compiled INT16 output buffer capacity differs")
        for path, digest in build["source_sha256"].items():
            if sha256(repository / path) != digest:
                raise ValueError("Compiled NPU source differs from selected repository")
        if build.get("monitor_sha256") != sha256(Path(__file__).resolve().with_name("axi_monitor.sv")):
            raise ValueError("Compiled timing monitor differs from requested monitor")
        binary = build_dir / "obj/Vtb_conv_npu"
    else:
        binary = build_comparison(runner, repository, build_dir, args)
    all_logs = []
    for row in cases:
        case_out = out / "cases" / row["name"]
        suite = case_out / "gemm.suite"
        suite.write_text(" ".join(str(case_out / filename)
                         for filename in ("config.mem", "init.mem", "golden.mem", "required.mem")) + "\n")
        command = [str(binary), "+SUITE=" + str(suite), "+NO_RANDOM_WAIT", "+NPU_UTIL_TRACE", "+NPU_UTIL_SUMMARY"]
        returncode = runner.command(command, case_out / "run.log", timeout=900)
        log = (case_out / "run.log").read_text()
        all_logs.append(log)
        measurements, tops, control, timing = [records(log, prefix) for prefix in
            ("CONV_TASK_PASS", "[NPU_UTIL]", "[NPU_CTRL_UTIL]", "COMMON_TIMING")]
        row["command"] = command
        row["returncode"] = returncode
        row["passed"] = (returncode == 0 and "CONV_NPU_PASS tasks=1" in log
                         and all(len(items) == 1 for items in (measurements, tops, control, timing)))
        if row["passed"]:
            row["measurement"] = measurements[0]
            row["utilization"] = tops[0]
            row["controller"] = control[0]
            row["timing"] = timing[0]
            if timing[0]["done"] != measurements[0]["cycles"]:
                raise ValueError("Independent timing monitor disagrees with testbench cycle count")
            if timing[0]["read_latency_min"] < args.first_read_latency:
                raise ValueError("Observed AXI response precedes the configured synchronous latency")
            if max(timing[0]["read_burst_bytes_max"], timing[0]["write_burst_bytes_max"]) > args.dma_max_bytes:
                raise ValueError("Observed AXI transaction exceeds the configured DMA limit")
            row["effective_array_utilization"] = row["dense_macs"] / (256 * measurements[0]["cycles"])
        else:
            print(log[-6000:])
            break
    (out / "run.log").write_text("\n".join(all_logs))
    passed = all(row.get("passed", False) for row in cases)
    rmax = max(1, args.ia_cache_blocks // 2)
    output_banks = min(32, args.ps_frames * rmax)
    s16_output_banks = min(output_banks, args.s16_output_banks) if args.s16_output_banks else output_banks
    buffers = {"ia": args.ia_cache_blocks * 16 * 16 * 2, "kernel": 2 * 16 * 16 * 2,
               "partial_sum": (args.ps_storage_rows or ((rmax + 1) * 16 - 1) * (args.ps_frames + 1)) * 16 * 4,
               "output_s8": output_banks * 16 * 16, "output_s16": s16_output_banks * 16 * 16 * 2}
    result = {"passed": passed,
              "source_repository": str(repository),
              "source_commit": subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip(),
              "build_manifest_sha256": sha256(build_dir / "build.json"),
              "schedule_source_sha256": {name: sha256(Path(__file__).resolve().parents[2] / name)
                  for name in ("drivers/dsa_schedule.h", "veri/top_regression/host_schedule.py")},
              "binary_sha256": sha256(binary), "workload_catalogue_sha256": sha256(workloads / "workloads.json"),
              "profile": {"array": [16, 16], "activation_datapath_bits": 16, "weight_datapath_bits": 16,
                          "external_operand_bits": 8, "accumulator_bits": 32, "output_bits": 8,
                          "bus_bits": args.bus_width, "ia_cache_blocks": args.ia_cache_blocks, "ps_frames": args.ps_frames,
                          "dma_max_bytes": args.dma_max_bytes, "bus_width": args.bus_width,
                          "ps_storage_rows": args.ps_storage_rows,
                          "s16_output_banks_max": args.s16_output_banks,
                          "physical_layout": args.layout, "schedule": args.schedule,
                          "read_outstanding": 4, "write_outstanding": 4,
                          "declared_main_buffer_bytes": buffers,
                          "declared_main_buffer_total_bytes": sum(buffers.values()),
                          "buffer_scope": "Declared main RAM payload; excludes caches, parameter tables, PE registers and control queues. INT16 output RAM is instantiated but inactive for these INT8 cases.",
                          "window_cache_data_bytes": args.cache_sets * 2 * 16,
                          "window_cache_policy": args.cache_policy,
                          "window_cache_used_for_common_gemm": False,
                          "cold_start": "Each case starts a fresh simulator process and resets the complete DUT; only external tensor memory is initialized.",
                          "memory": memory_profile(args),
                          "timing": "Cycle 0 is the accepted calc_start rising edge; done is the first rising edge observing done_valid. Every AXI read completion and write response must precede or coincide with done. Last write-response time is reported separately. Excludes host preparation and the three-cycle completion backpressure check."},
              "cases": cases}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": passed, "cases": sum(row.get("passed", False) for row in cases),
                      "result": str(out / "summary.json")}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
