#!/usr/bin/env python3
"""验证输出写回范围比较的完整状态、公开输出和四态传播。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/oa_writer.sv")
REFERENCE = "016d9854cf0524b04e7a59f6df13a47b630e686b"
PROFILES = ((4, 32, 4, 8), (8, 64, 8, 8), (16, 32, 7, 32),
            (16, 64, 16, 32), (16, 64, 29, 32), (16, 64, 32, 32),
            (32, 64, 32, 32))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
from scripts.rtl.source_files import input_files, with_dependencies
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_logged(command, log, timeout=300):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--scenarios", type=int, default=1024)
    parser.add_argument("--numeric-scenarios", type=int, default=256)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / "reference.sv"
    reference.write_text(read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    candidate = out / "candidate.sv"
    candidate.write_bytes((ROOT / SOURCE).read_bytes())
    dependencies = with_dependencies([ROOT / SOURCE], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in input_files(dependencies, ROOT)}
    original_registers = set(re.findall(r"\b(\w+)\s*<=", reference.read_text()))
    current_registers = set(re.findall(r"\b(\w+)\s*<=", candidate.read_text()))
    if original_registers != current_registers:
        raise RuntimeError("完整状态检查要求保留全部写回寄存器")

    def prove(job):
        profile, fpga = job
        lanes, bus, count, width = profile
        label = f"n{lanes}_b{bus}_c{count}_r{width}_fpga{int(fpga)}"
        options = (["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else
                   ["-USYNTHESIS", "-UXILINX_FPGA"])
        options += [f"-GVLEN={lanes}", f"-GBUS_WIDTH={bus}",
                    f"-GCOUNT_WIDTH={count}", f"-GREG_WIDTH={width}"]
        commands = []
        for name, source in (("reference", reference), ("candidate", candidate)):
            sources = with_dependencies([source], ROOT)
            commands += ["read_slang --top oa_writer " + shlex.join(options + list(map(str, sources))),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top oa_writer -flatten", "async2sync", "opt_clean",
                         "rename oa_writer " + name, "design -stash " + name]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from candidate -as candidate candidate",
                     "equiv_make reference candidate proof", "hierarchy -top proof",
                     "equiv_simple -seq 1", "equiv_induct -seq 3", "equiv_status -assert"]
        script, log = out / (label + ".ys"), out / (label + ".log")
        script.write_text("\n".join(commands) + "\n")
        run_logged([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
        text = log.read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if not match or int(match[2]) or "Equivalence successfully proven!" not in text:
            raise RuntimeError("完整写回状态证明未完成：" + label)
        row = dict(profile=profile, fpga=fpga, passed=True, proven_bits=int(match[1]),
                   input_value_constraints=None, handshake_constraints=None,
                   log_sha256=digest(log), script_sha256=digest(script))
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        formal = list(pool.map(prove, ((profile, fpga) for profile in PROFILES for fpga in (False, True))))

    # 每个时钟沿前后比较全部公开输出，覆盖配置变化、暂停和未知输入。
    four_state_body = runpy.run_path(str(ROOT / "test/oa_writer_geometry/run_four_state.py"))["BODY"]
    bench_source = ROOT / "test/oa_writer/tb_equivalence.sv"
    prefix = bench_source.read_text().split("    int unsigned cycle_count")[0]
    simulation = out / "simulation"
    simulation.mkdir(exist_ok=True)
    bench = simulation / "four_state.sv"
    bench.write_text(prefix + four_state_body)
    copied = []
    for index, path in enumerate(dependencies):
        target = simulation / f"source_{index}.sv"
        target.write_text(path.read_text().replace("int unsigned", "integer"))
        copied.append(target)
    original = simulation / "reference.sv"
    original.write_text(re.sub(r"\boa_writer\b", "oa_writer_ref", reference.read_text())
                        .replace("int unsigned", "integer"))
    four_state = []
    for lanes, bus, count in ((4, 32, 4), (16, 64, 29), (32, 64, 32)):
        for fpga in (False, True):
            label = f"n{lanes}_b{bus}_c{count}_fpga{int(fpga)}"
            binary, log = simulation / (label + ".vvp"), simulation / (label + ".log")
            definitions = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else []
            run_logged(["iverilog", "-g2012", "-s", "tb_oa_writer_equivalence", *definitions,
                        f"-Ptb_oa_writer_equivalence.VLEN={lanes}",
                        f"-Ptb_oa_writer_equivalence.BUS_WIDTH={bus}",
                        f"-Ptb_oa_writer_equivalence.COUNT_WIDTH={count}",
                        f"-Ptb_oa_writer_equivalence.SCENARIOS={args.scenarios}",
                        "-o", binary, *copied, original, bench], simulation / (label + "_compile.log"))
            run_logged(["vvp", binary], log)
            match = re.search(r"OA_GEOMETRY_FOUR_STATE_PASS (.*)", log.read_text())
            if match is None:
                raise RuntimeError("完整写回四态检查未完成：" + label)
            row = dict(vlen=lanes, bus_width=bus, count_width=count, fpga=fpga, passed=True,
                       **{key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", match[1])},
                       log_sha256=digest(log), binary_sha256=digest(binary))
            four_state.append(row)
            print(json.dumps(row), flush=True)

    numeric = []
    for fpga in (False, True):
        label = "fpga" if fpga else "generic"
        folder = out / ("numeric_" + label)
        folder.mkdir(exist_ok=True)
        definitions = (["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else
                       ["-USYNTHESIS", "-UXILINX_FPGA"])
        numeric_reference = folder / "reference.sv"
        numeric_reference.write_text(re.sub(r"\boa_writer\b", "oa_writer_ref", reference.read_text()))
        run_logged([args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal", "-j", "2",
                    "--top-module", "tb_oa_writer_equivalence", "--Mdir", folder / "obj", *definitions,
                    "-GVLEN=16", "-GBUS_WIDTH=64", "-GCOUNT_WIDTH=29",
                    f"-GSCENARIOS={args.numeric_scenarios}", "-GCYCLES_PER_SCENARIO=1024",
                    *dependencies, numeric_reference, bench_source], folder / "compile.log", timeout=600)
        binary = folder / "obj/Vtb_oa_writer_equivalence"
        log = folder / "run.log"
        run_logged([binary], log)
        match = re.search(r"OA_WRITER_EQ_PASS (.*)", log.read_text())
        if match is None:
            raise RuntimeError("完整写回事务比较未完成：" + label)
        row = dict(fpga=fpga, passed=True,
                   **{key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", match[1])},
                   log_sha256=digest(log), binary_sha256=digest(binary))
        numeric.append(row)
        print(json.dumps(row), flush=True)

    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("验证期间源文件发生变化")
    report = dict(passed=True, reference=args.reference, reference_sha256=digest(reference),
                  source_sha256=hashes, runner_sha256=digest(__file__),
                  formal_state_registers=sorted(current_registers),
                  all_public_outputs_and_common_state_compared=True,
                  formal=formal, four_state=four_state, numeric=numeric)
    (out / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
