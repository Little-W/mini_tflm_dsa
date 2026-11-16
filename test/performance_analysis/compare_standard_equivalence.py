#!/usr/bin/env python3
"""Compare the standard-core hardware performance runs of two source versions."""

import argparse
import copy
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(path):
    return {"path": str(path), "sha256": sha256(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True,
                        help="Original measurement directory containing sim/build.json and results/cases")
    parser.add_argument("--proposed", type=Path, required=True,
                        help="Proposed measurement directory containing the same eight hardware performance cases")
    parser.add_argument("--patch-manifest", type=Path, required=True,
                        help="JSON file with a files list of path, source_sha256, and proposed_sha256")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output JSON report path")
    args = parser.parse_args()
    original = args.original.resolve()
    proposed = args.proposed.resolve()
    original_build_path = original / "sim/build.json"
    proposed_build_path = proposed / "sim/build.json"
    old_build = json.loads(original_build_path.read_text())
    new_build = json.loads(proposed_build_path.read_text())
    patch = json.loads(args.patch_manifest.read_text())
    expected_changes = {item["path"]: item for item in patch["files"]}
    old_sources = old_build["source_sha256"]
    new_sources = new_build["source_sha256"]
    changed_sources = {
        name: {"original_sha256": old_sources[name],
               "proposed_sha256": new_sources.get(name)}
        for name in old_sources if old_sources[name] != new_sources.get(name)
    }
    checks = {
        "same_profile": old_build["profile"] == new_build["profile"],
        "same_configuration": old_build["configuration"] == new_build["configuration"],
        "same_dependencies": old_build["external_dependency_sha256"] == new_build["external_dependency_sha256"],
        "same_picorv32_commit": old_build["picorv32_commit"] == new_build["picorv32_commit"],
        "same_verilator": old_build["verilator"] == new_build["verilator"],
        "same_source_file_set": set(old_sources) == set(new_sources),
        "exact_patch_file_set": set(changed_sources) == set(expected_changes),
        "exact_patch_hashes": all(
            name in expected_changes
            and item["original_sha256"] == expected_changes[name]["source_sha256"]
            and item["proposed_sha256"] == expected_changes[name]["proposed_sha256"]
            for name, item in changed_sources.items()
        ),
        "sources_unchanged_during_build": old_build["sources_unchanged_during_build"]
            and new_build["sources_unchanged_during_build"],
    }
    pairs = []
    for path in sorted((proposed / "results/cases").glob("*/*/perf_63/result.json")):
        original_path = original / path.relative_to(proposed)
        old = json.loads(original_path.read_text())
        new = json.loads(path.read_text())
        normalized = []
        for root, record in [(original, old), (proposed, new)]:
            value = copy.deepcopy(record)
            value.pop("case_dir")
            value.pop("host_seconds")
            value["simulator"].pop("simulator_sha256")
            value["simulator"]["command"] = [
                argument.replace(str(root), "MEASUREMENT_ROOT")
                for argument in value["simulator"]["command"]
            ]
            normalized.append(value)
        pair_checks = {
            "both_passed": old["passed"] and new["passed"],
            "all_result_fields_equal": normalized[0] == normalized[1],
            "result_bytes_equal": (original_path.parent / "result.bin").read_bytes()
                == (path.parent / "result.bin").read_bytes(),
            "output_bytes_equal": (original_path.parent / "output.bin").read_bytes()
                == (path.parent / "output.bin").read_bytes(),
            "original_simulator_matches_build": old["simulator"]["simulator_sha256"] == old_build["binary_sha256"],
            "proposed_simulator_matches_build": new["simulator"]["simulator_sha256"] == new_build["binary_sha256"],
        }
        pairs.append({
            "model_id": new["model_id"], "sample_index": new["sample_index"],
            "passed": all(pair_checks.values()), "checks": pair_checks,
            "original_result": reference(original_path),
            "proposed_result": reference(path),
            "invoke_cycles": new["result"]["invoke_cycles"],
            "init_cycles": new["result"]["init_cycles"],
            "npu_busy_cycles": new["network"]["npu_busy_cycles"],
            "network_counter_fields": len(new["network"]),
            "all_counter_scopes": [row["scope"] for row in new["simulator"]["counters"]],
            "window_job_records": len(new["simulator"]["window_jobs"]),
            "output_sha256": new["simulator"]["output_sha256"],
            "firmware_elf_sha256": new["firmware_elf_sha256"],
        })
    expected_models = {"mnist_cnn", "mobilenet_v1_vww", "ds_cnn_kws", "resnet8_cifar10"}
    checks["complete_eight_cases"] = {
        (row["model_id"], row["sample_index"]) for row in pairs
    } == {(model, sample) for model in expected_models for sample in [0, 1]} and len(pairs) == 8
    checks["all_cases_equal"] = all(row["passed"] for row in pairs)
    summary = {
        "passed": all(checks.values()),
        "script_sha256": sha256(Path(__file__)),
        "scope": "Standard core; four complete models, two inputs each, hardware performance firmware",
        "comparison": "Every result field, firmware result byte, output byte, boot/network counter, CPU/DMA profile, and window job record",
        "metadata_normalization": ["Measurement directory paths", "Host elapsed time", "Simulator binary SHA256"],
        "checks": checks,
        "profile": new_build["profile"],
        "original_build": reference(original_build_path),
        "proposed_build": reference(proposed_build_path),
        "original_simulator_sha256": old_build["binary_sha256"],
        "proposed_simulator_sha256": new_build["binary_sha256"],
        "original_source_sha256": old_sources,
        "proposed_source_sha256": new_sources,
        "changed_sources": changed_sources,
        "patch_manifest": reference(args.patch_manifest.resolve()),
        "pairs": pairs,
    }
    destination = args.out.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"passed": summary["passed"], "pairs": len(pairs), "result": str(destination)}, indent=2))
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
