#!/usr/bin/env python3
"""验证实际样本偏移模块映射后的全部公开输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lanes", type=int, nargs="+", default=[1, 4, 8, 16])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/npu/conv/conv_im2col_stream.sv"
    source_hash = digest(source)
    text = source.read_text()
    found = re.search(r'\(\* keep_hierarchy = "yes" \*\)\s*'
                      r'module conv_im2col_sample_offsets\b.*?endmodule', text, re.S)
    if found is None:
        raise RuntimeError("未找到完整的样本偏移模块")
    module = out / "sample_offsets.sv"
    module.write_text(found.group() + "\n")
    cases = {}
    for lanes in args.lanes:
        if lanes < 1:
            raise ValueError("通道数量必须为正整数")
        cases[f"lanes{lanes}"] = dict(
            top="conv_im2col_sample_offsets", sources=[str(module)],
            options=["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1", f"-Gp_lanes={lanes}"],
            parameters=dict(p_lanes=lanes), configuration="各通道独立的九位样本偏移")
    cases_file = out / "cases.json"
    cases_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    with (out / "synthesis.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--source-root", str(ROOT), "--case-config", str(cases_file),
                        "--cases", *cases, "--out", str(out / "synthesis"),
                        "--abc9-batch-size", "64", "--abc9-isolate-leaves"],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    records = []
    for lanes in args.lanes:
        folder = out / "synthesis" / f"lanes{lanes}"
        mapped = folder / "mapped.json"
        metrics = json.loads((folder / "metrics.json").read_text())
        script = out / f"lanes{lanes}_proof.ys"
        script.write_text("\n".join([
            f"read_slang --top conv_im2col_sample_offsets -Gp_lanes={lanes} " + shlex.quote(str(module)),
            "prep -top conv_im2col_sample_offsets -flatten", "opt -full",
            "rename -hide w:*", "rename -top reference", "design -stash reference",
            "read_json " + shlex.quote(str(mapped)),
            "delete =A:blackbox", "read_verilog -overwrite +/xilinx/cells_sim.v",
            "rename conv_im2col_sample_offsets current",
            "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
            "hierarchy -top current", "flatten -wb", "proc", "memory_map", "opt -full",
            "rename -hide w:*", "design -stash current",
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current proof", "hierarchy -top proof",
            "equiv_simple", "equiv_status -assert",
        ]) + "\n")
        log = out / f"lanes{lanes}_proof.log"
        stage = run_stage(script, log, dict(os.environ))
        proven = re.search(r"Of those cells (\d+) are proven and 0 are unproven", log.read_text())
        if proven is None or int(proven[1]) != 9 * lanes:
            raise RuntimeError("映射比较未覆盖全部样本输出")
        records.append(dict(lanes=lanes, passed=True, compared_output_bits=9*lanes,
                            resources=metrics["resources"], mapped_sha256=digest(mapped),
                            log_sha256=digest(log), **stage))
        print("SAMPLE_OFFSETS_MAPPED_PASS", lanes, flush=True)
    if digest(source) != source_hash:
        raise RuntimeError("验证期间源码发生变化")
    result = dict(passed=True, source_sha256=source_hash, helper_sha256=digest(module),
                  primitive_library_sha256=digest(library), input_constraints=[],
                  primitive_model="完整 cells_sim.v 功能模型", cases=records)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
