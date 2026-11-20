#!/usr/bin/env python3
"""验证实际配置寄存、控制器退出和输出完成条件，不约束转置输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def one(pattern,source):
    match=re.search(pattern,source,re.S)
    if match is None:raise ValueError(pattern)
    return match.group(0)+"\n"


def mode_module(top,controller,scheduler):
    cfg_fire=one(r'assign cfg_stage2_fire\s*=.*?;',top)
    is_mode=one(r'wire is_mode\s*=.*?;',top)
    mode_position=top.index("run_is_mode <= 1'b0;")
    begin=top.rfind('        always_ff',0,mode_position)
    end=top.index('\n        wire is_mode',mode_position)
    mode_update=top[begin:end]
    mode_update=re.sub(r'^\s*(?!run_is_mode\b)\w+\s*<=.*?;\s*$', '',mode_update,flags=re.M)
    enum=one(r'typedef enum logic \[3:0\].*?\} state_t;',controller)
    state_transition=one(r'always_comb begin\s*next_state=current_state;.*?endcase\s*end',controller)
    state_transition=state_transition.replace('check_config_valid()','cfg_invalid')
    ready=one(r'assign sa_ready\s*=.*?;',controller).replace('sa_ready','ctrl_sa_ready')
    scheduler_ready=one(r'assign ready\s*=.*?;',scheduler).replace('assign ready','assign frame_scheduler_ready').replace('phase','scheduler_phase').replace('IDLE','4\'d0')
    coalesce=one(r'wire oa_ws_coalesce_pre\s*=.*?;',top)+one(r'wire oa_is_coalesce_pre\s*=.*?;',top)+one(r'wire oa_row_coalesce_pre\s*=.*?;',top)
    complete=one(r'wire exec_oa_complete\s*=.*?;',top)
    return '''module fifo_mode_control_formal # (parameter ENABLE_IS_MODE=1)(
    input logic clk,core_rst_n,cfg_stage2_valid,cfg_mode_s2,
    input logic [2:0] cfg_capacity_phase,
    input logic [3:0] controller_state,scheduler_phase,
    input logic calc_start,cfg_invalid,oa_calc_over,done_ready,
    input logic commit_now,reuse_stationary_now,issue_ia_now,ia_sending_done,
    input logic frame_mode_q,oa_ws_coalesce_q,oa_is_coalesce_q,
    input logic frame_command_active,frame_compute_seen,partial_sum_calc_over,
    input logic frame_store_seen,ps_frame_complete,frame_command_final,
    input logic frame_output_seen,frame_output_armed
);
    logic cfg_stage2_fire,ctrl_sa_ready,frame_scheduler_ready,run_is_mode;
'''+enum+'''
    state_t current_state,next_state;
    assign current_state=state_t'(controller_state);
'''+cfg_fire+is_mode+ready+scheduler_ready+mode_update+state_transition+coalesce+complete+'''
    logic sampled=0, last_reset, last_ready,last_fire,last_mode;
    always_ff @(posedge clk) begin
        sampled<=1;
        last_reset<=core_rst_n;
        last_ready<=ctrl_sa_ready;
        last_fire<=cfg_stage2_fire;
        last_mode<=is_mode;
        if(sampled && last_reset && core_rst_n) begin
            if(!last_ready) assert(is_mode==last_mode);
            if(is_mode!=last_mode) assert(last_fire&&last_ready);
        end
    end
    always_comb begin
        if(cfg_stage2_fire) assert(ctrl_sa_ready&&frame_scheduler_ready);
        if(current_state==INIT || current_state==WEIGHT_START ||
           current_state==IA_START || current_state==IA_WAIT)
            if(next_state==IDLE) assert(oa_calc_over&&done_ready);
        if(frame_mode_q) assert(!oa_row_coalesce_pre);
        if(frame_mode_q&&frame_command_final&&exec_oa_complete)
            assert(frame_output_seen || (frame_output_armed&&oa_calc_over));
    end
endmodule
'''


def writer_module(source):
    header=source[source.index('    input logic clk'):source.index('\n);')]
    ports=[];names=[]
    for line in header.splitlines():
        if line.strip().startswith('input '):
            line=line.strip().rstrip(',')
            ports.append(line)
            names.append(re.findall(r'\b\w+\b',line)[-1])
    return '''module fifo_writer_control_formal #(parameter VLEN=16,DATA_WIDTH=8,REG_WIDTH=32,
    BUS_WIDTH=64,COUNT_WIDTH=12,ENABLE_IS_MODE=1)(\n'''+',\n'.join(ports)+''');
    wire write_done,oa_calc_over;
    oa_writer #(.VLEN(VLEN),.DATA_WIDTH(DATA_WIDTH),.REG_WIDTH(REG_WIDTH),
        .BUS_WIDTH(BUS_WIDTH),.COUNT_WIDTH(COUNT_WIDTH),.ENABLE_IS_MODE(ENABLE_IS_MODE)) u_writer(
'''+',\n'.join('        .'+name+'('+name+')' for name in names)+''',
        .write_done(write_done),.oa_calc_over(oa_calc_over));
    logic sampled=0,last_reset,last_done;
    always_ff @(posedge clk) begin
        sampled<=1;last_reset<=rst_n;last_done<=write_done;
        if(sampled&&last_reset&&rst_n&&oa_calc_over) assert(last_done);
    end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker)));return
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    paths=[ROOT/name for name in ('rtl/npu/top/npu_top.sv','rtl/npu/control/npu_controller.sv',
        'rtl/npu/control/ps_window_scheduler.sv','rtl/npu/writeback/oa_writer.sv')]
    sources=[p.read_text() for p in paths]
    mode=out/'mode.sv';mode.write_text(mode_module(*sources[:3]))
    writer=out/'writer.sv';writer.write_text(writer_module(sources[3]))
    summary={'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'properties':['mode holds while task controller is busy','mode changes only on configuration commit',
        'configuration commit requires both controllers ready','normal execution exits only after output completion',
        'frame execution disables coalescing','final frame waits for output completion',
        'output completion follows a DMA completion event'],'runs':[]}
    cases=[('mode','fifo_mode_control_formal',[mode],'-GENABLE_IS_MODE=1'),
        ('mode_disabled','fifo_mode_control_formal',[mode],'-GENABLE_IS_MODE=0'),
        ('writer','fifo_writer_control_formal',[paths[3],writer],'')]
    for name,top,inputs,options in cases:
        script=out/(name+'.ys')
        script.write_text(f'read_slang --top {top} {options} '+' '.join(map(str,inputs))+
            f'\nprep -top {top} -flatten\nasync2sync\nopt_clean\nchformal -lower\n'+
            'sat -seq 3 -tempinduct -maxsteps 5 -set-init-zero -prove-asserts -verify\n')
        with (out/(name+'.log')).open('w') as stream:
            result=subprocess.run([sys.executable,__file__,'--out',str(out),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT)
        log=(out/(name+'.log')).read_text()
        passed=result.returncode==0 and 'SUCCESS' in log
        summary['runs'].append({'case':name,'passed':passed})
        print(json.dumps(summary['runs'][-1]),flush=True)
        if not passed:raise RuntimeError(log[-9000:])
    summary['passed']=all(item['passed'] for item in summary['runs'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
