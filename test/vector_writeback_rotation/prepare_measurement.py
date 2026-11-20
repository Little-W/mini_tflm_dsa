#!/usr/bin/env python3
"""固定向量写回参考源码和当前源码，生成相同参数的 FPGA 综合配置。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_writeback.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="7419df81")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ("reference", "current"):
        data = (read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT)
                if label == "reference" else (ROOT / SOURCE).read_bytes())
        path = out / f"{label}.sv"
        path.write_bytes(data)
        hashes[label] = hashlib.sha256(data).hexdigest()
        cases[label] = {
            "top": "vector_writeback", "options": ["-GTILE=16", "-GBUS_WIDTH=64"],
            "sources": [str(path)], "configuration": "TILE=16, BUS_WIDTH=64",
        }
    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (out / "sources.json").write_text(json.dumps({
        "reference_ref": args.reference, "source_sha256": hashes,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
