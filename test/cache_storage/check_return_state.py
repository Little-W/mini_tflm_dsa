#!/usr/bin/env python3
"""证明查询边沿的驻留条件和运行状态与原有元数据、填充状态具有相同周期结果。"""
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
SOURCE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block_body(source, marker):
    start = source.index(marker)
    begin = source.index("begin", start)
    body = source.index("\n", begin) + 1
    depth = 0
    for token in re.finditer(r"\bbegin\b|\bend\b", source[begin:]):
        depth += 1 if token[0] == "begin" else -1
        if depth == 0:
            return source[body:begin + token.start()]
    raise ValueError("未完整提取寄存器更新过程：" + marker)


def proof_source(source):
    tag_state = block_body(source, "end else begin : g_direct_tag_compare")
    activity = block_body(tag_state, "always_ff @(posedge clk or negedge rst_n)")
    tag_state = '''
 logic [WAYS-1:0][31:LB] lookup_tag_raw;
 logic [WAYS-1:0] lookup_valid_next;
 logic [WAYS-1:0][2:0][31:LB] lookup_candidate_tags;
 logic [WAYS-1:0][2:0] lookup_candidate_valid_next;
 logic cache_active_q;
 always_ff @(posedge clk or negedge rst_n)begin
''' + activity + '''
 end
 for(genvar way=0;way<WAYS;way++)begin:g_capture
  logic saved_resident;
  always_ff @(posedge clk)saved_resident<=lookup_valid_next[way];
  assign work_tag_hits[way]=cache_active_q && saved_resident &&
   !(g_saved_fill_match.fill_active_q && fill_way==WI'(way) &&
     g_saved_fill_match.lookup_fill_set_match_q);
  assign demand_tag_hits[way]=cache_active_q && saved_resident &&
   !(g_saved_fill_match.fill_active_q && fill_way==WI'(way) &&
     g_saved_fill_match.lookup_fill_set_match_q);
 end
'''
    fill_state = block_body(source, "if (DEMAND_DEPTH == 1) begin : g_saved_fill_match")
    resident_state = block_body(source, "if (DEMAND_DEPTH == 1) begin : g_direct_lookup")
    return '''module cache_return_state #(
 parameter SETS=16, WAYS=2, LB=7, SI=$clog2(SETS), WI=WAYS>1?$clog2(WAYS):1
)(input logic clk,rst_n,cfg_valid,cfg_ready,select_launch,bypass_launch,fill_success,
 input logic span_req_ready,span_rsp_valid,span_rsp_ready,span_last,bypass_q,req_fire,
 input logic [SI-1:0] lookup_read_set,select_set,
 input logic [3:0][SI-1:0] lookup_candidate_set,
 input logic [WI-1:0] select_way,
 input logic [WAYS-1:0][31:LB] raw_tag,
 input logic [WAYS-1:0] raw_valid,
 input logic [WAYS-1:0][2:0] raw_candidate_valid,
 input logic [31:0] next_address,
 output logic equivalent,four_state_equal,observed);
 localparam DEMAND_DEPTH=1;
 localparam [1:0] F_IDLE=2'd0,F_REQ=2'd1,F_DATA=2'd2;
 logic [1:0] fill_state;
 logic configured,clearing;
 logic [SI-1:0] clear_set,fill_set,lookup_snapshot_set;
 logic [WI-1:0] fill_way;
 logic [WAYS-1:0] saved_valid,reference_work,reference_demand;
 logic [WAYS-1:0] work_tag_hits,demand_tag_hits;
 logic [WAYS-1:0][2:0] candidates_equal,candidates_four_state_equal;
 logic [WAYS-1:0][31:LB] saved_tag;
 typedef struct packed {logic[31:0] address;} request_t;
 request_t work_request,lookup_read_request;
 logic [31:0] demand_addr;
 assign lookup_read_request.address=next_address;
 always_ff @(posedge clk) begin
  work_request<=lookup_read_request;
  saved_tag<=raw_tag;
  if(rst_n && !(cfg_valid && cfg_ready)) saved_valid<=raw_valid;
  if(!rst_n)begin end
  else if(cfg_valid && cfg_ready)begin end
  else lookup_snapshot_set<=lookup_read_set;
  if(fill_state==F_IDLE || fill_success)begin
   fill_set<=bypass_q?SI'(0):select_set;
   fill_way<=bypass_q?WI'(0):select_way;
  end
 end
 always_ff @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin
   fill_state<=F_IDLE;configured<=0;clearing<=0;clear_set<='0;
   demand_addr<='0;observed<=0;
  end else begin
   observed<=1;
   if(cfg_valid && cfg_ready)begin configured<=1;clearing<=1;clear_set<='0;end
   else begin
    if(clearing)begin
     if(clear_set==SI'(SETS-1))clearing<=0;
     else clear_set<=clear_set+1'b1;
    end
    if(req_fire)demand_addr<=work_request.address;
    if(select_launch)fill_state<=F_REQ;
    if(bypass_launch)fill_state<=F_REQ;
    if(fill_state==F_REQ && span_req_ready)fill_state<=F_DATA;
    if(fill_state==F_DATA && span_rsp_valid && span_rsp_ready)
     if(span_last)fill_state<=select_launch?F_REQ:F_IDLE;
   end
  end
 end
 if(1)begin:g_saved_fill_match
''' + fill_state + '''
 end
 if(1)begin:g_direct_tag_compare
''' + tag_state + '''
 end
 for(genvar metadata_way=0;metadata_way<WAYS;metadata_way++)begin:g_metadata_way
  logic lookup_saved_fill_match;
  wire [31:LB] unused_lookup_tag_raw=raw_tag[metadata_way];
  wire lookup_valid_raw=raw_valid[metadata_way];
  wire lookup_valid_saved=saved_valid[metadata_way];
  wire [2:0] lookup_candidate_valid=raw_candidate_valid[metadata_way];
  wire [2:0][31:LB] lookup_candidate_tags={3{raw_tag[metadata_way]}};
  if(1)begin:g_direct_lookup
''' + resident_state + '''
  end
  wire valid_lookup=configured && !clearing && saved_valid[metadata_way] &&
   !(fill_state!=F_IDLE && fill_way==WI'(metadata_way) && fill_set==lookup_snapshot_set);
  assign reference_work[metadata_way]=valid_lookup;
  assign reference_demand[metadata_way]=valid_lookup;
  for(genvar candidate=0;candidate<3;candidate++)begin:g_candidate_reference
   localparam SOURCE=candidate==0?0:candidate+1;
   logic saved_candidate_valid,saved_candidate_resident;
   logic [SI-1:0] saved_candidate_set;
   always_ff @(posedge clk)begin
    saved_candidate_valid<=saved_valid[metadata_way];
    saved_candidate_set<=lookup_snapshot_set;
    if(rst_n && !(cfg_valid && cfg_ready))
     saved_candidate_valid<=raw_candidate_valid[metadata_way][candidate];
    if(!rst_n)begin end
    else if(cfg_valid && cfg_ready)begin end
    else saved_candidate_set<=lookup_candidate_set[SOURCE];
    saved_candidate_resident<=g_direct_tag_compare.lookup_candidate_valid_next[metadata_way][candidate];
   end
   wire reference_candidate=saved_candidate_valid;
   assign candidates_equal[metadata_way][candidate]=
    (g_direct_tag_compare.cache_active_q && saved_candidate_resident)==
    (g_direct_tag_compare.cache_active_q && reference_candidate);
   assign candidates_four_state_equal[metadata_way][candidate]=
    (g_direct_tag_compare.cache_active_q && saved_candidate_resident)===
    (g_direct_tag_compare.cache_active_q && reference_candidate);
  end
 end
 assign equivalent=!observed ||
  ({work_tag_hits,demand_tag_hits}=={reference_work,reference_demand} &&
   g_direct_tag_compare.cache_active_q==(configured && !clearing) && (&candidates_equal));
 assign four_state_equal=
  ({work_tag_hits,demand_tag_hits}==={reference_work,reference_demand}) && (&candidates_four_state_equal);
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source_path = args.source_root.resolve() / SOURCE
    source = source_path.read_text()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    actual = out / "cache_return_state.sv"
    actual.write_text(proof_source(source))
    runs = []
    for sets, ways, line_shift in ((2, 1, 4), (8, 2, 4), (16, 2, 7), (32, 2, 8)):
        name = f"s{sets}_w{ways}_l{line_shift}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text(shlex.join(["read_slang", "--top", "cache_return_state",
            f"-GSETS={sets}", f"-GWAYS={ways}", f"-GLB={line_shift}", str(actual)]) +
            "\nprep -top cache_return_state -flatten\nasync2sync\nopt_clean\n"
            "sat -verify -tempinduct -seq 2 -set-at 1 rst_n 0 -prove equivalent 1\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        assert "Induction step proven: SUCCESS!" in log.read_text()
        runs.append(dict(sets=sets, ways=ways, line_bytes=1 << line_shift,
                         passed=True, log_sha256=digest(log)))
        print("CACHE_RETURN_STATE_PASS", name, flush=True)
    bench = out / "four_state.sv"
    bench.write_text('''module tb;
 logic clk=0,rst_n=0,cfg_valid=0,cfg_ready=1,select_launch=0,bypass_launch=0,fill_success=0;
 logic span_req_ready=0,span_rsp_valid=0,span_rsp_ready=0,span_last=0,bypass_q=0,req_fire=0;
 logic [3:0] lookup_read_set=0,select_set=0;
 logic [15:0] candidate_set_flat='0;
 wire [3:0][3:0] lookup_candidate_set=candidate_set_flat;
 logic [0:0] select_way=0;
 logic [1:0][31:7] raw_tag='0;
 logic [1:0] raw_valid=0;
 logic [5:0] candidate_valid_flat='0;
 wire [1:0][2:0] raw_candidate_valid=candidate_valid_flat;
 logic [31:0] next_address=0;
 wire equivalent,four_state_equal,observed;
 integer checks=0,known_bits=0,unknown_bits=0,hits=0;
 logic [12:0] control;
 logic [31:7] tag_value;
 cache_return_state dut(.*);
 task cycle;
  begin
   #1;clk=1;#1;
   if(four_state_equal!==1'b1)$fatal(1,"Cache return state differs at check %0d",checks);
   for(integer index=0;index<2;index++)begin
    if(dut.work_tag_hits[index]===1'b0 || dut.work_tag_hits[index]===1'b1)known_bits++;
    else unknown_bits++;
    if(dut.work_tag_hits[index]===1'b1)hits++;
   end
   checks++;clk=0;
  end
 endtask
 initial begin
  cycle();rst_n=1;cfg_valid=1;cycle();cfg_valid=0;
  repeat(20)cycle();
  for(integer sample=0;sample<20000;sample++)begin
   control=13'($urandom);
   control[12]=1;control[11]=sample%401==0;control[10]=1;
   if(sample%517==0)control[12]=0;
   if(sample%517==1)control[11]=1;
   if(sample%11==0)control[sample%10]=1'bx;
   if(sample%17==0)control[sample%10]=1'bz;
   {rst_n,cfg_valid,cfg_ready,select_launch,bypass_launch,fill_success,span_req_ready,
    span_rsp_valid,span_rsp_ready,span_last,bypass_q,req_fire}=control[12:1];
   if(sample%331==4)rst_n=1'bx;
   if(sample%337==8)rst_n=1'bz;
   if(sample%347==9)cfg_valid=1'bx;
   if(sample%349==3)cfg_ready=1'bz;
   lookup_read_set=4'($urandom);select_set=4'($urandom);select_way=1'($urandom);
   candidate_set_flat=16'($urandom);candidate_valid_flat=6'($urandom);
   if(sample%29==0)candidate_set_flat[sample%16]=1'bx;
   if(sample%31==0)candidate_valid_flat[sample%6]=1'bz;
   raw_valid=sample%3==0?2'b11:2'($urandom);next_address=$urandom;
   for(integer way=0;way<2;way++)begin
    tag_value=sample%2==0?next_address[31:7]:dut.demand_addr[31:7];
    if(sample%7==0)tag_value[sample%25+7]=1'bx;
    if(sample%13==0)tag_value[sample%25+7]=1'bz;
    raw_tag[way]=tag_value;
   end
   if(sample%19==0)raw_valid[sample%2]=1'bx;
   if(sample%23==0)next_address[sample%32]=1'bz;
   cycle();
  end
  if(hits<100 || unknown_bits==0)$fatal(1,"Insufficient cache state coverage");
  $display("CACHE_RETURN_FOUR_STATE_PASS checks=%0d known_bits=%0d unknown_bits=%0d hits=%0d",
           checks,known_bits,unknown_bits,hits);
  $finish;
 end
endmodule
''')
    with (out / "compile.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(out / "run.vvp"),
                        str(actual), str(bench)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out / "four_state.log").open("w") as stream:
        subprocess.run(["vvp", str(out / "run.vvp")], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=60)
    message = (out / "four_state.log").read_text()
    match = re.search(r"CACHE_RETURN_FOUR_STATE_PASS (.*)", message)
    if match is None:
        raise RuntimeError("缓存返回状态四态检查结果缺失")
    four_state = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", match[1])}
    assert source_path.read_text() == source
    report = dict(passed=True, formal=runs, four_state=four_state, source_sha256=digest(source_path),
                  proof_sha256=digest(actual), test_sha256=digest(Path(__file__)),
                  assumptions="第一个采样边沿复位；后续配置、请求、填充和元数据输入不受限制")
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
