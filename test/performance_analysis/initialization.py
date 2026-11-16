#!/usr/bin/env python3
"""Measure initialization cost and repeated-inference amortization from RTL runs."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean


def read_models(directory: Path, mode: int) -> dict:
    models = {}
    for path in sorted(directory.glob(f"*/sample_*/perf_{mode}/result.json")):
        run = json.loads(path.read_text())
        if not run["passed"]:
            raise ValueError(f"Inference did not pass: {path}")
        models.setdefault(run["model_id"], []).append(run)
    if not models:
        raise ValueError("No passing performance runs were found")
    return models


def measurements(runs: list) -> dict:
    result = {key: mean(run["result"][key] for run in runs)
              for key in ("init_cycles", "invoke_cycles", "arena_used_bytes")}
    result["initialize_and_invoke_cycles"] = result["init_cycles"] + result["invoke_cycles"]
    result["samples"] = [run["sample_index"] for run in runs]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--modified", type=Path, required=True)
    parser.add_argument("--original-mode", type=int, default=31)
    parser.add_argument("--modified-mode", type=int, default=63)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    before = read_models(args.original, args.original_mode)
    after = read_models(args.modified, args.modified_mode)
    if before.keys() != after.keys():
        raise ValueError("The two result directories cover different models")
    rows = []
    for name in sorted(before):
        old, new = measurements(before[name]), measurements(after[name])
        if old["samples"] != new["samples"]:
            raise ValueError("The two versions cover different input samples")
        extra_init = new["init_cycles"] - old["init_cycles"]
        saved = old["invoke_cycles"] - new["invoke_cycles"]
        break_even = max(1, math.ceil(extra_init / saved)) if saved > 0 else None
        rows.append({"model": name, "original": old, "modified": new,
                     "additional_initialization_cycles": extra_init,
                     "saved_cycles_per_invoke": saved,
                     "minimum_inferences_to_amortize_initialization": break_even})
    output = {"definition": {
        "initialization": "Firmware init_start through init_cycles, including model access, operator registration, AllocateTensors, input/output lookup and the first input copy; excludes firmware boot before init_start.",
        "invoke": "Unprofiled MicroInterpreter::Invoke measured by the RV32 cycle counter.",
        "amortization": "Smallest positive inference count for which additional initialization is covered by the measured mean Invoke saving; assumes the same initialized interpreter is reused.",
        "memory": "Tensor arena bytes reported by arena_used_bytes, excluding firmware and external model storage."},
        "models": rows,
        "aggregate_one_inference_per_model": {
            "original_initialize_and_invoke_cycles": sum(r["original"]["initialize_and_invoke_cycles"] for r in rows),
            "modified_initialize_and_invoke_cycles": sum(r["modified"]["initialize_and_invoke_cycles"] for r in rows)}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"models": len(rows), "result": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
