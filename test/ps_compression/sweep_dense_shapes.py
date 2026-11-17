#!/usr/bin/env python3
"""Measure batched Dense reuse using trained weights and independent INT32 references."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import ctypes
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np

from sweep_shared_plans import ROOT, HERE, DENSE_LAYERS, bench, digest, firmware, run_plan, tensor_case, words
from stream_soc_trace import event_digest
from planner_profile import normalize_profile, profile_header, profile_signature
from verify_integer_graph import requant

INPUT, WEIGHT, BIAS, MULTIPLIER, SHIFT, OUTPUT = (0x10000, 0x20000, 0x60000, 0x61000, 0x62000, 0x70000)
SOURCES = (("mnist_cnn", 5), ("mnist_cnn", 6), ("mobilenet_v1_vww", 29))
FIELDS = (
    "r", "w", "row_groups", "row_tail_tiles", "col_groups", "col_tail_tiles",
    "is_mode", "candidates", "estimated_cycles", "read_words", "read_requests",
    "write_words", "write_requests", "compute_cycles", "ps_payload_bytes",
    "ps_control", "ia_banks", "ia_bytes", "ps_bytes", "frame_rows", "predicted_resident_frames",
    "read_beats", "write_beats",
    "path", "force_raw", "adaptive_active", "planner_admitted", "ia_slots",
    "literal_record_bytes", "estimated_record_bytes", "micro_commands", "frame_count",
    "array_stream_cycles", "weight_shift_rows", "operand_read_bytes",
    "lhs_read_rounds", "rhs_read_rounds", "intermediate_ps_rows")
SCORE = ("estimated_cycles", "read_words", "read_requests", "compute_cycles", "write_requests", "ps_payload_bytes", "is_mode")
PLAN = ("ia_banks", "is_mode", "r", "w", "ps_control")
SCHEDULE_FIELDS = 23
CANDIDATE_FIELDS = len(FIELDS)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build_planner(out, compiler, hardware):
    out.mkdir(parents=True, exist_ok=True)
    source = HERE / "dense_plan_export.c"
    header = out / "hardware_profile.h"
    header.write_text(profile_header(hardware))
    tracked = [source, ROOT / "drivers/dsa_accel.c", *sorted((ROOT / "drivers").glob("*.h"))]
    before = {str(path.relative_to(ROOT)): digest(path) for path in tracked}
    library = out / "dense_plan_export.so"
    command = [compiler, "-std=c11", "-O2", "-fPIC", "-shared", "-Wall", "-Wextra", "-Werror",
               "-Wno-unused-function", "-fsanitize=undefined", "-fno-sanitize-recover=all",
               "-DDSA_MMIO_CUSTOM=1", "-DDSA_PS_COMPRESS=1",
               f"-DDSA_PS_POOL_BYTES={hardware['ps_pool_bytes']}", "-include", str(header),
               "-I", str(ROOT / "drivers"), str(source), "-o", str(library)]
    with (out / "compile.log").open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if any(digest(ROOT / name) != value for name, value in before.items()):
        raise RuntimeError("Planner source changed during compilation")
    report = dict(source_sha256=before, library_sha256=digest(library), compile_command=command,
                  literal_bound_capability=hardware["literal_bound_capability"],
                  hardware_profile=hardware, hardware_profile_sha256=profile_signature(hardware),
                  generated_header_sha256=digest(header))
    bench.write_json(out / "build.json", report)
    lib = ctypes.CDLL(str(library))
    lib.export_dense_candidates.argtypes = [ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint32]
    lib.export_dense_candidates.restype = ctypes.c_int
    lib.dense_set_weights.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    lib.dense_set_weights.restype = ctypes.c_int
    lib.dense_weight_bound.argtypes = [ctypes.POINTER(ctypes.c_int32)]
    lib.dense_weight_bound.restype = ctypes.c_uint32
    lib.dense_prepared_literal_bytes.argtypes = []
    lib.dense_prepared_literal_bytes.restype = ctypes.c_uint32
    lib.dense_set_parameters.argtypes = [ctypes.c_void_p, ctypes.c_uint32] * 3
    lib.dense_set_parameters.restype = ctypes.c_int
    lib.dense_profile_values.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
    lib.dense_profile_values.restype = ctypes.c_int
    observed = (ctypes.c_uint32 * 19)()
    if not lib.dense_profile_values(observed, len(observed)):
        raise RuntimeError("Unable to read the planner's effective hardware inputs")
    costs = hardware["planner_costs"]
    expected = [hardware["bus_width"], hardware["dma_max_bytes"],
                costs["read_beat_cycles"], costs["write_beat_cycles"],
                costs["read_request_cycles"], costs["write_request_cycles"],
                hardware["shared_total_bytes"], hardware["shared_bank_bytes"],
                hardware["shared_ia_bank_mask"], hardware["ps_directory_rows"],
                hardware["ps_caps"], hardware["ia_cache_bytes"], hardware["ps_pool_bytes"],
                hardware["matrix_output_banks"] & 65535, hardware["matrix_output_banks"] >> 16,
                hardware["memory_timing"]["ram_read_first_latency"], hardware["memory_timing"]["ram_fixed_lat"],
                costs["ia_tile_setup_cycles"], costs["quant_group_setup_cycles"]]
    if list(observed) != expected:
        raise RuntimeError(f"Prepared planner profile differs: {list(observed)} != {expected}")
    report["effective_profile_verified"] = True
    bench.write_json(out / "build.json", report)
    return lib, report


def candidates(lib, case, selection="critical"):
    values = [case["rows"], case["reduction"], case["cols"], case["input_offset"],
              case["weight_offset"], int(case["per_channel"]), 1, 1, 0, 0]
    config = (ctypes.c_int32 * len(values))(*values)
    raw_weights = case["regions"][1][1]
    blob = ctypes.create_string_buffer(raw_weights)
    if not lib.dense_set_weights(blob, len(raw_weights)):
        raise RuntimeError("Unable to supply actual trained weights to Prepare")
    parameters = [ctypes.create_string_buffer(case["regions"][index][1]) for index in (2, 3, 4)]
    sizes = [len(case["regions"][index][1]) for index in (2, 3, 4)]
    if not lib.dense_set_parameters(parameters[0], sizes[0], parameters[1], sizes[1], parameters[2], sizes[2]):
        raise RuntimeError("Unable to supply the actual bias and quantization parameters to Prepare")
    case["proven_ps_literal_bytes"] = lib.dense_weight_bound(config)
    case["ps_bound_source"] = "drivers/dsa_ps_bound.h:dsa_ps_bound_s8 over the supplied immutable packed weights and the complete corrected S8 input interval"
    case["ps_bound_weight_sha256"] = sha(raw_weights)
    if selection == "auto":
        plans, total_candidates = [], 0
        for raw in (1, 0):
            config[9] = raw
            selected, buffer = (ctypes.c_uint64 * SCHEDULE_FIELDS)(), (ctypes.c_uint64 * (CANDIDATE_FIELDS * 8192))()
            count = lib.export_dense_candidates(config, selected, buffer, 8192)
            if count <= 0:
                raise RuntimeError(f"Driver AUTO preparation failed: {case['case_id']}, policy={raw}, status={count}")
            plan = dict(zip(FIELDS[:SCHEDULE_FIELDS], selected))
            plan.update(force_raw=raw, selection="driver_auto",
                        prepared_literal_bytes=lib.dense_prepared_literal_bytes())
            if (raw or case["reduction"] > 16) and (plan["ps_control"] & 1) != raw:
                raise RuntimeError("Prepared policy differs from requested runtime storage mode")
            plans.append(plan)
            total_candidates += count
        case["driver_auto_plans"] = plans
        return plans, total_candidates
    selected, buffer = (ctypes.c_uint64 * SCHEDULE_FIELDS)(), (ctypes.c_uint64 * (CANDIDATE_FIELDS * 8192))()
    count = lib.export_dense_candidates(config, selected, buffer, 8192)
    if count <= 0:
        raise RuntimeError(f"Candidate enumeration failed for {case['case_id']}: {count}")
    if selection == "legal":
        return [dict(zip(FIELDS, buffer[index*CANDIDATE_FIELDS:(index+1)*CANDIDATE_FIELDS]))
                for index in range(count)], count
    groups, effective = {}, []
    for index in range(count):
        row = dict(zip(FIELDS, buffer[index * CANDIDATE_FIELDS:(index + 1) * CANDIDATE_FIELDS]))
        stream, stationary = (case["cols"], case["rows"]) if row["is_mode"] else (case["rows"], case["cols"])
        row_limit = 1 << (max(1, math.ceil(stream / 16)) - 1).bit_length()
        col_limit = 1 << (max(1, math.ceil(stationary / 16)) - 1).bit_length()
        if row["r"] > row_limit or row["w"] > col_limit:
            continue
        effective.append(row)
        key = (row["ia_banks"], row["is_mode"], row["force_raw"], bool(row["path"]))
        if key not in groups or tuple(row[k] for k in SCORE) < tuple(groups[key][k] for k in SCORE):
            groups[key] = row
    unique = {tuple(row[key] for key in PLAN): row for row in groups.values()}
    if selection == "complete_raw":
        center = case["refinement_plan"]
        nearby_r = {max(1, center["r"] // 2), center["r"], center["r"] * 2}
        nearby_w = {max(1, center["w"] // 2), max(1, center["w"] - 1), center["w"], center["w"] + 1, center["w"] * 2}
        for row in effective:
            if row["force_raw"] or not row["path"] or (row["r"] in nearby_r and row["w"] in nearby_w):
                unique[tuple(row[key] for key in PLAN)] = row
    if not unique:
        raise RuntimeError("No useful legal candidate")
    return list(unique.values()), count


def unpack_weights(case):
    n, k = case["cols"], case["reduction"]
    tiles = math.ceil(k / 16)
    packed = np.frombuffer(case["regions"][1][1], dtype=np.int8)
    output = np.empty((n, k), dtype=np.int8)
    for row in range(n):
        for column in range(k):
            output[row, column] = packed[((row // 16) * tiles + column // 16) * 256 + (row % 16) * 16 + column % 16]
    return output


def pack_weights(weight):
    n, k = weight.shape
    tiles = math.ceil(k / 16)
    output = np.zeros(math.ceil(n / 16) * tiles * 256, dtype=np.int8)
    for row in range(n):
        for column in range(k):
            output[((row // 16) * tiles + column // 16) * 256 + (row % 16) * 16 + column % 16] = weight[row, column]
    return output.tobytes()


def expanded_case(first, second, rows, columns=None):
    native_n, k = first["cols"], first["reduction"]
    n = native_n if columns is None else columns
    channel_map = np.arange(n) % native_n
    native_weight = unpack_weights(first)
    weight = native_weight[channel_map]
    input_rows = [np.frombuffer(case["regions"][0][1], dtype=np.int8).reshape(-1, k)[0]
                  for case in (first, second)]
    source = np.stack([input_rows[row % 2] for row in range(rows)])
    bias = np.frombuffer(first["regions"][2][1], dtype="<i4")[channel_map]
    multipliers = np.frombuffer(first["regions"][3][1], dtype="<i4")
    shifts = np.frombuffer(first["regions"][4][1], dtype="<i4")
    if first["per_channel"]:
        multipliers, shifts = multipliers[channel_map], shifts[channel_map]
    parameters = dict(multipliers=multipliers.astype(np.int64).tolist(), shifts=shifts.astype(np.int64).tolist())
    accum = (source.astype(np.int64) + first["input_offset"]) @ (weight.astype(np.int64) + first["weight_offset"]).T
    accum += bias.astype(np.int64)
    accum = (accum + (1 << 31)) % (1 << 32) - (1 << 31)
    output = np.clip(requant(accum, parameters) + first["registers"][0x040],
                     first["registers"][0x04c], first["registers"][0x050]).astype(np.int8)
    for sample, original in enumerate((first, second)):
        if sample < rows:
            expected = np.frombuffer(original["golden"], dtype=np.int8)[channel_map]
            if not np.array_equal(output[sample], expected):
                raise RuntimeError("Independent matrix reference differs from the prepared sample")
    kind = "batched_trained_dense" if columns is None else "representative_expanded_channels"
    case_id = f"{first['model']}_op{first['operator_index']}_{kind}_m{rows}_k{k}_n{n}"
    registers = dict(first["registers"])
    registers.update({0x010: INPUT, 0x014: WEIGHT, 0x018: OUTPUT, 0x01c: BIAS,
                      0x020: rows, 0x028: n, 0x034: n,
                      0x044: MULTIPLIER if first["per_channel"] else int(multipliers[0]),
                      0x048: SHIFT if first["per_channel"] else int(shifts[0])})
    regions = [(INPUT, source.tobytes()), (WEIGHT, pack_weights(weight)), (BIAS, bias.tobytes()),
               (MULTIPLIER, words(parameters["multipliers"])), (SHIFT, words(parameters["shifts"])),
               (OUTPUT, bytes([0x5a]) * output.size)]
    for (address, raw), (next_address, _) in zip(regions, [*regions[1:], (0x1e0000, b"")]):
        if address + len(raw) > next_address:
            raise ValueError("Expanded tensor exceeds its memory allocation")
    result = {key: value for key, value in first.items() if key not in ("regions", "golden", "registers")}
    result.update(case_id=case_id, reference_kind=kind, rows=rows, cols=n,
                  input_bytes=len(regions[0][1]), weight_bytes=len(regions[1][1]), output_bytes=output.size,
                  input_sha256=sha(regions[0][1]), weight_sha256=sha(regions[1][1]), output_sha256=sha(output.tobytes()),
                  input_construction="Alternate prepared samples 0 and 1 by row",
                  input_source_sha256=[case["input_sha256"] for case in (first, second)],
                  native_weight_shape=[native_n, k], output_channel_map=channel_map.tolist(),
                  weight_construction="Preserve trained weights" if columns is None else "Repeat trained output-channel rows with their bias and quantization parameters",
                  reference="Independent INT64 matrix product, modulo INT32, and quotient/remainder nearest-even requantization",
                  registers=registers, regions=regions, golden=output.tobytes())
    return result


def actual_case(prepared, model, index, sample):
    result = tensor_case(prepared, model, index, sample)
    result.update(case_id=f"{model}_op{index}_actual_s{sample}", reference_kind="actual_trained_dense",
                  weight_sha256=sha(result["regions"][1][1]), input_construction="Prepared activation tensor",
                  weight_construction="Original trained weights", input_samples=[sample])
    return result


def summarize(out, results, settings):
    comparisons = []
    for case_id in sorted({row["case_id"] for row in results}):
        rows = [row for row in results if row["case_id"] == case_id]
        sides, chosen_records = {}, {}
        for raw, policy in ((1, "raw"), (0, "adaptive")):
            selected = [row for row in rows if row["ps_control"] & 1 == raw]
            if selected:
                chosen = min(selected, key=lambda row: (row["job"]["task_cycles"], row["ia_banks"], row["ps_control"]))
                chosen_records[policy] = chosen
                sides[policy] = {key: chosen[key] for key in ("name", *PLAN,
                    "ps_payload_compression_ratio", "ps_record_compression_ratio", "ps_ratio_to_raw_payload_with_directory", "ps_raw_fraction")}
                sides[policy].update(chosen["job"])
        if len(sides) == 2:
            speedup = sides["raw"]["task_cycles"] / sides["adaptive"]["task_cycles"]
            raw, adaptive = chosen_records["raw"], chosen_records["adaptive"]
            checks = dict(same_hardware=raw["simulator_sha256"] == adaptive["simulator_sha256"] == settings["simulator_sha256"],
                          same_firmware=raw["firmware_elf_sha256"] == adaptive["firmware_elf_sha256"] == settings["firmware_elf_sha256"],
                          same_memory_timing=raw["memory_timing"] == adaptive["memory_timing"] == settings["planner_hardware_profile"]["memory_timing"],
                          same_planner_profile=raw["planner_hardware_profile_sha256"] == adaptive["planner_hardware_profile_sha256"] == settings["planner_hardware_profile_sha256"],
                          same_tensors=all(raw[key] == adaptive[key] for key in ("input_sha256", "weight_sha256", "output_sha256", "registers")),
                          correct_outputs=raw["passed"] and adaptive["passed"])
            comparisons.append(dict(case_id=case_id, reference_kind=rows[0]["reference_kind"],
                rows=rows[0]["rows"], reduction=rows[0]["reduction"], cols=rows[0]["cols"],
                measured_candidates=len(rows), speedup=speedup, target_met=speedup >= 1.2,
                checks=checks, passed=all(checks.values()), **sides))
    report = dict(passed=bool(results) and all(row["passed"] for row in results) and all(pair["passed"] for pair in comparisons),
                  complete=len(results) == settings["expected_cases"] and len(comparisons) == settings["tensor_shapes"],
                  completed_cases=len(results), settings=settings, comparisons=comparisons, results=results)
    bench.write_json(out / "summary.json", report)
    fields = ("case_id", "reference_kind", "rows", "reduction", "cols", *PLAN,
              "task_cycles", "cpu_cycles", "read_bytes", "ia_read_bytes", "weight_read_bytes", "ar", "rbeats",
              "ps_rows", "ps_raw_rows", "ps_write_words", "ps_read_words", "ps_wait_cycles",
              "ps_payload_compression_ratio", "ps_record_compression_ratio", "ps_ratio_to_raw_payload_with_directory",
              "ps_raw_fraction", "frame_commands", "frame_pressure_events", "early_finish_frames", "passed")
    with (out / "plans.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in sorted(results, key=lambda row: (row["case_id"], row["job"]["task_cycles"])):
            values = {**result, **result["job"]}
            writer.writerow({key: values[key] for key in fields})
    return report


def restore_result(out, case, plan, settings):
    banks, mode, r, w, control = plan
    name = f"{case['case_id']}_ia{banks}_is{mode}_r{r}_w{w}_ps{control}"
    directory = out / "cases" / name
    try:
        record = json.loads((directory / "result.json").read_text())
        if (not record["passed"] or not all(record["checks"].values()) or
            tuple(record[key] for key in PLAN) != plan or
            record["simulator_sha256"] != settings["simulator_sha256"] or
            record["firmware_elf_sha256"] != settings["firmware_elf_sha256"] or
            record["ram_fixed_lat"] != settings["ram_fixed_lat"] or
            record["planner_hardware_profile_sha256"] != settings["planner_hardware_profile_sha256"] or
            any(record[key] != case[key] for key in ("case_id", "input_sha256", "weight_sha256", "output_sha256", "rows", "reduction", "cols")) or
            record["registers"] != {str(key): value for key, value in case["registers"].items()} or
            (directory / "output.bin").read_bytes() != case["golden"] or
            digest(directory / "run.log") != record["run_log_sha256"] or
            event_digest(directory / "ps_events.txt") != record["ps"]["event_file_sha256"]):
            return None
        return record
    except (OSError, KeyError, ValueError, EOFError):
        return None


def archive_case(out, record):
    if not record["passed"]:
        return
    directory = out / "cases" / record["name"]
    source = directory / "ps_events.txt"
    if source.exists():
        raw = source.read_bytes()
        if sha(raw) != record["ps"]["event_file_sha256"]:
            raise RuntimeError("PS events changed after validation")
        compressed = gzip.compress(raw, compresslevel=3, mtime=0)
        if gzip.decompress(compressed) != raw:
            raise RuntimeError("PS event compression did not preserve the validated bytes")
        target = source.with_name(source.name + ".gz")
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(compressed)
        temporary.replace(target)
        source.unlink()
    for name in ("data.mem", "input_after.bin", "weight_after.bin"):
        (directory / name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gcc", required=True)
    parser.add_argument("--host-cc", default="gcc")
    parser.add_argument("--suite", choices=("actual", "batch", "representative", "both"), default="both")
    parser.add_argument("--selection", choices=("auto", "critical", "complete_raw"), default="critical")
    parser.add_argument("--literal-bound", action="store_true", help="Advertise and use the hardware's certified S16/S24 capacity fields")
    parser.add_argument("--samples", nargs="+", type=int, choices=(0, 1), default=[0, 1])
    parser.add_argument("--layers", nargs="+", help="Optional model:index selection")
    parser.add_argument("--refine-from", type=Path, help="Refine shapes that met 1.2x in a previous sweep summary")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--use-recorded-simulator", action="store_true",
                        help="Use the verified executable and recorded build hashes after the working RTL changes")
    parser.add_argument("--rows", nargs="+", type=int, default=[4, 16, 64])
    parser.add_argument("--representative-rows", type=int, default=64)
    parser.add_argument("--run-jobs", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--latency", type=int, default=0)
    args = parser.parse_args()
    if any(row <= 0 for row in [*args.rows, args.representative_rows]):
        parser.error("Row counts must be positive")
    if args.selection == "complete_raw" and args.refine_from is None:
        parser.error("complete_raw selection requires --refine-from")
    if args.literal_bound and args.use_recorded_simulator:
        parser.error("A literal-bound run requires the simulator's current verified sources")
    started = time.monotonic()
    out, sim_dir = args.out.resolve(), args.sim.resolve()
    manifest = json.loads((sim_dir / "build.json").read_text())
    if args.use_recorded_simulator:
        if not manifest.get("sources_unchanged_during_build") or not manifest.get("source_sha256"):
            raise RuntimeError("The simulator lacks a successful recorded source check")
    else:
        bench.verify_sources(manifest)
    binary = sim_dir / "obj/Vtb_model_benchmark"
    if manifest["returncode"] or digest(binary) != manifest["binary_sha256"]:
        raise RuntimeError("Simulator executable differs from its build manifest")
    hardware = normalize_profile(manifest, root=ROOT, literal_bound=args.literal_bound,
                                 ram_fixed_lat=args.latency)
    if hardware["raw_only"]:
        raise RuntimeError("The comparison requires runtime-selectable RAW and compressed storage")
    previous_settings = json.loads((out / "settings.json").read_text()) if args.resume else None
    if previous_settings:
        if (previous_settings["simulator_sha256"] != digest(binary) or
            previous_settings["hardware_profile"] != manifest["profile"] or
            previous_settings["ram_fixed_lat"] != args.latency or
            previous_settings["planner_hardware_profile_sha256"] != profile_signature(hardware) or
            previous_settings.get("literal_bound_capability", False) != args.literal_bound or
            previous_settings["selection"] != args.selection or previous_settings["suite"] != args.suite):
            raise RuntimeError("Resume hardware, memory timing, or candidate selection differs")
        lib, planner = None, previous_settings["planner"]
        fw = json.loads((out / "firmware/firmware.json").read_text())
        bench.verify_sources(fw)
        if (digest(out / "firmware/cpu.mem") != fw["mem_sha256"] or
            digest(out / "firmware/cpu.elf") != fw["elf_sha256"] or
            fw["elf_sha256"] != previous_settings["firmware_elf_sha256"]):
            raise RuntimeError("Resume firmware differs from the recorded executable")
    else:
        lib, planner = build_planner(out / "planner", args.host_cc, hardware)
        fw = firmware(out / "firmware", args.gcc)
    cases = []
    source_layers = DENSE_LAYERS if args.suite == "actual" else SOURCES
    if args.layers:
        available = {f"{model}:{index}" for model, index in source_layers}
        if set(args.layers) - available:
            parser.error("Unknown layer selection")
        source_layers = [(model, index) for model, index in source_layers if f"{model}:{index}" in args.layers]
    for model, index in source_layers:
        if args.suite == "actual":
            cases += [actual_case(args.prepared.resolve(), model, index, sample) for sample in args.samples]
            continue
        first, second = [tensor_case(args.prepared.resolve(), model, index, sample) for sample in (0, 1)]
        if args.suite in ("batch", "both"):
            cases += [expanded_case(first, second, rows) for rows in args.rows]
        if args.suite in ("representative", "both"):
            cases += [expanded_case(first, second, args.representative_rows, columns) for columns in (64, 128, 256)]
    if args.refine_from:
        previous = json.loads(args.refine_from.read_text())
        centers = {row["case_id"]: row["adaptive"] for row in previous["comparisons"] if row["target_met"]}
        cases = [case for case in cases if case["case_id"] in centers]
        for case in cases:
            case["refinement_plan"] = {key: centers[case["case_id"]][key] for key in PLAN}
        if not cases:
            parser.error("No selected shapes met the speedup target in the supplied summary")
    work, candidate_records = [], []
    previous_candidates = {row["case_id"]: row for row in previous_settings["candidates"]} if previous_settings else {}
    if previous_settings and set(previous_candidates) != {case["case_id"] for case in cases}:
        raise RuntimeError("Resume tensor shapes differ from the recorded search")
    for case in cases:
        if previous_settings:
            saved = previous_candidates[case["case_id"]]
            selected, legal_count = saved["selected"], saved["legal_candidates"]
        else:
            selected, legal_count = candidates(lib, case, args.selection)
        candidate_records.append(dict(case_id=case["case_id"], legal_candidates=legal_count, selected=selected))
        work += [(case, tuple(row[key] for key in PLAN)) for row in selected]
    settings = dict(suite=args.suite, expected_cases=len(work), tensor_shapes=len(cases),
                    hardware_profile=manifest["profile"], simulator_sha256=digest(binary),
                    firmware_elf_sha256=fw["elf_sha256"], planner=planner, candidates=candidate_records,
                    ram_fixed_lat=args.latency, ps_word_bits=128,
                    ps_directory_bits_per_row=hardware["ps_directory_bits_per_row"],
                    planner_hardware_profile=hardware,
                    planner_hardware_profile_sha256=profile_signature(hardware),
                    literal_bound_capability=args.literal_bound,
                    selection=args.selection,
                    candidate_rule=("All distinct effective RAW R/W/IA/WSIS long/frame candidates, all adaptive long candidates, and neighboring adaptive frame candidates"
                                    if args.selection == "complete_raw" else
                                    "Production dsa_prepare_matmul_s8 AUTO schedule for each runtime PS policy" if args.selection == "auto" else
                                    "Lowest production estimate per IA split, WS/IS direction, RAW/adaptive request, and long/frame path"),
                    oversized_r_w_aliases_removed=True,
                    source_sha256={str(path.relative_to(ROOT)): digest(path) for path in (Path(__file__).resolve(), HERE / "sweep_shared_plans.py", HERE / "stream_soc_trace.py", HERE / "planner_profile.py")},
                    simulator_source_validation="recorded_build" if args.use_recorded_simulator else "working_sources",
                    simulator_build_sha256=digest(sim_dir / "build.json"),
                    ps_event_storage="gzip after exact event-byte verification",
                    measurement="NPU task cycles; expanded tensors are independent of complete-network totals")
    bench.write_json(out / "settings.json", settings)
    print(json.dumps(dict(shapes=len(cases), cases=len(work))), flush=True)
    results, pending = [], []
    for case, plan in work:
        saved = restore_result(out, case, plan, settings) if args.resume else None
        if saved is None:
            pending.append((case, plan))
        else:
            results.append(saved)
    settings["resumed_cases"] = len(results)
    print(json.dumps(dict(resumed_cases=len(results), pending_cases=len(pending))), flush=True)
    with ThreadPoolExecutor(max_workers=args.run_jobs) as executor:
        futures = [executor.submit(run_plan, binary, out, fw, case, plan, args.latency, hardware) for case, plan in pending]
        for future in as_completed(futures):
            result = future.result()
            archive_case(out, result)
            results.append(result)
            print(json.dumps(dict(name=result["name"], passed=result["passed"],
                                  task_cycles=result["job"]["task_cycles"], ps_words=result["job"]["ps_write_words"])), flush=True)
    settings["elapsed_seconds"] = time.monotonic() - started
    report = summarize(out, results, settings)
    print(json.dumps(dict(passed=report["passed"], cases=len(results),
        comparisons=[dict(case_id=row["case_id"], raw_cycles=row["raw"]["task_cycles"],
                          adaptive_cycles=row["adaptive"]["task_cycles"], speedup=row["speedup"],
                          target_met=row["target_met"]) for row in report["comparisons"]])), flush=True)
    if not report["passed"] or not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
