#!/usr/bin/env python3
"""从矩阵引擎提取完整偏置寄存区域，生成相同配置的综合比较。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from run import ROOT, SOURCE, extract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", default="f3e85795")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", args.reference_ref + ":" + SOURCE],
                                       cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    cases, hashes = {}, {}
    for name, source in (("reference", original), ("current", current)):
        path = out / f"{name}.sv"
        path.write_text(extract(source, "matrix_bias_storage"))
        hashes[name] = hashlib.sha256(source.encode()).hexdigest()
        cases[name] = dict(top="matrix_bias_storage", options=["-DSYNTHESIS=1", "-Gp_size=16"],
                           sources=[str(path)], parameters={"p_size": 16},
                           configuration="Complete 16-lane bias history and compute capture registers")
    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (out / "source_sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")


if __name__ == "__main__":
    main()
