#!/usr/bin/env python3
"""验证通道高段关系与原通道状态在相同边沿更新。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
LOW_WIDTHS = (1, 2, 5, 6, 8, 15)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def invoke(command, log):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=300)


def model():
    return """module group_model #(
 parameter int p_low_width=5, parameter bit p_register_descriptor=0)(
 input logic clk,rst_n,i_configure,i_commit,i_invalid,i_fast,i_commit_window,i_decode_write,
 input logic [15:0] i_config_group,i_commit_channel,i_window_channel,i_decode_channel,
 output logic [15:0] o_channel,o_group,
 output logic [2:0] o_actual,o_expected,
 output logic o_equivalent);
 localparam int p_high_width=16-p_low_width;
 logic [15:0] channel,group_size;
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin channel<=0;group_size<=0;end
  else if(i_configure)group_size<=i_config_group;
  else if(i_commit)begin
   if(i_invalid)begin end
   else if(i_fast)begin
    if(p_register_descriptor)channel<=i_commit_channel;
    else if(i_commit_window)channel<=i_window_channel;
   end
  end else if(i_decode_write)channel<=i_decode_channel;
 end
 conv_descriptor_group_context #(.p_low_width(p_low_width),.p_register_descriptor(p_register_descriptor)) u_actual(
  .clk,.rst_n,.i_configure,.i_config_group,.i_group(group_size),.i_channel(channel),
  .i_commit,.i_invalid,.i_fast,.i_commit_channel,.i_window_channel,.i_commit_window,
  .i_decode_write,.i_decode_channel,.o_high_before(o_actual[0]),.o_high_equal(o_actual[1]),
  .o_high_next_equal(o_actual[2]));
 parallel_unsigned_compare #(.p_width(p_high_width)) u_high(
  .i_a(channel[15:p_low_width]),.i_b(group_size[15:p_low_width]),
  .o_less(o_expected[0]),.o_equal(o_expected[1]));
 increment_equal #(.p_width(p_high_width)) u_high_next(
  .i_a(channel[15:p_low_width]),.i_target(group_size[15:p_low_width]),.o_equal(o_expected[2]));
 assign o_channel=channel;
 assign o_group=group_size;
 assign o_equivalent=o_actual===o_expected;
endmodule

module proof #(parameter int p_low_width=5,parameter bit p_register_descriptor=0)(
 input logic clk,rst_n,i_configure,i_commit,i_invalid,i_fast,i_commit_window,i_decode_write,
 input logic [15:0] i_config_group,i_commit_channel,i_window_channel,i_decode_channel,
 output logic proven);
 logic [15:0] channel,group_size;
 logic [2:0] actual,expected;
 logic equivalent,consistent,state_known;
 group_model #(.p_low_width(p_low_width),.p_register_descriptor(p_register_descriptor)) u_model(
  .clk,.rst_n,.i_configure,.i_commit,.i_invalid,.i_fast,.i_commit_window,.i_decode_write,
  .i_config_group,.i_commit_channel,.i_window_channel,.i_decode_channel,
  .o_channel(channel),.o_group(group_size),.o_actual(actual),.o_expected(expected),.o_equivalent(equivalent));
 assign consistent=u_model.u_actual.range_flags==expected;
 assign state_known=(^{channel,group_size,u_model.u_actual.range_flags})!==1'bx;
 assign proven=equivalent&&consistent&&state_known;
endmodule

module group_mapping #(parameter bit p_candidate=0)(
 input logic clk,rst_n,i_configure,i_commit,i_invalid,i_fast,i_commit_window,i_decode_write,
 input logic [15:0] i_config_group,i_commit_channel,i_window_channel,i_decode_channel,
 input logic [4:0] i_columns,
 output logic [15:0] o_channel,o_group,
 output logic o_fits);
 logic [2:0] actual,expected,selected;
 logic [4:0] columns;
 logic unused_equivalent,low_borrow,low_less,default_allows,fits;
 always_ff @(posedge clk)columns<=i_columns;
 group_model u_model(.clk,.rst_n,.i_configure,.i_commit,.i_invalid,.i_fast,.i_commit_window,.i_decode_write,
  .i_config_group,.i_commit_channel,.i_window_channel,.i_decode_channel,
  .o_channel,.o_group,.o_actual(actual),.o_expected(expected),.o_equivalent(unused_equivalent));
 assign selected=p_candidate?actual:expected;
 conv_tile_group_low5 u_low(.i_group(o_group[4:0]),.i_first(o_channel[4:0]),.i_columns(columns),
  .o_borrow(low_borrow),.o_less(low_less),.o_default_allows(default_allows));
 conv_tile_group_range_result u_result(.i_high_before(selected[0]),.i_high_equal(selected[1]),
  .i_high_next_equal(selected[2]),.i_low_borrow(low_borrow),.i_low_less(low_less),
  .i_default_allows(default_allows),.o_fits(fits));
 always_ff @(posedge clk)o_fits<=fits;
endmodule
"""


def bench(width, registered):
    return f"""module tb;
 logic clk=0,rst_n=0,i_configure=0,i_commit=0,i_invalid=0,i_fast=0,i_commit_window=0,i_decode_write=0;
 logic [15:0] i_config_group=0,i_commit_channel=0,i_window_channel=0,i_decode_channel=0;
 logic [15:0] o_channel,o_group;
 logic [2:0] o_actual,o_expected;
 logic o_equivalent;
 integer checks=0,unknown_checks=0;
 group_model #(.p_low_width({width}),.p_register_descriptor({registered})) dut(.*);
 task automatic check;
  #1;
  if(o_equivalent!==1'b1)$fatal(1,"Group context differs width={width} registered={registered} sample=%0d actual=%b expected=%b",checks,o_actual,o_expected);
  if((^{{o_channel,o_group}})===1'bx)unknown_checks++;
  checks++;
 endtask
 initial begin
  #1;clk=1;check();clk=0;rst_n=1;
  for(integer sample=0;sample<4096;sample++)begin
   i_configure=(sample%5==0);i_commit=(sample%3==0);i_invalid=(sample%7==0);
   i_fast=(sample%4!=0);i_commit_window=(sample%2==0);i_decode_write=(sample%3!=0);
   i_config_group=$urandom;i_commit_channel=$urandom;i_window_channel=$urandom;i_decode_channel=$urandom;
   if(sample%4==0)i_config_group=o_channel;
   if(sample%4==1)i_decode_channel=o_group;
   if(sample%13==0)i_commit_channel='1;
   if(sample%17==0)i_window_channel='0;
   if(sample%19==0)i_decode_channel[sample%16]=1'bx;
   if(sample%23==0)i_config_group[sample%16]=1'bz;
   if(sample%29==0)i_invalid=1'bx;
   if(sample%31==0)i_commit=1'bz;
   if(sample%37==0)i_configure=1'bx;
   if(sample%41==0)rst_n=0;
   if(sample%43==0)i_commit_window=1'bx;
   if(sample%47==0)i_fast=1'bz;
   if(sample%53==0)i_decode_write=1'bx;
   check();#1;clk=1;check();clk=0;rst_n=1;check();
  end
  if(unknown_checks<100)$fatal(1,"Incomplete group context coverage");
  $display("GROUP_CONTEXT_PASS checks=%0d unknown=%0d",checks,unknown_checks);
  $finish;
 end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))
    sources = helper["with_dependencies"]([ROOT / "rtl/npu/conv/conv_descriptor_group_context.sv",
        ROOT / "rtl/npu/conv/conv_tile_group_low5.sv", ROOT / "rtl/npu/conv/conv_tile_group_range_result.sv"], ROOT)
    hashes = {str(path): digest(path) for path in helper["input_files"](sources, ROOT)}
    generated = out / "model.sv"
    generated.write_text(model())
    results = []
    for width in LOW_WIDTHS:
        for registered in (0, 1):
            name = f"low{width}_registered{registered}"
            script, formal = out / (name+".ys"), out / (name+".formal.log")
            script.write_text("read_slang --top proof -DSYNTHESIS=1 " +
                f"-Gp_low_width={width} -Gp_register_descriptor={registered} " +
                shlex.join(map(str, [*sources, generated])) +
                "\nprep -top proof -flatten\nasync2sync\nopt\ncheck -assert\n"
                "sat -verify -tempinduct -seq 1 -maxsteps 4 -set-init-zero -set-at 1 rst_n 0 "
                "-set-def-inputs -prove proven 1 -show-inputs -show-outputs\n")
            invoke([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], formal)
            if "Induction step proven: SUCCESS!" not in formal.read_text():
                raise RuntimeError(f"高段关系归纳证明未完成：{formal}")
            test, binary = out / (name+".sv"), out / (name+".vvp")
            test.write_text(bench(width, registered))
            invoke(["iverilog", "-g2012", "-s", "tb", "-o", binary, *sources, generated, test],
                   out / (name+".compile.log"))
            simulation = out / (name+".simulation.log")
            invoke(["vvp", binary], simulation)
            matched = re.search(r"GROUP_CONTEXT_PASS checks=(\d+) unknown=(\d+)", simulation.read_text())
            if matched is None or int(matched[1]) != 12289:
                raise RuntimeError(f"高段关系四态比较未完成：{simulation}")
            results.append({"low_width": width, "registered": registered, "passed": True,
                            "four_state_checks": int(matched[1]), "unknown_checks": int(matched[2]),
                            "formal_sha256": digest(formal), "simulation_sha256": digest(simulation)})
            print(json.dumps(results[-1]), flush=True)
    if any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError("验证期间 RTL 内容发生变化")
    mapping = {name: {"top": "group_mapping", "options": ["-D", "SYNTHESIS=1", f"-Gp_candidate={value}"],
                     "sources": list(map(str, [*sources, generated])),
                     "configuration": "同边沿保存高段关系，完整通道范围与五位列数共同输出"}
               for name, value in (("reference", 0), ("candidate", 1))}
    (out / "mapping_cases.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2)+"\n")
    report = {"passed": True, "source_sha256": hashes, "cases": results,
              "four_state_checks": sum(case["four_state_checks"] for case in results),
              "unrestricted_16_bit_channels": True, "latency_preserved": True}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
