#!/usr/bin/env python3
"""Collect verified model and common-operator measurements for the report."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--models", type=Path, required=True)
parser.add_argument("--initialization", type=Path, required=True)
parser.add_argument("--validation", type=Path, required=True)
parser.add_argument("--gemm", type=Path, required=True)
parser.add_argument("--conv", type=Path, required=True)
parser.add_argument("--cache", type=Path, required=True)
parser.add_argument("--gemmini-search", type=Path, required=True)
parser.add_argument("--reference-set", type=Path)
parser.add_argument("--window-pipeline", type=Path)
parser.add_argument("--bottlenecks", type=Path)
parser.add_argument("--timing", type=Path)
parser.add_argument("--depthwise-mapping", type=Path)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
REPO = Path(__file__).resolve().parents[2]
args.out.mkdir(parents=True, exist_ok=True)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


model = read(args.models)
gemm = read(args.gemm)
conv = read(args.conv)
assert gemm["passed"] and conv["passed"]
validation = read(args.validation)
assert validation["passed"]
assert validation.get("complete", True)
for name, expected in validation.get("production_source_sha256", {}).items():
    assert sha(REPO / name) == expected, f"Production source changed after validation: {name}"

profiles = list(dict.fromkeys(r["gemmini_profile"] for r in gemm["cases"]))
assert profiles and set(profiles) == {r["gemmini_profile"] for r in conv["cases"]}
totals = []
for config in profiles:
    g = [r for r in gemm["cases"] if r["gemmini_profile"] == config]
    c = [r for r in conv["cases"] if r["gemmini_profile"] == config]
    assert len(g) == 31 and len(c) == 3
    assert len({r["name"] for r in g}) == 31 and len({r["name"] for r in c}) == 3
    totals.append({
        "gemmini_profile": config,
        "gemm_npu_cycles": sum(r["mini_modified_cycles"] for r in g),
        "gemm_gemmini_cycles": sum(r["gemmini_cycles"] for r in g),
        "gemm_npu_faster_cases": sum(r["mini_modified_cycles"] < r["gemmini_cycles"] for r in g),
        "conv_npu_cycles": sum(r["mini_modified_cycles"] for r in c),
        "conv_gemmini_cycles": sum(r["gemmini_cycles"] for r in c),
        "conv_npu_faster_cases": sum(r["mini_modified_cycles"] < r["gemmini_cycles"] for r in c),
    })

input_files = [args.models, args.initialization, args.validation,
               args.gemm, args.conv, args.cache, args.gemmini_search]
if args.reference_set:
    input_files.append(args.reference_set)
for optional in (args.window_pipeline, args.bottlenecks, args.timing, args.depthwise_mapping):
    if optional:
        input_files.append(optional)

out = {
    "scope": {
        "common_operators": "Complete accelerator RTL, host CPU execution excluded; common 32-bit AXI service and numerical tensors.",
        "models": "PicoRV32 executes complete TFLM Invoke; two inputs per model, independent performance and tensor-trace runs.",
        "clock_hz_for_time_conversion": 100000000,
        "clock_is_post_synthesis_measurement": False,
        "gemmini_full_tflm_models_executed": False,
        "sources": {str(p.resolve()): sha(p) for p in input_files},
    },
    "versions": {
        "mini_original": "48b73c51242c2bb1636bc30cbfc130dcda4d9834",
        "mini_modified_production": validation["tested_production_commit"],
        "gemmini": "b82d49cca798a59f010488a6f6de7243f0616536",
        "gemmini_rocc_tests": "7ac28e7e7f447d4131db03292de405e5bd978410",
        "final_frontend_sha256": hashlib.sha256((REPO / "rtl/npu/conv/conv_im2col_frontend.sv").read_bytes()).hexdigest(),
    },
    "models": model["models"],
    "aggregate_invoke": model["aggregate_one_inference_per_model"],
    "aggregate_initialization_and_invoke": model["aggregate_initialization_plus_one_inference_per_model"],
    "initialization": read(args.initialization),
    "definitions": model["definitions"],
    "common_gemm_memory_service": model["common_gemm_memory_service"],
    "operator_totals": totals,
    "gemmini_profiles": gemm["gemmini_profiles"],
    "npu_profile": gemm["mini_modified_profile"],
    "npu_conv_profile": conv["mini_modified_profile"],
    "gemm": gemm["cases"],
    "conv": conv["cases"],
    "window_cache": read(args.cache),
    "gemmini_schedule_search": read(args.gemmini_search),
    "validation": validation,
}
if args.reference_set:
    references = read(args.reference_set)
    assert references["passed"] and references["total_cases"] == 31
    assert references["npu_total_cycles"] == totals[0]["gemm_npu_cycles"]
    out["gemmini_reference_set"] = references
for key, path in (("window_pipeline", args.window_pipeline),
                  ("bottleneck_analysis", args.bottlenecks),
                  ("timing_analysis", args.timing),
                  ("gemmini_depthwise_mapping", args.depthwise_mapping)):
    if path:
        value = read(path)
        assert value["passed"], path
        out[key] = value
target = args.out / "gemmini_measurements.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")

fields = ["name", "operation", "m", "n", "k", "useful_macs", "npu_cycles",
          *[config + "_cycles" for config in profiles], "npu_read_bytes",
          *[config + "_read_bytes" for config in profiles], "output_sha256"]
with (args.out / "gemmini_operator_cycles.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for data in (gemm, conv):
        names = list(dict.fromkeys(r["name"] for r in data["cases"]))
        for name in names:
            rows = {r["gemmini_profile"]: r for r in data["cases"] if r["name"] == name}
            first = rows[profiles[0]]
            assert len({r["mini_modified_cycles"] for r in rows.values()}) == 1
            assert len({r["output_sha256"] for r in rows.values()}) == 1
            row = {"name": name, "operation": first["operator"],
                   **first.get("matrix_shape", {}), "useful_macs": first["useful_macs"],
                   "npu_cycles": first["mini_modified_cycles"],
                   "npu_read_bytes": first["mini_modified_read_bytes"],
                   "output_sha256": first["output_sha256"]}
            for config, r in rows.items():
                row[config + "_cycles"] = r["gemmini_cycles"]
                row[config + "_read_bytes"] = r["gemmini_read_bytes"]
            writer.writerow(row)
print(json.dumps({"models": len(model["models"]), "common_cases": 34,
                  "comparisons": len(gemm["cases"]) + len(conv["cases"]),
                  "gemmini_configurations": len(profiles), "json_bytes": target.stat().st_size}))
