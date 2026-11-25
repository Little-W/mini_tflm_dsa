#!/usr/bin/env python3
"""提取两版 IA 循环边界逻辑，证明全部二态输入并逐位检查 X/Z。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/loaders/ia_loader_ctrl.sv"
CASES = ((29, 7, 5), (32, 7, 5), (8, 4, 3), (16, 5, 4))


def extract(source, name):
    first = source.index("  logic ia_iter_last;")
    last = source.index("  count_t l2_next_equal_i_a;", first)
    body = source[first:last].replace("  logic ia_iter_last;\n", "").replace("  logic w_iter_last;\n", "")
    return f"""module {name} #(
    parameter integer CNT_W=29, LOAD_CNT_W=7, W_CNT_W=5
)(
    input logic [31:0] cfg_ia_reuse_num, ia_reuse_num_act,
    input logic [LOAD_CNT_W-1:0] ia_idx,
    input logic [W_CNT_W-1:0] w_cnt,w_cur_r,
    input logic is_last_l2_group,
    output logic ia_iter_last,w_iter_last
);
    typedef logic [CNT_W-1:0] count_t;
    count_t r_cur,w_cur;
    assign r_cur=is_last_l2_group ? count_t'(ia_reuse_num_act) : count_t'(cfg_ia_reuse_num);
    assign w_cur=count_t'(w_cur_r);
""" + body + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7ddc0d8d")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    model = out / "boundaries.sv"
    model.write_text(extract(reference, "reference_boundaries") + extract(current, "current_boundaries") + """
module proof #(parameter integer CNT_W=29, LOAD_CNT_W=7, W_CNT_W=5)(
    input logic [31:0] cfg_ia_reuse_num,ia_reuse_num_act,
    input logic [LOAD_CNT_W-1:0] ia_idx,
    input logic [W_CNT_W-1:0] w_cnt,w_cur_r,
    input logic is_last_l2_group,
    output wire [1:0] reference_value,current_value,
    output wire equivalent
);
reference_boundaries #(.CNT_W(CNT_W),.LOAD_CNT_W(LOAD_CNT_W),.W_CNT_W(W_CNT_W)) u_reference(
    .cfg_ia_reuse_num,.ia_reuse_num_act,.ia_idx,.w_cnt,.w_cur_r,.is_last_l2_group,
    .ia_iter_last(reference_value[0]),.w_iter_last(reference_value[1]));
current_boundaries #(.CNT_W(CNT_W),.LOAD_CNT_W(LOAD_CNT_W),.W_CNT_W(W_CNT_W)) u_current(
    .cfg_ia_reuse_num,.ia_reuse_num_act,.ia_idx,.w_cnt,.w_cur_r,.is_last_l2_group,
    .ia_iter_last(current_value[0]),.w_iter_last(current_value[1]));
assign equivalent=reference_value===current_value;
endmodule
""")
    bench = out / "tb.sv"
    bench.write_text("""module tb;
parameter integer CNT_W=29,LOAD_CNT_W=7,W_CNT_W=5;
localparam integer INPUT_BITS=65+LOAD_CNT_W+2*W_CNT_W;
logic [31:0] cfg_ia_reuse_num,ia_reuse_num_act;
logic [LOAD_CNT_W-1:0] ia_idx;
logic [W_CNT_W-1:0] w_cnt,w_cur_r;
logic is_last_l2_group;
wire [1:0] reference_value,current_value;
wire equivalent;
logic [INPUT_BITS-1:0] values,saved_values;
logic [31:0] random_state=32'd20261125;
integer checks=0;
proof #(.CNT_W(CNT_W),.LOAD_CNT_W(LOAD_CNT_W),.W_CNT_W(W_CNT_W)) dut(.*);
function automatic [31:0] random_word;
    random_state=random_state^(random_state<<13);
    random_state=random_state^(random_state>>17);
    random_state=random_state^(random_state<<5);
    return random_state;
endfunction
task check_value;
    {cfg_ia_reuse_num,ia_reuse_num_act,ia_idx,w_cnt,w_cur_r,is_last_l2_group}=values;
    #1;
    if(equivalent!==1'b1)$fatal(1,"IA iteration differs count_width=%0d inputs=%h ref=%b current=%b",
        CNT_W,values,reference_value,current_value);
    checks++;
endtask
initial begin
    for(integer sample=0;sample<20000;sample++)begin
        values=INPUT_BITS'({random_word(),random_word(),random_word(),random_word()});
        check_value();
        if(sample%32==0)begin
            saved_values=values;
            for(integer index=0;index<INPUT_BITS;index++)begin
                values=saved_values;values[index]=1'bx;check_value();
                values=saved_values;values[index]=1'bz;check_value();
            end
        end
    end
    values='x;check_value();values='z;check_value();
    $display("PASS checks=%0d",checks);$finish;
end
endmodule
""")
    common = ROOT / "rtl/common/add_equal.sv"
    report = dict(passed=False, reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  source_sha256={SOURCE: hashlib.sha256(current.encode()).hexdigest(),
                    str(common.relative_to(ROOT)): hashlib.sha256(common.read_bytes()).hexdigest()},
                  seed=20261125, input_constraints=False, cases=[])
    for count, load, weight in CASES:
        label = f"c{count}_l{load}_w{weight}"
        options = dict(CNT_W=count, LOAD_CNT_W=load, W_CNT_W=weight)
        script, log = out / (label + ".ys"), out / (label + "_formal.log")
        script.write_text(shlex.join(["read_slang", "--top", "proof",
                          *[f"-G{k}={v}" for k, v in options.items()], str(model), str(common)]) +
                          "\nprep -top proof -flatten\ncheck -assert\n" +
                          "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        binary = out / (label + ".vvp")
        with (out / (label + "_compile.log")).open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", *[f"-Ptb.{k}={v}" for k, v in options.items()],
                            "-o", str(binary), str(model), str(bench), str(common)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        simulation = subprocess.check_output(["vvp", str(binary)], text=True)
        (out / (label + "_four_state.log")).write_text(simulation)
        checks = 20002 + 1250 * (65 + load + 2*weight)
        record = dict(parameters=options, formal_passed="SUCCESS!" in log.read_text(),
                      four_state_passed=f"PASS checks={checks}" in simulation, comparisons=checks)
        report["cases"].append(record)
        report["passed"] = all(r["formal_passed"] and r["four_state_passed"] for r in report["cases"])
        (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not report["passed"]:
            raise RuntimeError("IA iteration verification did not complete")
    if report["source_sha256"] != {
        SOURCE: hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest(),
        str(common.relative_to(ROOT)): hashlib.sha256(common.read_bytes()).hexdigest()}:
        raise RuntimeError("RTL changed during iteration verification")


if __name__ == "__main__":
    main()
