#!/usr/bin/env python3
"""Compare complete-model hardware runs and separate measured waiting causes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze import ARRAY_OPS, CONTROLLER_FIELDS, analyze, ceildiv, sha256


CONTROLLER_WAIT_CONDITIONS = {
    "array_wait_weight_tail": "WEIGHT_START && !oa_calc_over && !weight_safe_to_send",
    "array_wait_weight_data": "WEIGHT_START && !oa_calc_over && weight_safe_to_send && !weight_data_valid",
    "array_wait_ia_data": "IA_START && !ia_data_valid",
    "array_wait_bias": "IA_START && ia_data_valid && !bias_ready_for_compute",
    "array_wait_quant": "IA_START && ia_data_valid && bias_ready_for_compute && !quant_params_valid",
    "array_wait_output": "IA_START && ia_data_valid && bias_ready_for_compute && quant_params_valid && fifo_full_flag",
    "array_wait_ia_done": "IA_WAIT && !ia_sending_done",
}


def common_gemm_traffic(path: Path) -> dict:
    report = json.loads(path.read_text())
    if not report.get("passed"):
        raise ValueError("Common GEMM measurements did not pass")
    memory = report["profile"]["memory"]
    if memory["read_beat_interval_cycles"] != 2 or memory["read_burst_transition_interval_min"] != 3:
        raise ValueError("Common GEMM memory service differs from the analyzed model")
    rows = []
    for case in report["cases"]:
        measured, timing = case["measurement"], case["timing"]
        read_payload = ceildiv(measured["ar_bytes"], 2)
        read_service = 2 * timing["read_beats"] + timing["read_commands"]
        write_payload = ceildiv(measured["write_bytes"], 4)
        write_service = timing["write_beats"] + 2 * timing["write_commands"] - 1
        floor = max(read_service, write_service)
        row = {"name": case["name"], "m": case["m"], "n": case["n"], "k": case["k"],
               "cycles": measured["cycles"], "read_bytes": measured["ar_bytes"],
               "read_requests": timing["read_commands"], "write_bytes": measured["write_bytes"],
               "read_payload_floor_cycles": read_payload, "write_payload_floor_cycles": write_payload,
               "read_transaction_service_floor_cycles": read_service,
               "write_transaction_service_floor_cycles": write_service,
               "current_traffic_duplex_floor_cycles": floor,
               "cycles_over_read_payload_floor_fraction": measured["cycles"] / read_payload - 1,
               "cycles_over_current_service_floor_fraction": measured["cycles"] / floor - 1,
               "maximum_speedup_if_only_nonoverlapped_waits_removed": measured["cycles"] / floor,
               "effective_array_utilization": case["effective_array_utilization"]}
        if case["name"] in ("model_m1024_n16_k144", "model_m64_n64_k576"):
            m, n, k = case["m"], case["n"], case["k"]
            tiling = case["tiling"]
            is_mode = bool(measured["dataflow"])
            a_passes = tiling["row_groups"] if is_mode else tiling["col_groups"]
            b_passes = tiling["col_groups"] if is_mode else tiling["row_groups"]
            bias_passes = 1 if is_mode or n <= 16 else tiling["row_groups"]
            layout = case.get("physical_layout", "row-major")
            a_depth = ceildiv(k, 16) * 16 if layout in ("lhs-packed", "both-packed") else k
            b_depth = ceildiv(k, 16) * 16 if layout in ("rhs-packed", "both-packed") else k
            components = {"a_bytes": m * a_depth * a_passes,
                          "b_bytes": b_passes * b_depth * n,
                          "bias_bytes": bias_passes * n * 4,
                          "dataflow": "is" if is_mode else "ws", "physical_layout": layout,
                          "row_groups": tiling["row_groups"], "col_groups": tiling["col_groups"],
                          "a_read_passes": a_passes, "b_read_passes": b_passes,
                          "rows_per_weight_pass": 16 * tiling["w_reuse" if is_mode else "ia_reuse"],
                          "weight_reload_factor": b_passes}
            if components["a_bytes"] + components["b_bytes"] + components["bias_bytes"] != measured["ar_bytes"]:
                raise ValueError("Representative GEMM traffic differs from its exact tile-reload formula")
            components["single_read_per_operand_bytes"] = m * k + k * n + 4 * n
            row["weight_reload_analysis"] = components
        rows.append(row)
    return {"source_summary_sha256": sha256(path), "cases": rows,
            "definitions": {
                "scope": "Measured cold-start accelerator-only GEMM with preformed input matrices and the shared 32-bit AXI test memory.",
                "read_payload_floor": "ceil(read_bytes/2), because this memory can return at most one 32-bit beat every two cycles.",
                "read_transaction_service_floor": "2*read_beats+read_requests from earliest first AR to last R. Within-burst spacing is 2 cycles; between bursts it is at least 3 cycles, including the first idle response latency of 3.",
                "write_transaction_service_floor": "write_beats+2*write_requests-1 from earliest first AW to last B; one active write transaction and no data-source stalls.",
                "duplex_floor": "Maximum of read and write service lower bounds with perfect overlap, fixed measured traffic, and earliest possible first requests.",
                "wait_interpretation": "Controller data-wait cycles often occur while the external memory is delivering required bytes. Eliminating controller gaps alone cannot remove these transfers. Further gains require fewer bytes or requests, more data reuse, or a faster memory service."}}


def summarize(report: dict, name: str) -> dict:
    model = next(row for row in report["models"] if row["model"] == name)
    layers = [row for row in report["layers"] if row["model"] == name]
    network = model["network_counters"]
    waits = {}
    sources = {}
    for key in CONTROLLER_FIELDS.values():
        if key in network:
            waits[key] = network[key]
            sources[key] = "mean of performance runs for all samples"
        elif key in model.get("instrumented_controller_totals", {}):
            waits[key] = model["instrumented_controller_totals"][key]
            sources[key] = "independent instrumented trace, sample 0"
        else:
            waits[key] = None
            sources[key] = "not measured"
    ia_rows = network.get("array_ia_valid_cycles", model.get("observed_ia_rows"))
    vector_busy = sum(row["counters"]["npu_busy_cycles"] for row in layers if row["operator"] not in ARRAY_OPS)
    result = {"hardware_cycles": model["hw_cycles"], "software_cycles": model["sw_cycles"],
              "software_speedup": model["speedup"], "npu_busy_cycles": model["npu_busy_cycles"],
              "software_init_cycles": model["sw_init_cycles"],
              "hardware_init_cycles": model["hw_init_cycles"],
              "software_init_plus_invoke_cycles": model["sw_init_plus_invoke_cycles"],
              "hardware_init_plus_invoke_cycles": model["hw_init_plus_invoke_cycles"],
              "init_plus_invoke_speedup": model["init_plus_invoke_speedup"],
              "cpu_outside_npu_busy_cycles": model["outside_npu_busy_cycles"],
              "cpu_outside_npu_busy_fraction": model["outside_busy_fraction"],
              "main_array_job_busy_cycles": model["array_job_busy_cycles"],
              "main_array_effective_utilization": model["array_busy_effective_utilization"],
              "main_array_ia_valid_cycles": ia_rows,
              "main_array_ia_issue_duty_factor": ia_rows / model["array_job_busy_cycles"] if ia_rows is not None else None,
              "main_array_spatial_occupancy": model["observed_spatial_occupancy"],
              "main_array_dense_macs": model["array_macs"], "main_array_padded_macs": model["observed_padded_array_macs"],
              "main_array_ws_padded_macs": model["ws_padded_array_macs"],
              "main_array_is_padded_macs": model["is_padded_array_macs"],
              "main_array_geometry_verified_per_layer": model["array_geometry_verified_per_layer"],
              "main_array_dataflow_geometry": model["dataflow_geometry_layer_counts"],
              "controller_waits": waits, "controller_counter_sources": sources,
              "vector_job_busy_cycles": vector_busy,
              "vector_compute_cycles": network.get("vector_compute_cycles"),
              "vector_dma_wait_cycles": network.get("vector_dma_wait_cycles"),
              "vector_counter_source": "mean of performance runs for all samples" if "vector_dma_wait_cycles" in network else "not measured",
              "read_bytes": network["npu_read_bytes"], "write_bytes": network["npu_write_bytes"],
              "read_requests": network["npu_read_bursts"], "write_requests": network["npu_write_bursts"],
              "cpu_instruction_reads": network["cpu_instruction_reads"],
              "cpu_mmio_reads": network["cpu_mmio_reads"], "cpu_mmio_write_bytes": network["cpu_mmio_write_bytes"],
              "target_cycles": model["target_cycles"],
              "further_speedup_to_target": model["required_accelerated_path_improvement"],
              "categories": model["categories"]}
    if (ia_rows is not None and model["observed_padded_array_macs"] is not None and
            ia_rows * report["array_size"]**2 != model["observed_padded_array_macs"]):
        raise ValueError("Measured valid IA vectors differ from the per-layer geometry totals")
    if all(waits[name] is not None for name in CONTROLLER_WAIT_CONDITIONS):
        named_waits = sum(waits[name] for name in CONTROLLER_WAIT_CONDITIONS)
        active = waits["array_controller_cycles"]
        if active is not None and named_waits > active:
            raise ValueError("Mutually exclusive controller counts exceed controller-active cycles")
        result["controller_named_wait_cycles"] = named_waits
        result["controller_other_cycles"] = None if active is None else active - named_waits
    if result["vector_dma_wait_cycles"] is not None:
        result["vector_dma_wait_fraction_of_vector_busy"] = result["vector_dma_wait_cycles"] / vector_busy
        result["vector_dma_wait_fraction_of_invoke"] = result["vector_dma_wait_cycles"] / result["hardware_cycles"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True, help="Original results/cases directory")
    parser.add_argument("--modified", type=Path, required=True, help="Modified results/cases directory")
    parser.add_argument("--software", type=Path, help="Software reference results/cases; defaults to --original")
    parser.add_argument("--original-mode", type=int, default=31)
    parser.add_argument("--modified-mode", type=int, default=63)
    parser.add_argument("--original-utilization-logs", type=Path)
    parser.add_argument("--target", type=float, default=1000)
    parser.add_argument("--common-gemm", type=Path, help="Modified common-GEMM summary.json for memory-service analysis")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    software = args.software or args.original
    original = analyze(args.prepared, args.original, 16, 8, 4, args.target,
                       args.original_utilization_logs, args.original_mode, software)
    modified = analyze(args.prepared, args.modified, 16, 8, 4, args.target,
                       None, args.modified_mode, software)
    names = {row["model"] for row in original["models"]}
    if names != {row["model"] for row in modified["models"]}:
        raise ValueError("Compared hardware results cover different models")
    rows = []
    for name in sorted(names):
        before, after = summarize(original, name), summarize(modified, name)
        if before["software_cycles"] != after["software_cycles"]:
            raise ValueError("Compared runs use different software measurements")
        row = {"model": name, "original": before, "modified": after,
               "hardware_speedup": before["hardware_cycles"] / after["hardware_cycles"],
               "main_array_busy_speedup": before["main_array_job_busy_cycles"] / after["main_array_job_busy_cycles"],
               "outside_npu_busy_reduction_cycles": before["cpu_outside_npu_busy_cycles"] - after["cpu_outside_npu_busy_cycles"],
               "npu_busy_reduction_cycles": before["npu_busy_cycles"] - after["npu_busy_cycles"]}
        rows.append(row)
    sw_total = sum(row["original"]["software_cycles"] for row in rows)
    old_total = sum(row["original"]["hardware_cycles"] for row in rows)
    new_total = sum(row["modified"]["hardware_cycles"] for row in rows)
    sw_init_total = sum(row["original"]["software_init_cycles"] for row in rows)
    old_init_total = sum(row["original"]["hardware_init_cycles"] for row in rows)
    new_init_total = sum(row["modified"]["hardware_init_cycles"] for row in rows)
    result = {"models": rows,
              "aggregate_one_inference_per_model": {"software_cycles": sw_total,
                  "original_cycles": old_total, "modified_cycles": new_total,
                  "original_software_speedup": sw_total / old_total,
                  "modified_software_speedup": sw_total / new_total,
                  "target_cycles": sw_total / args.target,
                  "cycles_above_target": new_total - sw_total / args.target,
                  "hardware_speedup": old_total / new_total},
              "aggregate_initialization_plus_one_inference_per_model": {
                  "software_init_cycles": sw_init_total,
                  "original_init_cycles": old_init_total,
                  "modified_init_cycles": new_init_total,
                  "software_cycles": sw_init_total + sw_total,
                  "original_cycles": old_init_total + old_total,
                  "modified_cycles": new_init_total + new_total,
                  "original_software_speedup": (sw_init_total + sw_total) / (old_init_total + old_total),
                  "modified_software_speedup": (sw_init_total + sw_total) / (new_init_total + new_total)},
              "definitions": {
                  "outside_npu_busy": "Unprofiled Invoke cycles minus measured NPU busy cycles; includes host dispatch, software operators, and other CPU work. CPU instructions may also execute while NPU is busy.",
                  "main_array_utilization": "Conv/FC useful MACs divided by 256 and the sum of per-layer NPU busy cycles in trace firmware, consistently for both versions.",
                  "controller_waits": "At most one of the seven named wait-cause fields increments per controller-active cycle. WEIGHT_START gives tail waiting priority over weight-data waiting; IA_START gives input data, bias, quantization, and output space that order. IA_WAIT is a separate state. The fields do not cover all active cycles; controller_other_cycles is the remainder. These fields overlap with independent DMA/array activity counters, and IA completion waiting can include useful arithmetic and pipeline drain.",
                  "controller_wait_conditions": CONTROLLER_WAIT_CONDITIONS,
                  "controller_counter_source": "rtl/npu/control/npu_controller.sv, util_active branch; test/model_benchmark/tb_model_benchmark.sv accumulates stable per-job counters at npu_done_fire.",
                  "vector_wait": "vector_engine.tb_observer.stat_dma_wait increments once when any listed DMA condition is true. It includes write-data transmission and can overlap vector_compute_cycles through the independent window-read and writeback state machines. It measures DMA-related activity or waiting, not exclusively cycles without arithmetic progress. Missing measurements are JSON null.",
                  "vector_dma_condition": "state==LOAD_WAIT || win_busy || state==POOL_LOAD_WAIT || (writeback_busy && !wr_req) || state==SOFT_LUT_WAIT || (rd_req && !rd_granted) || (wr_req && !wr_granted) || (state==CONFIGURE && !dma_cfg_ready)",
                  "vector_compute_condition": "state==EXECUTE || state==EXECUTE_COMMIT || state==ADD_MULT || state==ADD_DRAIN || state==ADD_ROUND || state==ADD_ROUND_WAIT || state==ADD_SUM || state==ADD_STORE || (state==SOFT_RUN && !soft_lut_req_valid && !soft_done)",
                  "vector_counter_source": "test/monitors/vector_engine_observer.sv; independent conditions update stat_compute and stat_dma_wait.",
                  "counter_scope": "Full-model timing uses perf firmware; layer-derived totals use trace firmware. The original standalone utilization logs describe sample 0; modified performance counters are averaged over both samples.",
                  "initialization": modified["notes"]["initialization"],
                  "target": "1000x targets use the same software-reference Invoke timings for both hardware versions."},
              "original_analysis": original, "modified_analysis": modified}
    if args.common_gemm:
        result["common_gemm_memory_service"] = common_gemm_traffic(args.common_gemm)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    for row in rows:
        new = row["modified"]
        print(f"{row['model']}: cycles={new['hardware_cycles']:.1f} software_speedup={new['software_speedup']:.2f} "
              f"array_util={new['main_array_effective_utilization']:.3%} outside_busy={new['cpu_outside_npu_busy_cycles']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
