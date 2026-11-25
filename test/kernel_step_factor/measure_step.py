#!/usr/bin/env python3
"""综合实际步长与捕获寄存器，并用完整器件模型证明全部输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from check_step import ROOT, SOURCE, digest, extract, run_worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="ed5c58ab")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    current_text = (root / SOURCE).read_text()
    reference_text = subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"],
                                            cwd=ROOT, text=True)
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    helpers = resolve([root / "rtl/common/parallel_prefix_add.sv"], root)
    copies, hashes = [], {str(SOURCE): digest(root / SOURCE)}
    for path in helpers:
        relative = path.relative_to(root)
        original = subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT)
        if original != path.read_bytes():
            raise ValueError("两份测量需要相同公共加法器：" + str(relative))
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original)
        copies.append(target)
        hashes[str(relative)] = digest(path)
    snapshots = {}
    for label, source in (("reference", reference_text), ("current", current_text)):
        text = extract(source, "kernel_step_capture")
        text = text.replace("    output logic [REG_WIDTH-1:0] o_step,\n", "")
        text = text.replace("    assign o_step = group_addr_step_next;\n", "")
        target = out / (label + ".sv")
        target.write_text(text)
        snapshots[label] = target
    cases = {}
    for width, count in ((32, 29), (64, 64)):
        for label in ("reference", "current"):
            cases[f"{label}_{width}"] = {
                "top": "kernel_step_capture",
                "sources": [snapshots[label].name],
                "options": ["-DSYNTHESIS=1", "-DXILINX_FPGA=1",
                            f"-GREG_WIDTH={width}", f"-GCOUNT_WIDTH={count}"],
                "parameters": {"REG_WIDTH": width, "COUNT_WIDTH": count},
                "configuration": "完整步长函数与原有复位、清空保持和初始化捕获寄存器"}
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    with (out / "mapping.log").open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--source-root", str(out), "--case-config", str(case_file),
                        "--cases", *cases, "--out", str(out / "mapping"),
                        "--lock-file", str(out / "mapping.lock")],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    records = []
    for name, case in cases.items():
        folder = out / "mapping" / name
        interface_file = folder / "interface_paths.json"
        subprocess.run([sys.executable, str(ROOT / "test/output_configuration/analyze_interfaces.py"),
                        "--top", "kernel_step_capture", "--netlist", str(folder / "mapped.json"),
                        "--pre-lut", str(folder / "pre_lut.il"), "--out", str(interface_file)],
                       check=True)
        metrics = json.loads((folder / "metrics.json").read_text())
        interfaces = json.loads(interface_file.read_text())
        record = {"name": name, "parameters": case["parameters"],
                  "resources": metrics["resources"], "graph_complete": metrics["paths"]["graph_complete"],
                  "register_path_cells": metrics["paths"]["longest_register_path_cells"],
                  "input_to_register_cells": interfaces["input_to_register"]["longest_register_path_cells"],
                  "mapped_sha256": digest(folder / "mapped.json")}
        if not name.startswith("current_"):
            records.append(record)
            continue
        width, count = case["parameters"]["REG_WIDTH"], case["parameters"]["COUNT_WIDTH"]
        commands = [
            f"read_slang -DSYNTHESIS=1 --top kernel_step_capture -GREG_WIDTH={width} -GCOUNT_WIDTH={count} "
            + shlex.join(map(str, [snapshots["reference"], *copies])),
            "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
            "prep -top kernel_step_capture -flatten", "async2sync", "opt -full",
            "rename -top reference", "rename -hide w:*", "design -stash reference",
            "read_json " + shlex.quote(str(folder / "mapped.json")), "delete =A:blackbox",
            "read_verilog -overwrite +/xilinx/cells_sim.v", "hierarchy -top kernel_step_capture",
            "rename -top current", "setattr -mod -unset keep_hierarchy", "flatten -wb", "proc",
            "memory_map", "async2sync", "opt -full", "rename -hide w:*", "design -stash current",
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current", "equiv_make reference current equivalent",
            "hierarchy -top equivalent", "equiv_simple -seq 3", "opt_clean",
            "equiv_induct -seq 4", "equiv_status -assert"]
        proof = run_worker(folder, "mapped_equivalence", commands)
        text = (folder / "mapped_equivalence.log").read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if match is None or int(match[1]) != width or int(match[2]):
            raise RuntimeError("实际映射需要证明全部公开输出位")
        record.update(mapped_equivalence=proof, equivalent_bits=width, unbounded_equivalence=True)
        records.append(record)
        print(json.dumps(record), flush=True)
    if hashes != {name: digest(root / name) for name in hashes}:
        raise RuntimeError("验证期间源文件发生变化")
    report = {"passed": True, "reference_commit": revision, "source_sha256": hashes,
              "reference_controller_sha256": hashlib.sha256(reference_text.encode()).hexdigest(),
              "primitive_library_sha256": digest(library), "profiles": records,
              "boundary_registers_are_analysis_only": True}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
