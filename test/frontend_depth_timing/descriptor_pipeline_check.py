#!/usr/bin/env python3
"""从前端实际 RTL 提取容量一准备项，证明捕获、提交、保存与清除关系。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('rtl/npu/conv/conv_im2col_frontend.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment(text,name):
    return re.search(r'\bassign\s+'+re.escape(name)+r'\s*=.*?;',text,re.S).group(0)


def clock_process(text,target):
    position=text.index(target)
    start=text.rfind('always_ff',0,position)
    begin=text.index('begin',start)
    level=0
    for match in re.finditer(r'\bbegin\b|\bend\b',text[begin:]):
        level+=1 if match.group(0)=='begin' else -1
        if not level:
            return text[start:begin+match.end()]
    raise ValueError('时钟过程未闭合')


def proof_source(source):
    state_type=re.search(r'typedef enum logic \[21:0\].*?} st_t;',source,re.S).group(0)
    payload_type=re.search(r'typedef struct packed \{\s*logic invalid, fast, padding, word_hit.*?} prepared_tile_t;',source,re.S).group(0)
    parameters=[]
    for name in ('p_lane_bytes','p_cache_read_bytes','p_cache_read_width','p_word_shift','TILE_COUNT_W','p_saved_group_lanes','COORD_W'):
        parameters.append(re.search(r'localparam int '+name+r'\s*=.*?;',source,re.S).group(0))
    expressions='\n'.join(assignment(source,name) for name in ('cfg_ready','finishing_tile','tile_ready_context','tile_ready','tile_capture','tile_commit'))
    processes=clock_process(source,"if (!rst_n) tile_prepared_valid")+'\n'+clock_process(source,'prepared_tile_q <= preparing_tile;')
    return r'''module descriptor_pipeline_check #(
  parameter int SIZE=16,LANES=8,LINE_BYTES=128,SLOT_W=3,
  parameter bit REGISTER_DESCRIPTOR=1
)(
  input logic clk,rst_n,cfg_valid,tile_valid,wr_valid,wr_ready,wr_last,error,
  input logic configured,pred_busy,pred_cfg_busy,pred_cfg_pending,cache_cfg_pending,
  input logic cache_cfg_ready,cache_hint_pending,
  input logic [1:0] cfg_prepare_phase,address_step_phase,
  input logic [2:0] cfg_idle_group_clear,
  input logic [21:0] state,
  input logic [2047:0] capture_payload,cache_word,buffer_word,
  output logic equivalent,overlap,stalled,clear_pending
);
'''+ '\n'.join(parameters)+'\n'+state_type+'\n'+payload_type+r'''
  prepared_tile_t preparing_tile,prepared_tile_q;
  logic [p_cache_read_width-1:0] cache_rsp_data,word_buf,prepared_word_data;
  logic tile_prepared_valid,tile_capture,tile_commit,tile_ready,tile_ready_context,cfg_ready,finishing_tile;
  assign preparing_tile=capture_payload;
  assign cache_rsp_data=cache_word;
  assign word_buf=buffer_word;
'''+expressions+'\n'+processes+r'''
  logic initialized=0;
  logic [1:0] model_count;
  logic model_written;
  prepared_tile_t model_payload;
  logic [p_cache_read_width-1:0] model_word;
  logic model_ready,model_commit,model_capture,model_context,model_consume;
  logic state_ok,handshake_ok,payload_ok;
  logic previous_pending,previous_commit,previous_capture,previous_clear;
  prepared_tile_t previous_payload;
  logic [p_cache_read_width-1:0] previous_word;
  // 独立事务模型用空闲项数及消费者就绪计算接收条件。
  assign model_context=(state[0] || (wr_valid && wr_ready && wr_last)) &&
    cfg_prepare_phase==0 && configured && !error && !pred_busy && !pred_cfg_busy &&
    !pred_cfg_pending && !cache_cfg_pending && !cache_hint_pending && address_step_phase==0;
  assign model_consume=!error && (state[0] || (wr_valid && wr_ready && wr_last));
  assign model_ready=model_context && !cfg_valid &&
    (!REGISTER_DESCRIPTOR || model_count==0 || model_consume);
  assign model_capture=tile_valid && model_ready;
  assign model_commit=REGISTER_DESCRIPTOR ? model_count!=0 && model_consume : model_capture;

  always_ff @(posedge clk) begin
    if (!rst_n) initialized<=1;
    if (!rst_n || error || (cfg_valid && cfg_ready)) begin
      model_count<=0;
    end else if (REGISTER_DESCRIPTOR) begin
      model_count<=model_count+2'(model_capture)-2'(model_commit);
    end else model_count<=0;
    if (!rst_n) model_written<=0;
    else if (model_capture) model_written<=1;
    if (model_capture) begin
      model_payload<=preparing_tile;
      model_word<=wr_valid && wr_ready && wr_last && state[19] ? cache_rsp_data : word_buf;
    end
    previous_pending<=tile_prepared_valid;
    previous_capture<=tile_capture;
    previous_commit<=tile_commit;
    previous_clear<=!rst_n || error || (cfg_valid && cfg_ready);
    previous_payload<=prepared_tile_q;
    previous_word<=prepared_word_data;
  end

  always_comb begin
    state_ok=model_count<=1 && tile_prepared_valid==(model_count!=0);
    handshake_ok=tile_ready==model_ready && tile_capture==model_capture && tile_commit==model_commit;
    handshake_ok &= !tile_capture || !REGISTER_DESCRIPTOR || !tile_prepared_valid || tile_commit;
    handshake_ok &= !tile_commit || !REGISTER_DESCRIPTOR || tile_prepared_valid;
    handshake_ok &= !cfg_ready || !tile_prepared_valid;
    payload_ok=!model_written || (prepared_tile_q==model_payload && prepared_word_data==model_word);
    if (REGISTER_DESCRIPTOR && tile_commit)
      payload_ok &= model_written && prepared_tile_q==model_payload && prepared_word_data==model_word;
    if (previous_pending && !previous_commit && !previous_clear) begin
      payload_ok &= tile_prepared_valid && prepared_tile_q==previous_payload && prepared_word_data==previous_word;
    end
    if (previous_capture && !previous_clear && REGISTER_DESCRIPTOR) state_ok &= tile_prepared_valid;
    if (previous_clear) state_ok &= !tile_prepared_valid;
    equivalent=!initialized || !rst_n || (state_ok && handshake_ok && payload_ok);
    overlap=initialized && rst_n && tile_capture && tile_commit;
    stalled=initialized && rst_n && tile_prepared_valid && !tile_commit && tile_valid;
    clear_pending=initialized && rst_n && tile_prepared_valid && error;
  end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    source=args.source_root.resolve()/SOURCE
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_hash=digest(source)
    generated=out/'proof.sv';generated.write_text(proof_source(source.read_text()))
    profiles=((2,1,16,1),(16,4,16,1),(16,8,16,1),(16,8,128,1),(64,16,128,1),(16,8,128,0))
    records=[]
    for size,lanes,line,registered in profiles:
        name=f's{size}_w{lanes}_l{line}_r{registered}'
        script=out/(name+'.ys');log=out/(name+'.log')
        common=f'read_slang --top descriptor_pipeline_check -GSIZE={size} -GLANES={lanes} -GLINE_BYTES={line} -GREGISTER_DESCRIPTOR={registered} {shlex.quote(str(generated))}\nprep -top descriptor_pipeline_check -flatten\nasync2sync\ndffunmap\n'
        script.write_text(common+'sat -seq 3 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -verify -show-inputs -show-outputs -dump_vcd '+shlex.quote(str(out/(name+'.vcd')))+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        text=log.read_text()
        if 'Induction step proven: SUCCESS!' not in text:raise RuntimeError('归纳检查未完成 '+name)
        coverage=[]
        if registered:
            for event in ('overlap','stalled','clear_pending'):
                cover_script=out/(name+'_'+event+'.ys');cover_log=out/(name+'_'+event+'.log')
                cover_script.write_text(common+'sat -seq 4 -set-at 1 rst_n 0 -set-at 4 '+event+' 1 -show-inputs -show-outputs\n')
                with cover_log.open('w') as stream:
                    subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(cover_script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
                if 'SAT solving finished - model found:' not in cover_log.read_text():raise RuntimeError('事件覆盖未完成 '+name+' '+event)
                coverage.append(event)
        records.append(dict(SIZE=size,LANES=lanes,LINE_BYTES=line,REGISTER_DESCRIPTOR=registered,passed=True,
                            induction_steps=int(re.findall(r'\[induction step (\d+)\]',text)[-1]),
                            covered_events=coverage,log_sha256=digest(log)))
        print('DESCRIPTOR_PIPELINE_PASS',name,flush=True)
    if digest(source)!=source_hash:raise RuntimeError('检查期间源文件发生变化')
    report=dict(passed=True,source_sha256=source_hash,source_path=str(source),generated_sha256=digest(generated),
                input_assumptions=[],initialization='rst_n=0 only at the first formal step',cases=records,
                scope='Actual capture/commit, valid state, complete captured descriptor and captured word. Upstream arithmetic and final coordinate/live-hit transforms remain outside this storage proof.')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
