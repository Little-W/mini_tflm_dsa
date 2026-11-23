#!/usr/bin/env python3
"""核对共同算子的输入、实际日志、访存条件及公开加速器周期。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from compare_fair_operators import memory_segment, records


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def check_run(run: Path, reference: dict) -> dict:
    """根据编译记录、逐项日志和完整内存检查生成比较结果。"""
    summary = load(run / "summary.json")
    build = load(run / "sim/build.json")
    binary = run / "sim/obj/Vtb_latest_operators"
    require(summary["passed"] and build["returncode"] == 0, "Simulation must pass")
    require(build["sources_unchanged_during_build"], "Compilation inputs changed")
    require(digest(binary) == build["binary_sha256"], "Simulator checksum differs")
    require("--assert" in build["command"], "RTL assertions must be enabled")
    for path, expected in build["source_sha256"].items():
        require(digest(Path(path)) == expected, "Compilation source differs: " + path)
    profile = summary["profile"]
    require(profile == build["profile"], "Hardware profiles differ")
    planner = load(run / "planner/build.json")
    require(planner["profile"] == profile, "Production planner hardware profile differs")
    for path, expected in planner["source_sha256"].items():
        require(digest(Path(path)) == expected, "Production planner source differs: " + path)
    for key, expected in reference["npu_profile"].items():
        require(profile[key] == expected, "Hardware setting differs: " + key)
    require(profile["memory_timing"]["ram_read_first_latency"] == 8,
            "The first read response must have eight-cycle service latency")
    expected_cases = {row["name"]: row for row in reference["cases"]}
    checked = []
    observed_names = set()
    for group_name in ("gemm", "conv"):
        group = load(run / group_name / "summary.json")
        require(group["passed"] and group["profile"] == profile,
                "Result group settings differ: " + group_name)
        require(group["build_manifest_sha256"] == digest(run / "sim/build.json"),
                "Result group build record differs")
        for row in group["cases"]:
            name = row["name"]
            require(name in expected_cases and name not in observed_names,
                    "Unexpected or repeated case: " + name)
            observed_names.add(name)
            target = expected_cases[name]
            require(row["passed"] and row["returncode"] == 0, "Case failed: " + name)
            require(row["workload_manifest_sha256"] == target["workload_manifest_sha256"],
                    "Workload description differs: " + name)
            require(row["input_tensor_sha256"] == target["input_tensor_sha256"],
                    "Input tensor checksums differ: " + name)
            require(row["output_sha256"] == row["observed_output_sha256"] == target["output_sha256"],
                    "Output tensor checksum differs: " + name)
            require("+NO_RANDOM_WAIT" in row["command"], "Memory service must be deterministic")
            require(row["command"][0] == str(binary), "Case used a different simulator")
            directory = run / group_name / "cases" / name
            configuration = [int(word, 16) for word in (directory / "config.mem").read_text().split()]
            require(configuration == row["configuration_words"], "Recorded task configuration differs")
            for filename, expected in row["files"].items():
                require(digest(directory / filename) == expected,
                        "Case memory image differs: " + name + "/" + filename)
            log = (directory / "run.log").read_text()
            measured, timing = row["measurement"], row["timing"]
            require(records(log, "COMMON_OPERATOR_PASS") == [measured],
                    "RTL result log differs: " + name)
            require(records(log, "COMMON_TIMING") == [timing], "Timing log differs: " + name)
            require(records(log, "COMMON_SCHEDULE") == [row["observed_schedule"]],
                    "Observed scheduling record differs: " + name)
            require(measured["cycles"] == timing["done"], "Completion counters differ")
            require(timing["read_latency_min"] >= 8, "Read response arrived too early")
            require(timing["read_outstanding_max"] <= 4 and timing["write_outstanding_max"] <= 4,
                    "Memory concurrency exceeds four reads or writes")
            require(max(timing["read_burst_bytes_max"], timing["write_burst_bytes_max"]) <= 2048,
                    "An AXI burst exceeds the configured limit")
            require(measured["ar_bytes"] == 8 * timing["read_beats"],
                    "AXI64 byte and beat counts differ")
            require(max(timing["last_r"], timing["last_b"]) <= timing["done"],
                    "Completion preceded the final memory response")
            output = memory_segment(directory / "golden.mem", row["addresses"]["c"],
                                    target["output_elements"])
            require(hashlib.sha256(output).hexdigest() == target["output_sha256"],
                    "The checked output image differs from the common output")
            cycles = measured["cycles"]
            public = target["public_cycles"]
            checked.append({
                "name": name, "kind": target["kind"], "shape": target["shape"],
                "npu_cycles": cycles, "public_cycles": public,
                "npu_remote_cycles": target["npu_remote_cycles"],
                "npu_previous_low_latency_cycles": target["npu_previous_low_latency_cycles"],
                "strictly_faster_than_all": all(cycles < value for value in public.values()),
                "output_sha256": target["output_sha256"],
                "schedule": row.get("schedule"), "timing": timing,
            })
    require(observed_names == set(expected_cases), "The common operator collection is incomplete")
    gemm = [row for row in checked if row["kind"] == "gemm"]
    groups = {}
    for kind in ("gemm", "conv", "dw", "all"):
        rows = [row for row in checked if kind == "all" or row["kind"] == kind]
        groups[kind] = {
            "cases": len(rows),
            "npu_cycles": sum(row["npu_cycles"] for row in rows),
            "gemmini_cycles": sum(row["public_cycles"]["gemmini_bird"] for row in rows),
            "strictly_faster_than_all": sum(row["strictly_faster_than_all"] for row in rows),
        }
    return {"numerical_and_timing_checks_passed": True,
            "all_gemm_strictly_leading": all(row["strictly_faster_than_all"] for row in gemm),
            "source_commit": summary["source_commit"], "profile": profile,
            "build_manifest_sha256": digest(run / "sim/build.json"),
            "planner_manifest_sha256": digest(run / "planner/build.json"),
            "groups": groups, "cases": checked}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--reference", type=Path,
                        default=Path(__file__).with_name("public_operator_reference_20261123.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--require-leading-gemm", action="store_true")
    args = parser.parse_args()
    result = check_run(args.run.resolve(), load(args.reference))
    result["reference_sha256"] = digest(args.reference)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    fields = ("name", "kind", "npu_remote_cycles", "npu_previous_low_latency_cycles",
              "npu_cycles", "gemmini_bird", "vta", "coral_vme", "strictly_faster_than_all")
    with (args.out / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in result["cases"]:
            item = {key: row[key] for key in fields if key in row}
            item.update(row["public_cycles"])
            writer.writerow(item)
    print(json.dumps({key: result[key] for key in (
        "numerical_and_timing_checks_passed", "all_gemm_strictly_leading", "groups")}, indent=2))
    return int(args.require_leading_gemm and not result["all_gemm_strictly_leading"])


if __name__ == "__main__":
    raise SystemExit(main())
