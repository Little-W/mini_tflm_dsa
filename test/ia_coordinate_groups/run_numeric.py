#!/usr/bin/env python3
"""复用真实 DMA 激励，比较 IA 全部公开输出及实际缓存返回数值。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from run_formal import ROOT, REFERENCE, PARENT, digest
from scripts.rtl.source_files import input_files, with_dependencies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--reference",default=REFERENCE)
    parser.add_argument("--verilator",default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    verilator = shutil.which(args.verilator)
    if not verilator:
        raise RuntimeError("找不到 Verilator")
    dependencies = with_dependencies([ROOT/PARENT],ROOT)
    hashes = {str(path.relative_to(ROOT)):digest(path) for path in input_files(dependencies,ROOT)}
    reference_helpers = []
    for name in ("ia_ordered_coordinate_equal", "ia_ordered_coordinate_same"):
        relative = "rtl/npu/loaders/" + name + ".sv"
        text = subprocess.check_output(["git", "show", args.reference + ":" + relative], cwd=ROOT, text=True)
        target = out / (name + "_reference.sv")
        target.write_text(re.sub(r"\b" + name + r"\b", name + "_reference", text))
        reference_helpers.append(target)
    rows = []
    for fpga in (False,True):
        name = "fpga" if fpga else "generic"
        folder = out/name
        folder.mkdir(exist_ok=True)
        flags = ["-DSYNTHESIS=1","-DXILINX_FPGA=1"] if fpga else ["-USYNTHESIS","-UXILINX_FPGA"]
        wrapper = folder/"verilator_mode"
        wrapper.write_text("#!"+sys.executable+"\nimport os,sys\nargs=sys.argv[1:]\n"+
            "if '--getenv' not in args and '--version' not in args:\n"+
            "    args += "+repr(flags + list(map(str,reference_helpers)))+"\n"+
            "os.execv("+repr(verilator)+",["+repr(verilator)+"]+args)\n")
        wrapper.chmod(0o755)
        command = [sys.executable,ROOT/"test/ia_timing/run_interface.py","--out",folder/"run",
                   "--reference-rev",args.reference,"--verilator",wrapper,
                   "--cases","prefetch_ordered","grouped32"]
        log = folder/"run.log"
        with log.open("w") as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                           check=True,timeout=900)
        report = json.loads((folder/"run/summary.json").read_text())
        if not report.get("passed"):
            raise RuntimeError("IA 数值检查未完成："+name)
        row = dict(fpga=fpga,passed=True,compile_options=flags,result=report,
                   log_sha256=digest(log),wrapper_sha256=digest(wrapper))
        rows.append(row)
        print(json.dumps(dict(fpga=fpga,passed=True,runs=report["runs"])),flush=True)
    if hashes != {name:digest(ROOT/name) for name in hashes}:
        raise RuntimeError("验证期间 RTL 内容发生变化")
    summary = dict(passed=True,reference=args.reference,source_sha256=hashes,
                   reference_helper_sha256={path.name:digest(path) for path in reference_helpers},
                   all_public_outputs_compared_each_cycle=True,profiles=rows)
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    main()
