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
from planner_profile import normalize_profile, profile_signature, capability_expectations

sys.path.insert(0, str(ROOT / "test/model_benchmark"))
from verify_integer_graph import limits, load_schema

HERE = Path(__file__).resolve().parent
INPUT, WEIGHT, BIAS, MULTIPLIER, SHIFT, OUTPUT = (0x10000, 0x20000, 0x30000, 0x31000, 0x32000, 0x40000)
DENSE_LAYERS = (("mnist_cnn", 5), ("mnist_cnn", 6), ("mobilenet_v1_vww", 29),
                ("ds_cnn_kws", 11), ("resnet8_cifar10", 14))


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
    options = node["options"]
    if node["op"] == "FULLY_CONNECTED":
        rows = math.prod(node["output_shapes"][0][:-1])
        reduction, output_channels, direct = weight_depth, weight_rows, True
    elif node["op"] == "CONV_2D":
        _, ih, iw, channels = node["input_shapes"][0]
        _, oh, ow, output_channels = node["output_shapes"][0]
        kh, kw = options["kernel_h"], options["kernel_w"]
        sh, sw = options["stride_h"], options["stride_w"]
        dh, dw = options.get("dilation_h_factor", 1), options.get("dilation_w_factor", 1)
        ph = max(0, (oh - 1) * sh + (kh - 1) * dh + 1 - ih) // 2 if options["padding"] == "SAME" else 0
        pw = max(0, (ow - 1) * sw + (kw - 1) * dw + 1 - iw) // 2 if options["padding"] == "SAME" else 0
        direct = bench.direct_pointwise(node)
        rows, reduction = oh * ow, kh * kw * channels
    else:
        raise ValueError(f"Unsupported sweep operator: {node['op']}")
    input_offset = -metadata[node["inputs"][0]]["zero_points"][0]
    weight_offsets = set(metadata[node["inputs"][1]]["zero_points"])
    if len(weight_offsets) != 1:
        raise ValueError("The NPU requires one weight zero point")
    weight_offset = -next(iter(weight_offsets))
    output_offset = metadata[node["outputs"][0]]["zero_points"][0]
    activation_min, activation_max = limits(metadata[node["outputs"][0]], options["fused_activation_function"])
    per_channel = len(parameters["multipliers"]) > 1
    if len(parameters["multipliers"]) != len(parameters["shifts"]) or len(parameters["multipliers"]) not in (1, output_channels):
        raise ValueError("Quantization parameters do not match the output channels")
    registers = {
        0x010: INPUT, 0x014: WEIGHT, 0x018: OUTPUT, 0x01c: BIAS,
        0x020: rows, 0x024: reduction, 0x028: output_channels,
        0x02c: reduction if direct else math.ceil(reduction / 16) * 32,
        0x030: reduction, 0x034: output_channels,
        0x038: input_offset if direct else 0, 0x03c: weight_offset, 0x040: output_offset,
        0x044: MULTIPLIER if per_channel else parameters["multipliers"][0],
        0x048: SHIFT if per_channel else parameters["shifts"][0],
        0x04c: activation_min, 0x050: activation_max}
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
    return dict(model=model_name, operator_index=index, operator_name=node["op"], sample=sample_index,
                model_sha256=manifest["model"]["sha256"], input_sha256=input_record["sha256"],
                output_sha256=expected["sha256"], rows=rows, reduction=reduction, cols=output_channels,
                input_bytes=len(source), weight_bytes=len(weight), output_bytes=len(golden),
                direct=direct, per_channel=per_channel, input_offset=input_offset,
                weight_offset=weight_offset, weight_layout="tile_packed_16x16",
                registers=registers, regions=regions, golden=golden)


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


def dense_plans(case, hardware):
    """Cover useful tile groups, each distinct frame height, and bank splits."""
    row_tiles, col_tiles = math.ceil(case["rows"] / 16), math.ceil(case["cols"] / 16)
    if row_tiles != 1:
        raise ValueError("Dense sweep candidates require a single input row tile")
    limit = 1 << (max(1, col_tiles) - 1).bit_length()
    powers = [1 << shift for shift in range(limit.bit_length())]
    candidates = []
    for banks in (1, 2, 4):
        if not hardware["shared_ia_bank_mask"] & (1 << banks):
            continue
        for mode in (0, 1):
            for extent in powers:
                r, w = (extent, 1) if mode else (1, extent)
                for control in (1, 0, 15, 14, *([7, 6] if r > 1 else []), *([11, 10] if r > 2 else [])):
                    candidates.append((banks, mode, r, w, control))
    # First compare one-read WS and IS for the widest layer.
    priority = [(1, 0, 1, powers[-1], control) for control in (1, 0)]
    priority += [(1, 1, powers[-1], 1, control) for control in (1, 0)]
    return list(dict.fromkeys([*priority, *candidates]))


def run_plan(binary, out, fw, case, values, latency, hardware=None):
    banks, mode, r, w, control = values
    if hardware is None:
        manifest = json.loads((Path(binary).resolve().parents[1] / "build.json").read_text())
        hardware = normalize_profile(manifest, root=ROOT, literal_bound=bool(control & 0x30),
                                     ram_fixed_lat=latency)
    if hardware["memory_timing"]["ram_fixed_lat"] != latency:
        raise ValueError("Requested memory timing differs from the planner profile")
    case_id = case.get("case_id", f"{case['model']}_op{case['operator_index']}")
    name = f"{case_id}_ia{banks}_is{mode}_r{r}_w{w}_ps{control}"
    directory = out / "cases" / name
    directory.mkdir(parents=True, exist_ok=True)
    stream, stationary = (case["cols"], case["rows"]) if mode else (case["rows"], case["cols"])
    row_tiles, col_tiles = math.ceil(stream / 16), math.ceil(stationary / 16)
    registers = dict(case["registers"])
    registers.update({0x054: r, 0x058: w, 0x05c: mode,
                      0x060: math.ceil(row_tiles / r), 0x064: (row_tiles - 1) % r + 1,
                      0x068: math.ceil(col_tiles / w), 0x06c: (col_tiles - 1) % w + 1,
                      0x108: banks, 0x120: control})
    ctrl = (4 if case["per_channel"] else 0) | 16 | 1024 | (8 if mode else 0) | (0 if case["direct"] else 2 | 64)
    config = [0x504c414e, ctrl, registers[0x018], case["output_bytes"], len(registers)]
    config += [value for pair in registers.items() for value in pair]
    expected = capability_expectations(hardware)
    config += [len(expected), *[value for triple in expected for value in triple]]
    bench.overlay(directory / "data.mem", [*case["regions"], (0x1e0000, words(config))])
    metadata = {key: value for key, value in case.items() if key not in ("regions", "golden")}
    metadata.update(ia_banks=banks, is_mode=mode, r=r, w=w, ps_control=control, ram_fixed_lat=latency,
        planner_hardware_profile_sha256=profile_signature(hardware),
        memory_timing=hardware["memory_timing"],
        ps_directory_bits_per_row=hardware["ps_directory_bits_per_row"])
    bench.write_json(directory / "case.json", metadata)
    result = simulator.run_sim(binary, directory, out / "firmware/cpu.mem", data_mem=directory / "data.mem",
        result_addr=fw["result_address"], result_words=4, output_addr_word=2, output_bytes_word=3,
        timeout_cycles=10000000, timeout_seconds=120, ram_fixed_lat=latency,
        extra_plusargs=[f"+PS_EVENTS={directory / 'ps_events.txt'}",
                       f"+INPUT_ADDR={registers[0x010]:x}", f"+INPUT_BYTES={case['input_bytes']}",
                       f"+INPUT_FILE={directory / 'input_after.bin'}",
                       f"+MODEL_ADDR={registers[0x014]:x}", f"+MODEL_BYTES={case['weight_bytes']}",
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
    if record["job"]:
        job = record["job"]
        record["ps_compact_rows"] = job["ps_rows"] - job["ps_raw_rows"]
        record["ps_payload_compression_ratio"] = 4 * job["ps_rows"] / job["ps_write_words"] if job["ps_write_words"] else None
        record["ps_average_words_per_row"] = job["ps_write_words"] / job["ps_rows"] if job["ps_rows"] else None
        record["ps_raw_fraction"] = job["ps_raw_rows"] / job["ps_rows"] if job["ps_rows"] else None
        directory_bits = hardware["ps_directory_bits_per_row"]
        encoded_bits = 128 * job["ps_write_words"] + directory_bits * job["ps_rows"]
        record["ps_record_compression_ratio"] = (512 + directory_bits) * job["ps_rows"] / encoded_bits if encoded_bits else None
        record["ps_ratio_to_raw_payload_with_directory"] = 512 * job["ps_rows"] / encoded_bits if encoded_bits else None
    bench.write_json(directory / "result.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gcc", required=True)
    parser.add_argument("--host-cc", default="gcc")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--suite", choices=("conv", "dense"), default="conv")
    parser.add_argument("--layers", nargs="+", help="Optional model:index selection within the suite")
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
    hardware = normalize_profile(manifest, root=ROOT, ram_fixed_lat=args.latency)
    fw = firmware(out / "firmware", args.gcc)
    layers = DENSE_LAYERS if args.suite == "dense" else (("mobilenet_v1_vww", 14), ("resnet8_cifar10", 4))
    if args.layers:
        selected = set(args.layers)
        known = {f"{model}:{index}" for model, index in layers}
        if selected - known:
            parser.error(f"Unknown suite layers: {sorted(selected - known)}")
        layers = [(model, index) for model, index in layers if f"{model}:{index}" in selected]
    cases = [tensor_case(args.prepared.resolve(), model, index, args.sample) for model, index in layers]
    from sweep_dense_shapes import build_planner, candidates, PLAN
    library, planner = build_planner(out / "planner", args.host_cc, hardware)
    work = []
    for case in cases:
        case["case_id"] = f"{case['model']}_op{case['operator_index']}"
        records, _ = candidates(library, case, "legal")
        legal = {tuple(record[key] for key in PLAN) for record in records}
        proposed = dense_plans(case, hardware) if args.suite == "dense" else plans(case["model"])
        selected = [plan for plan in proposed if plan in legal]
        if not selected:
            raise RuntimeError("No requested plan fits the selected hardware profile")
        work += [(case, plan) for plan in selected]
    results = []
    with ThreadPoolExecutor(max_workers=args.run_jobs) as executor:
        for future in as_completed([executor.submit(run_plan, binary, out, fw, case, plan, args.latency, hardware)
                                    for case, plan in work]):
            result = future.result()
            results.append(result)
            print(json.dumps({**{key: result[key] for key in ("name", "passed", "cpu_cycles")},
                              **{key: result["job"].get(key) for key in
                                 ("task_cycles", "ps_rows", "ps_write_words", "ps_wait_cycles")}}), flush=True)
    report = dict(passed=all(row["passed"] for row in results), expected_cases=len(work),
                  completed_cases=len(results), suite=args.suite, sample=args.sample,
                  hardware_profile=manifest["profile"], simulator_sha256=digest(binary),
                  firmware_elf_sha256=fw["elf_sha256"], ram_fixed_lat=args.latency,
                  ps_word_bytes=16, planner=planner, planner_hardware_profile=hardware,
                  planner_hardware_profile_sha256=profile_signature(hardware), results=results)
    bench.write_json(out / "summary.json", report)
    with (out / "plans.csv").open("w", newline="") as stream:
        fields = ("model", "operator_index", "sample", "operator_name", "rows", "reduction", "cols",
                  "ia_banks", "is_mode", "r", "w", "ps_control", "per_channel",
                  "cpu_cycles", "task_cycles", "read_bytes", "ia_read_bytes", "weight_read_bytes",
                  "ar", "rbeats", "array_rows", "ps_wait_cycles", "ps_rows", "ps_raw_rows",
                  "ps_compact_rows", "ps_write_words", "ps_read_words",
                  "ps_payload_compression_ratio", "ps_average_words_per_row",
                  "ps_raw_fraction", "ps_record_compression_ratio", "ps_ratio_to_raw_payload_with_directory",
                  "frame_commands", "frame_pressure_events", "early_finish_frames", "passed")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in sorted(results, key=lambda value: (value["model"], value["operator_index"], value["job"]["task_cycles"])):
            values = {**result, **result["job"]}
            writer.writerow({key: values[key] for key in fields})
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
