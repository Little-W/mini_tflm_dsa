#!/usr/bin/env python3
"""验证完整缓存快照函数在相同采样边沿的二态和四态输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from rtl_source_view import read_sources, module_definition, source_manifest
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")
HELPERS = ("conv_cache_snapshot_fields", "conv_cache_snapshot_equal", "conv_cache_snapshot_range")
NAMES = ("i_request", "i_fg_state", "i_request_count", "i_req_fire", "i_lookup_input_valid",
         "i_preview_source_select", "i_work_word", "i_demand_word", "i_expected_set",
         "i_base", "i_end", "i_request_range", "i_head_range", "i_reference")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def support(text, prefix):
    body = '\n'.join(module_definition(text, name) for name in HELPERS)
    for name in HELPERS:
        body = re.sub(r"\b" + name + r"\b", prefix + name, body)
    return body

def comparison():
    connections = ",".join(f".{name}({name})" for name in NAMES if name != "i_reference")
    instances = []
    for prefix, result in (("reference_", "expected"), ("candidate_", "actual")):
        instances.append(f"""{prefix}conv_cache_snapshot_fields #(.p_set_width(SI)) u_{result} (
    .clk(clk),{connections},
`ifndef SYNTHESIS
    .i_reference(i_reference),
`endif
    .o_request({result}[RW+3:4]),.o_work_word_matches({result}[3]),
    .o_work_snapshot_matches({result}[2]),.o_demand_word_matches({result}[1]),
    .o_response_snapshot_ready({result}[0]));""")
    return f"""module comparison #(parameter integer SI=4, RW=131+SI, W=RW+137+SI)(
  input logic clk,input logic [W-1:0] stimulus,
  output logic [RW+3:0] expected,actual,output logic equivalent);
  logic [RW-1:0] i_request;
  logic [1:0] i_fg_state;
  logic i_request_count,i_req_fire,i_lookup_input_valid,i_preview_source_select;
  logic [31:2] i_work_word,i_demand_word;
  logic [SI-1:0] i_expected_set;
  logic [31:0] i_base,i_end;
  logic i_request_range,i_head_range;
  logic [4:0] i_reference;
  assign {{{','.join(NAMES)}}}=stimulus;
  {''.join(instances)}
  assign equivalent=expected==actual;
endmodule
"""


def bench():
    return """module tb;
  localparam integer SI=8,RW=131+SI,W=RW+137+SI;
  logic clk=0;
  logic [W-1:0] stimulus,saved;
  logic [RW+3:0] expected,actual;
  logic equivalent;
  logic [31:0] random_state=32'h2b91c6e5;
  integer checks=0;
  comparison #(.SI(SI)) dut(.*);
  task automatic tick;
    clk=0;#1;clk=1;#1;
    if(expected!==actual)
      $fatal(1,"SNAPSHOT_FUNCTION_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
    clk=0;
  endtask
  initial begin
    for(integer trial=0;trial<32;trial++) begin
      for(integer bit_index=0;bit_index<W;bit_index++) begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        stimulus[bit_index]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      saved=stimulus;tick();
      for(integer bit_index=0;bit_index<W;bit_index++) begin
        stimulus=saved;stimulus[bit_index]=1'bx;tick();
        stimulus=saved;stimulus[bit_index]=1'bz;tick();
      end
      stimulus='x;tick();stimulus='z;tick();
    end
    $display("SNAPSHOT_FUNCTION_FOUR_STATE_PASS checks=%0d",checks);
    $finish;
  end
endmodule
"""


def run(command, log, cwd):
    with log.open("w") as stream:
        subprocess.run([str(value) for value in command], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, reference, out = args.source_root.resolve(), args.reference_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original, current = read_sources(reference, SOURCE), read_sources(root, SOURCE)
    common = [root / "rtl/common/unsigned_compare.sv", root / "rtl/common/parallel_unsigned_compare.sv"]
    model = support(original, "reference_") + "\n" + support(current, "candidate_") + "\n" + comparison()
    proof = out / "comparison.sv"
    proof.write_text(model)
    profiles = []
    for width in (1, 2, 4, 8, 16):
        script, log = out / f"set_width_{width}.ys", out / f"set_width_{width}.log"
        script.write_text(f"read_slang --top comparison -DSYNTHESIS=1 -GSI={width} " +
            " ".join(shlex.quote(str(path)) for path in [*common, proof]) + "\n"
            "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
            "prep -top comparison -flatten\n"
            "sat -seq 2 -prove-skip 1 -verify -prove equivalent 1 -set-def-inputs -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("快照函数形式检查未完成")
        profiles.append({"set_width": width, "passed": True, "log_sha256": digest(log)})
    four = out / "four_state.sv"
    four.write_text(model + bench())
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", *common, four],
        out / "four_state_compile.log", root)
    run(["vvp", out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"SNAPSHOT_FUNCTION_FOUR_STATE_PASS checks=(\d+)",
                        (out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 18272:
        raise RuntimeError("快照函数四态检查数量不符")
    if current != read_sources(root, SOURCE) or original != read_sources(reference, SOURCE):
        raise RuntimeError("检查期间快照源码发生变化")
    result = {"passed": True, "actual_rtl_modules": True, "external_inputs_constrained": False,
              "reference_sha256": digest(reference / SOURCE), "candidate_sha256": digest(root / SOURCE),
              "common_sha256": {str(path.relative_to(root)): digest(path) for path in common},
              "formal_profiles": profiles, "four_state_cases": int(matched[1]),
              "proof_sha256": digest(proof), "four_state_log_sha256": digest(out / "four_state.log")}
    result["dependency_sha256"] = source_manifest(root, SOURCE)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "formal_profiles": len(profiles),
                      "four_state_cases": int(matched[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
