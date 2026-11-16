#!/usr/bin/env python3
"""Join verified common workloads by case fingerprints and compare RTL cycles."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def load(path: Path) -> dict:
    value = json.loads(path.read_text())
    if value.get("passed") is False:
        raise ValueError("Comparison input contains a failed suite")
    if not value.get("cases") or any(not row.get("passed") for row in value["cases"]):
        raise ValueError("Comparison requires completed, successful cases")
    return value


def indexed(value: dict) -> dict:
    result = {row["name"]: row for row in value["cases"]}
    if len(result) != len(value["cases"]):
        raise ValueError("Duplicate common workload case")
    return result


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mini-original", type=Path, required=True)
    parser.add_argument("--mini-modified", type=Path, required=True)
    parser.add_argument("--gemmini", nargs="+", required=True, help="One or more profile=results.json arguments")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    args = parser.parse_args()
    original, modified = load(args.mini_original), load(args.mini_modified)
    before, after = indexed(original), indexed(modified)
    if before.keys() != after.keys():
        raise ValueError("NPU versions cover different workload cases")
    profiles, rows, sources = [], [], {"mini_original": digest(args.mini_original), "mini_modified": digest(args.mini_modified)}
    labels = set()
    for argument in args.gemmini:
        if "=" not in argument:
            raise ValueError("Gemmini input must be profile=results.json")
        label, filename = argument.split("=", 1)
        if not label or label in labels:
            raise ValueError("Gemmini profile names must be nonempty and unique")
        labels.add(label)
        path = Path(filename)
        report = load(path)
        gemmini = indexed(report)
        if before.keys() != gemmini.keys():
            raise ValueError("Gemmini and NPU cover different workload cases")
        sources[label] = digest(path)
        profiles.append({"name": label, "configuration": report["cases"][0].get("config"),
                         "hardware_configuration": report.get("configuration"),
                         "parameters_header_sha256": report["cases"][0].get("params_header_sha256")})
        for name, old in before.items():
            new, gem = after[name], gemmini[name]
            if len({old["workload_manifest_sha256"], new["workload_manifest_sha256"], gem["workload_manifest_sha256"]}) != 1:
                raise ValueError("Workload definition differs between accelerators: " + name)
            if len({old["output_sha256"], new["output_sha256"], gem["expected_output_sha256"], gem["observed_output_sha256"]}) != 1:
                raise ValueError("Expected output bytes differ between accelerators: " + name)
            if gem["output_mismatches"] != 0:
                raise ValueError("Gemmini output bytes differ from the shared reference")
            if gem["outside_output_mismatches"] != 0 or not gem["memory_drained"]:
                raise ValueError("Gemmini memory completion or non-output preservation check failed")
            old_cycles, new_cycles, gem_cycles = old["measurement"]["cycles"], new["measurement"]["cycles"], gem["cycles"]
            if min(old_cycles, new_cycles, gem_cycles) <= 0:
                raise ValueError("Measured cycles must be positive")
            launch_cycles = gem.get("launch_to_complete_cycles")
            launch_available = isinstance(launch_cycles, int) and launch_cycles > 0
            if not launch_available:
                launch_cycles = None
            macs = old["useful_macs"] if "useful_macs" in old else old["dense_macs"]
            if gem["macs"] != macs:
                raise ValueError("Compared MAC counts differ")
            row = {"name": name, "operator": old.get("operator", "gemm"), "gemmini_profile": label,
                   "useful_macs": macs, "workload_manifest_sha256": old["workload_manifest_sha256"],
                   "output_sha256": old["output_sha256"], "shared_definition_and_output_verified": True,
                   "mini_original_cycles": old_cycles, "mini_modified_cycles": new_cycles, "gemmini_cycles": gem_cycles,
                   "gemmini_launch_to_complete_cycles": launch_cycles,
                   "gemmini_launch_timing_available": launch_available,
                   "gemmini_speedup_over_original": old_cycles / gem_cycles,
                   "gemmini_speedup_over_modified": new_cycles / gem_cycles,
                   "gemmini_launch_speedup_over_modified": new_cycles / launch_cycles if launch_available else None,
                   "modified_speedup_over_original": old_cycles / new_cycles,
                   "mini_original_read_bytes": old["measurement"]["ar_bytes"],
                   "mini_modified_read_bytes": new["measurement"]["ar_bytes"], "gemmini_read_bytes": gem["read_bytes"],
                   "mini_original_write_bytes": old["measurement"]["write_bytes"],
                   "mini_modified_write_bytes": new["measurement"]["write_bytes"], "gemmini_write_bytes": gem["write_bytes"],
                   "mini_original_read_requests": old["timing"]["read_commands"],
                   "mini_modified_read_requests": new["timing"]["read_commands"], "gemmini_read_requests": gem["read_requests"],
                   "mini_original_write_requests": old["timing"]["write_commands"],
                   "mini_modified_write_requests": new["timing"]["write_commands"], "gemmini_write_requests": gem["write_requests"],
                   "mini_original_macs_per_cycle": macs / old_cycles,
                   "mini_modified_macs_per_cycle": macs / new_cycles, "gemmini_macs_per_cycle": macs / gem_cycles,
                   "mini_original_last_write_response": old["timing"]["last_b"],
                   "mini_modified_last_write_response": new["timing"]["last_b"],
                   "gemmini_last_write_response": gem["last_b_cycle"]}
            if row["operator"] == "gemm":
                row["matrix_shape"] = {key: old[key] for key in ("m", "n", "k")}
                row["mini_modified_layout"] = new.get("physical_layout", "row-major")
                row["mini_modified_dataflow"] = new.get("dataflow", "ws")
                row["mini_modified_tiling"] = new.get("tiling")
                row["gemmini_dataflow"] = gem.get("dataflow")
                row["gemmini_storage_transpose"] = gem.get("operand_storage_transpose", "none")
                row["gemmini_tensor_alignment_bytes"] = gem.get("tensor_alignment_bytes", 64)
                row["gemmini_tensor_addresses"] = gem.get("tensor_addresses")
                row["gemmini_tile"] = gem.get("explicit_tile")
            else:
                row["convolution"] = old["conv"]
            rows.append(row)
    result = {"passed": True, "source_summary_sha256": sources,
              "mini_original_profile": original["profile"], "mini_modified_profile": modified["profile"],
              "gemmini_profiles": profiles, "cases": rows,
              "definitions": {
                  "speedup": "gemmini_speedup_over_modified = mini_modified_cycles / gemmini_cycles; values above 1 favor Gemmini.",
                  "scope": "Independent cold-start operator measurements using shared synthetic tensors. GEMM inputs are already matrices; Conv/DW measurements include hardware input gathering.",
                  "timing": "Complete accelerator task with external memory service, computation and output responses. The original per-engine summaries retain exact launch/completion event definitions.",
                  "resource_comparison": "Array dimensions, internal operand widths, primary buffer capacities, auxiliary vector engines and external memory service are reported separately in profiles."}}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    fields = [key for key, value in rows[0].items() if not isinstance(value, dict)]
    with (args.out / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"passed": True, "cases": len(before), "gemmini_profiles": len(profiles),
                      "result": str((args.out / "comparison.json").resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
