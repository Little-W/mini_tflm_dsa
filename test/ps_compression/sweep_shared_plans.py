#!/usr/bin/env python3
"""Measure selected reuse plans using trained tensors and the network simulator."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import math
from pathlib import Path
import struct
import subprocess
import sys

from run_soc import ROOT, bench, builder, digest, parse_jobs, simulator, verify_stream

sys.path.insert(0, str(ROOT / "test/model_benchmark"))
from verify_integer_graph import limits, load_schema

HERE = Path(__file__).resolve().parent
INPUT, WEIGHT, BIAS, MULTIPLIER, SHIFT, OUTPUT = (0x10000, 0x20000, 0x30000, 0x31000, 0x32000, 0x40000)


def words(values):
    return b"".join(struct.pack("<I", int(value) & 0xffffffff) for value in values)


def firmware(out, gcc):
    out.mkdir(parents=True, exist_ok=True)
    source = HERE / "plan_sweep_firmware.c"
    startup, linker = ROOT / "veri/soc_csrc/start.S", ROOT / "veri/soc_csrc/link.ld"
    elf = out / "cpu.elf"
    builder.run([gcc, "-march=rv32im_zicsr", "-mabi=ilp32", "-O3", "-nostdlib", "-nostartfiles",
                 "-ffreestanding", "-fno-builtin", "-T", linker, startup, source, "-o", elf], out / "build.log")
    builder.run([builder.compiler_sibling(gcc, "objcopy"), "-O", "binary", elf, out / "cpu.bin"], out / "objcopy.log")
    raw = (out / "cpu.bin").read_bytes()
    raw += bytes((-len(raw)) % 4)
    (out / "cpu.mem").write_text("@00000000\n" + "".join(f"{v[0]:08x}\n" for v in struct.iter_unpack("<I", raw)))
    listing = subprocess.check_output([builder.compiler_sibling(gcc, "nm"), elf], text=True)
    symbols = {line.split()[-1]: int(line.split()[0], 16) for line in listing.splitlines()
               if len(line.split()) == 3}
    report = dict(elf_sha256=digest(elf), mem_sha256=digest(out / "cpu.mem"),
                  result_address=symbols["plan_sweep_result"],
                  source_sha256={str(path.relative_to(ROOT)): digest(path) for path in (source, startup, linker)})
    bench.write_json(out / "firmware.json", report)
    return report


def tensor_case(prepared, model_name, index, sample_index):
    directory = prepared / model_name
    manifest = json.loads((directory / "manifest.json").read_text())
    node = next(node for node in manifest["graph"]["nodes"] if node["index"] == index)
    sample = next(sample for sample in manifest["samples"] if sample["sample_index"] == sample_index)
    expected = next(row for row in sample["nodes"] if row["index"] == index)
    metadata = {tensor["index"]: tensor for tensor in manifest["graph"]["tensors"]}
    model = load_schema().Model.GetRootAsModel(bench.checked_payload(directory, manifest["model"]), 0)
    graph = model.Subgraphs(0)
    records = [sample["input"], *sample["nodes"]]
    input_record = next(record for record in records if record["tensor_index"] == node["inputs"][0])
    source = bench.checked_payload(directory, input_record)

    def constant(tensor_index):
        buffer = model.Buffers(graph.Tensors(tensor_index).Buffer())
        return buffer.DataAsNumpy().tobytes()

    linear_weight = constant(node["inputs"][1])
    weight_shape = node["input_shapes"][1]
    weight_rows, weight_depth = weight_shape[0], math.prod(weight_shape[1:])
    reduction_tiles = math.ceil(weight_depth / 16)
    packed = bytearray(math.ceil(weight_rows / 16) * reduction_tiles * 256)
    for row in range(weight_rows):
        for column in range(weight_depth):
            target = ((row // 16) * reduction_tiles + column // 16) * 256 + (row % 16) * 16 + column % 16
            packed[target] = linear_weight[row * weight_depth + column]
    weight = bytes(packed)
    bias = constant(node["inputs"][2])
    parameters = expected["integer_parameters"]
    golden = bench.checked_payload(directory, expected)
    _, ih, iw, channels = node["input_shapes"][0]
    _, oh, ow, output_channels = node["output_shapes"][0]
    options = node["options"]
    kh, kw = options["kernel_h"], options["kernel_w"]
    sh, sw = options["stride_h"], options["stride_w"]
    dh, dw = options.get("dilation_h_factor", 1), options.get("dilation_w_factor", 1)
    ph = max(0, (oh - 1) * sh + (kh - 1) * dh + 1 - ih) // 2 if options["padding"] == "SAME" else 0
    pw = max(0, (ow - 1) * sw + (kw - 1) * dw + 1 - iw) // 2 if options["padding"] == "SAME" else 0
    direct = bench.direct_pointwise(node)
    rows, reduction = oh * ow, kh * kw * channels
    input_offset = -metadata[node["inputs"][0]]["zero_points"][0]
    output_offset = metadata[node["outputs"][0]]["zero_points"][0]
    activation_min, activation_max = limits(metadata[node["outputs"][0]], options["fused_activation_function"])
    registers = {
        0x010: INPUT, 0x014: WEIGHT, 0x018: OUTPUT, 0x01c: BIAS,
        0x020: rows, 0x024: reduction, 0x028: output_channels,
        0x02c: reduction if direct else math.ceil(reduction / 16) * 32,
        0x030: reduction, 0x034: output_channels,
        0x038: input_offset if direct else 0, 0x03c: 0, 0x040: output_offset,
        0x044: MULTIPLIER, 0x048: SHIFT, 0x04c: activation_min, 0x050: activation_max}
    if not direct:
        def pair(lo, hi):
            return lo | hi << 16
        registers.update({0x074: INPUT, 0x078: pair(ih, iw), 0x07c: pair(channels, channels),
                          0x080: 0, 0x084: pair(kh, kw), 0x088: pair(oh, ow),
                          0x08c: pair(sh, sw), 0x090: pair(dh, dw), 0x094: pair(ph, pw),
                          0x098: input_offset})
    regions = [(INPUT, source), (WEIGHT, weight), (BIAS, bias),
               (MULTIPLIER, words(parameters["multipliers"])), (SHIFT, words(parameters["shifts"])),
               (OUTPUT, bytes([0x5a]) * len(golden))]
    for address, raw in regions:
        if len(raw) > 0x10000:
            raise ValueError("Tensor exceeds its sweep memory allocation")
    return dict(model=model_name, operator_index=index, sample=sample_index,
                model_sha256=manifest["model"]["sha256"], input_sha256=input_record["sha256"],
                output_sha256=expected["sha256"], rows=rows, reduction=reduction, cols=output_channels,
                input_bytes=len(source), weight_bytes=len(weight), output_bytes=len(golden),
                direct=direct, weight_layout="tile_packed_16x16", registers=registers, regions=regions, golden=golden)


def plans(model):
    # Each tuple is IA banks, WS/IS, R, W, PS control.
    if model == "mobilenet_v1_vww":
        return [(1,0,4,4,1), (1,0,4,4,0), (1,0,4,4,14), (4,0,4,1,14),
                (1,0,4,8,14), (2,0,4,4,0), (2,0,4,4,14), (2,0,8,2,0),
                (4,0,4,2,14), (4,0,4,4,14), (1,1,4,2,1), (1,1,4,2,0),
                (2,1,8,1,1), (4,1,8,2,14), (4,1,8,4,14)]
    return [(1,1,2,4,1), (1,1,2,8,0), (1,1,2,4,0), (1,1,2,8,14),
            (1,1,2,4,14), (2,1,2,4,1), (2,1,2,4,0), (4,1,2,4,14),
            (1,1,1,8,1), (1,1,1,16,0), (2,0,4,1,1), (2,0,4,2,1),
            (2,0,8,1,1), (4,0,8,2,14)]


def run_plan(binary, out, fw, case, values, latency):
    banks, mode, r, w, control = values
    name = f"{case['model']}_op{case['operator_index']}_ia{banks}_is{mode}_r{r}_w{w}_ps{control}"
    directory = out / "cases" / name
    directory.mkdir(parents=True, exist_ok=True)
    stream, stationary = (case["cols"], case["rows"]) if mode else (case["rows"], case["cols"])
    row_tiles, col_tiles = math.ceil(stream / 16), math.ceil(stationary / 16)
    registers = dict(case["registers"])
    registers.update({0x054: r, 0x058: w, 0x05c: mode,
                      0x060: math.ceil(row_tiles / r), 0x064: (row_tiles - 1) % r + 1,
                      0x068: math.ceil(col_tiles / w), 0x06c: (col_tiles - 1) % w + 1,
                      0x108: banks, 0x120: control})
    ctrl = 4 | 16 | 1024 | (8 if mode else 0) | (0 if case["direct"] else 2 | 64)
    config = [0x504c414e, ctrl, OUTPUT, case["output_bytes"], len(registers)]
    config += [value for pair in registers.items() for value in pair]
    bench.overlay(directory / "data.mem", [*case["regions"], (0x1e0000, words(config))])
    metadata = {key: value for key, value in case.items() if key not in ("regions", "golden")}
    metadata.update(ia_banks=banks, is_mode=mode, r=r, w=w, ps_control=control, ram_fixed_lat=latency)
    bench.write_json(directory / "case.json", metadata)
    result = simulator.run_sim(binary, directory, out / "firmware/cpu.mem", data_mem=directory / "data.mem",
        result_addr=fw["result_address"], result_words=4, output_addr_word=2, output_bytes_word=3,
        timeout_cycles=10000000, timeout_seconds=120, ram_fixed_lat=latency,
        extra_plusargs=[f"+PS_EVENTS={directory / 'ps_events.txt'}",
                       f"+INPUT_ADDR={INPUT:x}", f"+INPUT_BYTES={case['input_bytes']}",
                       f"+INPUT_FILE={directory / 'input_after.bin'}",
                       f"+MODEL_ADDR={WEIGHT:x}", f"+MODEL_BYTES={case['weight_bytes']}",
                       f"+MODEL_FILE={directory / 'weight_after.bin'}"])
    jobs = parse_jobs((directory / "run.log").read_text())
    stream_check = verify_stream(directory / "ps_events.txt", (directory / "run.log").read_text())
    checks = dict(simulator=result["passed"], one_job=len(jobs) == 1,
                  output=(directory / "output.bin").read_bytes() == case["golden"],
                  input=(directory / "input_after.bin").read_bytes() == case["regions"][0][1],
                  weight=(directory / "weight_after.bin").read_bytes() == case["regions"][1][1],
                  partial_sums=stream_check["passed"], firmware_unchanged=digest(out / "firmware/cpu.mem") == fw["mem_sha256"])
    record = dict(name=name, **metadata, passed=all(checks.values()), checks=checks,
                  cpu_cycles=result.get("result_words", [0])[0], job=jobs[0] if len(jobs) == 1 else {},
                  ps=stream_check, firmware_elf_sha256=fw["elf_sha256"],
                  simulator_sha256=digest(binary), run_log_sha256=digest(directory / "run.log"))
    bench.write_json(directory / "result.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gcc", required=True)
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--run-jobs", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--latency", type=int, default=0)
    args = parser.parse_args()
    out = args.out.resolve()
    sim_dir = args.sim.resolve()
    manifest = json.loads((sim_dir / "build.json").read_text())
    bench.verify_sources(manifest)
    binary = sim_dir / "obj/Vtb_model_benchmark"
    if manifest["returncode"] or digest(binary) != manifest["binary_sha256"]:
        raise RuntimeError("Simulator executable differs from its build manifest")
    if manifest["profile"]["shared_total_bytes"] != 14336 or manifest["profile"]["conv_cache_data_bytes"] != 4096:
        raise RuntimeError("Expected the 14 KiB shared-memory SoC with 4 KiB im2col cache")
    fw = firmware(out / "firmware", args.gcc)
    cases = [tensor_case(args.prepared.resolve(), model, index, args.sample)
             for model, index in (("mobilenet_v1_vww", 14), ("resnet8_cifar10", 4))]
    work = [(case, plan) for case in cases for plan in plans(case["model"])]
    results = []
    with ThreadPoolExecutor(max_workers=args.run_jobs) as executor:
        for future in as_completed([executor.submit(run_plan, binary, out, fw, case, plan, args.latency)
                                    for case, plan in work]):
            result = future.result()
            results.append(result)
            print(json.dumps({key: result[key] for key in ("name", "passed", "cpu_cycles")}), flush=True)
    report = dict(passed=all(row["passed"] for row in results), expected_cases=len(work),
                  completed_cases=len(results), hardware_profile=manifest["profile"], results=results)
    bench.write_json(out / "summary.json", report)
    with (out / "plans.csv").open("w", newline="") as stream:
        fields = ("model", "operator_index", "ia_banks", "is_mode", "r", "w", "ps_control",
                  "cpu_cycles", "task_cycles", "read_bytes", "ia_read_bytes", "weight_read_bytes",
                  "frame_commands", "frame_pressure_events", "early_finish_frames", "passed")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in sorted(results, key=lambda value: (value["model"], value["job"]["task_cycles"])):
            values = {**result, **result["job"]}
            writer.writerow({key: values[key] for key in fields})
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
