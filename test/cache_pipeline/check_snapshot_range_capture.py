#!/usr/bin/env python3
"""验证完整请求来源选择、范围位和快照采样边沿的等价性。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from check_snapshot_functions import support


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def between(text, start, stop):
    first = text.index(start)
    return text[first:text.index(stop, first)]


def context(name, text):
    declaration = between(text, "  typedef struct packed {\n    logic [31:0] address, epoch",
                          "  demand_t request_queue")
    cache_set = between(text, "  function automatic logic [SI-1:0] cache_set", "  endfunction") + "  endfunction\n"
    preview = between(text, "  unsigned_compare #(.p_width(32)) u_preview_base",
                      "  // 读取数据来源只依赖")
    selection = between(text, "  if (DEMAND_DEPTH == 1) begin : g_direct_read_source",
                        "  always_comb begin\n    lookup_read_set")
    selection = selection.replace("request_queue[DQ_AW'(request_head + DQ_AW'(1))]", "head_request")
    selection = selection.replace("request_queue[request_head]", "head_request")
    parameters = re.search(r"conv_cache_snapshot_fields #\((.*?)\) u_fields", text, re.S)
    if parameters is None:
        raise RuntimeError("未找到实际快照实例")
    if name == "candidate" and ".p_capture_range(1'b1)" not in parameters[1]:
        raise RuntimeError("候选实例未启用完整请求范围位保存")
    return f"""module {name} #(parameter integer SI=4,RW=131+SI,W=2*RW+201+SI)(
  input logic clk,input logic [W-1:0] stimulus,output logic [RW+3:0] observed);
  localparam integer DEMAND_DEPTH=1,DQ_CW=1,DQ_AW=1,LB=7,SETS=1<<SI;
  localparam logic [1:0] FG_MISS=1;
{declaration}
  demand_t incoming_request,preview_request,lookup_input_request,lookup_read_request;
  demand_t head_request;
  logic [RW-1:0] head_bits,incoming_bits;
  logic [31:0] preview_addr,base_q,end_q,preview_index;
  logic [31:2] work_word,demand_word;
  logic [SI-1:0] expected_set;
  logic [1:0] fg_state;
  logic request_count,req_fire,lookup_input_valid,preview_source_select;
  logic windowed_q,preview_index_valid;
  logic preview_below_base,preview_below_end,unused_preview_base_equal,unused_preview_end_equal;
  logic request_head;
  logic [4:0] reference_values;
  assign {{incoming_bits,head_bits,preview_addr,base_q,end_q,preview_index,work_word,demand_word,
           expected_set,fg_state,request_count,req_fire,lookup_input_valid,preview_source_select,
           windowed_q,preview_index_valid,reference_values}}=stimulus;
  assign incoming_request=incoming_bits;
  assign head_request=head_bits;
  assign request_head=1'b0;
  assign lookup_input_request=preview_source_select ? preview_request : incoming_request;
{cache_set}
{preview}
{selection}
  {name}_conv_cache_snapshot_fields #({parameters[1]}) u_fields (
    .clk(clk),.i_request(lookup_read_request),.i_fg_state(fg_state),
    .i_request_count(request_count),.i_req_fire(req_fire),.i_lookup_input_valid(lookup_input_valid),
    .i_preview_source_select(preview_source_select),.i_work_word(work_word),.i_demand_word(demand_word),
    .i_expected_set(expected_set),.i_base(base_q),.i_end(end_q),
    .i_request_range(incoming_request.in_range),.i_head_range(head_request.in_range),
`ifndef SYNTHESIS
    .i_reference(reference_values),
`endif
    .o_request(observed[RW+3:4]),.o_work_word_matches(observed[3]),
    .o_work_snapshot_matches(observed[2]),.o_demand_word_matches(observed[1]),
    .o_response_snapshot_ready(observed[0]));
endmodule
"""


def bench():
    return """module tb;
  localparam integer SI=8,RW=131+SI,W=2*RW+201+SI;
  logic clk=0;
  logic [W-1:0] stimulus,saved;
  logic [RW+3:0] expected,actual;
  logic equivalent;
  logic [31:0] random_state=32'h29507183;
  integer checks=0;
  comparison #(.SI(SI)) dut(.*);
  task automatic tick;
    clk=0;#1;clk=1;#1;
    if(expected!==actual)$fatal(1,"Snapshot range differs at sample %0d",checks);
    checks++;
    clk=0;
  endtask
  initial begin
    for(integer trial=0;trial<16;trial++)begin
      for(integer bit_index=0;bit_index<W;bit_index++)begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        stimulus[bit_index]=random_state[0];
      end
      if(trial%4==0)stimulus='0;
      if(trial%4==1)stimulus='1;
      saved=stimulus;tick();
      for(integer bit_index=0;bit_index<W;bit_index++)begin
        stimulus=saved;stimulus[bit_index]=1'bx;tick();
        stimulus=saved;stimulus[bit_index]=1'bz;tick();
      end
      stimulus='x;tick();stimulus='z;tick();
    end
    $display("SNAPSHOT_RANGE_CAPTURE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def run(command, log):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, reference, out = args.source_root.resolve(), args.reference_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root / SOURCE, reference / SOURCE, root / "rtl/common/onehot_mux.sv",
               root / "rtl/common/unsigned_compare.sv", root / "rtl/common/parallel_unsigned_compare.sv"]
    hashes = {str(path): digest(path) for path in sources}
    current, original = sources[0].read_text(), sources[1].read_text()
    text = "\n".join((support(original, "reference_"), support(current, "candidate_"),
                       context("reference", original), context("candidate", current)))
    text += """module comparison #(parameter integer SI=4,RW=131+SI,W=2*RW+201+SI)(
      input logic clk,input logic [W-1:0] stimulus,
      output logic [RW+3:0] expected,actual,output logic equivalent);
      reference #(.SI(SI)) u_reference(.*,.observed(expected));
      candidate #(.SI(SI)) u_candidate(.*,.observed(actual));
      assign equivalent=expected==actual;
    endmodule
"""
    model = out / "comparison.sv"
    model.write_text(text)
    common = sources[2:]
    profiles = []
    for width in (1, 2, 4, 8, 16):
        script, log = out / f"set_width_{width}.ys", out / f"set_width_{width}.log"
        script.write_text(f"read_slang --top comparison -DSYNTHESIS=1 -GSI={width} " +
            " ".join(shlex.quote(str(path)) for path in [*common, model]) + "\n"
            "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
            "prep -top comparison -flatten\ncheck -assert\n"
            "sat -seq 2 -prove-skip 1 -verify -prove equivalent 1 -set-def-inputs\n"
            "sat -seq 1 -tempinduct -tempinduct-inductonly -verify -prove equivalent 1 -set-def-inputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
        profiles.append({"set_width": width, "passed": True, "log_sha256": digest(log)})
    four = out / "four_state.sv"
    four.write_text(text.replace("always_comb", "always @*") + bench())
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", *common, four],
        out / "four_state_compile.log")
    run(["vvp", out / "four_state.vvp"], out / "four_state.log")
    matched = re.search(r"SNAPSHOT_RANGE_CAPTURE_PASS checks=(\d+)", (out / "four_state.log").read_text())
    expected_samples = 16 * (2 * (2 * (131 + 8) + 201 + 8) + 3)
    if not matched or int(matched[1]) != expected_samples:
        raise RuntimeError("范围采样四态检查未完成")
    if any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError("检查期间源码发生变化")
    result = {"passed": True, "actual_read_source_selection": True, "external_inputs_constrained": False,
              "formal_profiles": profiles, "four_state_cases": int(matched[1]),
              "source_sha256": hashes, "model_sha256": digest(model), "checker_sha256": digest(__file__)}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("SNAPSHOT_RANGE_CAPTURE_PASS", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
