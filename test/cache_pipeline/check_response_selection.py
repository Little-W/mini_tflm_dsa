#!/usr/bin/env python3
"""比较缓存响应数据、有效位及成功和错误资格的实际表达式。"""
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
input logic response_count,response_error,queue_error,
input logic [WAYS-1:0] work_tag_hits,
input logic fast_control_ready,lookup_snapshot_valid,work_snapshot_matches_q,work_range,
input logic [READ_WIDTH-1:0] queue_data,ram_rdata,
input logic [WAYS-1:0][READ_WIDTH-1:0] speculative_data"""
NAMES = ("fg_state", "response_count", "response_error", "queue_error", "work_tag_hits",
         "fast_control_ready", "lookup_snapshot_valid", "work_snapshot_matches_q", "work_range",
         "queue_data", "ram_rdata", "speculative_data")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment(source: str, name: str) -> str:
    found = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if found is None:
        raise RuntimeError("缺少响应表达式：" + name)
    return found[0]


def model(name: str, source: str) -> str:
    start = source.index("    logic [READ_WIDTH-1:0] fast_hit_data;")
    fast_data = source[start:source.index("    logic [1:0] fast_response_conditions;", start)]
    start = source.index("  end else begin : g_single_response")
    start = source.index("\n", source.index("    // 单个在途名额", start)) + 1
    end = source.index("\n  end\n  assign response_pop", start)
    response = source[start:end]
    response = re.sub(r"\bassign response_push\s*=.*?;", "", response, flags=re.S)
    response = response.replace("g_direct_response_lookup.fast_response_conditions", "fast_response_conditions")
    response = response.replace("response_queue_data[response_head]", "queue_data")
    response = response.replace("response_queue_error[response_head]", "queue_error")
    return f"""module {name} #(parameter integer WAYS=2,READ_WIDTH=128)(
{PORTS},output logic [READ_WIDTH+3:0] observed);
  localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
  logic [READ_WIDTH-1:0] core_rsp_data,rsp_data;
  logic core_rsp_valid,core_rsp_error,fast_hit_response;
  logic rsp_valid,rsp_error,rsp_success,rsp_failure;
  logic [1:0] fast_response_conditions;
  assign fast_response_conditions={{lookup_snapshot_valid && work_snapshot_matches_q && work_range,
                                   fast_control_ready}};
{fast_data}
  {assignment(source,'fast_hit_response')}
  {assignment(source,'core_rsp_valid')}
  {assignment(source,'core_rsp_error')}
  {assignment(source,'core_rsp_data')}
{response}
  assign observed={{rsp_data,rsp_valid,rsp_error,rsp_success,rsp_failure}};
endmodule
"""


def support(source: str) -> str:
    result = ""
    for name in ("conv_cache_direct_response", "conv_cache_snapshot_response", "conv_cache_response_data_select"):
        start = source.index("module " + name)
        result += source[start:source.index("endmodule", start)+len("endmodule")] + "\n"
    return result


def bench() -> str:
    declarations = PORTS.replace("input logic", "logic").replace(",\n", ";\n") + ";\n"
    return f"""module tb;
  localparam integer WAYS=2,READ_WIDTH=128,W=9+WAYS+(2+WAYS)*READ_WIDTH;
  {declarations}
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'ha37951e4;
  logic [READ_WIDTH+3:0] expected,actual;
  integer checks=0;
  assign {{{','.join(NAMES)}}}=stimulus;
  reference #(.WAYS(WAYS),.READ_WIDTH(READ_WIDTH)) u_reference(.*,.observed(expected));
  candidate #(.WAYS(WAYS),.READ_WIDTH(READ_WIDTH)) u_candidate(.*,.observed(actual));
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
      $fatal(1,"RESPONSE_SELECTION_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for(integer trial=0;trial<4;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[b]=random_state[0];
      end
      if(trial==0) stimulus='0;
      if(trial==1) stimulus='1;
      if(trial==2) begin
        for(integer index=1;index<4;index++)
          stimulus[READ_WIDTH*index+:READ_WIDTH]=stimulus[0+:READ_WIDTH];
      end
      saved=stimulus;
      for(integer controls=0;controls<(trial==0?4194304:262144);controls++) begin
        stimulus=saved;
        if(trial==0) begin
          for(integer b=0;b<11;b++) stimulus[W-11+b]=value((controls>>(2*b))&3);
        end else begin
          stimulus[W-10]=1'b1;stimulus[W-9]=1'b1;
          stimulus[W-11]=value(controls&3);
          for(integer b=1;b<9;b++) stimulus[W-9+b]=value((controls>>(2*b))&3);
        end
        check();
      end
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus=saved;stimulus[b]=1'bz;check();
      end
      stimulus='x;check();stimulus='z;check();
    end
    $display("RESPONSE_SELECTION_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def run(command: list, log: Path, cwd: Path) -> None:
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="f1910d02")
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
    proof.write_text(modules + f"""module comparison #(parameter integer WAYS=2,READ_WIDTH=128)(
{PORTS},output logic equivalent);
  logic [READ_WIDTH+3:0] expected,actual;
  reference #(.WAYS(WAYS),.READ_WIDTH(READ_WIDTH)) u_reference({connections},.observed(expected));
  candidate #(.WAYS(WAYS),.READ_WIDTH(READ_WIDTH)) u_candidate({connections},.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles = []
    for ways in (1,2):
        for width in (32,64,128):
            script, log = out / f"ways{ways}_width{width}.ys", out / f"ways{ways}_width{width}.log"
            script.write_text(f"read_slang --top comparison -DSYNTHESIS=1 -GWAYS={ways} -GREAD_WIDTH={width} " +
                shlex.quote(str(proof)) + "\nprep -top comparison -flatten\n"
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError("缓存响应选择的证明未完成")
            profiles.append(dict(ways=ways,read_width=width,passed=True,log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text(modules + bench())
    run(["iverilog","-g2012","-s","tb","-o",out / "four_state.vvp",four],
        out / "four_state_compile.log", root)
    run(["vvp",out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"RESPONSE_SELECTION_FOUR_STATE_PASS checks=(\d+)",(out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 4984928:
        raise RuntimeError("缓存响应选择的四态检查数量不符")
    if current != (root / SOURCE).read_text():
        raise RuntimeError("响应检查期间生产源码发生变化")
    result = dict(passed=True,actual_rtl_expressions=True,external_inputs_constrained=False,
        source_sha256=digest(root / SOURCE),reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        sat_profiles=profiles,four_state_cases=int(matched[1]),proof_sha256=digest(proof),
        four_state_log_sha256=digest(out / "four_state.log"))
    (out / "summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
