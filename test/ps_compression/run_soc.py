#!/usr/bin/env python3
"""Measure lossless PS capacity reuse on complete trained CNNs in the same SoC."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import importlib.util
import json
import math
import time
from pathlib import Path
import re
import sys

from stream_soc_trace import verify as verify_stream

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BENCH = ROOT / "test/model_benchmark"
sys.path.insert(0, str(BENCH))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


bench = module("ps_network_runner", BENCH / "run.py")
builder = module("ps_network_firmware", BENCH / "build_firmware.py")
simulator = module("ps_network_simulator", BENCH / "build_sim.py")
model_data = module("ps_network_models", BENCH / "model_data.py")
FIELDS = ("task_cycles", "core_cycles", "read_bytes", "ia_read_bytes", "weight_read_bytes",
          "ar", "rbeats", "write_bytes", "ps_wait_cycles", "array_rows", "ps_write_words",
          "ps_read_words", "ps_rows", "ps_raw_rows")
KIND_NAMES = {0: "gemm", 1: "conv", 2: "depthwise", 3: "pool", 4: "vector", 5: "add", 6: "softmax"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_jobs(log):
    jobs, pending = [], {}
    for line in log.splitlines():
        if not line.startswith(("PS_JOB ", "PS_JOB_END ")):
            continue
        row = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)}
        if line.startswith("PS_JOB "):
            if pending:
                raise ValueError("Overlapping NPU tasks")
            pending = row
        else:
            if not pending or row["job"] != pending["job"]:
                raise ValueError("NPU completion has no matching task")
            jobs.append({**pending, **row})
            pending = {}
    if pending:
        raise ValueError("Incomplete NPU task")
    return jobs


def logical_layers(jobs, case):
    prepared = json.loads((Path(case["prepared_dir"]) / "manifest.json").read_text())
    supported = {"CONV_2D": "conv", "DEPTHWISE_CONV_2D": "depthwise",
                 "AVERAGE_POOL_2D": "pool", "MAX_POOL_2D": "pool",
                 "FULLY_CONNECTED": "dense", "ADD": "add", "SOFTMAX": "softmax"}
    expected = [(index, node) for index, node in enumerate(prepared["graph"]["nodes"])
                if node["op"] in supported]
    if len(jobs) != len(expected):
        raise ValueError("Hardware task count differs from the executable model operators")
    result = []
    for job, (index, node) in zip(jobs, expected):
        op = node["op"]
        physical_kind = (0 if bench.direct_pointwise(node) else 1) if op == "CONV_2D" else {
            "DEPTHWISE_CONV_2D": 2, "AVERAGE_POOL_2D": 3, "MAX_POOL_2D": 3,
            "FULLY_CONNECTED": 0, "ADD": 5, "SOFTMAX": 6}[op]
        if job["kind"] != physical_kind or job["error"] != 0:
            raise ValueError(f"Task {job['job']} does not match successful operator {index}: {op}")
        if op in ("CONV_2D", "FULLY_CONNECTED"):
            shape = node["input_shapes"][1]
            rows = math.prod(node["output_shapes"][0][:-1])
            reduction, columns = math.prod(shape[1:]), shape[0]
            if (job["k"], job["n"], job["m"]) != (rows, reduction, columns):
                raise ValueError(f"Matrix dimensions differ at operator {index}: {op}")
        matrix = op in ("CONV_2D", "FULLY_CONNECTED")
        item = {key: job[key] for key in FIELDS}
        item.update(kind=supported[op], physical_kind=KIND_NAMES[job["kind"]],
                    operator_index=index, operator_name=op,
                    rows=job["k"] if matrix else 0, reduction=job["n"] if matrix else 0,
                    cols=job["m"] if matrix else 0,
                    start_cycle=job["cycle"], end_cycle=job["end_cycle"],
                    elapsed_cycles=job["end_cycle"]-job["cycle"], retry_count=0,
                    attempts=[{key: job[key] for key in ("is", "r", "w", "error", "task_cycles")}],
                    ps_control=job["ps_control"] if matrix else 0,
                    frame_commands=job["frame_commands"] if matrix else 0,
                    frame_pressure_events=job["frame_pressure_events"] if matrix else 0,
                    early_finish_frames=job["early_finish_frames"] if matrix else 0,
                    ia_banks=job.get("ia_banks", 0) if matrix else 0,
                    ia_bytes=job.get("ia_bytes", 0) if matrix else 0,
                    ps_bytes=job.get("ps_bytes", 0) if matrix else 0)
        result.append(item)
    return result


def validate_result(result, configuration, binary, runner_hash):
    directory = Path(result["case_dir"])
    log = (directory / "run.log").read_text()
    result["configuration"] = configuration
    result["sim_binary_sha256"] = digest(binary)
    result["jobs"] = parse_jobs(log)
    case = json.loads((directory / "case.json").read_text())
    result["gemm_layers"] = logical_layers(result["jobs"], case)
    cpu_layers = {layer["index"]: layer for layer in result.get("layers", [])}
    for layer in result["gemm_layers"]:
        cpu_layer = cpu_layers.get(layer["operator_index"])
        layer["cpu_operator_cycles"] = cpu_layer["cycles"] if cpu_layer else None
    result["ps"] = verify_stream(directory / "ps_events.txt", log)
    result["checks"]["all_ps_int32_rows"] = result["ps"]["passed"]
    result["checks"]["job_observations"] = len(result["jobs"]) == result["network"]["jobs"]
    result["checks"]["no_operator_restarts"] = result["network"]["capacity_retries"] == 0
    result["checks"]["no_hardware_errors"] = result["network"]["npu_errors"] == 0
    if configuration == "raw":
        result["checks"]["raw_payload_rows"] = all(j["ps_rows"] == j["ps_raw_rows"] for j in result["jobs"])
    result["runner_sha256"] = runner_hash
    result["checks"]["runner_unchanged"] = digest(Path(__file__)) == runner_hash
    result["passed"] = all(result["checks"].values())
    result["run_log_sha256"] = digest(directory / "run.log")
    bench.write_json(directory / "result.json", result)
    return result


def summarize(out, results, settings):
    lookup = {(r["configuration"], r["model_id"], r["kind"], r["sample_index"]): r for r in results}
    pairs, comparisons = [], []
    for key, adaptive in sorted(lookup.items()):
        config, model, kind, sample = key
        raw = lookup.get(("raw", model, kind, sample))
        if config != "adaptive" or raw is None:
            continue
        checks = {
            "same_hardware": raw["sim_binary_sha256"] == adaptive["sim_binary_sha256"],
            "same_memory_timing": raw["ram_fixed_lat"] == adaptive["ram_fixed_lat"],
            "same_firmware": raw["firmware_elf_sha256"] == adaptive["firmware_elf_sha256"],
            "same_model_and_input": raw["model"]["sha256"] == adaptive["model"]["sha256"] and
                                    raw["input_sha256"] == adaptive["input_sha256"],
            "all_outputs_equal": raw["output_comparison"]["actual_sha256"] ==
                                 adaptive["output_comparison"]["actual_sha256"],
            "same_operators": [(l["kind"], l["rows"], l["reduction"], l["cols"]) for l in raw["gemm_layers"]] ==
                              [(l["kind"], l["rows"], l["reduction"], l["cols"]) for l in adaptive["gemm_layers"]]}
        if kind == "trace":
            checks["all_node_outputs_equal"] = ([t["comparison"]["actual_sha256"] for t in raw["trace"]] ==
                                                [t["comparison"]["actual_sha256"] for t in adaptive["trace"]])
        pairs.append({"model": model, "kind": kind, "sample": sample, "checks": checks, "passed": all(checks.values())})
    for model in [*settings["models"], "all_models"]:
        selected = [(m, sample) for m in settings["models"] if model in (m, "all_models")
                    for sample in settings["samples_by_model"][m]
                    if ("raw", m, "perf", sample) in lookup and ("adaptive", m, "perf", sample) in lookup]
        if not selected:
            continue
        for category in ("conv", "dense", "gemm_total", "inference"):
            sides = {}
            for config in ("raw", "adaptive"):
                records = [lookup[(config, m, "perf", sample)] for m, sample in selected]
                if category == "inference":
                    sides[config] = {"cycles": sum(r["result"]["invoke_cycles"] for r in records),
                                     "read_bytes": sum(r["network"]["npu_read_bytes"] for r in records),
                                     "initialization_cycles": sum(r["result"]["init_cycles"] for r in records),
                                     "planning_cycles": sum(r["result"]["planning_cycles"] for r in records),
                                     "retry_count": sum(r["network"]["capacity_retries"] for r in records)}
                else:
                    layers = [l for r in records for l in r["gemm_layers"]
                              if l["kind"] in (("conv", "dense") if category == "gemm_total" else (category,))]
                    sides[config] = {"cycles": sum(l["elapsed_cycles"] for l in layers),
                                     "retry_count": sum(l["retry_count"] for l in layers),
                                     **{key: sum(l[key] for l in layers) for key in FIELDS}}
            if sides["adaptive"]["cycles"]:
                ratio = sides["raw"]["cycles"] / sides["adaptive"]["cycles"]
                comparisons.append({"model": model, "category": category, "sample_pairs": selected, **sides,
                                    "speedup": ratio, "cycle_reduction_percent": 100 * (1 - 1 / ratio),
                                    "target_speedup": 1.20, "target_met": ratio >= 1.20})
    expected = sum(len(v) for v in settings["samples_by_model"].values()) * len(settings["configurations"]) * len(settings["kinds"])
    cpu_comparisons = []
    for model in [*settings["models"], "all_models"]:
        selected = [(m, sample) for m in settings["models"] if model in (m, "all_models")
                    for sample in settings["samples_by_model"][m]
                    if ("raw", m, "trace", sample) in lookup and ("adaptive", m, "trace", sample) in lookup]
        for category in ("conv", "dense", "gemm_total"):
            sides = {}
            for config in ("raw", "adaptive"):
                layers = [layer for m, sample in selected
                          for layer in lookup[(config, m, "trace", sample)]["gemm_layers"]
                          if layer["kind"] in (("conv", "dense") if category == "gemm_total" else (category,))]
                sides[config] = {"cycles": sum(layer["cpu_operator_cycles"] for layer in layers)}
            if sides["adaptive"]["cycles"]:
                cpu_comparisons.append({"model": model, "category": category, "sample_pairs": selected,
                                        "measurement": "trace_operator_begin_to_end", **sides,
                                        "speedup": sides["raw"]["cycles"] / sides["adaptive"]["cycles"]})
    report = {"format_version": 7, "passed": bool(results) and all(r["passed"] for r in results) and
              all(p["passed"] for p in pairs), "complete": len(results) == expected,
              "completed_cases": len(results), "expected_cases": expected, "settings": settings,
              "comparisons": comparisons, "cpu_operator_comparisons": cpu_comparisons,
              "output_pairs": pairs, "results": results}
    bench.write_json(out / "soc_summary.json", report)
    with (out / "comparison.csv").open("w", newline="") as stream:
        fields = ("model", "category", "samples", "raw_cycles", "adaptive_cycles",
                  "speedup", "cycle_reduction_percent", "target_speedup", "target_met")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in comparisons:
            writer.writerow({**{key: item[key] for key in fields if key in item},
                             "samples": len(item["sample_pairs"]),
                             "raw_cycles": item["raw"]["cycles"],
                             "adaptive_cycles": item["adaptive"]["cycles"]})
    with (out / "layers.csv").open("w", newline="") as stream:
        fields = ("model", "sample", "run_kind", "configuration", "operator_index",
                  "operator_name", "physical_kind", "rows", "reduction", "cols",
                  "cycles", "cpu_operator_cycles", "is_mode", "r", "w", "ia_banks", "ia_bytes", "ps_bytes",
                  "ps_control", "frame_commands", "pressure_events", "early_finish_frames",
                  "ps_rows", "ps_raw_rows", "ps_write_words", "ps_read_words", "read_bytes")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in sorted(results, key=lambda item: (item["model_id"], item["sample_index"],
                                                        item["kind"], item["configuration"])):
            for layer in result["gemm_layers"]:
                attempt = layer["attempts"][0]
                writer.writerow({**{key: layer[key] for key in fields if key in layer},
                                 "model": result["model_id"], "sample": result["sample_index"],
                                 "run_kind": result["kind"], "configuration": result["configuration"],
                                 "cycles": layer["elapsed_cycles"], "is_mode": attempt["is"],
                                 "r": attempt["r"], "w": attempt["w"],
                                 "pressure_events": layer["frame_pressure_events"]})
    with (out / "cpu_layers.csv").open("w", newline="") as stream:
        fields = ("model", "sample", "configuration", "operator_index", "operator_name",
                  "cpu_operator_cycles", "npu_busy_cycles", "cpu_mmio_reads", "cpu_mmio_write_bytes")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in sorted(results, key=lambda item: (item["model_id"], item["sample_index"], item["configuration"])):
            if result["kind"] != "trace":
                continue
            graph = json.loads((Path(result["case_dir"]) / "case.json").read_text())["prepared_dir"]
            names = {node["index"]: node["op"] for node in
                     json.loads((Path(graph) / "manifest.json").read_text())["graph"]["nodes"]}
            for layer in result["layers"]:
                writer.writerow({"model": result["model_id"], "sample": result["sample_index"],
                                 "configuration": result["configuration"], "operator_index": layer["index"],
                                 "operator_name": names[layer["index"]], "cpu_operator_cycles": layer["cycles"],
                                 **{key: layer[key] for key in fields[-3:]}})
    with (out / "timings.csv").open("w", newline="") as stream:
        fields = ("model", "sample", "run_kind", "configuration", "initialization_cycles",
                  "planning_cycles", "invoke_cycles")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for result in sorted(results, key=lambda item: (item["model_id"], item["sample_index"],
                                                        item["kind"], item["configuration"])):
            writer.writerow({"model": result["model_id"], "sample": result["sample_index"],
                             "run_kind": result["kind"], "configuration": result["configuration"],
                             "initialization_cycles": result["result"]["init_cycles"],
                             "planning_cycles": result["result"]["planning_cycles"],
                             "invoke_cycles": result["result"]["invoke_cycles"]})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=ROOT / "build/ps_compression/soc")
    p.add_argument("--prepared", type=Path, default=ROOT / "build/model_benchmark/prepared")
    p.add_argument("--firmware-root", type=Path)
    p.add_argument("--object-cache", type=Path)
    p.add_argument("--pool-bytes", type=int, default=12288,
                   help="Initial PS allocation; shared hardware also includes the initial 2048-byte IA allocation")
    p.add_argument("--configs", nargs="+", choices=("raw", "adaptive"), default=["raw", "adaptive"])
    p.add_argument("--models", nargs="+", choices=model_data.MODELS, default=list(model_data.MODELS))
    p.add_argument("--dataflow", type=int, choices=(0, 1, 2), default=2)
    p.add_argument("--samples", nargs="+", type=int)
    p.add_argument("--kind", choices=("perf", "trace", "both"), default="both")
    p.add_argument("--verilator", default="verilator")
    p.add_argument("--gcc", default="riscv64-unknown-elf-gcc")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--bus-width", type=int, choices=(32,64))
    p.add_argument("--shared-bank-bytes", type=int, choices=(1024,2048,4096))
    p.add_argument("--shared-bank-count", type=int, choices=(6,7,8,9))
    p.add_argument("--first-read-latency", type=int, default=8)
    p.add_argument("--run-jobs", type=int, choices=(1, 2, 3), default=2)
    p.add_argument("--latency", type=int, default=0)
    p.add_argument("--timeout-cycles", type=int, default=1000000000)
    p.add_argument("--host-timeout", type=int, default=1800)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--build-only", action="store_true")
    args = p.parse_args()
    if args.pool_bytes < 128 or args.pool_bytes % 64 or args.jobs < 1:
        p.error("pool must be a multiple of 64 bytes of at least 128 bytes; jobs must be positive")
    out, prepared_dir = args.out.resolve(), args.prepared.resolve()
    out.mkdir(parents=True, exist_ok=True)
    configs, names = list(dict.fromkeys(args.configs)), list(dict.fromkeys(args.models))
    kinds = ["perf", "trace"] if args.kind == "both" else [args.kind]
    prepared, samples = {}, {}
    for name in names:
        directory = prepared_dir / name
        model_data.validate_model(directory)
        prepared[name] = json.loads((directory / "manifest.json").read_text())
        samples[name] = [s for s in prepared[name]["samples"] if args.samples is None or s["sample_index"] in args.samples]
        if not samples[name] or (args.samples is not None and set(args.samples) != {s["sample_index"] for s in samples[name]}):
            p.error("Requested samples are absent from " + name)
    runner_hash = digest(Path(__file__))
    settings = {"models": names, "samples_by_model": {name: [s["sample_index"] for s in samples[name]] for name in names},
                "configurations": configs, "kinds": kinds, "pool_bytes": args.pool_bytes, "dataflow": args.dataflow,
                "prepared_manifest_sha256": {name: digest(prepared_dir / name / "manifest.json") for name in names},
                "runner_sha256": runner_hash, "rounding_mode": "nearest_even", "ram_fixed_lat": args.latency,
                "timing": "CPU rdcycle around complete Invoke; initialization and its measured driver planning subset are recorded separately",
                "hardware_operator_timing": "NPU accepted START through matching completion in performance runs",
                "cpu_operator_timing": "Trace operator begin/end markers include CPU dispatch and MMIO; tensor snapshots occur after the end marker",
                "operator_classification": "Model graph; pointwise Conv remains Conv when executed by GEMM",
                "comparison": "Same RTL and firmware executables, tensor addresses, physical memories, clock, WS/IS planner and SRAM bandwidth; config.flags selects runtime RAW"}
    bench.write_json(out / "settings.json", settings)
    binary = simulator.build_sim(out / "sim", args.verilator, args.jobs,
        skip=args.resume and (out / "sim/build.json").exists(), ps_pool_bytes=args.pool_bytes,
        bus_width=args.bus_width,first_read_latency=args.first_read_latency,
        shared_bank_bytes=args.shared_bank_bytes,shared_bank_count=args.shared_bank_count)
    settings["hardware_profile"] = json.loads((out / "sim/build.json").read_text())["profile"]
    bench.write_json(out / "settings.json", settings)
    if args.build_only:
        print(json.dumps({"passed": True, "binary": str(binary)}), flush=True)
        return
    firmware_root = (args.firmware_root or out / "firmware").resolve()
    object_cache = (args.object_cache or firmware_root / "objects").resolve()
    firmwares = {}
    for config in configs:
        for kind in kinds:
            directory = firmware_root / f"runtime_{args.pool_bytes}_{kind}_df{args.dataflow}"
            expected = {"DSA_PS_POOL_BYTES": args.pool_bytes, "DSA_PS_FORCE_RAW": 0,
                        "DSA_PS_COMPRESS": 1, "DSA_DEFAULT_DATAFLOW": args.dataflow, "DSA_PS_ADAPTIVE_W": 1}
            try:
                fw = json.loads((directory / "firmware.json").read_text())
                bench.verify_sources(fw)
                if (not fw["passed"] or fw["trace_enabled"] != (kind == "trace") or
                    any(fw["compile_defines"].get(k) != v for k, v in expected.items()) or
                    any(digest(directory / file) != fw[key] for file, key in (("cpu.elf", "elf_sha256"), ("cpu.mem", "mem_sha256")))):
                    raise ValueError("Firmware configuration or payload differs")
            except (OSError, ValueError, KeyError, RuntimeError):
                fw = builder.build_firmware(directory, args.gcc, hardware=True, trace=kind == "trace",
                    jobs=args.jobs, object_cache=object_cache, ps_pool_bytes=args.pool_bytes,
                    force_raw=False, adaptive_window=True, dataflow=args.dataflow)
            firmwares[config, kind] = directory, fw
    results, work = [], []
    for config in configs:
        for kind in kinds:
            fw_dir, fw = firmwares[config, kind]
            for name in names:
                for sample in samples[name]:
                    directory = out / "cases" / config / name / f"sample_{sample['sample_index']:04d}" / kind
                    result_path = directory / "result.json"
                    if args.resume and result_path.exists():
                        saved = json.loads(result_path.read_text())
                        case = json.loads((directory / "case.json").read_text())
                        if (saved["passed"] and saved["runner_sha256"] == runner_hash and
                            saved.get("ram_fixed_lat") == args.latency and
                            saved["firmware_elf_sha256"] == fw["elf_sha256"] and
                            saved["sim_binary_sha256"] == digest(binary) and
                            saved["input_sha256"] == sample["input"]["sha256"] and
                            case["prepared_sha256"] == settings["prepared_manifest_sha256"][name] and
                            case["data_mem_sha256"] == digest(directory / "data.mem") and
                            saved["run_log_sha256"] == digest(directory / "run.log")):
                            results.append(validate_result(saved, config, binary, runner_hash))
                            continue
                    case = bench.create_case(directory, prepared_dir / name, prepared[name], sample, bench.HARDWARE_MODE,
                                             fw_dir, fw, ps_force_raw=config == "raw")
                    work.append((directory, case, fw, config))
    def execute(item):
        directory, case, fw, config = item
        started = time.monotonic()
        result = bench.execute_case(binary, directory, case, fw, latency=args.latency,
            cycle_limit=args.timeout_cycles, seconds_limit=args.host_timeout,
            extra_plusargs=[f"+PS_EVENTS={directory / 'ps_events.txt'}"])
        result["host_seconds"] = time.monotonic() - started
        return validate_result(result, config, binary, runner_hash)
    with ThreadPoolExecutor(max_workers=args.run_jobs) as pool:
        for future in as_completed([pool.submit(execute, item) for item in work]):
            result = future.result()
            results.append(result)
            summarize(out, results, settings)
            print(json.dumps({"configuration": result["configuration"], "model": result["model_id"],
                              "kind": result["kind"], "sample": result["sample_index"], "passed": result["passed"],
                              "cycles": result.get("result", {}).get("invoke_cycles"),
                              "initialization_cycles": result.get("result", {}).get("init_cycles"),
                              "planning_cycles": result.get("result", {}).get("planning_cycles"),
                              "retries": result.get("network", {}).get("capacity_retries")}), flush=True)
    report = summarize(out, results, settings)
    print(json.dumps({"passed": report["passed"], "complete": report["complete"],
                      "comparisons": report["comparisons"]}), flush=True)
    if not report["passed"] or not report["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
