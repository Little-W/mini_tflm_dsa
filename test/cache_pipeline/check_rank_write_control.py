#!/usr/bin/env python3
"""验证替换来源表的写入优先级、地址及四态控制。"""
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
SOURCE = Path("rtl/npu/dma/cache/conv_cache_rank_table.sv")
PORTS = """input logic i_clear_en,i_write_en,i_fill_valid,i_hint_valid,i_hit_valid,
input logic [p_addr_width-1:0] i_clear_addr,i_fill_addr,i_hint_addr,i_hit_addr"""
NAMES = ("i_clear_en", "i_write_en", "i_fill_valid", "i_hint_valid", "i_hit_valid",
         "i_clear_addr", "i_fill_addr", "i_hint_addr", "i_hit_addr")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(name, source):
    start = source.index("  assign bank_i_wr_en[0]")
    end = source.index("  // 每个存储体读取", start)
    expressions = source[start:end]
    return f"""module {name} #(parameter integer p_addr_width=8)(
{PORTS},output logic [3*p_addr_width+2:0] observed);
  logic [2:0] bank_i_wr_en;
  logic [2:0][p_addr_width-1:0] bank_i_wr_addr;
  logic hit_write_eligible;
{expressions}
  assign observed={{bank_i_wr_en,bank_i_wr_addr}};
endmodule
"""


def support(source):
    declaration = source.index("module conv_cache_rank_hit_write")
    start = source.rfind('(* keep_hierarchy = "yes" *)', 0, declaration)
    return source[start:source.index("endmodule", declaration)+len("endmodule")] + "\n"


def bench():
    declarations = PORTS.replace("input logic", "logic").replace(",\n", ";\n") + ";\n"
    return f"""module tb;
  localparam integer p_addr_width=8,W=5+4*p_addr_width;
  {declarations}
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'hb1596e43;
  logic [3*p_addr_width+2:0] expected,actual;
  integer checks=0;
  assign {{{','.join(NAMES)}}}=stimulus;
  reference u_reference(.*,.observed(expected));
  candidate u_candidate(.*,.observed(actual));
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
      $fatal(1,"RANK_WRITE_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for(integer trial=0;trial<64;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      if(trial%4==2) begin
        for(integer index=1;index<4;index++)
          stimulus[p_addr_width*index+:p_addr_width]=stimulus[0+:p_addr_width];
      end
      saved=stimulus;
      for(integer controls=0;controls<1024;controls++) begin
        stimulus=saved;
        for(integer b=0;b<5;b++) stimulus[W-5+b]=value((controls>>(2*b))&3);
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
    $display("RANK_WRITE_FOUR_STATE_PASS checks=%0d",checks);$finish;
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
    proof.write_text(modules + f"""module comparison #(parameter integer p_addr_width=8)(
{PORTS},output logic equivalent);
  logic [3*p_addr_width+2:0] expected,actual;
  reference #(.p_addr_width(p_addr_width)) u_reference({connections},.observed(expected));
  candidate #(.p_addr_width(p_addr_width)) u_candidate({connections},.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles = []
    for width in (1,4,8):
        script, log = out / f"width{width}.ys", out / f"width{width}.log"
        script.write_text(f"read_slang --top comparison -Gp_addr_width={width} " +
            shlex.quote(str(proof)) + "\nprep -top comparison -flatten\n"
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("替换来源写入控制的证明未完成")
        profiles.append(dict(sets=1<<width,passed=True,log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text(modules + bench())
    run(["iverilog","-g2012","-s","tb","-o",out / "four_state.vvp",four],
        out / "four_state_compile.log", root)
    run(["vvp",out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"RANK_WRITE_FOUR_STATE_PASS checks=(\d+)",(out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 70336:
        raise RuntimeError("替换来源写入控制的四态检查数量不符")
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
