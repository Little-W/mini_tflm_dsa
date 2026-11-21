#!/usr/bin/env python3
"""验证实际双模式 DMA 返回寄存过程的路由资格和四态保持行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/dma/axi_dual_block_dma.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(source, name):
    start = source.index("    assign fe_output_ready =")
    block_start = source.index("    always_ff @(posedge clk or negedge rst_n)", start)
    block_end = source.index("    always_ff @(posedge clk)", block_start)
    assignments = []
    for signal in ("fe_output_ready", "fe_input_ready", "fe_output_drained", "rd_response_tag"):
        match = re.search(r"    assign " + signal + r"\s*=.*?;", source, re.S)
        if match is None:
            raise ValueError("无法定位返回控制表达式：" + signal)
        assignments.append(match[0])
    qualified = "fe_matrix_output_valid" if "logic fe_matrix_output_valid;" in source else \
        "(fe_output_valid && !fe_output_window)"
    return f"""module {name} (
    input logic clk, rst_n, fe_wr_valid, win_frontend_rsp_ready, win_frontend_active,
    input logic conv_done_r,
    input logic [2:0] conv_tag_q, linear_response_tag,
    output logic fe_output_valid, fe_output_window, fe_output_drained,
    output logic fe_input_ready, fe_output_ready,
    output logic matrix_valid,
    output logic [2:0] rd_response_tag
);
    logic fe_matrix_output_valid;
""" + "\n".join(assignments) + "\n" + source[block_start:block_end] + \
        f"\n    assign matrix_valid = {qualified};\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="0097b66e")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(
        ["git", "show", args.reference + ":" + SOURCE], cwd=ROOT, text=True)
    modules = out / "stages.sv"
    modules.write_text(extract(source, "current_stage") + extract(reference, "reference_stage"))
    connections = ".clk(clk), .rst_n(rst_n), .fe_wr_valid(fe_wr_valid), " \
        ".win_frontend_rsp_ready(win_frontend_rsp_ready), .win_frontend_active(win_frontend_active), " \
        ".conv_done_r(conv_done_r), .conv_tag_q(conv_tag_q), .linear_response_tag(linear_response_tag)"
    outputs = "    logic [8:0] observed [2];\n"
    for index, label in enumerate(("current", "reference")):
        outputs += f"    {label}_stage u_{label} ({connections}, " \
            f".fe_output_valid(observed[{index}][0]), .fe_output_window(observed[{index}][1]), " \
            f".fe_output_drained(observed[{index}][2]), .fe_input_ready(observed[{index}][3]), " \
            f".fe_output_ready(observed[{index}][4]), .matrix_valid(observed[{index}][5]), " \
            f".rd_response_tag(observed[{index}][8:6]));\n"
    formal = out / "formal.sv"
    formal.write_text("""module routing_proof (
    input logic clk, rst_n, fe_wr_valid, win_frontend_rsp_ready, win_frontend_active,
    input logic conv_done_r,
    input logic [2:0] conv_tag_q, linear_response_tag,
    output logic correct
);
""" + outputs + "    assign correct = observed[0] == observed[1];\nendmodule\n")
    script = out / "proof.ys"
    script.write_text("read_slang --top routing_proof " + shlex.join([str(modules), str(formal)]) +
        "\nprep -top routing_proof -flatten\nasync2sync\nopt_clean\n" +
        "sat -seq 3 -prove-skip 1 -prove correct 1 -verify -set-def-inputs "
        "-set-init-def -set-at 1 rst_n 0\n" +
        "sat -seq 1 -tempinduct-inductonly -tempinduct-def -maxsteps 3 "
        "-prove correct 1 -verify -set-def-inputs -set-init-def\n")
    with (out / "formal.log").open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                       cwd=ROOT, check=True, timeout=120)
    log = (out / "formal.log").read_text()
    if "Induction step proven: SUCCESS!" not in log:
        raise RuntimeError("返回路由归纳证明未完成")
    bench = out / "tb.sv"
    bench.write_text("""module tb;
    logic clk=0, rst_n=0, fe_wr_valid=0, win_frontend_rsp_ready=0, win_frontend_active=0;
    logic conv_done_r=0;
    logic [2:0] conv_tag_q=0, linear_response_tag=0;
    integer comparisons=0;
    function automatic logic bit_value(input integer value);
        case (value & 3)
            0: bit_value=1'b0;
            1: bit_value=1'b1;
            2: bit_value=1'bx;
            default: bit_value=1'bz;
        endcase
    endfunction
    task automatic check_outputs;
        #1;
        if (observed[0] !== observed[1]) $fatal(1, "route mismatch");
        comparisons++;
    endtask
""" + outputs + """    initial begin
        #1; clk=1; #1; clk=0; #1;
        for (int cycle=0; cycle<65536; cycle++) begin
            rst_n=(cycle%127==0)?1'b0:1'b1;
            fe_wr_valid=bit_value(cycle);
            win_frontend_rsp_ready=bit_value(cycle>>2);
            win_frontend_active=bit_value(cycle>>4);
            conv_done_r=bit_value(cycle>>6);
            for (int bit_index=0;bit_index<3;bit_index++) begin
                conv_tag_q[bit_index]=bit_value(cycle>>(8+2*bit_index));
                linear_response_tag[bit_index]=bit_value((cycle>>bit_index)^cycle);
            end
            check_outputs(); clk=1; check_outputs(); clk=0; check_outputs();
        end
        $display("RETURN_ROUTING_PASS comparisons=%0d", comparisons);
        $finish;
    end
endmodule
""")
    with (out / "build.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(out / "simulation"),
                        str(modules), str(bench)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(["vvp", str(out / "simulation")], capture_output=True, text=True,
                            check=True, timeout=60)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if "RETURN_ROUTING_PASS comparisons=196608" not in result.stdout:
        raise RuntimeError("返回路由四态比较未完成")
    if source != (ROOT / SOURCE).read_text():
        raise RuntimeError("验证期间源文件发生变化")
    report = {"passed": True, "reference": args.reference,
              "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
              "test_sha256": digest(Path(__file__)), "functional_inputs_constrained": False,
              "reset_and_unbounded_induction": True, "four_state_comparisons": 196608,
              "formal_log_sha256": digest(out / "formal.log"),
              "simulation_log_sha256": digest(out / "run.log")}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
