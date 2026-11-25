#!/usr/bin/env python3
"""用 FPGA 完整功能模型证明自动推断乘法的全部步长输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    local, out = args.local.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads((local / "summary.json").read_text())
    if not report["passed"]:
        raise RuntimeError("局部步长证明尚未完成")
    source = local / "current.sv"
    if digest(source) != report["sources_sha256"][source.name]:
        raise RuntimeError("步长源码与证明记录不同")
    mapper = ROOT / "scripts/fpga/open_fpga_synth.py"
    command = [sys.executable, str(mapper), "--case-config", str(local / "cases.json"),
               "--cases", "reference", "current", "--out", str(out / "synthesis")]
    with (out / "synthesis.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    folder = out / "synthesis/current"
    mapped = json.loads((folder / "mapped.json").read_text())["modules"]["row_step_current"]
    dsp_count = sum(cell["type"] == "DSP48E1" for cell in mapped["cells"].values())
    if dsp_count != 2:
        raise RuntimeError("生产步长乘法需要两个自动推断的 DSP")
    commands = [
        f"read_slang --top row_step_current -DSYNTHESIS=1 {source}",
        "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
        "prep -top row_step_current -flatten", "async2sync", "opt -full",
        "rename -hide w:*", "rename -top reference", "design -stash reference",
        "read_verilog " + str(folder / "mapped.v"),
        "read_verilog -overwrite +/xilinx/cells_sim.v",
        "rename row_step_current current", "hierarchy -top current", "flatten -wb",
        "proc", "memory_map", "async2sync", "opt -full", "rename -hide w:*",
        "design -stash current", "design -copy-from reference -as reference reference",
        "design -copy-from current -as current current", "equiv_make reference current proof",
        "hierarchy -top proof", "equiv_simple -seq 2", "opt_clean", "equiv_induct -seq 3",
        "equiv_status -assert",
    ]
    script, log = out / "proof.ys", out / "proof.log"
    script.write_text("\n".join(commands) + "\n")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(mapper), "--worker", str(script)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
    count = re.search(r"Of those cells (\d+) are proven and 0 are unproven", log.read_text())
    if not count:
        raise RuntimeError("映射后输出证明未完整通过")
    import pyosys
    summary = dict(passed=True, output_bits=64, equivalent_bits=int(count[1]),
                   inferred_dsp_count=dsp_count, source_sha256=digest(source),
                   mapped_sha256=digest(folder / "mapped.json"),
                   primitive_library_sha256=digest(Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"),
                   proof_script_sha256=digest(script), proof_log_sha256=digest(log),
                   synthesis_command=command)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
