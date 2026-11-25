#!/usr/bin/env python3
"""保存完整加法器的参考与当前源码，并生成显式综合参数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/common/parallel_prefix_add.sv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    records = {}
    for label in ("reference", "current"):
        root = out / label
        data = (subprocess.check_output(["git", "show", revision + ":" + SOURCE], cwd=ROOT)
                if label == "reference" else (ROOT / SOURCE).read_bytes())
        helper = root / SOURCE
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_bytes(data)
        wrapper = (Path(__file__).parent / "measure.sv").read_text()
        if label == "reference":
            wrapper = wrapper.replace(",.p_parallel_high_prefix(1'b1)", "")
        (root / "measure.sv").write_text(wrapper)
        case = dict(arithmetic=dict(
            top="parallel_high_carry_measure", sources=["measure.sv", SOURCE],
            parameters=dict(WIDTH=32, SPLIT=16, CARRY=1),
            options=["-D", "SYNTHESIS=1", "-GWIDTH=32", "-GSPLIT=16", "-GCARRY=1"],
            configuration="输入和完整33位输出寄存的32位加法"))
        (root / "cases.json").write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")
        records[label] = {SOURCE: hashlib.sha256(data).hexdigest(),
                          "measure.sv": hashlib.sha256(wrapper.encode()).hexdigest()}
    (out / "inputs.json").write_text(json.dumps(dict(reference_commit=revision,
        source_sha256=records), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
