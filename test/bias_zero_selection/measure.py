#!/usr/bin/env python3
"""综合生产矩阵引擎的偏置需求表达式，测量地址到偏置资格的完整寄存器路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MATRIX = Path("rtl/npu/top/npu_matrix_engine.sv")
HELPER = Path("rtl/npu/top/npu_bias_presence.sv")
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="9e3e5d6a6f47befe6c86aceacad7999923206458")
    parser.add_argument("--validated-inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    validation = json.loads((args.validated_inputs / "summary.json").read_text())
    if validation["passed"] is not True:
        raise ValueError("偏置需求表达式尚未完成验证")
    for relative, expected in validation["source_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError("验证后的生产 RTL 已发生变化")
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    cases = {}
    for label in ("reference", "current"):
        if label == "reference":
            matrix = subprocess.check_output(["git", "show", f"{args.reference}:{MATRIX}"],
                                             cwd=ROOT, text=True)
            helper_text = subprocess.check_output(["git", "show", f"{args.reference}:{HELPER}"],
                                                  cwd=ROOT, text=True)
        else:
            matrix = (ROOT / MATRIX).read_text()
            helper_text = (ROOT / HELPER).read_text()
        first = matrix.index("    localparam int unsigned p_bias_zero_groups")
        zero_logic = matrix[first:matrix.index("    assign bias_execution_address_i_base", first)]
        instance = re.search(r"    npu_bias_presence u_bias_presence\s*\(.*?\);", matrix, re.S).group(0)
        helper = out / (label + "_presence.sv")
        helper.write_text(helper_text)
        top = "bias_selection_path"
        model = out / (label + ".sv")
        model.write_text("""// 输入与输出均由寄存器限定，组合部分直接提取自生产矩阵引擎。
module bias_selection_path (
    input logic clk, // 测量时钟
    input logic [31:0] i_address, // 偏置字节地址
    input logic [5:0] i_controls, // 帧模式及偏置应用条件
    output logic [2:0] o_status // 保存的偏置需求和两种位宽的地址非零标志
);
    localparam int p_reg_width = 32;
    localparam int p_controller_bias_w = 32;
    logic [31:0] i_bias_base;
    logic [5:0] controls_q;
    logic bias_base_nonzero, controller_bias_base_nonzero, exec_bias_present;
    logic o_frame_mode_q, o_is_mode, ws_final_bias, frame_exec_final, frame_exec_init, bias_zero_o_equal;
    always_ff @(posedge clk) begin
        i_bias_base <= i_address;
        controls_q <= i_controls;
        o_status <= {exec_bias_present, bias_base_nonzero, controller_bias_base_nonzero};
    end
    assign {o_frame_mode_q,o_is_mode,ws_final_bias,frame_exec_final,frame_exec_init,bias_zero_o_equal} = controls_q;
""" + zero_logic + instance + "\nendmodule\n")
        sources = resolve([model, helper], ROOT)
        cases[label] = {"top": top, "sources": list(map(str, sources)),
                        "options": ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"],
                        "configuration": "32 位偏置地址与帧资格的完整寄存器路径"}
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
        "--case-config", str(case_file), "--cases", "reference", "current", "--out", str(out / "pre"),
        "--through", "pre_lut"], cwd=ROOT, check=True)
    report = {"reference_revision": args.reference, "source_sha256": validation["source_sha256"],
              "cases": {}}
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

        def address_source(name, cell, port):
            return cell.get("attributes", {}).get("fpga_register_origin", "").startswith("i_bias_base [")

        def presence_sink(name, cell, port):
            return cell.get("attributes", {}).get("fpga_register_origin", "") == "o_status [2]"

        paths = connected_paths(module, limit=3, group_limit=3,
                                root_filter=address_source, sink_filter=presence_sink)
        if not paths["graph_complete"] or not paths["register_to_register_paths"]:
            raise RuntimeError("偏置需求路径分析不完整")
        metrics = json.loads((mapped / "metrics.json").read_text())
        report["cases"][label] = {"resources": metrics["resources"],
            "longest_register_path_cells": metrics["paths"]["longest_register_path_cells"],
            "address_to_presence_paths": paths}
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
