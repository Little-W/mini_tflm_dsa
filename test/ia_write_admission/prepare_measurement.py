#!/usr/bin/env python3
"""保存共享 RAM 生产参数对应的完整 IA 模块综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source_group, read_current_source, shared_ia_parameters

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="7ff66a59")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = {"DATA_WIDTH": 16, "SIZE": 16, "BUS_WIDTH": 64, "REG_WIDTH": 32,
                  "COUNT_WIDTH": 29, "CACHE_BLOCKS": 32, "COMPACT_S8": 1,
                  "ORDERED_JOB": 1, "RAM_WORD_ADDR_WIDTH": 12,
                  "PS_FRAME_COUNT": 16}
    cases, hashes = {}, {}
    for label in ("reference", "current"):
        folder = out / label
        folder.mkdir(exist_ok=True)
        sources, hashes[label] = [], {}
        for name in ("ia_loader", "ia_loader_ctrl", "ia_loader_cache_mgr"):
            relative = Path("rtl/npu/loaders") / (name + ".sv")
            data = (read_rtl_source_group(f"{args.reference_rev}:{relative}", cwd=ROOT)
                    if label == "reference" else read_current_source(ROOT / relative).encode())
            path = folder / relative.name
            path.write_bytes(data)
            sources.append(str(path))
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
        values = shared_ia_parameters(parameters, (folder / "ia_loader.sv").read_text())
        cases["loader_" + label] = {
            "top": "ia_loader", "sources": sources, "parameters": values,
            "options": ["-D", "SYNTHESIS=1", "-DXILINX_FPGA=1"] +
                       [f"-G{name}={value}" for name, value in values.items()],
            "configuration": "完整 IA 模块，64 位总线、32 个缓存块、12 位外部共享 RAM 字地址",
        }
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    (out / "input_manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")


if __name__ == "__main__":
    main()
