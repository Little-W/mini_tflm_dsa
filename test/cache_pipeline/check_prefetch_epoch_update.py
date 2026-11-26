#!/usr/bin/env python3
"""验证每个预取槽位的代次匹配值、完整写入条件和四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from rtl_source_view import read_sources, module_definition, controller_module, source_manifest
import re
import shlex
import subprocess
import sys

from check_response_selection import ROOT, SOURCE, digest, run
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
sys.path.insert(0, str(ROOT / "test/conv_frontend/tools"))
from check_state_context import Statements


def model(name: str, source: str) -> str:
    source = controller_module(source)
    first = source.index("  // 代次比较与需求接收及预取写入同时保存")
    first = source.index("\n", first) + 1
    loop = source.index("  for (genvar slot=0; slot<PF_DEPTH; slot++) begin : g_prefetch_valid", first)
    comparisons = source[first:loop]
    body_start = source.index("\n", loop) + 1
    declarations = source[body_start:source.index("`ifndef ASIC_SYNTHESIS", body_start)]
    first = source.index("always_ff", loop)
    first = source.index("begin", first)
    writes = []

    def selected(statement: str) -> str:
        match = re.fullmatch(r"pf_epoch_matches\s*\[\s*slot\s*\]\s*<=\s*(.*);", statement, re.S)
        if match is None:
            return ""
        writes.append(match[1])
        return "observed = " + match[1] + ";"

    updates = Statements(source[first:], select_assignment=selected).statement()
    if len(writes) != 4:
        raise RuntimeError("预取代次匹配的实际写入次数不符")
    return f"""module {name} #(parameter integer PF_AW=3,SLOT=0)(
  input logic [133+PF_AW:0] stimulus,output logic observed);
  localparam integer PF_DEPTH=1<<PF_AW,slot=SLOT;
  logic rst_n,cfg_valid,cfg_ready,req_fire,pf_push,prior_match;
  logic [PF_AW-1:0] pf_push_slot;
  logic [31:0] pf_offer_epoch,work_epoch,demand_epoch,slot_epoch;
  typedef struct packed {{logic [31:0] epoch;}} request_t;
  request_t processing_request;
  logic [63:0] prefetch_keys_o_rd_data [PF_DEPTH];
  logic pf_offer_matches_work,pf_offer_matches_demand;
  assign {{rst_n,cfg_valid,cfg_ready,req_fire,pf_push,pf_push_slot,
           pf_offer_epoch,work_epoch,demand_epoch,slot_epoch,prior_match}}=stimulus;
  assign processing_request.epoch=work_epoch;
  for(genvar key_index=0;key_index<PF_DEPTH;key_index++)
    assign prefetch_keys_o_rd_data[key_index]={{32'd0,slot_epoch}};
{comparisons}
{declarations}
  always_comb begin
    observed=prior_match;
{updates}
  end
endmodule
"""


def support(source):
    return '\n'.join(module_definition(source, name) for name in ('conv_cache_snapshot_equal', 'conv_cache_prefetch_epoch_value')) + '\n'

def bench() -> str:
    return """module tb;
  localparam integer PF_AW=3,SLOT=7,W=134+PF_AW;
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'ha6158b37;
  logic expected,actual;
  integer checks=0;
  reference #(.PF_AW(PF_AW),.SLOT(SLOT)) u_reference(.*,.observed(expected));
  candidate #(.PF_AW(PF_AW),.SLOT(SLOT)) u_candidate(.*,.observed(actual));
  function automatic logic value(input integer index);
    case(index)
      0:value=1'b0;1:value=1'b1;2:value=1'bx;3:value=1'bz;
    endcase
  endfunction
  task automatic check;
    #1;
    if(expected!==actual)
      $fatal(1,"PREFETCH_EPOCH_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for(integer trial=0;trial<8;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      if(trial%4==2)
        for(integer index=1;index<4;index++) stimulus[1+32*index+:32]=stimulus[1+:32];
      saved=stimulus;
      for(integer controls=0;controls<65536;controls++) begin
        stimulus=saved;
        for(integer b=0;b<8;b++) stimulus[W-8+b]=value((controls>>(2*b))&3);
        check();
      end
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus=saved;stimulus[b]=1'bz;check();
      end
      stimulus='x;check();stimulus='z;check();
    end
    $display("PREFETCH_EPOCH_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="f1910d02")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = read_sources(root, SOURCE)
    original = (read_sources(args.reference_root.resolve(), SOURCE) if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, SOURCE, text=True))
    modules = model("reference", original) + model("candidate", current) + support(current)
    proof = out / "comparison.sv"
    proof.write_text(modules + """module comparison #(parameter integer PF_AW=3,SLOT=0)(
  input logic [133+PF_AW:0] stimulus,output logic equivalent);
  logic expected,actual;
  reference #(.PF_AW(PF_AW),.SLOT(SLOT)) u_reference(.*,.observed(expected));
  candidate #(.PF_AW(PF_AW),.SLOT(SLOT)) u_candidate(.*,.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles = []
    for width in (1,3):
        for slot in (0,(1<<width)-1):
            script, log = out / f"width{width}_slot{slot}.ys", out / f"width{width}_slot{slot}.log"
            script.write_text(f"read_slang --top comparison -DSYNTHESIS=1 -GPF_AW={width} -GSLOT={slot} " +
                shlex.quote(str(proof)) + "\nprep -top comparison -flatten\n"
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError("预取代次匹配的证明未完成")
            profiles.append(dict(slots=1<<width,slot=slot,passed=True,log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text(modules + bench())
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", four],
        out / "four_state_compile.log", root)
    run(["vvp", out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"PREFETCH_EPOCH_FOUR_STATE_PASS checks=(\d+)", (out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 526496:
        raise RuntimeError("预取代次匹配的四态检查数量不符")
    if current != read_sources(root, SOURCE):
        raise RuntimeError("预取代次检查期间生产源码发生变化")
    result = dict(passed=True,actual_rtl_expressions=True,external_inputs_constrained=False,
        source_sha256=digest(root / SOURCE),reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        profiles=profiles,four_state_cases=int(matched[1]),proof_sha256=digest(proof),
        four_state_log_sha256=digest(out / "four_state.log"))
    result["dependency_sha256"] = source_manifest(root, SOURCE)
    (out / "summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
