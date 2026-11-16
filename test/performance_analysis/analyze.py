#!/usr/bin/env python3
"""Calculate WS/IS shape occupancy and throughput from complete model runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

ARRAY_OPS = {"CONV_2D", "FULLY_CONNECTED"}
CONTROLLER_FIELDS = {
    "active": "array_controller_cycles", "weight_tail_stall": "array_wait_weight_tail",
    "weight_data_stall": "array_wait_weight_data", "ia_data_stall": "array_wait_ia_data",
    "bias_stall": "array_wait_bias", "quant_stall": "array_wait_quant",
    "fifo_stall": "array_wait_output", "ia_done_wait": "array_wait_ia_done"}


def ceildiv(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def geometry(node: dict, array_size: int, vector_pes: int) -> dict:
    """Count dense-equivalent MACs, including convolution spatial padding."""
    op = node["op"]
    result = {"dense_macs": 0, "array_macs": 0, "dw_macs": 0,
              "ws_padded_macs": 0, "is_padded_macs": 0, "ideal_arithmetic_cycles": 0,
              "im2col_values_per_pass": 0}
    if op in ARRAY_OPS:
        weight = node["input_shapes"][1]
        output = node["output_shapes"][0]
        n, k = weight[0], math.prod(weight[1:])
        m = math.prod(output) // n
        macs = m * n * k
        padded = m * ceildiv(n, array_size) * array_size * ceildiv(k, array_size) * array_size
        is_padded = n * ceildiv(m, array_size) * array_size * ceildiv(k, array_size) * array_size
        result.update(m=m, n=n, k=k, dense_macs=macs, array_macs=macs,
                      ws_padded_macs=padded, is_padded_macs=is_padded,
                      ws_ia_rows=padded // array_size**2, is_ia_rows=is_padded // array_size**2,
                      ws_spatial_occupancy=macs / padded, is_spatial_occupancy=macs / is_padded,
                      ideal_arithmetic_cycles=min(padded, is_padded) // array_size**2,
                      spatial_occupancy=None)
        if op == "CONV_2D":
            result["im2col_values_per_pass"] = m * k
            result["category"] = "pointwise_conv" if weight[1:3] == [1, 1] else "spatial_conv"
        else:
            result["category"] = "fully_connected"
    elif op == "DEPTHWISE_CONV_2D":
        kernel = node["input_shapes"][1]
        macs = math.prod(node["output_shapes"][0]) * kernel[1] * kernel[2]
        result.update(dense_macs=macs, dw_macs=macs,
                      ideal_arithmetic_cycles=ceildiv(macs, vector_pes), category="depthwise_conv")
    else:
        result["category"] = op.lower()
    return result


def observe_geometry(item: dict, array_size: int, ia_rows: int | float | None) -> None:
    """Validate an observed stream length against both legal array directions."""
    item["measured_ia_rows"] = ia_rows
    item["dataflow_geometry"] = "unmeasured"
    item["dataflow_geometry_candidates"] = []
    item["observed_padded_macs"] = None
    if ia_rows is None:
        return
    matches = [mode for mode in ("ws", "is") if ia_rows == item[mode + "_ia_rows"]]
    if not matches:
        raise ValueError(f"IA vector count differs from both WS and IS geometry: {item.get('model')} layer {item.get('layer')}")
    item["dataflow_geometry_candidates"] = matches
    item["dataflow_geometry"] = matches[0] if len(matches) == 1 else "ambiguous"
    item["ia_rows_match_ws_geometry"] = "ws" in matches
    item["ia_rows_match_is_geometry"] = "is" in matches
    item["observed_padded_macs"] = ia_rows * array_size**2
    item["spatial_occupancy"] = item["array_macs"] / item["observed_padded_macs"]
    item["ideal_arithmetic_cycles"] = ia_rows


def read_utilization_log(path: Path, nodes: list[dict]) -> list[dict]:
    """Associate top-level job traces with the graph's accelerated nodes."""
    records = []
    for line in path.read_text().splitlines():
        if line.startswith("[NPU_UTIL]"):
            records.append({key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)})
    accelerated = [node for node in nodes if node["op"] in ARRAY_OPS | {
        "DEPTHWISE_CONV_2D", "AVERAGE_POOL_2D", "MAX_POOL_2D", "ADD"}]
    # Older logs do not include Softmax jobs. Newer logs may include them.
    if len(records) != len(accelerated):
        accelerated = [node for node in nodes if node["op"] in ARRAY_OPS | {
            "DEPTHWISE_CONV_2D", "AVERAGE_POOL_2D", "MAX_POOL_2D", "ADD", "SOFTMAX"}]
    if len(records) != len(accelerated):
        raise ValueError(f"Job count in {path} differs from the graph")
    for record, node in zip(records, accelerated):
        record["layer"] = node["index"]
        record["operator"] = node["op"]
    return records


def read_controller_log(path: Path, nodes: list[dict]) -> list[dict]:
    records = [{key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
               for line in path.read_text().splitlines() if line.startswith("[NPU_CTRL_UTIL]")]
    selected = [node for node in nodes if node["op"] in ARRAY_OPS]
    if len(records) != len(selected):
        raise ValueError("Controller job count differs from the graph")
    for record, node in zip(records, selected):
        record["layer"] = node["index"]
        record["operator"] = node["op"]
    return records


def analyze(prepared: Path, results: Path, array_size: int, vector_pes: int,
            bus_bytes: int, target: float, utilization_logs: Path | None = None,
            hardware_mode: int = 31, software_results: Path | None = None) -> dict:
    manifests = sorted(prepared.glob("*/manifest.json"))
    if not manifests:
        raise ValueError("No prepared model manifests found")
    runs = [json.loads(path.read_text()) for path in sorted(results.glob("*/*/*/result.json"))]
    indexed = {}
    for run in runs:
        if not run.get("passed"):
            raise ValueError("Analysis requires successful model runs")
        key = (run["model_id"], run["sample_index"], run["kind"], run["mode"])
        if key in indexed:
            raise ValueError("Duplicate model run")
        indexed[key] = run
    software_index = indexed
    if software_results is not None:
        software_index = {}
        for path in sorted(software_results.glob("*/*/*/result.json")):
            run = json.loads(path.read_text())
            if run["mode"] == 0 and run["kind"] == "perf":
                if not run.get("passed"):
                    raise ValueError("Software reference run did not pass")
                software_index[(run["model_id"], run["sample_index"], "perf", 0)] = run
    models = []
    layers = []
    for path in manifests:
        manifest = json.loads(path.read_text())
        name = manifest["name"]
        nodes = manifest["graph"]["nodes"]
        samples = [sample["sample_index"] for sample in manifest["samples"]]
        model_runs = [run for run in runs if run["model_id"] == name]
        if not model_runs:
            continue
        if any(run["model"]["sha256"] != manifest["model"]["sha256"] for run in model_runs):
            raise ValueError("Measured and prepared models differ")
        software = [software_index[(name, sample, "perf", 0)] for sample in samples]
        hardware = [indexed[(name, sample, "perf", hardware_mode)] for sample in samples]
        traces = [indexed[(name, sample, "trace", hardware_mode)] for sample in samples]
        for sample, sw, hw in zip(manifest["samples"], software, hardware):
            if sw["model"]["sha256"] != hw["model"]["sha256"]:
                raise ValueError("Software and hardware model bytes differ")
            if sw["input_sha256"] != hw["input_sha256"] or hw["input_sha256"] != sample["input"]["sha256"]:
                raise ValueError("Software and hardware input bytes differ")
            if sw["ram_fixed_lat"] != hw["ram_fixed_lat"]:
                raise ValueError("Software and hardware RAM latency differs")
            if sw["output_comparison"]["actual_sha256"] != hw["output_comparison"]["actual_sha256"]:
                raise ValueError("Software and hardware outputs differ")
        trace_by_index = [{row["index"]: row for row in trace["layers"]} for trace in traces]
        selected = []
        job_by_layer = {}
        if utilization_logs and (utilization_logs / name / "run.log").is_file():
            job_by_layer = {job["layer"]: job for job in
                read_utilization_log(utilization_logs / name / "run.log", nodes)}
        for node in nodes:
            observed = [trace[node["index"]] for trace in trace_by_index]
            shared_keys = set.intersection(*(set(item) for item in observed))
            counters = {key: mean(row[key] for row in observed)
                        for key in shared_keys if isinstance(observed[0][key], (int, float)) and key != "index"}
            item = {"model": name, "layer": node["index"], "operator": node["op"],
                    "input_shapes": node["input_shapes"], "output_shapes": node["output_shapes"],
                    **geometry(node, array_size, vector_pes), "counters": counters}
            busy = counters["npu_busy_cycles"]
            item["outside_busy_cycles"] = counters["cycles"] - busy
            item["current_traffic_duplex_floor_cycles"] = max(
                ceildiv(int(counters["npu_read_bytes"]), bus_bytes),
                ceildiv(int(counters["npu_write_bytes"]), bus_bytes))
            if node["op"] in ARRAY_OPS and busy:
                ia_rows = counters.get("array_ia_valid_cycles")
                if ia_rows is None and node["index"] in job_by_layer:
                    ia_rows = job_by_layer[node["index"]]["ia_row"]
                observe_geometry(item, array_size, ia_rows)
                item["array_busy_effective_utilization"] = item["array_macs"] / (array_size**2 * busy)
                if ia_rows is not None:
                    item["ia_issue_duty_factor"] = ia_rows / busy
            item["arithmetic_and_current_traffic_floor_cycles"] = max(
                item["ideal_arithmetic_cycles"], item["current_traffic_duplex_floor_cycles"])
            layers.append(item)
            selected.append(item)
        sw_cycles = mean(run["result"]["invoke_cycles"] for run in software)
        hw_cycles = mean(run["result"]["invoke_cycles"] for run in hardware)
        sw_init = mean(run["result"]["init_cycles"] for run in software)
        hw_init = mean(run["result"]["init_cycles"] for run in hardware)
        busy_cycles = mean(run["network"]["npu_busy_cycles"] for run in hardware)
        network_keys = set.intersection(*(set(run["network"]) for run in hardware))
        network_counters = {key: mean(run["network"][key] for run in hardware)
                            for key in network_keys if isinstance(hardware[0]["network"][key], (int, float))
                            and key != "index"}
        array_busy = sum(row["counters"]["npu_busy_cycles"] for row in selected if row["operator"] in ARRAY_OPS)
        array_macs = sum(row["array_macs"] for row in selected)
        padded_macs = sum(row["ws_padded_macs"] for row in selected)
        is_padded_macs = sum(row["is_padded_macs"] for row in selected)
        array_layers = [row for row in selected if row["operator"] in ARRAY_OPS]
        layer_geometry_verified = all(row.get("observed_padded_macs") is not None for row in array_layers)
        observed_padded = sum(row["observed_padded_macs"] for row in array_layers) if layer_geometry_verified else None
        network_ia = network_counters.get("array_ia_valid_cycles")
        if network_ia is not None:
            network_padded = network_ia * array_size**2
            if observed_padded is not None and network_padded != observed_padded:
                raise ValueError("Performance and layer-trace IA vector counts differ")
            observed_padded = network_padded
        direction_counts = dict.fromkeys(("ws", "is", "ambiguous", "unmeasured"), 0)
        for row in array_layers:
            direction_counts[row.get("dataflow_geometry", "unmeasured")] += 1
        category_rows = defaultdict(list)
        for row in selected:
            category_rows[row["category"]].append(row)
        categories = []
        for category, group in category_rows.items():
            cyc = sum(row["counters"]["cycles"] for row in group)
            categories.append({"category": category, "nodes": len(group), "cycles": cyc,
                               "fraction_of_unprofiled_invoke": cyc / hw_cycles,
                               "busy_cycles": sum(row["counters"]["npu_busy_cycles"] for row in group),
                               "read_bytes": sum(row["counters"]["npu_read_bytes"] for row in group),
                               "write_bytes": sum(row["counters"]["npu_write_bytes"] for row in group)})
        result = {"model": name, "model_sha256": manifest["model"]["sha256"],
                  "manifest_sha256": sha256(path), "samples": len(samples),
                  "sw_cycles": sw_cycles, "hw_cycles": hw_cycles,
                  "sw_init_cycles": sw_init, "hw_init_cycles": hw_init,
                  "sw_init_plus_invoke_cycles": sw_init + sw_cycles,
                  "hw_init_plus_invoke_cycles": hw_init + hw_cycles,
                  "init_plus_invoke_speedup": (sw_init + sw_cycles) / (hw_init + hw_cycles),
                  "speedup": sw_cycles / hw_cycles, "target_speedup": target,
                  "target_cycles": sw_cycles / target,
                  "required_accelerated_path_improvement": hw_cycles * target / sw_cycles,
                  "npu_busy_cycles": busy_cycles, "outside_npu_busy_cycles": hw_cycles - busy_cycles,
                  "outside_busy_fraction": (hw_cycles - busy_cycles) / hw_cycles,
                  "array_macs": array_macs, "dw_macs": sum(row["dw_macs"] for row in selected),
                  "dense_macs": sum(row["dense_macs"] for row in selected),
                  "ws_padded_array_macs": padded_macs, "ws_spatial_occupancy": array_macs / padded_macs,
                  "is_padded_array_macs": is_padded_macs, "is_spatial_occupancy": array_macs / is_padded_macs,
                  "observed_padded_array_macs": observed_padded,
                  "observed_spatial_occupancy": array_macs / observed_padded if observed_padded else None,
                  "array_geometry_verified_per_layer": layer_geometry_verified,
                  "dataflow_geometry_layer_counts": direction_counts,
                  "array_job_busy_cycles": array_busy,
                  "array_busy_effective_utilization": array_macs / (array_size**2 * array_busy),
                  "whole_invoke_array_effective_utilization": array_macs / (array_size**2 * hw_cycles),
                  "ideal_arithmetic_cycles": sum(row["ideal_arithmetic_cycles"] for row in selected),
                  "arithmetic_and_current_traffic_floor_cycles": sum(row["arithmetic_and_current_traffic_floor_cycles"] for row in selected),
                  "read_bytes": sum(row["counters"]["npu_read_bytes"] for row in selected),
                  "write_bytes": sum(row["counters"]["npu_write_bytes"] for row in selected),
                  "network_counters": network_counters,
                  "network_counter_samples": samples,
                  "categories": categories}
        if utilization_logs and (utilization_logs / name / "run.log").is_file():
            log = utilization_logs / name / "run.log"
            jobs = read_utilization_log(log, nodes)
            result["utilization_log_sha256"] = sha256(log)
            result["instrumented_jobs"] = jobs
            controllers = read_controller_log(log, nodes)
            result["instrumented_controller_jobs"] = controllers
            result["instrumented_controller_totals"] = {
                destination: sum(job[source] for job in controllers)
                for source, destination in CONTROLLER_FIELDS.items()}
            result["instrumented_log_sample_index"] = 0
            result["observed_ia_rows"] = sum(job["ia_row"] for job in jobs)
            result["ia_rows_match_ws_geometry"] = result["observed_ia_rows"] == padded_macs / array_size**2
        models.append(result)
    return {"array_size": array_size, "vector_pes": vector_pes, "bus_bytes": bus_bytes,
            "hardware_mode": hardware_mode,
            "result_source_sha256": {str(path.relative_to(results)): sha256(path)
                                      for path in sorted(results.glob("*/*/*/result.json"))},
            "software_result_source_sha256": {
                str(path.relative_to(software_results or results)): sha256(path)
                for path in sorted((software_results or results).glob("*/*/perf_0/result.json"))},
            "notes": {
                "dense_macs": "Standard dense operator count including convolution spatial zero padding; excludes array dimension padding.",
                "ws_geometry": "K and N are spatial dimensions; M is streamed without rounding M to the array size.",
                "is_geometry": "K and M are spatial dimensions; N is streamed without rounding N to the array size.",
                "dataflow_geometry": "Per-layer measured IA vector counts are compared with both WS and IS formulas. Equal formulas are labelled ambiguous; observed padded MACs remain exact. A direction is not inferred when both counts match. Missing IA measurements are labelled unmeasured.",
                "array_busy_utilization": "Dense array MAC count divided by size squared and all NPU-busy cycles for Conv/FC jobs; includes hardware memory/control stalls.",
                "current_traffic_floor": "Conditional lower bound with measured byte traffic unchanged, independent full-rate read and write channels, and perfect overlap. It omits CPU, pooling, Add, Softmax, setup, and array fill/drain costs.",
                "ideal_arithmetic": "Observed array spatially padded MACs divided by size squared plus DW MACs divided by vector PE count; excludes other operators and scheduling costs. Without IA observations, the smaller WS/IS geometric count supplies an optimistic arithmetic bound.",
                "profiling": "Whole-model cycles come from perf firmware; layer counters come from trace firmware. Fractions normalized to perf cycles are estimates of contributions, not profiled shares.",
                "initialization": "Firmware init_cycles covers target/model initialization, resolver/interpreter creation, AllocateTensors including operator preparation, and copying the input tensor. init_plus_invoke adds this interval to one Invoke; it excludes earlier firmware startup and later output checks.",
                "target": "Target cycles describe a design requirement, not a forecast or achieved result."
            }, "models": models, "layers": layers}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True, help="results/cases directory")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--array-size", type=int, default=16)
    parser.add_argument("--vector-pes", type=int, default=8)
    parser.add_argument("--bus-bytes", type=int, default=4)
    parser.add_argument("--target", type=float, default=1000)
    parser.add_argument("--utilization-logs", type=Path)
    parser.add_argument("--hardware-mode", type=int, default=31)
    parser.add_argument("--software-results", type=Path, help="Separate results/cases directory containing perf mode 0")
    args = parser.parse_args()
    if min(args.array_size, args.vector_pes, args.bus_bytes, args.target) <= 0:
        parser.error("Hardware sizes and target must be positive")
    report = analyze(args.prepared, args.results, args.array_size, args.vector_pes,
                     args.bus_bytes, args.target, args.utilization_logs, args.hardware_mode, args.software_results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for model in report["models"]:
        print(f"{model['model']}: shape={model['ws_spatial_occupancy']:.4%} "
              f"array_busy_util={model['array_busy_effective_utilization']:.4%} "
              f"target_cycles={model['target_cycles']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
