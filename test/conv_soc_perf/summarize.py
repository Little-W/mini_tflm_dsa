#!/usr/bin/env python3
"""Summarize measured SoC counters; never estimate CPU cycles from host time."""
import argparse
import csv
import json
from pathlib import Path


def flatten(result):
    cpu = result["cpu_result"]
    counters = result["counters"]["call_window"]
    row = {
        "layer": result["layer"], "mode": result["mode"],
        "fixed_response_latency": result["fixed_response_latency"],
        "passed": result["passed"], "call_cycles": cpu["total_call_cycles"],
        "npu_busy_cycles": counters["npu_busy_cycles"],
        "non_npu_busy_call_cycles": result["non_npu_busy_call_cycles"],
        "observer_window_cycles": counters["cycles"],
        "observer_extra_cycles": counters["cycles"] - cpu["total_call_cycles"],
        "cpu_instruction_reads": counters["cpu_instruction_reads"],
        "cpu_instruction_bus_bytes": 4 * counters["cpu_instruction_reads"],
        "cpu_ram_data_read_bus_bytes": 4 * counters["cpu_ram_data_reads"],
        "cpu_ram_write_bytes": counters["cpu_ram_write_bytes"],
        "cpu_mmio_read_bus_bytes": 4 * counters["cpu_mmio_reads"],
        "cpu_mmio_write_bytes": counters["cpu_mmio_write_bytes"],
        "npu_read_bytes": counters["npu_read_bytes"],
        "npu_write_bytes": counters["npu_write_bytes"],
        "npu_ar": counters["npu_ar"], "npu_aw": counters["npu_aw"],
        "jobs": counters["jobs"], "conv_jobs": counters["conv_jobs"],
        "is_jobs": counters["is_jobs"], "done_jobs": counters["done_jobs"],
        "ia_im2col_blocks": counters["ia_im2col_blocks"],
        "kernel_im2col_blocks": counters["kernel_im2col_blocks"],
        "compared_outputs": cpu["compared_outputs"],
        "output_fnv1a": f"{cpu['output_fnv1a']:08x}",
    }
    for name, region in result["regions"].items():
        for field in ["cpu_read_bus_bytes", "cpu_write_bytes", "npu_read_bytes", "npu_write_bytes"]:
            row[f"{name}_{field}"] = region[field]
    row["npu_unclassified_read_bytes"] = counters["npu_read_bytes"] - sum(
        region["npu_read_bytes"] for region in result["regions"].values())
    row["npu_unclassified_write_bytes"] = counters["npu_write_bytes"] - sum(
        region["npu_write_bytes"] for region in result["regions"].values())
    return row


def csv_write(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(directory):
    primary = json.loads((directory / "summary.json").read_text())["results"]
    assert len(primary) == 10 and all(result["passed"] for result in primary)
    rows = [flatten(result) for result in primary]
    csv_write(directory / "results.csv", rows)
    comparisons = []
    for layer in dict.fromkeys(row["layer"] for row in rows):
        baseline = next(row for row in rows if row["layer"] == layer and row["mode"] == 0)
        hardware = next(row for row in rows if row["layer"] == layer and row["mode"] == 1)
        comparisons.append({
            "layer": layer, "legacy_call_cycles": baseline["call_cycles"],
            "hardware_ws_call_cycles": hardware["call_cycles"],
            "speedup_legacy_div_hardware": baseline["call_cycles"] / hardware["call_cycles"],
            "hardware_cycle_change_percent": 100 * (hardware["call_cycles"] / baseline["call_cycles"] - 1),
            "legacy_npu_busy_cycles": baseline["npu_busy_cycles"],
            "hardware_npu_busy_cycles": hardware["npu_busy_cycles"],
            "legacy_non_npu_busy_cycles": baseline["non_npu_busy_call_cycles"],
            "hardware_non_npu_busy_cycles": hardware["non_npu_busy_call_cycles"],
            "legacy_npu_read_bytes": baseline["npu_read_bytes"],
            "hardware_npu_read_bytes": hardware["npu_read_bytes"],
            "legacy_cpu_scratch_write_bytes": baseline["scratch_cpu_write_bytes"],
            "hardware_cpu_scratch_write_bytes": hardware["scratch_cpu_write_bytes"],
            "legacy_starts": baseline["jobs"], "hardware_starts": hardware["jobs"],
        })
    csv_write(directory / "comparisons.csv", comparisons)
    (directory / "comparisons.json").write_text(json.dumps(comparisons, indent=2) + "\n")
    extra = []
    for name in ["latency4_summary.json", "is_summary.json"]:
        extra.extend(json.loads((directory / name).read_text())["results"])
    assert len(extra) == 3 and all(result["passed"] for result in extra)
    csv_write(directory / "results_extra.csv", [flatten(result) for result in extra])
    print(json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    summarize(parser.parse_args().directory)
