#!/usr/bin/env python3
"""验证每路元数据命中更新的来源、优先级与四态选择。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from check_registered_tag_control import ROOT, assign, digest, run
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file

SOURCE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")
PORTS = """input logic [1:0] fg_state,
input logic bypass_q,demand_filled,work_lookup_ready,demand_lookup_ready,req_fire,lookup_range,
input logic [WI-1:0] demand_fill_way,
input logic [WAYS-1:0] work_tag_hits,demand_tag_hits"""
NAMES = ("fg_state", "bypass_q", "demand_filled", "work_lookup_ready", "demand_lookup_ready",
         "req_fire", "lookup_range", "demand_fill_way", "work_tag_hits", "demand_tag_hits")


def connection(source, name):
    start = source.index("." + name + "(", source.index("    ) u_metadata (")) + len(name) + 2
    depth, end = 1, start
    while depth:
        if source[end] == "(":
            depth += 1
        elif source[end] == ")":
            depth -= 1
        end += 1
    return source[start:end-1]


def model(name, source):
    start = source.index("  always_comb begin\n    lookup_way =")
    end = source.index("  localparam int p_prefetch_fill_tag_groups", start)
    way = source[start:end]
    metadata = re.search(r"wire\s+metadata_hit\s*=\s*(.*?);", source, re.S)[1]
    eligible, selected = "", ""
    if "logic selected_metadata_hit, metadata_hit_parallel" in source:
        start = source.index("  logic metadata_work_eligible, metadata_demand_eligible;")
        eligible = source[start:source.index("  for (genvar metadata_way", start)]
        start = source.index("    logic selected_metadata_hit, metadata_hit_parallel")
        selected = source[start:source.index("    conv_cache_metadata_way #(",start)]
    if "conv_cache_lookup_hit #(.p_ways(WAYS)) u_lookup_hit" in source:
        start = source.index("  conv_cache_lookup_hit #(.p_ways(WAYS)) u_lookup_hit")
        lookup = source[start:source.index("  );", start)+5]
    else:
        lookup = assign(source, "lookup_hit")
    return f"""module {name} #(parameter integer WAYS=2,WI=(WAYS==1?1:$clog2(WAYS)))(
{PORTS},output logic [WAYS-1:0] observed);
  localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
  logic lookup_ready,lookup_hit,metadata_hit;
  logic [WI-1:0] lookup_way;
  {assign(source,'lookup_ready')}
{lookup}
  assign metadata_hit={metadata};
{way}
{eligible}
  for(genvar metadata_way=0;metadata_way<WAYS;metadata_way++) begin:g_way
{selected}
    assign observed[metadata_way]=({connection(source,'i_metadata_hit')}) && ({connection(source,'i_hit_selected')});
  end
endmodule
"""


def support(source):
    result = ""
    for name in ("conv_cache_metadata_hit_select", "conv_cache_metadata_hit_finish", "conv_cache_metadata_eligibility",
                 "conv_cache_lookup_hit", "conv_cache_demand_hit", "conv_cache_snapshot_response"):
        declaration = source.index("module " + name)
        start = declaration
        result += source[start:source.index("endmodule", declaration)+len("endmodule")] + "\n"
    return result


def bench():
    declarations = PORTS.replace("input logic","logic").replace(",\n",";\n") + ";\n"
    return f"""module tb;
  localparam integer WAYS=2,WI=1,W=8+WI+2*WAYS;
  {declarations}
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'h8c69375b;
  logic [WAYS-1:0] expected,actual;
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
      $fatal(1,"METADATA_HIT_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for(integer trial=0;trial<8;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      saved=stimulus;
      for(integer controls=0;controls<65536;controls++) begin
        stimulus=saved;
        for(integer b=0;b<8;b++) stimulus[W-8+b]=value((controls>>(2*b))&3);
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
    $display("METADATA_HIT_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,default=ROOT)
    parser.add_argument("--reference-root",type=Path)
    parser.add_argument("--reference-ref",default="4885effb")
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    root,out=args.source_root.resolve(),args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    current=(root/SOURCE).read_text()
    original=((args.reference_root.resolve()/SOURCE).read_text() if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, SOURCE, text=True))
    modules=model("reference",original)+model("candidate",current)+support(current)
    connections=",".join(f".{name}({name})" for name in NAMES)
    proof=out/"comparison.sv"
    proof.write_text(modules+f"""module comparison #(parameter integer WAYS=2,WI=(WAYS==1?1:$clog2(WAYS)))(
{PORTS},output logic equivalent);
  logic [WAYS-1:0] expected,actual;
  reference #(.WAYS(WAYS)) u_reference({connections},.observed(expected));
  candidate #(.WAYS(WAYS)) u_candidate({connections},.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles=[]
    for ways in (1,2):
        script,log=out/f"ways{ways}.ys",out/f"ways{ways}.log"
        script.write_text(f"read_slang --top comparison -GWAYS={ways} "+shlex.quote(str(proof))+
            "\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run([sys.executable,ROOT/"scripts/fpga/open_fpga_synth.py","--worker",script],log,root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("元数据命中更新的证明未完成")
        profiles.append(dict(ways=ways,passed=True,log_sha256=digest(log)))
    four=out/"four_state.sv"
    four.write_text(modules+bench())
    run(["iverilog","-g2012","-s","tb","-o",out/"four_state.vvp",four],out/"four_state_compile.log",root)
    run(["vvp",out/"four_state.vvp"],out/"four_state.log",root)
    matched=re.search(r"METADATA_HIT_FOUR_STATE_PASS checks=(\d+)",(out/"four_state.log").read_text())
    if not matched or int(matched[1])!=524504:
        raise RuntimeError("元数据命中更新的四态检查数量不符")
    if current!=(root/SOURCE).read_text():
        raise RuntimeError("控制检查期间生产源码发生变化")
    result=dict(passed=True,actual_rtl_expressions=True,external_inputs_constrained=False,
        source_sha256=digest(root/SOURCE),reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        sat_profiles=profiles,four_state_cases=int(matched[1]),proof_sha256=digest(proof),
        four_state_log_sha256=digest(out/"four_state.log"))
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
