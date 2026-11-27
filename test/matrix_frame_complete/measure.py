#!/usr/bin/env python3
"""综合已验证的帧完成表达式，统计部分和完成输入到结果寄存器的实际路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validated-inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    inputs, out = args.validated_inputs.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    validation = json.loads((inputs / "summary.json").read_text())
    if validation["passed"] is not True:
        raise ValueError("输入表达式尚未完成验证")
    for relative, expected in validation["source_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("验证后的生产 RTL 已发生变化")
    cases = {}
    for label in ("reference", "current"):
        top = "completion_registered_" + label
        model = out / (label + ".sv")
        model.write_text(f"""// 保存实际完成条件的输入和结果，用于计算完整组合路径。
module {top} (
    input logic clk, // 测量时钟
    input logic [10:0] i_controls, // 帧完成条件
    output logic o_complete // 已保存的完成结果
);
    logic [10:0] controls_q;
    logic result;
    always_ff @(posedge clk) begin
        controls_q <= i_controls;
        o_complete <= result;
    end
    completion_{label} u_completion(.i_controls(controls_q), .o_complete(result));
endmodule
""")
        cases[label] = {"top": top, "options": ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"],
                        "sources": [str(inputs / "completion.sv"), str(model)],
                        "configuration": "矩阵帧完成条件的完整寄存器路径"}
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
        "--case-config", str(case_file), "--cases", "reference", "current", "--out", str(out / "pre"),
        "--through", "pre_lut"], cwd=ROOT, check=True)
    report = {"source_sha256": validation["source_sha256"], "cases": {}}
    for label, case in cases.items():
        top, mapped = case["top"], out / "mapped" / label
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/remap_fpga_luts.py"),
            "--source", str(out / "pre" / label), "--out", str(mapped), "--mode", "physical-cost",
            "--delay-target-ps", "6667", "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
            "--discard-abc9-temporaries"], cwd=ROOT, check=True)
        module = json.loads((mapped / "mapped.json").read_text())["modules"][top]
        for name, origin in register_origins(out / "pre" / label / "pre_lut.il", top).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        def store_source(name, cell, port):
            origin = cell.get("attributes", {}).get("fpga_register_origin", "")
            return origin in ("controls_q [5]", "controls_q [4]")
        paths = connected_paths(module, limit=3, group_limit=3, root_filter=store_source)
        if not paths["graph_complete"]:
            raise RuntimeError("帧完成路径分析不完整")
        metrics = json.loads((mapped / "metrics.json").read_text())
        report["cases"][label] = {"resources": metrics["resources"],
            "longest_register_path_cells": metrics["paths"]["longest_register_path_cells"],
            "partial_sum_completion_paths": paths}
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
