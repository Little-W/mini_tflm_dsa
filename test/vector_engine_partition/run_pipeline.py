#!/usr/bin/env python3
"""验证向量引擎量化阶段数组的完整状态转移和四态行为。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pipeline(source, name, current):
    if current:
        source = source.replace('vector_engine_control_pkg::', '')
        for original in ('TILE', 'PE_COUNT', 'SHARED_QUANT_ENABLE', 'ACTIVE_COUNT_W', 'TILE_INDEX_W'):
            source = re.sub(r'\bp_' + original.lower() + r'\b', original, source)
    reset = re.search(r"q_accumulator\s*<=0;.*?q_active\s*<=0;", source, re.S)
    start = source.index("      if (depthwise && !SHARED_QUANT_ENABLE && state")
    end = source.index("      if (softmax_s8)", start)
    if reset is None:
        raise ValueError("缺少量化状态的复位逻辑")
    body = source[start:end]
    right = [f"q_right[{i}]" if current else f"q_right_{i}" for i in range(3)]
    index = [f"q_index[{i}]" if current else f"q_index_{i}" for i in range(7)]
    declarations = (
        "logic [5:0] q_right[3];\nlogic [TILE_INDEX_W-1:0] q_index[7];\n"
        if current else "logic [5:0] " + ",".join(right) + ";\n"
        + "logic [TILE_INDEX_W-1:0] " + ",".join(index) + ";\n")
    outputs = ["q_accumulator", "q_multiplier", "q_rounded", *right, "q_valid",
               *index, "q_clamped_q", "q_issue", "q_count", "q_active"]
    return f"""module {name} #(
  parameter int TILE=16, PE_COUNT=8,
  parameter bit SHARED_QUANT_ENABLE=0,
  parameter int ACTIVE_COUNT_W=$clog2(TILE+1),
  parameter int TILE_INDEX_W=$clog2(TILE+PE_COUNT+1)
) (
  input logic clk, rst_n, depthwise, state_failed,
  input logic [5:0] state,
  input logic dw_quant_input_active, dw_quant_start, input_drain_ready,
  input logic [ACTIVE_COUNT_W-1:0] active,
  input logic signed [31:0] quant_req_accumulator[TILE], params_o_multiplier,
  input logic [5:0] params_o_right_shift,
  input logic signed [63:0] rounding_result,
  input logic signed [31:0] q_clamped_data,
  output logic [162+9*TILE_INDEX_W-1:0] saved_state
);
  localparam logic [5:0] IDLE=0, CHECK=1, FAILED=20, DONE=21;
  logic signed [31:0] q_accumulator, q_multiplier;
  logic signed [63:0] q_rounded;
  logic [6:0] q_valid;
  logic [7:0] q_clamped_q;
  logic [TILE_INDEX_W-1:0] q_issue, q_count;
  logic q_active;
  {declarations}
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      {reset[0]}
    end else begin
{body}
      if (state==CHECK || (state==FAILED && input_drain_ready)) begin
        q_active<=0;
        q_valid<=0;
      end
    end
  end
  assign saved_state={{{','.join(outputs)}}};
endmodule
"""


def execute(command, log):
    with log.open("w") as stream:
        result = subprocess.run([str(x) for x in command], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=180)
    if result.returncode:
        raise RuntimeError(str(log) + "\n" + log.read_text()[-8000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-engine", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = args.source_root / "rtl/npu/conv/vector_engine_control.sv"
    original = args.reference_engine.read_text()
    current = current_path.read_text()
    sources = pipeline(original, "reference_pipeline", False) + pipeline(current, "selected_pipeline", True)
    records = []
    for tile, pes, shared in ((8, 4, 0), (16, 8, 0), (16, 16, 0), (16, 8, 1)):
        folder = out / f"tile{tile}_pe{pes}_shared{shared}"
        folder.mkdir(exist_ok=True)
        width = (tile + pes).bit_length()
        state_width = 162 + 9 * width
        active_width = tile.bit_length()
        header = f"""module property_top(
  input logic clk, rst_n, depthwise, state_failed,
  input logic [5:0] state,
  input logic dw_quant_input_active, dw_quant_start, input_drain_ready,
  input logic [{active_width-1}:0] active,
  input logic signed [31:0] quant_req_accumulator[{tile}], params_o_multiplier,
  input logic [5:0] params_o_right_shift,
  input logic signed [63:0] rounding_result,
  input logic signed [31:0] q_clamped_data,
  output wire identical
);
  wire [{state_width-1}:0] reference_state, selected_state;
  reference_pipeline #(.TILE({tile}),.PE_COUNT({pes}),.SHARED_QUANT_ENABLE({shared})) original (
      .saved_state(reference_state), .*);
  selected_pipeline #(.TILE({tile}),.PE_COUNT({pes}),.SHARED_QUANT_ENABLE({shared})) selected (
      .saved_state(selected_state), .*);
  assign identical = reference_state === selected_state;
endmodule
"""
        model = folder / "model.sv"
        model.write_text(sources + header)
        script = folder / "prove.ys"
        script.write_text(
            f"read_slang --top property_top {model}\n"
            "prep -top property_top -flatten\nasync2sync\ndffunmap\nopt_clean\n"
            "sat -verify -seq 2 -tempinduct -set-init-zero -set-def-inputs -prove identical 1\n")
        execute([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], folder / "prove.log")
        bench = folder / "bench.sv"
        bench.write_text(f"""module tb;
  logic clk=0, rst_n=0, depthwise, state_failed;
  logic [5:0] state;
  logic dw_quant_input_active, dw_quant_start, input_drain_ready;
  logic [{active_width-1}:0] active;
  logic signed [31:0] quant_req_accumulator[{tile}], params_o_multiplier;
  logic [5:0] params_o_right_shift;
  logic signed [63:0] rounding_result;
  logic signed [31:0] q_clamped_data;
  wire identical;
  integer unsigned random_state=32'h7c511e34;
  function automatic integer unsigned random_next;
    random_state^=random_state<<13;
    random_state^=random_state>>17;
    random_state^=random_state<<5;
    return random_state;
  endfunction
  function automatic logic four(input logic [1:0] value);
    case (value) 0:four=0; 1:four=1; 2:four=1'bx; 3:four=1'bz; endcase
  endfunction
  property_top dut(.*);
  initial begin
    for (int cycle=0; cycle<65536; cycle++) begin
      rst_n=(cycle%97)!=0;
      depthwise=cycle%5!=0;
      state_failed=cycle%29==0;
      state=6'(random_next());
      dw_quant_input_active=cycle%7!=0;
      dw_quant_start=cycle%23==0;
      input_drain_ready=1'(random_next());
      active={active_width}'(random_next());
      params_o_multiplier=random_next();
      params_o_right_shift=6'(random_next());
      rounding_result={{random_next(),random_next()}};
      q_clamped_data=random_next();
      for (int lane=0; lane<{tile}; lane++) quant_req_accumulator[lane]=random_next();
      if(cycle%3==0) begin
        depthwise=four(2'(random_next()));
        state_failed=four(2'(random_next()));
        dw_quant_input_active=four(2'(random_next()));
        dw_quant_start=four(2'(random_next()));
        params_o_right_shift[cycle%6]=four(2'(random_next()));
        rounding_result[cycle%64]=four(2'(random_next()));
        quant_req_accumulator[cycle%{tile}][cycle%32]=four(2'(random_next()));
      end
      #1; clk=1; #1;
      if(identical!==1'b1) $fatal(1,"量化阶段状态不一致，周期 %0d",cycle);
      clk=0; #1;
      if(cycle%31==0) begin
        rst_n=0; #1;
        if(identical!==1'b1) $fatal(1,"异步复位状态不一致");
      end
    end
    $display("VECTOR_PIPELINE_PASS cycles=65536");
    $finish;
  end
endmodule
""")
        executable = folder / "simulation.vvp"
        execute(["iverilog", "-g2012", "-s", "tb", "-o", executable, model, bench], folder / "compile.log")
        execute(["vvp", executable], folder / "simulate.log")
        record = {"tile": tile, "pe_count": pes, "shared_quant": bool(shared),
                  "saved_state_bits": state_width, "inductive_equivalence": True,
                  "four_state_cycles": 65536, "passed": True}
        records.append(record)
        print(json.dumps(record), flush=True)
    summary = {"passed": True, "checks": records,
               "reference_sha256": digest(args.reference_engine),
               "current_sha256": digest(current_path), "test_sha256": digest(__file__)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
