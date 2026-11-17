#!/usr/bin/env python3
"""Run shared raw-input Conv and depthwise Conv through the complete NPU top."""
from __future__ import annotations

import argparse
import json
import hashlib
import re
import subprocess
from pathlib import Path

from run_mini import (build_comparison, load_runner, payload, records, sha256, pack_matrix,
                      default_config, plan_schedule, schedule_key, plan_capacity, memory_profile)


def prepare_case(runner, source: Path, out: Path, ia_cache_blocks=8, ps_frames=16,
                 ps_storage_rows=799, s16_output_banks=4, schedule_mode="auto",
                 dataflow="auto", rhs_layout="auto", requested_r=0, requested_w=0,
                 dma_max_bytes=2048, bus_width=64, read_beat_cycles=1) -> dict:
    description = json.loads((source / "case.json").read_text())
    depthwise = description["operator"] == "depthwise"
    h, w, cin, cout, oh, ow, kh, kw = (description[key] for key in
        ("input_h", "input_w", "input_channels", "output_channels", "output_h", "output_w", "kernel_h", "kernel_w"))
    m, k = oh * ow, kh * kw * (1 if depthwise else cin)
    addresses = {"a": 0x10000, "weights_npu": 0x20000, "bias": 0x30000,
                 "multiplier": 0x31000, "shift": 0x32000, "c": 0x40000}
    image = bytearray(runner.SENTINEL * runner.WORDS)
    data = {name: payload(source, tensor) for name, tensor in description["tensors"].items()}
    candidates = []
    physical = {key: data[key] for key in ("a", "weights_npu", "bias")}
    selected_mode, rhs_packed, schedule, planning = 0, 0, None, None
    if depthwise:
        selected_layout = "depthwise-native"
        tiling = runner.plan(m, cout, 16, ia_cache_blocks, ps_frames, 0, 0, False, False)
    else:
        if rhs_layout == "auto" and schedule_mode != "auto":
            raise ValueError("Automatic layout requires automatic schedule selection")
        layouts = ("raw", "packed") if rhs_layout == "auto" else (rhs_layout,)
        for layout in layouts:
            config = default_config(m, k, cout, ia_blocks=ia_cache_blocks, ps_frames=ps_frames,
                ps_storage_rows=ps_storage_rows, flow={"ws": 0, "is": 1, "auto": 2}[dataflow],
                requested_r=requested_r, requested_w=requested_w, has_bias=1,
                lhs_bytes=2, lhs_stride=((k+15)//16)*32, rhs_stride=k, output_stride=cout,
                lhs_address=addresses["a"], rhs_address=addresses["weights_npu"],
                output_address=addresses["c"], spatial=1, per_channel=0,
                rhs_tile_packed=int(layout == "packed"), output_banks_s16=s16_output_banks,
                dma_max_bytes=dma_max_bytes, axi_data_bits=bus_width, read_beat_cycles=read_beat_cycles)
            candidate = plan_schedule(config) if schedule_mode == "auto" else None
            candidates.append(dict(layout=layout, configuration=config, schedule=candidate))
        choice = min(candidates, key=lambda x: schedule_key(x["schedule"])) if rhs_layout == "auto" else candidates[0]
        selected_layout, planning, schedule = (choice[key] for key in ("layout", "configuration", "schedule"))
        rhs_packed = int(selected_layout == "packed")
        if rhs_packed:
            physical["weights_npu"] = pack_matrix(data["weights_npu"], cout, k)
        if schedule_mode == "legacy":
            selected_mode = int(dataflow == "is")
            tiling, _ = plan_capacity(m, cout, 16, ia_cache_blocks, ps_frames,
                requested_r, requested_w, bool(selected_mode), False, ps_storage_rows*64 if k>16 else 0)
        else:
            tiling, selected_mode = schedule["tiling"], schedule["dataflow_mode"]
    regions = []
    for key, value in physical.items():
        address = addresses[key]
        end = address + len(value)
        if end > len(image):
            raise ValueError("Conv tensor exceeds the test memory")
        regions.append((address, end))
        image[address:end] = value
    if depthwise:
        for key, value in (("multiplier", description["npu_quant_multiplier"]), ("shift", description["npu_quant_shift"])):
            address = addresses[key]
            image[address:address + 4 * cout] = int(value).to_bytes(4, "little", signed=True) * cout
            regions.append((address, address + 4 * cout))
    regions.append((addresses["c"], addresses["c"] + len(data["c_s8"])))
    ordered = sorted(regions)
    if ordered[-1][1] > len(image) or any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Shared Conv tensor regions overlap or exceed memory")
    golden = bytearray(image)
    golden[addresses["c"]:addresses["c"] + len(data["c_s8"])] = data["c_s8"]
    cfg = [0] * 64
    fields = {0: 0x4E505531, 1: 16, 2: ia_cache_blocks, 3: m, 4: k, 5: cout,
              6: tiling["ia_reuse"], 7: tiling["w_reuse"], 8: selected_mode, 9: ps_frames,
              10: runner.WORDS, 11: runner.WORDS, 12: int(not depthwise),
              14: addresses["a"], 15: addresses["weights_npu"], 16: addresses["bias"],
              17: addresses["c"], 18: ((k + 15) // 16) * 32, 19: k, 20: cout,
              24: addresses["multiplier"] if depthwise else description["npu_quant_multiplier"],
              25: addresses["shift"] if depthwise else description["npu_quant_shift"],
              26: -128, 27: 127, 29: rhs_packed << 1,
              30: tiling["row_groups"] | tiling["col_groups"] << 16,
              31: tiling["row_tail_tiles"] | tiling["col_tail_tiles"] << 16,
              32: int(not depthwise), 33: addresses["a"], 34: h, 35: w, 36: cin, 37: cin,
              39: kh, 40: kw, 41: oh, 42: ow, 43: description["stride_h"], 44: description["stride_w"],
              45: description["dilation_h"], 46: description["dilation_w"],
              47: description["pad_top"], 48: description["pad_left"], 59: int(depthwise)}
    for index, value in fields.items():
        cfg[index] = value & 0xFFFFFFFF
    out.mkdir(parents=True, exist_ok=True)
    runner.sparse_mem(out / "init.mem", image)
    runner.sparse_mem(out / "golden.mem", golden)
    (out / "config.mem").write_text("".join(f"{value:08x}\n" for value in cfg))
    row = {"name": description["name"], "operator": description["operator"], "conv": description["conv"],
           "useful_macs": description["useful_macs"], "output_elements": oh * ow * cout,
           "workload_manifest_sha256": sha256(source / "case.json"),
           "output_sha256": description["tensors"]["c_s8"]["sha256"],
           "input_tensor_sha256": {key: value["sha256"] for key, value in description["tensors"].items()},
           "requested_rhs_layout": rhs_layout, "physical_rhs_layout": selected_layout,
           "physical_payload": {key: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                                for key, value in physical.items()},
           "dataflow": None if depthwise else ("is" if selected_mode else "ws"),
           "schedule_mode": "vector" if depthwise else schedule_mode,
           "schedule_configuration": planning, "schedule": schedule, "layout_candidates": candidates,
           "addresses": addresses, "tiling": tiling if not depthwise else None,
           "files": {name: sha256(out / name) for name in ("init.mem", "golden.mem", "config.mem")}}
    (out / "case.json").write_text(json.dumps(row, indent=2) + "\n")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=1)
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
    parser.add_argument("--schedule", choices=("auto", "legacy"), default="auto")
    parser.add_argument("--dataflow", choices=("auto", "ws", "is"), default="auto")
    parser.add_argument("--rhs-layout", choices=("raw", "packed", "auto"), default="auto")
    parser.add_argument("--ia-reuse", type=int, default=0)
    parser.add_argument("--w-reuse", type=int, default=0)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--windowed", action=argparse.BooleanOptionalAction, default=None,
                        help="Use the windowed input mode; defaults to the selected repository's production register reset")
    parser.add_argument("--prefetch", action=argparse.BooleanOptionalAction, default=None,
                        help="Enable input prefetch; defaults to the selected repository's production register reset")
    parser.add_argument("--cases", nargs="+")
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
    package_text = (repository / "rtl/npu/conv/conv_im2col_pkg.sv").read_text()
    register_text = (repository / "rtl/axi_top/npu_axil_reg_if.sv").read_text()
    if args.windowed is None:
        args.windowed = re.search(r"cfg_conv\.windowed\s*<=\s*1'b1", register_text) is not None
    if args.prefetch is None:
        args.prefetch = re.search(r"cfg_conv\.prefetch_enable\s*<=\s*1'b1", register_text) is not None
    if (args.windowed and "windowed" not in package_text) or (args.prefetch and "prefetch_enable" not in package_text):
        raise ValueError("Selected NPU repository does not support requested input configuration")
    catalogue = json.loads((workloads / "workloads.json").read_text())
    selected = [row for row in catalogue["cases"] if args.cases is None or row["name"] in args.cases]
    if not selected or (args.cases and {row["name"] for row in selected} != set(args.cases)):
        raise ValueError("Requested Conv workload is absent")
    cases = []
    for row in selected:
        manifest = workloads / row["manifest"]
        if sha256(manifest) != row["manifest_sha256"]:
            raise ValueError("Shared Conv manifest changed")
        cases.append(prepare_case(runner, manifest.parent, out / "cases" / row["name"],
                                  args.ia_cache_blocks,args.ps_frames,args.ps_storage_rows,
                                  args.s16_output_banks,args.schedule,args.dataflow,args.rhs_layout,
                                  args.ia_reuse,args.w_reuse,args.dma_max_bytes,args.bus_width,args.read_beat_cycles))
    build_dir = out / "sim"
    build_dir.mkdir(exist_ok=True)
    if args.skip_build:
        build = json.loads((build_dir / "build.json").read_text())
        if build["returncode"] or build["cache_sets"] != args.cache_sets or build["cache_policy"] != args.cache_policy:
            raise ValueError("Compiled Conv profile differs")
        if build.get("dma_max_bytes", 1024) != args.dma_max_bytes or build.get("bus_width", 32) != args.bus_width:
            raise ValueError("Compiled DMA transaction limit differs from requested limit")
        if build.get("read_beat_cycles", 2) != args.read_beat_cycles:
            raise ValueError("Compiled memory read throughput differs from requested throughput")
        if (build.get("first_read_latency", 3) != args.first_read_latency or
                build.get("memory_timing", "legacy") != args.memory_timing):
            raise ValueError("Compiled memory latency differs from requested latency")
        if any(build.get(key) != value for key,value in (
            ("ia_cache_blocks",args.ia_cache_blocks),("ps_frames",args.ps_frames),
            ("ps_storage_rows",args.ps_storage_rows),("s16_output_banks_max",args.s16_output_banks))):
            raise ValueError("Compiled matrix storage capacities differ")
        expected_defines = (["-DCOMMON_WINDOWED_INPUT"] if args.windowed else []) + (["-DCOMMON_PREFETCH_INPUT"] if args.prefetch else [])
        if build.get("comparison_defines", []) != expected_defines:
            raise ValueError("Compiled window and prefetch configuration differs")
        for path, digest in build["source_sha256"].items():
            if sha256(repository / path) != digest:
                raise ValueError("Compiled NPU sources differ")
        for path, digest in build["comparison_source_sha256"].items():
            if sha256(Path(path)) != digest:
                raise ValueError("Compiled Conv test sources differ")
        binary = build_dir / "obj/Vtb_common_conv"
    else:
        binary = build_comparison(runner, repository, build_dir, args,
                                  Path(__file__).resolve().with_name("tb_common_conv.sv"), "tb_common_conv")
    logs = []
    for row in cases:
        case_out = out / "cases" / row["name"]
        command = [str(binary), "+CONFIG=" + str(case_out / "config.mem"),
                   "+INIT=" + str(case_out / "init.mem"), "+GOLDEN=" + str(case_out / "golden.mem"),
                   "+NO_RANDOM_WAIT", "+NPU_UTIL_TRACE", "+NPU_UTIL_SUMMARY"]
        returncode = runner.command(command, case_out / "run.log", timeout=900)
        log = (case_out / "run.log").read_text()
        logs.append(log)
        measured, timing = records(log, "COMMON_CONV_PASS"), records(log, "COMMON_TIMING")
        row["command"], row["returncode"] = command, returncode
        row["passed"] = returncode == 0 and len(measured) == 1 and len(timing) == 1
        if row["passed"]:
            row["measurement"], row["timing"] = measured[0], timing[0]
            if measured[0]["cycles"] != timing[0]["done"]:
                raise ValueError("Conv timing counters disagree")
            if timing[0]["read_latency_min"] < args.first_read_latency:
                raise ValueError("Observed AXI response precedes the configured synchronous latency")
            if max(timing[0]["read_burst_bytes_max"], timing[0]["write_burst_bytes_max"]) > args.dma_max_bytes:
                raise ValueError("Observed AXI transaction exceeds the configured DMA limit")
            row["utilization"] = records(log, "[NPU_UTIL]")
            row["controller"] = records(log, "[NPU_CTRL_UTIL]")
            row["useful_macs_per_wall_cycle"] = row["useful_macs"] / measured[0]["cycles"]
        else:
            print(log[-6000:])
            break
    (out / "run.log").write_text("\n".join(logs))
    passed = all(row.get("passed", False) for row in cases)
    result = {"passed": passed, "source_repository": str(repository),
              "source_commit": subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip(),
              "build_manifest_sha256": sha256(build_dir / "build.json"), "binary_sha256": sha256(binary),
              "workload_catalogue_sha256": sha256(workloads / "workloads.json"),
              "schedule_source_sha256": {name: sha256(Path(__file__).resolve().parents[2] / name)
                  for name in ("drivers/dsa_schedule.h", "veri/top_regression/host_schedule.py")},
              "profile": {"array": [16, 16], "depthwise_vector_pes": 8, "operand_datapath_bits": 16,
                          "external_operand_bits": 8, "accumulator_bits": 32, "bus_bits": args.bus_width,
                          "dma_max_bytes": args.dma_max_bytes, "bus_width": args.bus_width,
                          "ia_cache_blocks":args.ia_cache_blocks,"ps_frames":args.ps_frames,
                          "ps_storage_rows":args.ps_storage_rows,"s16_output_banks_max":args.s16_output_banks,
                          "cache_sets": args.cache_sets, "cache_ways": 2, "cache_line_bytes": 16,
                          "cache_policy": args.cache_policy, "read_outstanding": 4, "write_outstanding": 4,
                          "windowed_input": args.windowed, "input_prefetch": args.prefetch,
                          "matrix_schedule": args.schedule, "requested_matrix_dataflow": args.dataflow,
                          "requested_matrix_rhs_layout": args.rhs_layout,
                          "depthwise_input_configuration": "The selected production vector engine derives its DMA input mode from the spatial operation; in the shared-cache implementation it enables windowed input and prefetch internally",
                          "cold_start": "Every case is a separate simulator process with complete DUT reset",
                          "memory": memory_profile(args),
                          "timing": "Accepted launch through done_valid, including hardware input gathering, DMA, calculation, quantization and all output write responses; no host preparation"},
              "cases": cases}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": passed, "cases": sum(row.get("passed", False) for row in cases),
                      "result": str(out / "summary.json")}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
