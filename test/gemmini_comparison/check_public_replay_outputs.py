#!/usr/bin/env python3
"""独立比较 NPU 与 Gemmini、VTA、Coral 重新执行后的实际输出文件。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run, replay, out = args.run.resolve(), args.replay.resolve(), args.out.resolve()
    public = json.loads((replay / "public_replay_summary.json").read_text())
    assert public["passed"]
    assert public["source_archive"]["sha256"] == "177b003e89bcaf1a233c8053d5c70708b1c0b08cf5b97f6e487c2af5735457b1"
    targets = {row["name"]: row for row in public["common_cases"]}
    comparisons = []
    for group in ("gemm", "conv"):
        summary = json.loads((run / group / "summary.json").read_text())
        assert summary["passed"]
        for row in summary["cases"]:
            name = row["name"]
            target = targets[name]
            observed = run / group / "cases" / name / "canonical_output.bin"
            actual = observed.read_bytes()
            assert len(actual) == target["output_elements"]
            assert digest(observed) == row["observed_output_sha256"] == target["output_sha256"]
            files = {"gemmini_bird": replay / "gemmini" / group / (
                name + ".output.bin" if group == "gemm" else name + "/result.output.bin")}
            if group == "gemm":
                files.update(vta=replay / "vta/cases" / name / "actual.bin",
                             coral_vme=replay / "coral/cases/external_staged" / name / "actual.bin")
            assert set(files) == set(target["cycles"])
            hashes = {}
            for accelerator, path in files.items():
                assert path.read_bytes() == actual, (name, accelerator)
                hashes[accelerator] = digest(path)
            comparisons.append({"name": name, "kind": group, "output_elements": len(actual),
                                "actual_output_sha256": digest(observed),
                                "public_actual_output_sha256": hashes, "passed": True})
    assert len(comparisons) == 36
    result = {"passed": True, "case_count": len(comparisons),
              "output_values": sum(row["output_elements"] for row in comparisons),
              "source_archive": public["source_archive"],
              "public_replay_summary_sha256": digest(replay / "public_replay_summary.json"),
              "comparison": "Actual output files compared byte for byte", "cases": comparisons}
    out.mkdir(parents=True, exist_ok=True)
    (out / "actual_output_comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "case_count", "output_values")}))


if __name__ == "__main__":
    main()
