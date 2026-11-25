#!/usr/bin/env python3
"""验证输出行索引计算及完整写回控制器的逐周期等价性。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/oa_writer.sv")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from scripts.rtl.source_files import input_files, with_dependencies
from rtl_reference import read_rtl_source
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instrument(content, name, registers):
    content = re.sub(r"\boa_writer\b", name, content)
    content, replacements = re.subn(
        r"output\s+logic\s+oa_calc_over\s*\n",
        "output logic oa_calc_over,\n    output logic [4095:0] formal_state\n",
        content,
        count=1,
    )
    if replacements != 1:
        raise ValueError("无法定位写回模块的完整公开端口")
    state = "    assign formal_state = {" + ", ".join(registers) + "};\n"
    return content.replace("endmodule", state + "endmodule", 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtl", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--reference", default="a2c61b53")
    parser.add_argument("--reference-rtl", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", default=[
        "4:32:4:4", "8:64:8:8", "8:64:9:9", "16:32:7:32",
        "16:64:16:32", "16:64:29:32", "16:64:32:32", "32:64:32:32",
    ])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.rtl.read_text()
    reference = (args.reference_rtl.read_text() if args.reference_rtl else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    registers = sorted(set(re.findall(r"\b(\w+)\s*<=", reference)))
    if set(registers) != set(re.findall(r"\b(\w+)\s*<=", current)):
        raise ValueError("当前证明要求两份控制器保留相同寄存器")
    reference_file = out / "reference.sv"
    current_file = out / "current.sv"
    reference_file.write_text(instrument(reference, "oa_writer_reference", registers))
    current_file.write_text(instrument(current, "oa_writer_current", registers))
    dependencies = with_dependencies([args.rtl.resolve()], ROOT)[1:]
    tracked = input_files([args.rtl.resolve(), *dependencies], ROOT)
    hashes = {str(path): digest(path) for path in tracked}
    inputs = " ".join(shlex.quote(str(path)) for path in dependencies)
    report = dict(
        passed=True,
        source_sha256=hashlib.sha256(current.encode()).hexdigest(),
        reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        reference=None if args.reference_rtl else args.reference,
        input_sha256=hashes,
        runner_sha256=digest(Path(__file__)),
        input_value_constraints=None,
        handshake_constraints=None,
        all_public_outputs_compared_each_cycle=True,
        all_state_signals_compared_each_cycle=registers,
        synthesis_define=True,
        profiles=[],
    )
    for profile in args.profiles:
        lanes, bus, count, register = map(int, profile.split(":"))
        label = f"n{lanes}_b{bus}_c{count}_r{register}"
        parameters = (f"-D SYNTHESIS=1 -D XILINX_FPGA=1 -GVLEN={lanes} "
                      f"-GBUS_WIDTH={bus} -GCOUNT_WIDTH={count} -GREG_WIDTH={register}")
        script = out / (label + ".ys")
        script.write_text(
            f"read_slang --top oa_writer_reference {parameters} {shlex.quote(str(reference_file))} {inputs}\n"
            "prep -top oa_writer_reference -flatten\nrename oa_writer_reference gold\ndesign -stash gold\n"
            f"read_slang --top oa_writer_current {parameters} {shlex.quote(str(current_file))} {inputs}\n"
            "prep -top oa_writer_current -flatten\nrename oa_writer_current gate\n"
            "design -copy-from gold -as gold gold\nmiter -equiv -flatten gold gate miter\n"
            "prep -top miter -flatten\nchformal -lower\nopt -full\n"
            "sat -verify -prove trigger 0 -tempinduct -seq 1 -set-init-zero "
            "-set-at 1 in_rst_n 0 -maxsteps 4\n"
        )
        stage = run_stage(script, script.with_suffix(".log"), dict(os.environ))
        row = dict(vlen=lanes, bus_width=bus, count_width=count,
                   register_width=register, passed=True, **stage)
        report["profiles"].append(row)
        print(json.dumps(row), flush=True)
    if hashes != {name: digest(Path(name)) for name in hashes}:
        raise RuntimeError("验证期间 RTL 内容发生变化")
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
