#!/usr/bin/env python3
"""保存生产 INT8 FIFO 的两份源码及相同参数的资源测量输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from run_formal import ROOT, SOURCE, read_rtl_source


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="cedf4ed33661a53c8194eca1d484cdc2279d7549")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--bus-width", type=int, choices=(32,64), default=64)
    parser.add_argument("--banks", type=int, choices=(8,16,32,64), default=32)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common_root = args.source_root / "rtl/common"
    if not common_root.is_dir():
        common_root = ROOT / "rtl/common"
    shutil.copytree(common_root, out / "source/rtl/common", dirs_exist_ok=True)
    source = (args.source_root / SOURCE).read_text()
    reference = (args.reference_file.read_text() if args.reference_file else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    cases = {}
    for label,text in (("reference",reference),("current",source)):
        target = out / f"{label}.sv"
        target.write_text(text)
        cases[label] = dict(top="vec_s8_to_fifo",sources=[str(target)],
                            options=["-D","XILINX_FPGA=1","-GVLEN=16",f"-GBANKS={args.banks}",
                                     f"-GBUS_WIDTH={args.bus_width}","-Gp_cyclic_storage=1",
                                     "-Gp_precomputed_watermark=1"],
                            configuration=f"完整 INT8 输出 FIFO，16 路向量、{args.banks} 个银行、{args.bus_width} 位总线")
    (out / "cases.json").write_text(json.dumps(cases,ensure_ascii=False,indent=2)+"\n")
    files = [out / "reference.sv",out / "current.sv",*sorted((out / "source/rtl/common").glob("*"))]
    report = dict(reference=args.reference,sources_sha256={str(p):digest(p) for p in files if p.is_file()})
    (out / "manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    main()
