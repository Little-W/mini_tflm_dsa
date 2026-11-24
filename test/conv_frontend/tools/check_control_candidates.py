#!/usr/bin/env python3
"""检查字标签并行比较与流状态候选的全部二态输入及逐位四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from check_request_qualification import control_module

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
DESCRIPTOR = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
STREAM = Path("rtl/npu/conv/conv_im2col_stream.sv")
STREAM_INPUTS = {
    name: 1 for name in (
        "o_chunk_reaches_end", "i_row_last_q", "i_row_base_valid", "i_geometry_tile",
        "i_next_row_padding", "next_row_word_hit", "i_row_coordinate_valid",
        "i_past_active_q", "o_active_after_chunk", "o_group_end_o_equal",
        "i_coordinate_address_valid", "i_next_tap_padding", "i_next_word_o_equal",
        "i_pad_q", "o_request_tap_context", "word_boundary", "stream_request_eligible",
        "row_request_eligible", "i_cache_req_ready")
}
WORD_INPUTS = {"i_row_base_addr": 32, "i_tap_step_bytes": 32, "i_tap_wrap_bytes": 32,
               "i_word_addr": 32, "i_addr": 32, "incoming_q_equal": 1, "i_incoming_tap_wrap": 1}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def section(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def declarations(values, direction=""):
    return [f"{direction}logic" + (f" [{width-1}:0]" if width > 1 else "") + " " + name
            for name, width in values.items()]


def stream_model(current, reference):
    candidate = section(current, "  // 各运行来源先形成目标状态", "\nendmodule")
    previous = section(reference, "  always_comb begin\n    stream_static_state = FETCH;", "\nendmodule")
    fields = ("stream_static_state", "stream_request_selected", "stream_row_selected",
              "stream_tap_selected", "o_stream_advance_state")
    for name in fields:
        previous = re.sub(r"\b" + name + r"\b", "reference_" + name, previous)
    return control_module(current, "conv_im2col_stream_control") + "\nmodule proof(\n" + \
        ",\n".join(declarations(STREAM_INPUTS, "input ") +
                    ["output logic equivalent", "output logic [56:0] actual_value,expected_value"]) + ''');
  import conv_im2col_frontend_pkg::*;
  st_t stream_static_state,stream_accepted_state,o_stream_advance_state;
  st_t reference_stream_static_state,reference_o_stream_advance_state;
  logic stream_read_accepted,stream_request_selected,stream_row_selected,stream_tap_selected;
  logic reference_stream_request_selected,reference_stream_row_selected,reference_stream_tap_selected;
''' + candidate + "\n" + previous + '''
  assign actual_value={stream_tap_selected,stream_row_selected,stream_request_selected,
                       stream_static_state,o_stream_advance_state};
  assign expected_value={reference_stream_tap_selected,reference_stream_row_selected,
                         reference_stream_request_selected,reference_stream_static_state,
                         reference_o_stream_advance_state};
  assign equivalent=actual_value===expected_value;
endmodule
'''


def word_model(current, reference):
    direct_start = "  if (!p_register_descriptor) begin : g_direct_incoming_word"
    direct_end = "  // 七种地址候选"
    actual = section(current, direct_start, direct_end)
    previous = section(reference, direct_start, direct_end)
    for name in ("g_direct_incoming_word", "g_prepared_incoming_word",
                 "o_incoming_word_o_equal", "o_incoming_live_word_o_equal"):
        previous = re.sub(r"\b" + name + r"\b", "reference_" + name, previous)
    address_logic = section(current, "  for (genvar candidate = 0; candidate < 7; candidate++) begin : g_incoming_address",
                            "  for (genvar target = 0; target < 2; target++) begin : g_next_row_match")
    operands = "\n".join(re.search(r"assign\s+"+name+r"\[candidate\]\[base\].*?;",address_logic,re.S).group()
                           for name in ("incoming_address_i_a","incoming_address_i_b"))
    comparison = section(address_logic,"      logic [p_word_shift:0] low_sum;","    end\n    end else")
    # 固定展开两个候选和两个目标，保留生产表达式并避免仿真器的多维生成索引限制。
    choices = []
    for candidate in (0,1):
        choices.append(re.sub(r"\b(candidate|base)\b",lambda match:str(candidate if match[0]=="candidate" else 0),operands))
        for target in (0,1):
            body=re.sub(r"\b(candidate|target)\b",lambda match:str(candidate if match[0]=="candidate" else target),comparison)
            choices.append(f"if(!p_register_descriptor)begin:g_candidate_{candidate}_{target}\n"+body+
                f"end else begin:g_saved_{candidate}_{target}\nassign incoming_candidate_word_match[{candidate}][{target}]=1'b0;\nend\n")
    return control_module(current, "conv_descriptor_match") + '''
module proof #(parameter int p_word_shift=3,parameter bit p_register_descriptor=0)(
''' + ",\n".join(declarations(WORD_INPUTS, "input ") +
                  ["output logic equivalent", "output logic [1:0] actual_value,expected_value"]) + ''');
  logic o_incoming_word_o_equal,o_incoming_live_word_o_equal;
  logic reference_o_incoming_word_o_equal,reference_o_incoming_live_word_o_equal;
  logic [1:0][1:0] incoming_candidate_word_match,unused_incoming_address_carry;
  logic [1:0][1:0][31:0] incoming_address_i_a,incoming_address_i_b,incoming_address_sum;
  wire [31:0] i_row_group_base='0,window_next_addr='0,window_next_group_base='0,i_tap_pair_bytes='0;
''' + actual + "\n" + "\n".join(choices) + "\n" + previous + '''
  assign actual_value={o_incoming_live_word_o_equal,o_incoming_word_o_equal};
  assign expected_value={reference_o_incoming_live_word_o_equal,reference_o_incoming_word_o_equal};
  assign equivalent=actual_value===expected_value;
endmodule
'''


def testbench(inputs, width, parameters, checks):
    bits = sum(inputs.values())
    padded = 32*((bits+31)//32)
    parameter_text = "#(" + ",".join(f".{name}({value})" for name, value in parameters.items()) + ")" \
        if parameters else ""
    return "module tb;\n" + ";\n".join(declarations(inputs)) + ";\n" + f'''
  logic equivalent;
  logic [{width-1}:0] actual_value,expected_value;
  logic [{padded-1}:0] pattern;
  logic [{bits-1}:0] applied,seen_x='0,seen_z='0;
  integer nonzero_results=0;
  proof {parameter_text} dut(.*);
  initial begin
    for(integer sample=0;sample<{checks};sample++)begin
      for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
''' + f'''
      if(sample%3==0)pattern[(sample/3)%{bits}]=1'bx;
      if(sample%5==0)pattern[(sample/5)%{bits}]=1'bz;
''' + "      {" + ",".join(inputs) + "}=pattern;\n" + ('''
      if(sample%8==0)begin i_word_addr=i_row_base_addr;i_addr=i_row_base_addr;incoming_q_equal=1'b1;end
      if(sample%8==1)begin i_word_addr=i_row_base_addr+i_tap_step_bytes;i_addr=i_word_addr;
        incoming_q_equal=1'b0;i_incoming_tap_wrap=1'b0;end
      if(sample%8==2)begin i_word_addr=i_row_base_addr+i_tap_wrap_bytes;i_addr=i_word_addr;
        incoming_q_equal=1'b0;i_incoming_tap_wrap=1'b1;end
''' if inputs == WORD_INPUTS else "") + "      applied={" + ",".join(inputs) + "};\n" + f'''
      for(integer bit_index=0;bit_index<{bits};bit_index++)begin
        if(applied[bit_index]===1'bx)seen_x[bit_index]=1'b1;
        if(applied[bit_index]===1'bz)seen_z[bit_index]=1'b1;
      end
      #1;
      if(equivalent!==1'b1)$fatal(1,"Candidate mismatch sample=%0d actual=%h expected=%h input=%h",
        sample,actual_value,expected_value,applied);
      if(actual_value!=='0)nonzero_results++;
    end
    if(seen_x!=='1||seen_z!=='1)$fatal(1,"Incomplete X/Z coverage x=%0d z=%0d",
      $countones(seen_x),$countones(seen_z));
    if({int(not parameters.get('p_register_descriptor',0))} && nonzero_results<100)
      $fatal(1,"Insufficient nonzero results %0d",nonzero_results);
    $display("CONTROL_CANDIDATES_FOUR_STATE_PASS checks={checks} input_bits={bits} nonzero=%0d",nonzero_results);
    $finish;
  end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root,out=args.source_root.resolve(),args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    paths=[root/DESCRIPTOR,root/STREAM,Path(__file__).resolve(),
           Path(__file__).with_name("check_request_qualification.py")]
    support=[root/"rtl/npu/conv/conv_im2col_frontend_pkg.sv",root/"rtl/common/add_equal.sv",
             root/"rtl/common/parallel_prefix_add.sv",root/"rtl/common/onehot_mux.sv"]
    paths+=support
    hashes={str(path):digest(path) for path in paths}
    references={str(path):read_reference_file(root, args.reference_ref, str(path), text=True) for path in (DESCRIPTOR,STREAM)}
    specifications=[("stream",stream_model((root/STREAM).read_text(),references[str(STREAM)]),
                     STREAM_INPUTS,57,[{}],65536),
                    ("word",word_model((root/DESCRIPTOR).read_text(),references[str(DESCRIPTOR)]),
                     WORD_INPUTS,2,[{"p_word_shift":shift,"p_register_descriptor":registered}
                     for shift in (1,2,3,4) for registered in (0,1)],8192)]
    cases=[]
    for category,model,inputs,width,configurations,checks in specifications:
        generated=out/(category+"_model.sv")
        # 四态模型使用状态枚举的完整位表示，状态常量和表达式保持相同。
        model=model.replace("$bits(st_t)","27").replace("conv_im2col_frontend_pkg::st_t","logic [26:0]")
        model=re.sub(r"\bst_t\b","logic [26:0]",model)
        generated.write_text(model.replace("always_comb","always @*"))
        for index,parameters in enumerate(configurations):
            name=category+str(index)
            formal,log=out/(name+".ys"),out/(name+".formal.log")
            settings=" ".join("-G"+name+"="+str(value) for name,value in parameters.items())
            formal.write_text("read_slang -DSYNTHESIS --top proof "+settings+" "+
                shlex.join(map(str,support+[generated]))+"\nsetattr -mod -unset keep_hierarchy\n"
                "prep -top proof -flatten\ncheck -assert\n"
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log.open("w") as handle:
                subprocess.run([sys.executable,str(ROOT/"scripts/fpga/open_fpga_synth.py"),"--worker",str(formal)],
                    stdout=handle,stderr=subprocess.STDOUT,check=True,timeout=180)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError(str(log))
            bench,binary,build,run=[out/(name+suffix) for suffix in (".sv",".vvp",".build.log",".run.log")]
            bench.write_text(testbench(inputs,width,parameters,checks))
            with build.open("w") as handle:
                subprocess.run([args.iverilog,"-g2012","-s","tb","-o",str(binary),
                    *map(str,support+[generated,bench])],stdout=handle,stderr=subprocess.STDOUT,check=True)
            with run.open("w") as handle:
                subprocess.run([args.vvp,str(binary)],stdout=handle,stderr=subprocess.STDOUT,check=True,timeout=120)
            if "CONTROL_CANDIDATES_FOUR_STATE_PASS" not in run.read_text():
                raise RuntimeError(str(run))
            cases.append(dict(name=name,parameters=parameters,formal_passed=True,four_state_checks=checks,
                input_bits=sum(inputs.values()),all_input_bits_x_z=True,model_sha256=digest(generated),
                formal_log_sha256=digest(log),simulation_log_sha256=digest(run)))
            print("CONTROL_CANDIDATES_PASS",name,flush=True)
    if hashes!={path:digest(path) for path in hashes}:
        raise RuntimeError("检查期间源码发生变化")
    (out/"summary.json").write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        sources_unchanged=True,reference_ref=args.reference_ref,
        reference_sha256={path:hashlib.sha256(source.encode()).hexdigest() for path,source in references.items()},
        inputs_constrained=False,cases=cases),indent=2,ensure_ascii=False)+"\n")


if __name__=="__main__":
    main()
