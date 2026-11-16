#!/usr/bin/env python3
"""Validate hardware-parameterized traffic expansion against saved RTL runs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path

from read_traffic import command_read_traffic


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_trace(path):
    records = []
    for line in Path(path).read_text().splitlines():
        if line == "FENCE":
            records.append({"fence": True})
        else:
            funct, rs1, rs2 = (int(value, 0) for value in line.split())
            records.append(dict(funct=funct, rs1=rs1, rs2=rs2))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-root", action="append", type=Path, default=[])
    parser.add_argument("--results", type=Path)
    parser.add_argument("--traces", type=Path)
    parser.add_argument("--dma-max-bytes", type=int, default=64)
    parser.add_argument("--reference-model", type=Path)
    parser.add_argument("--allow-partial", action="store_true",
                        help="Validate completed cases from a suite containing unsuccessful runs")
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reference = None
    if args.reference_model:
        if args.dma_max_bytes != 64:
            raise ValueError("The reference model describes 64-byte hardware")
        spec = importlib.util.spec_from_file_location("reference_read_traffic", args.reference_model)
        reference = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reference)
    items, inputs, excluded = [], [], []
    for root in args.search_root:
        for path in sorted(root.glob("*/*/*/record.json")):
            record = json.loads(path.read_text())
            if record.get("status") == "passed":
                items.append((str(path.relative_to(root)), path, path.with_name("commands.txt"),
                              record["result"], record.get("commands_sha256"), root.name))
    if args.results:
        if not args.traces:
            raise ValueError("A trace directory is required for result summaries")
        summary = json.loads(args.results.read_text())
        hardware_max = summary.get("configuration", {}).get("dma_max_bytes")
        if hardware_max is not None and hardware_max != args.dma_max_bytes:
            raise ValueError("Requested DMA maximum differs from the measured hardware configuration")
        suite_passed = summary.get("passed", all(row.get("passed", False) for row in summary["cases"]))
        if not suite_passed and not args.allow_partial:
            raise ValueError("The supplied result summary did not pass")
        inputs.append(dict(path=str(args.results.resolve()), sha256=digest(args.results),
                           suite_passed=suite_passed,
                           build_manifest_sha256=summary.get("build_manifest_sha256"),
                           configuration=summary.get("configuration")))
        excluded.extend(summary.get("failures", []))
        for case in summary["cases"]:
            if not case.get("passed", False) and args.allow_partial:
                excluded.append(dict(name=case["name"], reason="RTL validation did not pass"))
                continue
            commands = args.traces / case["name"] / "commands.txt"
            items.append((case["name"], args.results, commands, case,
                          case.get("commands_sha256"), args.results.parent.name))
    if not items or args.expected_count is not None and len(items) != args.expected_count:
        raise ValueError(f"Expected {args.expected_count} measured cases, found {len(items)}")
    checked, failures, groups = [], [], Counter()
    for name, source, commands, actual, expected_hash, group in items:
        if (not actual.get("passed") or actual.get("outside_output_mismatches", 0) or
                actual.get("output_mismatches", 0) or not actual.get("memory_drained", True)):
            raise ValueError(f"RTL validation did not pass: {source}")
        command_hash = digest(commands)
        if expected_hash and command_hash != expected_hash:
            raise ValueError(f"Command checksum differs: {commands}")
        trace = read_trace(commands)
        predicted = command_read_traffic(trace, dma_max_bytes=args.dma_max_bytes)
        matches = all(predicted[key] == actual[key] for key in ("read_bytes", "read_requests"))
        reference_matches = reference is None or reference.command_read_traffic(trace) == predicted
        row = dict(group=group, name=name, commands_sha256=command_hash,
                   source_sha256=digest(source), predicted=predicted,
                   observed={key: actual[key] for key in ("read_bytes", "read_requests")},
                   matches=matches, reference_matches=reference_matches)
        if "max_read_burst_bytes" in actual:
            row["observed_max_read_burst_bytes"] = actual["max_read_burst_bytes"]
            if actual["max_read_burst_bytes"] > args.dma_max_bytes:
                raise ValueError("Measured read burst exceeds the configured hardware maximum")
        checked.append(row)
        groups[group] += 1
        if not matches or not reference_matches:
            failures.append(row)
    result = dict(passed=not failures, hardware_dma_max_bytes=args.dma_max_bytes,
                  checked_cases=len(checked), groups=dict(groups), failures=failures, cases=checked,
                  inputs=inputs, excluded_runs=excluded,
                  model_sha256=digest(Path(__file__).with_name("read_traffic.py")),
                  validator_sha256=digest(__file__),
                  reference_model_sha256=digest(args.reference_model) if args.reference_model else None,
                  definitions={"software_loads": "Use the exact encoded command column count; software MAX_BYTES does not determine the hardware packet size",
                               "hardware_loops": "A/B groups use dma_max_bytes/16, INT32 D groups use dma_max_bytes/64, each at least one block",
                               "timing_lower_bound": "Two cycles per 32-bit read beat and one additional cycle per request"})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "hardware_dma_max_bytes", "checked_cases", "groups")}, indent=2))
    if failures:
        print(json.dumps(failures[:5], indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
