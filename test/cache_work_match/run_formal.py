#!/usr/bin/env python3
"""证明缓存工作及需求字地址的保存比较与直接比较一致。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('rtl/npu/dma/cache/conv_read_cache.sv')
DECLARATION='  logic work_word_matches_q, demand_word_matches_q;\n'
UPDATE='''    // 工作请求与预读字地址在同一边沿更新，比较结果同时保存。
    work_word_matches_q <= lookup_read_word == lookup_read_request.address[31:2];
    // 缺失请求仅在工作请求出队时更新，比较使用当前边沿之后的请求地址。
    demand_word_matches_q <= req_fire ? lookup_read_word == work_request.address[31:2] :
        lookup_read_word == demand_addr[31:2];
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='a52df78e')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    current=(ROOT/SOURCE).read_text()
    original=read_rtl_source(args.reference+':'+str(SOURCE), cwd=ROOT, text=True)
    normalized=current.replace(DECLARATION,'',1).replace(UPDATE,'',1).replace(
        '      work_word_matches_q;','      lookup_snapshot_word == work_request.address[31:2];',1).replace(
        '      demand_word_matches_q;', '      lookup_snapshot_word == demand_addr[31:2];', 1)
    assert normalized==original
    assert 'demand_addr<=work_request.address;demand_set<=work_request.set_index;' in current
    assert current.count(DECLARATION)==1 and current.count(UPDATE)==1
    assert '    work_request <= lookup_read_request;\n'+UPDATE in current
    assert '''    if (!rst_n) begin
      lookup_snapshot_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      lookup_snapshot_valid <= 1'b0;
    end else begin
      lookup_snapshot_set <= lookup_read_set;
      lookup_snapshot_word <= lookup_read_word;
''' in current
    proof=out/'proof.sv'
    proof.write_text('''module match_proof (
  input logic clk,rst_n,cfg_valid,cfg_ready,next_snapshot_valid,req_fire,
  input logic [31:2] lookup_read_word,next_work_word,
  output logic equivalent
);
  typedef struct packed {logic [31:0] address;} request_t;
  request_t lookup_read_request,work_request;
  logic [31:2] lookup_snapshot_word;
  logic [31:0] demand_addr;
  logic lookup_snapshot_valid;
  logic observed_reset=1'b0;
'''+DECLARATION+'''  assign lookup_read_request.address={next_work_word,2'b0};
  always_ff @(posedge clk) begin
    work_request<=lookup_read_request;
'''+UPDATE+'''    if(!rst_n) observed_reset<=1'b1;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) demand_addr<=32'b0;
    else if(!(cfg_valid && cfg_ready) && req_fire) demand_addr<=work_request.address;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) lookup_snapshot_valid<=1'b0;
    else if(cfg_valid && cfg_ready) lookup_snapshot_valid<=1'b0;
    else begin
      lookup_snapshot_valid<=next_snapshot_valid;
      lookup_snapshot_word<=lookup_read_word;
    end
  end
  assign equivalent=!observed_reset || !lookup_snapshot_valid ||
    (work_word_matches_q==(lookup_snapshot_word==work_request.address[31:2]) &&
     demand_word_matches_q==(lookup_snapshot_word==demand_addr[31:2]));
endmodule
''')
    script=out/'run.ys';log=out/'formal.log'
    script.write_text('read_slang --top match_proof '+shlex.quote(str(proof))+
        '\nprep -top match_proof -flatten\nasync2sync\nopt_clean\n'+
        'sat -verify -seq 1 -tempinduct -maxsteps 4 -prove equivalent 1\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    assert 'Induction step proven: SUCCESS!' in log.read_text()
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(passed=True,reference=args.reference,source_sha256=digest(ROOT/SOURCE),
        reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        unchanged_outside_saved_word_comparison=True,actual_source_update=True,inputs_constrained=False,
        word_address_bits=30,property='After reset, every valid snapshot has the same saved and direct work-word and demand-word matches',
        proof_sha256=digest(proof),script_sha256=digest(script),log_sha256=digest(log))
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
