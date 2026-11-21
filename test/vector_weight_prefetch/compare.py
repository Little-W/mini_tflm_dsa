#!/usr/bin/env python3
"""逐项比较权重预取前后的功能用例、周期统计和数据传输统计。"""

import argparse
import hashlib
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    candidate = json.loads(args.candidate.read_text())
    for key in ("tile", "cache_sets", "cache_policy", "cache_line_bytes", "bus_width",
                "window_lanes", "shared_quant", "shared_storage", "implementation"):
        if reference[key] != candidate[key]:
            raise RuntimeError(f"比较配置不一致: {key}")
    for key, default in (("shared_bank_bytes", 4096), ("shared_bank_count", 8), ("shared_ia_banks", 1)):
        if reference.get(key, default) != candidate.get(key, default):
            raise RuntimeError(f"共享存储配置不一致: {key}")
    if reference.get("stable_stimulus", False) != candidate.get("stable_stimulus", False):
        raise RuntimeError("随机数据生成方式不一致")
    if not candidate.get("check_weight_prefetch"):
        raise RuntimeError("候选运行需要启用权重预取检查")
    if len(reference["runs"]) != len(candidate["runs"]):
        raise RuntimeError("两次运行的 PE 配置数量不一致")
    profiles = []
    for old, new in zip(reference["runs"], candidate["runs"]):
        if not old["passed"] or not new["passed"] or old["pe"] != new["pe"]:
            raise RuntimeError("功能运行未通过或 PE 配置不一致")
        if old["totals"] != new["totals"]:
            raise RuntimeError("功能用例或输出数量不一致")
        if len(old["cases"]) != len(new["cases"]):
            raise RuntimeError("用例记录数量不一致")
        for expected, actual in zip(old["cases"], new["cases"]):
            if expected != actual:
                changed = {key: [expected.get(key), actual.get(key)]
                           for key in sorted(expected.keys() | actual.keys())
                           if expected.get(key) != actual.get(key)}
                raise RuntimeError(f"用例统计不一致 {expected['name']}: {changed}")
        log_path = Path(new["log"])
        match = re.search(r"^VECTOR_WEIGHT_PREFETCH_PASS (.*)$", log_path.read_text(), re.MULTILINE)
        if not match:
            raise RuntimeError("缺少权重预取检查结果")
        counts = {name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", match[1])}
        if any(value == 0 for value in counts.values()):
            raise RuntimeError("权重预取检查存在未覆盖的事件")
        profiles.append({"pe": new["pe"], "passed": True,
                         "identical_case_records": len(new["cases"]),
                         "totals": new["totals"], "prefetch_checks": counts,
                         "candidate_log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest()})
    result = {"passed": True, "comparison": "all case fields must match exactly",
              "reference": str(args.reference.resolve()), "candidate": str(args.candidate.resolve()),
              "reference_sha256": hashlib.sha256(args.reference.read_bytes()).hexdigest(),
              "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
              "profiles": profiles}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(profiles),
                      "identical_case_records": sum(p["identical_case_records"] for p in profiles)}))


if __name__ == "__main__":
    main()
