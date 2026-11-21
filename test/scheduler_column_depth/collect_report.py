#!/usr/bin/env python3
"""检查综合、形式验证与独立功能测试的源码版本，并保存统一摘要。"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from support import ROOT, check_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "build/scheduler_column_depth"
    parser.add_argument("--measurement", type=Path, default=base / "measurement")
    parser.add_argument("--formal", type=Path, default=base / "formal")
    parser.add_argument("--functional", type=Path, default=base / "functional")
    parser.add_argument("--out", type=Path, default=base / "results.json")
    args = parser.parse_args()
    measurement = json.loads((args.measurement / "measurement.json").read_text())
    formal = json.loads((args.formal / "summary.json").read_text())
    functional = json.loads((args.functional / "summary.json").read_text())
    if not formal["passed"] or not functional["passed"]:
        raise RuntimeError("验证未全部通过")
    if formal["inputs"] != measurement["inputs"]:
        raise RuntimeError("综合与形式验证的输入文件不同")
    check_sources(measurement["inputs"])
    expected = measurement["inputs"]["source_sha256"]
    source_name = Path(measurement["inputs"].get("source_path", measurement["inputs"]["source"])).name
    tests = {}
    for name, test in functional["tests"].items():
        hashes = [value for path, value in test["source_sha256"].items()
                  if Path(path).name == source_name]
        if hashes != [expected] or not test["passed"]:
            raise RuntimeError(f"独立功能测试的调度器源码不同：{name}")
        for helper, expected_helper in measurement["inputs"]["helper_sha256"].items():
            helper_hashes = [value for path, value in test["source_sha256"].items()
                             if Path(path).name == Path(helper).name]
            if helper_hashes != [expected_helper]:
                raise RuntimeError(f"独立功能测试的公共依赖不同：{name} {helper}")
        tests[name] = {key: value for key, value in test.items()
                       if key not in ("compile_command", "run_command", "source_sha256", "elapsed_seconds")}
        tests[name]["source_sha256"] = {Path(path).name: value
                                        for path, value in test["source_sha256"].items()}
    derived_state_bits = {}
    registered_relation_bits = {"reference": 0, "current": 0}
    if "frame_open" in formal.get("additional_relation_outputs", []):
        derived_state_bits["frame_open"] = measurement["parameters"]["FRAME_COUNT"]
        for label in registered_relation_bits:
            source_path = args.measurement / "inputs" / label / measurement["inputs"]["source"]
            source_text = source_path.read_text()
            if re.search(r"\bframe_open\s*(?:\[[^]]+\])?\s*<=", source_text):
                registered_relation_bits[label] += derived_state_bits["frame_open"]
    result = {
        "passed": True, "synthesis": measurement,
        "behavior": {"additional_pipeline_stages": 0,
                     "derived_state_bits": derived_state_bits,
                     "registered_relation_bits": registered_relation_bits,
                     "registered_state_bits_added": registered_relation_bits["current"] -
                         registered_relation_bits["reference"],
                     "mapped_flip_flop_change":
                         measurement["cases"]["current"]["resources"]["flip_flops"] -
                         measurement["cases"]["reference"]["resources"]["flip_flops"],
                     "public_cycle_relationships_unchanged": True},
        "formal": formal,
        "functional": {"passed": True, "cases": functional["cases"],
                       "commands": functional["commands"], "tests": tests},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.out)


if __name__ == "__main__":
    main()
