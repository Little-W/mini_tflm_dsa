#!/usr/bin/env python3
"""Compare the matrix planner's traffic estimates with measured AXI events."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "veri/top_regression"))
from host_schedule import schedules


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(summary: dict) -> dict:
    if not summary.get("passed") or not summary.get("cases"):
        raise ValueError("A complete successful GEMM measurement is required")
    rows = []
    for case in summary["cases"]:
        if not case.get("passed"):
            raise ValueError("Every measured case must have passed")
        config = dict(case["schedule_configuration"], flow=int(case["dataflow"] == "is"))
        reuse = case["tiling"]
        matches = [candidate for candidate in schedules(config)
                   if all(candidate["tiling"][key] == reuse[key]
                          for key in ("ia_reuse", "w_reuse"))]
        if len(matches) != 1:
            raise ValueError("Measured configuration is absent from the legal schedule candidates")
        estimate, measured, timing = matches[0], case["measurement"], case["timing"]
        expected_read_bytes = estimate["read_words"] * 4
        rows.append(dict(
            name=case["name"], m=case["m"], n=case["n"], k=case["k"],
            dataflow=case["dataflow"], physical_layout=case["physical_layout"],
            ia_reuse=reuse["ia_reuse"], w_reuse=reuse["w_reuse"],
            workload_manifest_sha256=case["workload_manifest_sha256"],
            predicted_read_bytes=expected_read_bytes,
            measured_read_bytes=measured["ar_bytes"],
            read_bytes_match=expected_read_bytes == measured["ar_bytes"],
            predicted_read_requests=estimate["read_requests"],
            measured_read_requests=measured["ar_requests"],
            read_request_delta=measured["ar_requests"]-estimate["read_requests"],
            predicted_write_words=estimate["write_words"],
            measured_write_words=timing["write_beats"],
            write_word_delta=timing["write_beats"]-estimate["write_words"],
            predicted_write_requests=estimate["write_requests"],
            measured_write_requests=timing["write_commands"],
            write_requests_match=estimate["write_requests"] == timing["write_commands"],
            measured_cycles=measured["cycles"],
        ))
    return dict(
        passed=all(row["read_bytes_match"] and row["write_requests_match"] for row in rows),
        cases=rows,
        exact_read_byte_cases=sum(row["read_bytes_match"] for row in rows),
        exact_write_request_cases=sum(row["write_requests_match"] for row in rows),
        definitions={
            "read_bytes": "Physical 32-bit AXI read data, including operand repetition, word alignment, packing padding and parameter tables",
            "read_requests": "Scheduling estimate before 4 KiB splitting; parameter request grouping is approximated by 16-channel blocks",
            "write_words": "Dense row word estimate; per-tile unaligned output transfers may add physical words",
            "write_requests": "Output tile or eligible coalesced-group requests; boundary splitting can add requests for other output layouts",
            "timing": "Measured accelerator launch through completion; estimated traffic is not an elapsed-cycle measurement",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mini", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.mini.read_text()))
    result["measurement_sha256"] = digest(args.mini)
    result["schedule_source_sha256"] = {
        name: digest(ROOT / name)
        for name in ("drivers/dsa_schedule.h", "veri/top_regression/host_schedule.py")
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                     ("passed", "exact_read_byte_cases", "exact_write_request_cases")}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
