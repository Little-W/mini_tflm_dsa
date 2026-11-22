#!/usr/bin/env python3
"""验证双项 AXI 缓冲的占用状态、完整输出及四态握手行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/soc/soc_axi_pingpong_buffer.sv")
WIDTHS = (1, 2, 34, 35, 36, 54, 64, 67, 73)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure_output_paths(path, tool_root):
    sys.path.insert(0, str(tool_root / "scripts/fpga"))
    from netlist_metrics import connected_paths
    module = json.loads(read_rtl_text(path))["modules"]["soc_axi_pingpong_chan"]
    next_bit = max(bit for net in module["netnames"].values() for bit in net["bits"]
                   if isinstance(bit, int)) + 1
    result = {}
    for port in ("m_valid", "s_ready"):
        name = "analysis_output_" + port
        module["cells"][name] = {
            "type": "FDRE", "attributes": {}, "parameters": {},
            "port_directions": {"D": "input", "Q": "output"},
            "connections": {"D": module["ports"][port]["bits"], "Q": [next_bit]}}
        next_bit += 1
        measured = connected_paths(module, limit=1, group_limit=0,
            root_filter=lambda cell_name, cell, pin: not cell_name.startswith("analysis_"),
            sink_filter=lambda cell_name, cell, pin: cell_name == name)
        if not measured["graph_complete"] or not measured["register_to_register_paths"]:
            raise RuntimeError("输出资格的连接图不完整")
        result[port] = measured["longest_register_path_cells"]
        del module["cells"][name]
    return result


def expose_state(text, label):
    channel = text.split("module soc_axil_pingpong_buffer", 1)[0]
    channel = channel.replace("module soc_axi_pingpong_chan #(", f"module {label} #(", 1)
    marker = "    output logic [WIDTH-1:0] m_data\n);"
    ports = """    output logic [WIDTH-1:0] m_data,
    output wire [2*WIDTH+3:0] formal_state,
    output wire formal_legal
);"""
    if channel.count(marker) != 1:
        raise ValueError("通道输出声明不匹配")
    channel = channel.replace(marker, ports, 1)
    if label == "reference":
        count = "count_q"
        legal = "count_q <= 2'd2"
    else:
        count = "({1'b0, full_q} + {1'b0, occupied_q})"
        legal = "(!full_q || occupied_q)"
    assignments = (f"    assign formal_state = {{data0_q, data1_q, rd_sel_q, wr_sel_q, {count}}};\n"
                   f"    assign formal_legal = {legal};\n")
    return channel.replace("endmodule", assignments + "endmodule", 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--tool-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="8aa34632c9cb0d1a8ea047a76d53e28dfee0006f")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=100000)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--lock-file", type=Path)
    args = parser.parse_args()
    source_root, tool_root, out = args.source_root.resolve(), args.tool_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(tool_root / "test"))
    from rtl_reference import read_rtl_source
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=tool_root, text=True)
    current = read_rtl_text(source_root / SOURCE)
    marker = "module soc_axil_pingpong_buffer"
    if reference.split(marker, 1)[1] != current.split(marker, 1)[1]:
        raise ValueError("AXI 与 AXI-Lite 封装发生变化")
    paths = {}
    for label, text in (("reference", reference), ("current", current)):
        paths[label] = out / f"{label}.sv"
        paths[label].write_text(expose_state(text, label))
    miter = out / "miter.sv"
    miter.write_text("""module miter #(parameter integer WIDTH=1)(
    input wire clk, rst_n, s_valid, m_ready,
    input wire [WIDTH-1:0] s_data,
    output wire correct
);
    wire r_ready, r_valid, c_ready, c_valid, r_legal, c_legal;
    wire [WIDTH-1:0] r_data, c_data;
    wire [2*WIDTH+3:0] r_state, c_state;
    reference #(.WIDTH(WIDTH)) r (
        .clk, .rst_n, .s_valid, .s_ready(r_ready), .s_data,
        .m_valid(r_valid), .m_ready, .m_data(r_data),
        .formal_state(r_state), .formal_legal(r_legal)
    );
    current #(.WIDTH(WIDTH)) c (
        .clk, .rst_n, .s_valid, .s_ready(c_ready), .s_data,
        .m_valid(c_valid), .m_ready, .m_data(c_data),
        .formal_state(c_state), .formal_legal(c_legal)
    );
    assign correct = ({r_ready, r_valid, r_data, r_state} ==
                      {c_ready, c_valid, c_data, c_state}) && r_legal && c_legal;
endmodule
""")
    report = {
        "passed": False, "reference": args.reference,
        "source_sha256": hashlib.sha256(current.encode()).hexdigest(),
        "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
        "functional_inputs_constrained": False, "initial_reset_cycle": 1,
        "all_public_outputs_compared": True, "invalid_data_compared": True,
        "all_storage_data_and_positions_compared": True,
        "occupancy_encoding_relation_compared": True,
        "axi_wrappers_identical": True, "formal": [],
    }
    for width in WIDTHS:
        folder = out / f"width_{width}"
        folder.mkdir(exist_ok=True)
        script, log = folder / "prove.ys", folder / "prove.log"
        inputs = " ".join(shlex.quote(str(p)) for p in (*paths.values(), miter))
        script.write_text(
            f"read_slang --top miter -GWIDTH={width} {inputs}\n"
            "prep -top miter -flatten\n"
            "sat -seq 2 -prove-skip 1 -prove correct 1 -verify -set-def-inputs "
            "-set-init-def -set-at 1 rst_n 0\n"
            "sat -seq 1 -tempinduct-inductonly -tempinduct-def -maxsteps 2 "
            "-prove correct 1 -verify -set-def-inputs -set-init-def\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(tool_root / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=tool_root, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        text = read_rtl_text(log)
        if ("SAT proof finished - no model found: SUCCESS!" not in text or
                "Induction step proven: SUCCESS!" not in text):
            raise RuntimeError(f"位宽 {width} 的状态归纳证明未完成")
        item = {"width": width, "passed": True, "compared_bits": 3 * width + 6,
                "log_sha256": digest(log)}
        report["formal"].append(item)
        print(json.dumps(item), flush=True)
    bench = Path(__file__).with_name("tb_four_state.sv")
    simulation = out / "four_state.vvp"
    with (out / "compile.log").open("w") as log:
        subprocess.run([args.iverilog, "-g2012", "-s", "tb_axi_occupancy",
                        "-o", str(simulation), str(bench), *(str(p) for p in paths.values())],
                       cwd=tool_root, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
    result = subprocess.run([args.vvp, str(simulation), f"+cycles={args.cycles}"],
                            capture_output=True, text=True, check=True, timeout=180)
    (out / "four_state.log").write_text(result.stdout + result.stderr)
    expected_checks = (2 * args.cycles + 1) * len(WIDTHS)
    expected = f"AXI_OCCUPANCY_PASS cycles={args.cycles} widths=9 output_checks={expected_checks}"
    if expected not in result.stdout:
        raise RuntimeError("四态状态比较未完成")
    report["four_state"] = {"passed": True, "cycles": args.cycles,
                            "complete_comparisons": expected_checks,
                            "unknown_controls_tested": True, "unknown_payload_tested": True,
                            "testbench_sha256": digest(bench),
                            "log_sha256": digest(out / "four_state.log")}
    if args.measure:
        raw_ref = out / "reference_raw.sv"
        raw_ref.write_text(reference)
        cases = {}
        for width in (2, 35, 64, 73):
            for label, source in (("reference", raw_ref), ("current", source_root / SOURCE)):
                cases[f"{label}{width}"] = {
                    "top": "soc_axi_pingpong_chan", "options": [f"-GWIDTH={width}", "-D", "SYNTHESIS=1"],
                    "sources": [str(source)], "configuration": {"WIDTH": width}}
        config = out / "cases.json"
        config.write_text(json.dumps(cases, indent=2) + "\n")
        cmd = [sys.executable, str(tool_root / "scripts/fpga/open_fpga_synth.py"),
               "--case-config", str(config), "--cases", *cases, "--out", str(out / "mapping")]
        if args.lock_file:
            cmd += ["--lock-file", str(args.lock_file.resolve())]
        with (out / "mapping.log").open("w") as log:
            subprocess.run(cmd, cwd=tool_root, stdout=log, stderr=subprocess.STDOUT, check=True)
        report["mapping"] = {}
        for name in cases:
            metrics = json.loads(read_rtl_text(out / "mapping" / name / "metrics.json"))
            report["mapping"][name] = {"resources": metrics["resources"],
                                        "max_register_path_cells": metrics["paths"]["longest_register_path_cells"],
                                        "graph_complete": metrics["paths"]["graph_complete"],
                                        "output_path_cells": measure_output_paths(
                                            out / "mapping" / name / "mapped.json", tool_root)}
    if current != read_rtl_text(source_root / SOURCE):
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "formal_profiles": len(report["formal"]),
                      "four_state_comparisons": expected_checks}), flush=True)


if __name__ == "__main__":
    main()
