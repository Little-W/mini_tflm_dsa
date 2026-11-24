#!/usr/bin/env python3
"""比较预取描述集合号保存逻辑的全部二值输入及四态输入。"""
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(name: str, source: str) -> str:
    start = source.index("  logic [3:0] offer_read_set_match_q;")
    end = source.index("  // 保存采样边沿的复位状态", start)
    body = source[start:end].replace("always_ff @(posedge clk)", "always_comb")
    body = body.replace(" <= ", " = ")
    return f"""module {name} #(parameter integer SI=8)(
  input logic [8*SI+1:0] stimulus, output logic [3:0] observed);
  logic rst_n,offer_capture;
  logic [SI-1:0] initial_pf_set,next_pf_set,offer_set_q,offer_next_set_q;
  logic [SI-1:0] incoming_snapshot_set,next_snapshot_set;
  logic [SI-1:0] incoming_hold_snapshot_set,next_hold_snapshot_set;
  assign {{rst_n,offer_capture,initial_pf_set,next_pf_set,offer_set_q,offer_next_set_q,
      incoming_snapshot_set,next_snapshot_set,incoming_hold_snapshot_set,next_hold_snapshot_set}}=stimulus;
{body}
  assign observed=offer_read_set_match_q;
endmodule
"""


def support(source: str) -> str:
    declaration = source.index("module conv_cache_offer_match_select")
    start = source.rfind('(* keep_hierarchy = "yes" *)', 0, declaration)
    return source[start:source.index("endmodule", declaration)+len("endmodule")] + "\n"


def bench() -> str:
    return """module tb;
  localparam integer SI=8,W=8*SI+2;
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'hd65e1739;
  logic [3:0] expected,actual;
  integer checks=0;
  reference #(.SI(SI)) u_reference(.*,.observed(expected));
  candidate #(.SI(SI)) u_candidate(.*,.observed(actual));
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
      $fatal(1,"OFFER_SET_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for(integer trial=0;trial<64;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      if(trial%4==2) begin
        for(integer index=1;index<8;index++)
          stimulus[SI*index+:SI]=stimulus[0+:SI];
      end
      saved=stimulus;
      for(integer controls=0;controls<16;controls++) begin
        stimulus=saved;
        stimulus[W-2]=value(controls&3);
        stimulus[W-1]=value((controls>>2)&3);
        check();
      end
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus=saved;stimulus[b]=1'bz;check();
      end
      stimulus='x;check();
      stimulus='z;check();
    end
    $display("OFFER_SET_FOUR_STATE_PASS checks=%0d",checks);$finish;
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
    parser.add_argument("--reference-ref", default="4885effb")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (root / SOURCE).read_text()
    original = ((args.reference_root.resolve() / SOURCE).read_text() if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, SOURCE, text=True))
    modules = model("reference", original) + model("candidate", current) + support(current)
    proof = out / "comparison.sv"
    proof.write_text(modules + """module comparison #(parameter integer SI=8)(
  input logic [8*SI+1:0] stimulus, output logic equivalent);
  logic [3:0] expected,actual;
  reference #(.SI(SI)) u_reference(.*,.observed(expected));
  candidate #(.SI(SI)) u_candidate(.*,.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles = []
    for width in (1,2,3,4,8):
        script, log = out / f"width{width}.ys", out / f"width{width}.log"
        script.write_text(f"read_slang --top comparison -DSYNTHESIS=1 -GSI={width} " +
            shlex.quote(str(proof)) + "\nprep -top comparison -flatten\n"
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("预取描述集合号保存逻辑的证明未完成")
        profiles.append(dict(sets=1<<width,passed=True,log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text(modules + bench())
    run(["iverilog","-g2012","-s","tb","-o",out / "four_state.vvp",four],
        out / "four_state_compile.log", root)
    run(["vvp",out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"OFFER_SET_FOUR_STATE_PASS checks=(\d+)",(out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 9600:
        raise RuntimeError("预取描述集合号保存逻辑的四态检查数量不符")
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
