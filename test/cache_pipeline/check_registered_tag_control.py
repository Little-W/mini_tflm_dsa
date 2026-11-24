#!/usr/bin/env python3
"""验证保存标签后的替换冲突和直接返回控制，保持自由输入及四态语义。"""
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
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")
PORTS = """input logic [1:0] fg_state,
input logic bypass_q,demand_lookup_ready,demand_filled,lookup_hit,
input logic [WAYS-1:0] demand_tag_hits,work_tag_hits,
input logic [SI-1:0] select_set,demand_fill_set,demand_set,lookup_set,
input logic [WI-1:0] select_way,demand_fill_way,lookup_way,
input logic fast_control_ready,lookup_snapshot_valid,work_snapshot_matches_q,work_range,
input logic response_count"""
NAMES = ("fg_state", "bypass_q", "demand_lookup_ready", "demand_filled", "lookup_hit",
         "demand_tag_hits", "work_tag_hits", "select_set", "demand_fill_set", "demand_set",
         "lookup_set", "select_way", "demand_fill_way", "lookup_way", "fast_control_ready",
         "lookup_snapshot_valid", "work_snapshot_matches_q", "work_range",
         "response_count")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assign(source, name):
    match = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if match is None:
        raise RuntimeError("缺少生产控制表达式：" + name)
    return match[0]


def model(name, source):
    start = source.index("  logic [WAYS-1:0] demand_selected_victim;")
    end = source.index('  (* keep = 1 *) logic select_launch_eligible;', start)
    victim = source[start:end]
    start = source.index("  end else begin : g_single_response")
    start = source.index("\n", source.index("    // 单个在途名额", start)) + 1
    endings = [source.find(marker, start) for marker in
               ("    assign rsp_data", "    logic [READ_WIDTH-1:0] response_data_by_way",
                "    logic [WAYS-1:0][READ_WIDTH-1:0] response_data_by_way")]
    end = min(value for value in endings if value >= 0)
    response = source[start:end].replace("g_direct_response_lookup.fast_response_conditions",
                                        "fast_response_conditions")
    return f"""module {name} #(parameter integer WAYS=2,SI=4,WI=(WAYS==1?1:$clog2(WAYS)))(
{PORTS},output logic [1:0] observed);
  localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
  logic select_victim_conflict,rsp_valid,core_rsp_valid,fast_hit_response;
  logic [1:0] fast_response_conditions;
  assign fast_response_conditions={{lookup_snapshot_valid && work_snapshot_matches_q && work_range,
                                   fast_control_ready}};
  {assign(source,'fast_hit_response')}
  {assign(source,'core_rsp_valid')}
{victim}
{response}
  assign observed={{select_victim_conflict,rsp_valid}};
endmodule
"""


def support(source):
    result = ""
    for name in ("conv_cache_direct_response", "conv_cache_snapshot_response", "conv_cache_victim_qualification",
                 "conv_cache_metadata_eligibility"):
        declaration = source.index("module " + name)
        start = source.rfind('(* keep_hierarchy = "yes" *)', 0, declaration)
        result += source[start:source.index("endmodule", declaration)+len("endmodule")] + "\n"
    return result


def bench():
    declarations = PORTS.replace("input logic", "logic").replace(",\n", ";\n") + ";\n"
    return f"""module tb;
  localparam integer WAYS=2,SI=8,WI=1,W=11+2*WAYS+4*SI+3*WI;
  {declarations}
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'h9e73db24;
  logic [1:0] expected,actual;
  integer checks=0;
  assign {{{','.join(NAMES)}}}=stimulus;
  reference #(.WAYS(WAYS),.SI(SI)) u_reference(.*,.observed(expected));
  candidate #(.WAYS(WAYS),.SI(SI)) u_candidate(.*,.observed(actual));
  function automatic logic value(input integer index);
    case(index)
      0:value=1'b0;
      1:value=1'b1;
      2:value=1'bx;
      3:value=1'bz;
    endcase
  endfunction
  task automatic check;
    #1;
    if(expected!==actual)
      $fatal(1,"TAG_CONTROL_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for(integer trial=0;trial<16;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      if(trial%4==2) begin
        for(integer index=1;index<4;index++) stimulus[3+3*WI+SI*index+:SI]=stimulus[3+3*WI+:SI];
      end
      saved=stimulus;
      for(integer controls=0;controls<16384;controls++) begin
        stimulus=saved;
        for(integer b=0;b<7;b++) stimulus[W-7+b]=value((controls>>(2*b))&3);
        check();
      end
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus[b]=1'bz;check();
      end
      stimulus=saved;
      for(integer b=0;b<W;b++)
        if(random_state[b%32]) stimulus[b]=(b%2)?1'bx:1'bz;
      check();
    end
    $display("TAG_CONTROL_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def run(command, log, cwd):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="4885effb")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (root / SOURCE).read_text()
    original = ((args.reference_root.resolve() / SOURCE).read_text() if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, SOURCE, text=True))
    modules = model("reference", original) + model("candidate", current) + support(current)
    connections = ",".join(f".{name}({name})" for name in NAMES)
    proof = out / "comparison.sv"
    proof.write_text(modules + f"""module comparison #(
parameter integer WAYS=2,SI=4,WI=(WAYS==1?1:$clog2(WAYS)))({PORTS},output logic equivalent);
  logic [1:0] expected,actual;
  reference #(.WAYS(WAYS),.SI(SI)) u_reference({connections},.observed(expected));
  candidate #(.WAYS(WAYS),.SI(SI)) u_candidate({connections},.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles = []
    for ways, si in ((1,4),(2,4),(1,8),(2,8)):
        script, log = out / f"ways{ways}_si{si}.ys", out / f"ways{ways}_si{si}.log"
        script.write_text(f"read_slang --top comparison -GWAYS={ways} -GSI={si} " +
            shlex.quote(str(proof)) + "\nprep -top comparison -flatten\n"
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("保存标签控制的等价证明未完成")
        profiles.append(dict(ways=ways,sets=1<<si,passed=True,log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text(modules + bench())
    run(["iverilog","-g2012","-s","tb","-o",out / "four_state.vvp",four],
        out / "four_state_compile.log", root)
    run(["vvp",out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"TAG_CONTROL_FOUR_STATE_PASS checks=(\d+)",(out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 263760:
        raise RuntimeError("保存标签控制的四态检查数量不符")
    if current != (root / SOURCE).read_text():
        raise RuntimeError("控制检查期间生产源码发生变化")
    result = dict(passed=True,actual_rtl_expressions=True,external_inputs_constrained=False,
        source_sha256=digest(root / SOURCE),reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        sat_profiles=profiles,four_state_cases=int(matched[1]),proof_sha256=digest(proof),
        four_state_log_sha256=digest(out / "four_state.log"))
    (out / "summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
