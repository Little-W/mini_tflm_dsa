#!/usr/bin/env python3
"""证明配置组位置在分块可接收前完成更新，并与描述符提交保持相同优先级。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/'rtl/npu/conv/conv_im2col_runtime_registers.sv'
    stream=ROOT/'rtl/npu/conv/conv_im2col_stream.sv'
    text=runtime.read_text(); ports=[]
    for line in text.splitlines():
        match=re.match(r'\s*input wire (.+?)\s+(\w+),?\s*//',line)
        if match:ports.append(match.groups())
    derived={'i_cfg_ready','i_cfg_prepare_phase','i_initial_group','i_tile_commit'}
    params={'p_size':16,'p_slot_width':6,'p_count_width':5,'p_chunk_width':5,'p_coord_width':35,
            'p_read_width':128,'p_word_shift':4,'p_row_high_width':27,'p_cache_sets':16,
            'p_cache_ways':2,'p_saved_group_lanes':16,'p_register_descriptor':1,
            'p_prepared_tile_width':561}
    header='module cfg_phase_comparison #(\n'+',\n'.join('parameter int '+k+'='+str(v)for k,v in params.items())+') (\n'
    header+=',\n'.join('input wire '+kind+' '+name for kind,name in ports if name not in derived)
    header+=',\ninput wire logic i_tile_commit_request,\noutput logic o_equivalent\n);\n'
    connections=','.join('.'+name+'('+name+')'for kind,name in ports)
    config_source=stream.read_text();start=config_source.index('  assign cfg_next_group_low =')
    end=config_source.index('  // 描述符提交优先',start)
    calculations=config_source[start:end]
    model=out/'comparison.sv'
    model.write_text(header+'''
localparam int p_prepared_count_w=p_count_width,p_prepared_slot_w=p_slot_width;
localparam int p_prepared_coord_w=p_coord_width;
`include "conv_im2col_prepared_tile.svh"
prepared_tile_t committing;
assign committing=prepared_tile_t'(i_committing_tile);
logic[2:0]i_cfg_prepare_phase;
logic i_cfg_ready,i_tile_commit;
logic[1:0][32:0]i_initial_group,actual_group,reference_group;
logic[2:0][31:0]descriptor_index;
conv_im2col_pkg::conv_cfg_t i_c;
logic[31:0]i_q0;
logic[16:0]cfg_next_group_low,cfg_next_group_high;
logic[32:0]o_cfg_next_group,o_cfg_skip_group;
assign i_q0=descriptor_index[1];
assign i_initial_group={o_cfg_skip_group,o_cfg_next_group};
assign i_cfg_ready=i_cfg_prepare_phase==0;
assign i_tile_commit=i_tile_commit_request&&i_cfg_ready&&!i_cfg_valid;
// 配置阶段顺序与几何模块一致，期间没有描述符提交。
always_ff @(posedge clk or negedge rst_n)begin
 if(!rst_n)i_cfg_prepare_phase<=0;
 else if(i_cfg_valid&&i_cfg_ready)i_cfg_prepare_phase<=1;
 else case(i_cfg_prepare_phase)
  1:i_cfg_prepare_phase<=2;2:i_cfg_prepare_phase<=3;
  3:i_cfg_prepare_phase<=4;4:i_cfg_prepare_phase<=0;
  default:;
 endcase
end
// 独立参考在配置接收时保存完整数学结果，描述符提交更新同一组字段。
always_ff @(posedge clk or negedge rst_n)begin
 if(!rst_n)reference_group<='0;
 else if(i_cfg_valid&&i_cfg_ready)begin
  reference_group[0]<={1'b0,i_q0}+{17'd0,i_cfg.group_c};
  reference_group[1]<={1'b0,i_q0}+{16'd0,i_cfg.group_c,1'b0};
 end else if(i_tile_commit&&!committing.invalid)
  reference_group<={committing.skip_group,committing.next_group};
end
'''+calculations+'\nconv_im2col_runtime_registers #(\n'+
       ','.join('.'+name+'('+name+')'for name in params)+') u_actual(\n'+connections+
       ',.o_configuration(i_c),.o_descriptor_index(descriptor_index),.o_group_advance(actual_group));\n'+
       'assign o_equivalent=(i_cfg_prepare_phase==1)||actual_group==reference_group;\nendmodule\n')
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources=resolver['with_dependencies']([runtime,model],ROOT)
    files=resolver['input_files']([*sources,stream],ROOT)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in files if p.is_relative_to(ROOT)}
    script,log=out/'induction.ys',out/'induction.log'
    script.write_text(shlex.join(['read_slang','--top','cfg_phase_comparison','-DSYNTHESIS=1',
                       '-I'+str(ROOT/'include'),*map(str,sources)])+
                       '\nprep -top cfg_phase_comparison -flatten\nasync2sync\nopt_clean\ndffunmap\n'+
                       'sat -verify -seq 2 -tempinduct -maxsteps 8 -set-init-zero -prove o_equivalent 1\n')
    with log.open('w')as output:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       stdout=output,stderr=subprocess.STDOUT,check=True,timeout=240)
    if 'SUCCESS!' not in log.read_text():raise RuntimeError('配置阶段组位置归纳证明未完成')
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=value for name,value in hashes.items()):
        raise RuntimeError('验证期间配置阶段源码发生变化')
    report={'passed':True,'unbounded_induction':True,'scope':'阶段1暂停接收描述符，阶段2至下一次配置接收前的完整组位置相同',
            'source_sha256':hashes,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('CFG_PHASE_INDUCTION_PASS',flush=True)


if __name__=='__main__':main()
