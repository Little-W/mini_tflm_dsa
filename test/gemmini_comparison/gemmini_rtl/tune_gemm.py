#!/usr/bin/env python3
"""Measure legal official Gemmini GEMM schedules with shared arithmetic and memory."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from read_traffic import command_read_traffic


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("command_generator", HERE.parent / "gemmini_command_trace/generate.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def ceil_div(a, b):
    return (a + b - 1) // b


def legal_tiles(case, config, flow):
    """Enumerate the exact bounds checked by official tiled_matmul()."""
    dim = config["dim"]
    mi, nj, kk = (ceil_div(case[key], dim) for key in ("m", "n", "k"))
    divisor = 2 if flow == "ws" else 1
    sp_rows = config["bank_num"] * config["bank_rows"] // divisor
    acc_rows = config["acc_rows"] // divisor
    for i in range(1, mi + 1):
        for j in range(1, nj + 1):
            if i * j * dim > acc_rows:
                continue
            for k in range(1, min(kk, sp_rows // ((i + j) * dim)) + 1):
                yield i, j, k


def traffic_bound(case, config, flow, tile):
    """Conservative payload bound from official outer-loop operand reuse."""
    m, n, k = (case[key] for key in ("m", "n", "k"))
    dim = config["dim"]
    i0, j0, k0 = (ceil_div(value, blocks * dim) for value, blocks in zip((m, n, k), tile))
    reuse_a = flow == "ws" and i0 * k0 <= 2
    reuse_b = flow == "ws" and j0 * k0 <= 2
    read_bytes = m * k * (1 if reuse_a else j0) + k * n * (1 if reuse_b else i0) + n * 4 * i0
    cycles = max(ceil_div(read_bytes, 2), ceil_div(m * n, 4), ceil_div(m * n * k, dim * dim))
    return {"minimum_read_payload_bytes": read_bytes, "minimum_cycles": cycles,
            "outer_iterations": i0 * j0 * k0}


def candidate_name(flow, tile):
    return flow + ("_auto" if tile is None else "_" + "_".join(map(str, tile)))


def rewrite_argument(command, name, value):
    result = list(command)
    index = result.index(name)
    result[index + 1] = str(value)
    return result


def import_measured_candidates(args, hardware, case, base, work, build_hash):
    """Reuse completed schedules with the same build, tensors and command bytes."""
    imported = []
    for summary_path, traces_path in args.seed:
        summary = json.loads(summary_path.read_text())
        suite_passed = summary.get("passed", all(row.get("passed", False) for row in summary["cases"]))
        if not suite_passed or summary.get("build_manifest_sha256") != build_hash:
            raise ValueError("Measured seeds must have passed with this exact hardware build")
        matches = [row for row in summary["cases"] if row["name"] == case["name"]]
        if not matches:
            continue
        measured = matches[0]
        source = traces_path / case["name"]
        metadata = json.loads((source / "metadata.json").read_text())
        if metadata.get("transpose", "none") != args.transpose:
            continue
        if metadata.get("tensor_alignment_bytes", 64) != args.tensor_alignment:
            continue
        flow = metadata["emission"]["dataflow"]
        if flow not in args.flows:
            continue
        tile = metadata["emission"].get("explicit_tile")
        if tile is not None and all(value == 0 for value in tile):
            tile = None
        if tile is not None and tuple(tile) not in set(legal_tiles(case, metadata["emission"]["config"], flow)):
            raise ValueError("Measured seed has a tile outside the enumerated legal bounds")
        if (metadata["workload_manifest_sha256"] != base["workload_manifest_sha256"] or
                metadata["memory_sha256"] != base["memory_sha256"] or
                metadata["expected_output_sha256"] != base["expected_output_sha256"] or
                measured["workload_manifest_sha256"] != base["workload_manifest_sha256"] or
                measured["observed_output_sha256"] != base["expected_output_sha256"] or
                not measured["passed"] or measured["outside_output_mismatches"] or
                not measured["memory_drained"]):
            raise ValueError("Measured seed arithmetic or memory differs from this workload")
        commands = source / "commands.txt"
        command_hash = generator.digest(commands)
        if command_hash != measured["commands_sha256"] or command_hash != metadata["commands_sha256"]:
            raise ValueError("Measured seed command checksum differs")
        traffic = command_read_traffic(generator.read_trace(commands),
                                       hardware["configuration"]["dma_max_bytes"])
        if any(traffic[key] != measured[key] for key in ("read_bytes", "read_requests")):
            raise ValueError("Measured seed traffic differs from the validated model")
        key = candidate_name(flow, tile)
        directory = work / key
        record_path = directory / "record.json"
        if record_path.exists():
            continue
        directory.mkdir(exist_ok=True)
        shutil.copyfile(commands, directory / "commands.txt")
        write_json(directory / "emission.json", metadata["emission"])
        write_json(directory / "result.json", measured)
        record = dict(name=key, flow=flow, tile=tile, status="passed", cycles=measured["cycles"],
                      expanded_read_traffic=traffic, commands_sha256=command_hash,
                      observed_output_sha256=measured["observed_output_sha256"], result=measured,
                      measured_seed=dict(summary=str(summary_path.resolve()),
                                         summary_sha256=generator.digest(summary_path),
                                         metadata=str((source / "metadata.json").resolve()),
                                         metadata_sha256=generator.digest(source / "metadata.json")))
        write_json(record_path, record)
        imported.append(record)
    return imported


def search_case(args, profile, source_path, built, hardware):
    case = json.loads(source_path.read_text())
    name = case["name"]
    work = args.output / profile / name
    work.mkdir(parents=True, exist_ok=True)
    generator.generate_case(work / "input", source_path.parent, case, built, 0x10000,
                            "ws", transpose=args.transpose, tensor_alignment=args.tensor_alignment)
    base = json.loads((work / "input/metadata.json").read_text())
    source_hash = generator.digest(source_path)
    simulator = Path(hardware["simulator"])
    dma_max_bytes = hardware["configuration"]["dma_max_bytes"]
    build_hash = generator.digest(args.build_root / ("generated_" + profile) / "build_manifest.json")
    binding = {"simulator_sha256": hardware["simulator_sha256"],
               "build_manifest_sha256": build_hash,
               "workload_manifest_sha256": source_hash,
               "trace_generator_sha256": built["binary_sha256"],
               "transpose": args.transpose, "hardware_dma_max_bytes": dma_max_bytes,
               "tensor_alignment_bytes": args.tensor_alignment,
               "traffic_model_sha256": generator.digest(HERE / "read_traffic.py"),
               "traffic_validations": hardware["traffic_validations"],
               "seed_summaries": {str(summary.resolve()): generator.digest(summary)
                                  for summary, _ in args.seed}}
    previous_binding = work / "binding.json"
    if previous_binding.exists() and json.loads(previous_binding.read_text()) != binding:
        raise ValueError(f"{profile}/{name}: search inputs changed; choose a new output directory")
    write_json(previous_binding, binding)
    candidates = []
    for flow in args.flows:
        candidates.append((flow, None, {"minimum_cycles": 0, "outer_iterations": 0}))
        options = [(flow, tile, traffic_bound(case, built["config"], flow, tile))
                   for tile in legal_tiles(case, built["config"], flow)]
        options.sort(key=lambda x: (x[2]["minimum_cycles"], x[2]["outer_iterations"],
                                    -math.prod(x[1]), x[1]))
        if args.candidates_per_flow:
            options = options[:args.candidates_per_flow]
        candidates.extend(options)
    best_path = work / "best.json"
    best = json.loads(best_path.read_text()) if best_path.exists() else None
    for measured in import_measured_candidates(args, hardware, case, base, work, build_hash):
        if best is None or measured["cycles"] < best["cycles"]:
            best = measured
            write_json(best_path, dict(best, workload_manifest_sha256=source_hash,
                                      build_manifest_sha256=build_hash))
    records = []
    progress_path = work / "progress.json"
    for flow, tile, bound in candidates:
        key = candidate_name(flow, tile)
        directory = work / key
        directory.mkdir(exist_ok=True)
        record_path = directory / "record.json"
        if record_path.exists():
            record = json.loads(record_path.read_text())
            if record["status"] == "passed" and (best is None or record["cycles"] < best["cycles"]):
                best = record
            records.append(record)
            continue
        record = {"name": key, "flow": flow, "tile": tile, "bound": bound}
        if best is not None and bound["minimum_cycles"] >= best["cycles"]:
            record.update(status="excluded_by_payload_bound", reference_cycles=best["cycles"])
            write_json(record_path, record)
            records.append(record)
            continue
        command = rewrite_argument(base["generator_command"], "--commands", directory / "commands.txt")
        command = rewrite_argument(command, "--metadata", directory / "emission.json")
        command = rewrite_argument(command, "--flow", flow)
        if tile is not None:
            command += ["--tile", ",".join(map(str, tile))]
        emission_run = subprocess.run(command, text=True, capture_output=True)
        (directory / "generation.log").write_text(emission_run.stdout + emission_run.stderr)
        if emission_run.returncode:
            raise RuntimeError(f"{profile}/{name}/{key}: official scheduler rejected legal bounds\n" +
                               emission_run.stdout + emission_run.stderr)
        emission = json.loads((directory / "emission.json").read_text())
        commands = generator.read_trace(directory / "commands.txt")
        generator.validate_trace(commands, case, base["tensors"], flow, built["config"])
        traffic = command_read_traffic(commands, dma_max_bytes=dma_max_bytes)
        record["expanded_read_traffic"] = traffic
        if best is not None and traffic["read_service_floor_cycles"] >= best["cycles"]:
            record.update(status="excluded_by_read_service_bound", reference_cycles=best["cycles"],
                          commands_sha256=generator.digest(directory / "commands.txt"))
            write_json(record_path, record)
            records.append(record)
            continue
        result_file = directory / "result.json"
        output = base["tensors"]["output"]
        simulator_command = [str(simulator), str(work / "input/memory.bin"), str(base["memory_base"]),
                             str(directory / "commands.txt"), str(output["address"]), str(output["bytes"]),
                             str(work / "input/expected_s8.bin"), str(emission["timed_start_record"]),
                             str(result_file), "2"]
        environment = os.environ.copy()
        if best is not None:
            environment["GEMMINI_MAX_CYCLES"] = str(best["cycles"] + 64)
        started = time.monotonic()
        execution = subprocess.run(simulator_command, text=True, capture_output=True, env=environment)
        (directory / "simulation.log").write_text(execution.stdout + execution.stderr)
        record.update(commands_sha256=generator.digest(directory / "commands.txt"),
                      host_elapsed_seconds=time.monotonic() - started,
                      rtl_cycle_limit=environment.get("GEMMINI_MAX_CYCLES"))
        if execution.returncode:
            if "Simulation cycle limit exceeded" in execution.stderr and best is not None:
                record.update(status="excluded_by_elapsed_cycles", reference_cycles=best["cycles"])
            else:
                record.update(status="rtl_failure", returncode=execution.returncode,
                              diagnostic=(execution.stdout + execution.stderr)[-3000:])
        else:
            result = json.loads(result_file.read_text())
            if any(result[key] != traffic[key] for key in ("read_bytes", "read_requests")):
                raise RuntimeError(f"{profile}/{name}/{key}: read-transaction expansion differs from RTL")
            output_hash = generator.digest(result_file.with_suffix(".output.bin"))
            if (not result["passed"] or result["outside_output_mismatches"] or
                    not result["memory_drained"] or output_hash != base["expected_output_sha256"]):
                raise RuntimeError(f"{profile}/{name}/{key}: output or memory validation failed")
            record.update(status="passed", cycles=result["cycles"],
                          observed_output_sha256=output_hash, result=result)
            if best is None or record["cycles"] < best["cycles"]:
                best = record
                write_json(work / "best.json", dict(best, workload_manifest_sha256=source_hash,
                                                    build_manifest_sha256=build_hash))
        write_json(record_path, record)
        records.append(record)
        write_json(progress_path, {"name": name, "profile": profile, "best": best,
                                  "processed_candidates": len(records), "candidate_count": len(candidates)})
    if best is None:
        raise RuntimeError(f"{profile}/{name}: no correct official schedule completed")
    destination = args.output / profile / "best_traces" / name
    generator.generate_case(destination, source_path.parent, case, built, 0x10000,
                            best["flow"], tuple(best["tile"]) if best["tile"] is not None else None,
                            args.transpose, tensor_alignment=args.tensor_alignment)
    if generator.digest(destination / "commands.txt") != best["commands_sha256"]:
        raise RuntimeError("Selected official trace differs from its measured command stream")
    statuses = {key: sum(r["status"] == key for r in records) for key in
                ["passed", "excluded_by_payload_bound", "excluded_by_read_service_bound",
                 "excluded_by_elapsed_cycles", "rtl_failure"]}
    report = {"name": name, "profile": profile, "shape": {k: case[k] for k in ("m", "n", "k")},
              "workload_manifest_sha256": source_hash, "build_manifest_sha256": build_hash,
              "candidate_count": len(candidates), "status_counts": statuses,
              "exhaustive_legal_tiles": args.candidates_per_flow == 0,
              "flows": args.flows, "transpose": args.transpose, "best": best,
              "hardware_dma_max_bytes": dma_max_bytes,
              "tensor_alignment_bytes": args.tensor_alignment,
              "software_max_bytes": built["config"]["max_bytes"],
              "traffic_model_sha256": generator.digest(HERE / "read_traffic.py"),
              "traffic_validations": hardware["traffic_validations"],
              "best_trace_metadata": str(destination / "metadata.json")}
    write_json(work / "summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gemmini-tests", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", default=["sp64_acc16", "sp32_acc32", "sp256_acc64"])
    parser.add_argument("--flows", nargs="+", choices=["ws", "os"], default=["ws", "os"])
    parser.add_argument("--transpose", choices=["none", "a", "b"], default="none")
    parser.add_argument("--tensor-alignment", type=int, default=64,
                        help="Power-of-two byte alignment of every tensor base address")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--traffic-validation", action="append", type=Path, default=[],
                        help="Completed traffic checks for this hardware build and model")
    parser.add_argument("--seed", action="append", nargs=2, type=Path, default=[],
                        metavar=("RESULTS_JSON", "TRACES_DIR"),
                        help="Reuse verified schedules from the same hardware build")
    parser.add_argument("--candidates-per-flow", type=int, default=8,
                        help="Test this many payload-ranked tiles per flow; 0 enumerates every legal tile")
    args = parser.parse_args()
    if args.jobs < 1 or args.candidates_per_flow < 0:
        parser.error("jobs must be positive and candidates-per-flow must be nonnegative")
    if args.tensor_alignment < 64 or args.tensor_alignment & (args.tensor_alignment - 1):
        parser.error("tensor-alignment must be a power of two of at least 64 bytes")
    if args.transpose != "none" and args.flows != ["ws"]:
        parser.error("Transposed layouts require --flows ws")
    args.output = args.output.resolve()
    args.build_root = args.build_root.resolve()
    args.workloads = args.workloads.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    catalogue = json.loads((args.workloads / "workloads.json").read_text())
    sources = [args.workloads / item["manifest"] for item in catalogue["cases"]
               if args.cases is None or item["name"] in args.cases]
    for item in catalogue["cases"]:
        if generator.digest(args.workloads / item["manifest"]) != item["manifest_sha256"]:
            raise ValueError("Workload catalogue checksum mismatch")
    jobs = []
    for profile in args.profiles:
        generated = args.build_root / ("generated_" + profile)
        hardware = json.loads((generated / "build_manifest.json").read_text())
        build_hash = generator.digest(generated / "build_manifest.json")
        model_hash = generator.digest(HERE / "read_traffic.py")
        verified = []
        for path in args.traffic_validation:
            report = json.loads(path.read_text())
            if (report.get("hardware_dma_max_bytes") == hardware["configuration"]["dma_max_bytes"] and
                    report.get("model_sha256") == model_hash and report.get("passed") and
                    report.get("checked_cases", 0) > 0 and
                    any(source.get("suite_passed") and source.get("build_manifest_sha256") == build_hash
                        for source in report.get("inputs", []))):
                verified.append(dict(path=str(path.resolve()), sha256=generator.digest(path),
                                     checked_cases=report["checked_cases"]))
        if not verified and hardware["configuration"]["dma_max_bytes"] != 64:
            raise ValueError("Measured read traffic must match this hardware build and model before searching")
        hardware["traffic_validations"] = verified
        if generator.digest(Path(hardware["simulator"])) != hardware["simulator_sha256"]:
            raise ValueError("Simulator checksum mismatch")
        if generator.digest(generated / "gemmini_params.h") != hardware["params_header_sha256"]:
            raise ValueError("Hardware parameter checksum mismatch")
        built = generator.build(args.output / profile / "trace_build", args.gemmini_tests.resolve(),
                                generated / "gemmini_params.h", "hardware-generated", "gcc")
        jobs.extend((profile, source, built, hardware) for source in sources)
    workload_bytes = {}
    for source in sources:
        workload = json.loads(source.read_text())
        workload_bytes[source] = ((workload["m"] + workload["n"]) * workload["k"] +
                                  4 * workload["n"])
    jobs.sort(key=lambda job: -workload_bytes[job[1]])
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(search_case, args, *job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            write_json(args.output / "results.json", {"search_complete": len(results) == len(jobs),
                       "completed_cases": len(results), "total_cases": len(jobs), "cases": results})
            print(json.dumps({"profile": result["profile"], "name": result["name"],
                              "cycles": result["best"]["cycles"], "flow": result["best"]["flow"],
                              "tile": result["best"]["tile"], "tested": result["status_counts"]}), flush=True)


if __name__ == "__main__":
    main()
