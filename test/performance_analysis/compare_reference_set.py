#!/usr/bin/env python3
"""Compare common GEMM results while retaining each measured hardware configuration."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npu", type=Path, required=True)
    parser.add_argument("--gemmini", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    measured_npu = json.loads(args.npu.read_text())
    npu = {case["name"]: case for case in measured_npu["cases"]}
    if len(npu) != len(measured_npu["cases"]) or not measured_npu.get("passed"):
        raise ValueError("The NPU result set must contain unique, successful cases")
    references, configurations, sources = {}, {}, []
    for path in args.gemmini:
        measured = json.loads(path.read_text())
        config = measured["configuration"]
        if (config["array_rows"], config["array_columns"], config["dma_bus_bits"]) != (16, 16, 32):
            raise ValueError("Reference must use the common 16x16 array and 32-bit interface")
        label = (f"sp{config['scratchpad_bytes']//1024}_acc{config['accumulator_bytes']//1024}"
                 f"_dma{config['dma_max_bytes']}")
        if label in configurations and configurations[label] != config:
            raise ValueError("Configuration labels must identify identical hardware settings")
        configurations[label] = config
        sources.append(dict(path=str(path.resolve()), sha256=digest(path), configuration=label,
                            successful_cases=sum(bool(case.get("passed")) for case in measured["cases"]),
                            unsuccessful_cases=len(measured.get("failures", []))))
        for case in measured["cases"]:
            if not case.get("passed"):
                continue
            other = npu[case["name"]]
            if (not case["memory_drained"] or case["outside_output_mismatches"] or
                    case.get("output_mismatches", 0) or
                    case["workload_manifest_sha256"] != other["workload_manifest_sha256"] or
                    case["observed_output_sha256"] != case["expected_output_sha256"] or
                    case["observed_output_sha256"] != other["output_sha256"] or
                    any(case[key] != other[key] for key in ("m", "n", "k"))):
                raise ValueError(f"Common arithmetic or memory validation differs: {path}/{case['name']}")
            item = dict(configuration=label, cycles=case["cycles"],
                        source=str(path.resolve()), build_manifest_sha256=case["build_manifest_sha256"],
                        commands_sha256=case["commands_sha256"],
                        observed_output_sha256=case["observed_output_sha256"],
                        read_bytes=case["read_bytes"], read_requests=case["read_requests"],
                        write_bytes=case["write_bytes"], write_requests=case["write_requests"],
                        tensor_alignment_bytes=case.get("tensor_alignment_bytes", 64),
                        dataflow=case.get("dataflow"),
                        operand_storage_transpose=case.get("operand_storage_transpose"),
                        explicit_tile=case.get("explicit_tile"))
            by_config = references.setdefault(case["name"], {})
            if label not in by_config or item["cycles"] < by_config[label]["cycles"]:
                by_config[label] = item
    rows = []
    for name, case in npu.items():
        if name not in references:
            raise ValueError("No successful reference for " + name)
        candidates = references[name]
        best = min(candidates.values(), key=lambda value: (value["cycles"], value["configuration"]))
        cycles = case["measurement"]["cycles"]
        rows.append(dict(name=name, shape={key: case[key] for key in ("m", "n", "k")},
                         workload_manifest_sha256=case["workload_manifest_sha256"],
                         observed_output_sha256=case["output_sha256"], npu_cycles=cycles,
                         references_by_configuration=candidates, fastest_valid_reference=best,
                         npu_faster=cycles < best["cycles"],
                         reference_to_npu_cycle_ratio=best["cycles"] / cycles))
    summaries = {}
    for label, config in configurations.items():
        present = [row for row in rows if label in row["references_by_configuration"]]
        complete = len(present) == len(rows)
        summaries[label] = dict(configuration=config, covered_cases=len(present), complete_case_set=complete,
                                total_cycles=(sum(row["references_by_configuration"][label]["cycles"]
                                                  for row in present) if complete else None),
                                npu_faster_cases=sum(row["npu_cycles"] <
                                    row["references_by_configuration"][label]["cycles"] for row in present))
    result = dict(passed=True, npu_source=str(args.npu.resolve()), npu_source_sha256=digest(args.npu),
                  reference_sources=sources, configurations=summaries, cases=rows,
                  npu_total_cycles=sum(row["npu_cycles"] for row in rows),
                  npu_faster_than_every_valid_reference=sum(row["npu_faster"] for row in rows),
                  total_cases=len(rows),
                  definitions={"per_case_minimum": "The fastest successful measured result across the listed hardware configurations",
                               "incomplete_configuration": "Only its successful cases participate; no total is computed"})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "total_cases", "npu_total_cycles",
                                                "npu_faster_than_every_valid_reference")}, indent=2))


if __name__ == "__main__":
    main()
