#!/usr/bin/env python3
"""检查实际输出预留寄存器的配置消费周期及偏置行状态组合表达式。"""
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
TOP = Path('rtl/npu/top/npu_top.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def reserve_model(source, name):
    phase = section(source, '        assign cfg_stage2_fire =',
                    '        // 配置阶段用独立的 16 位部分乘积')
    state = section(source, '        logic [IS_BIAS_VALID_W-1:0] is_bias_group_rows_target;',
                    '        wire is_mode =')
    reset, capture = state.split('end else if (cfg_stage2_fire) begin')
    names = {'ia_reuse_num_eff', 'output_reserve_banks', 'output_reserve_with_extra'}

    def assignments(text):
        return '\n'.join(match[0] for match in re.finditer(r'\b(\w+)\s*<=\s*.*?;', text, re.S)
                         if match[1] in names)

    calculation = section(source, '        assign output_reserve_i_a =',
                          '        wire [31:0] exec_stream_k =')
    direct = re.search(r'    assign direct_final_stream=.*?;', source, re.S)[0]
    if not re.search(r"3'd3:\s*begin\s*direct_output_cfg<=", source):
        raise ValueError('需要核对直接输出资格的实际保存阶段')
    for marker in ('cfg_stage1_valid && !cfg_stage2_valid',
                   'frame_mode_q <= use_frame_commands_s2;'):
        if marker not in source:
            raise ValueError('需要核对配置字段的实际保存条件：' + marker)
    return f'''module {name} #(parameter int REG_WIDTH=32,SIZE=16)(
    input logic clk,core_rst_n,i_load,ctrl_sa_ready,frame_scheduler_ready,
    input logic [REG_WIDTH-1:0] i_reuse,
    input logic i_direct,i_frame,
    output logic cfg_stage2_valid,
    output wire cfg_stage2_fire,
    output logic [2:0] cfg_capacity_phase,
    output wire [31:0] o_reserve,
    output logic frame_mode_q
);
    localparam int DIRECT_OUTPUT_EXTRA_BANKS=(SIZE-1+1+12+SIZE-1)/SIZE;
    logic [REG_WIDTH-1:0] cfg_ia_reuse_eff_s2,ia_reuse_num_eff;
    logic direct_output_cfg,use_frame_commands_s2;
    logic [31:0] output_reserve_banks,output_reserve_with_extra,output_reserve_calc;
    logic [31:0] output_reserve_i_a,output_reserve_i_b;
    logic output_reserve_i_carry,output_reserve_o_carry;
    wire direct_final_stream;
{phase}
{calculation}
{direct}
    // 未改变的资格计算用任意一位结果表示，保存阶段与实际源码一致。
    always_ff @(posedge clk or negedge core_rst_n) begin
        if(!core_rst_n) begin
            cfg_stage2_valid<=1'b0;
            cfg_ia_reuse_eff_s2<=REG_WIDTH'(1);
            direct_output_cfg<=1'b0;
            use_frame_commands_s2<=1'b0;
            frame_mode_q<=1'b0;
        end else begin
            if(cfg_stage2_fire) begin
                cfg_stage2_valid<=1'b0;
                frame_mode_q<=use_frame_commands_s2;
            end
            if(!cfg_stage2_valid && i_load) begin
                cfg_stage2_valid<=1'b1;
                cfg_ia_reuse_eff_s2<=i_reuse;
            end
            if(cfg_stage2_valid && cfg_capacity_phase==3'd2)
                use_frame_commands_s2<=i_frame;
            if(cfg_stage2_valid && cfg_capacity_phase==3'd3)
                direct_output_cfg<=i_direct;
        end
    end
    always_ff @(posedge clk or negedge core_rst_n) begin
        if(!core_rst_n) begin
{assignments(reset)}
        end else if(cfg_stage2_fire) begin
{assignments(capture)}
        end
    end
    assign o_reserve=output_reserve_banks;
endmodule
'''


def row_model(source, name):
    first = '        logic [IS_BIAS_ROW_W-1:0] is_bias_row_increment;'
    body = section(source, first, '        always_ff @(posedge clk or negedge core_rst_n)')
    return f'''module {name} #(parameter int IS_BIAS_ROW_W=5,
    IS_BIAS_VALID_W=IS_BIAS_ROW_W+1)(
    input logic [IS_BIAS_ROW_W-1:0] is_bias_row_idx,
    input logic [IS_BIAS_VALID_W-1:0] is_bias_rows_valid,
    input logic is_mode,acc_data_valid,init_cfg_ia,send_ia_trigger,bias_sleep,
    output wire [IS_BIAS_ROW_W-1:0] o_next
);
{body}
    assign o_next=is_bias_row_next;
endmodule
'''


def run(script, log):
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)


def four_state(out, files):
    instances=[]
    profiles=((1,4),(8,8),(16,16),(32,16),(32,32))
    for i,(width,size) in enumerate(profiles):
        for label,prefix in (('reference','r'),('candidate','c')):
            instances.append(f'''    {label} #(.REG_WIDTH({width}),.SIZE({size})) {prefix}{i}(
        .clk,.core_rst_n,.i_load,.ctrl_sa_ready,.frame_scheduler_ready,
        .i_reuse(reuse[{width-1}:0]),.i_direct,.i_frame,
        .cfg_stage2_valid({prefix}v[{i}]),.cfg_stage2_fire({prefix}f[{i}]),
        .cfg_capacity_phase({prefix}p[{i}]),.o_reserve({prefix}r[{i}]),
        .frame_mode_q({prefix}m[{i}]));''')
    for i,width in enumerate((1,2,4,5,6,8)):
        for label,prefix in (('reference','r'),('candidate','c')):
            instances.append(f'''    {label}_row #(.IS_BIAS_ROW_W({width})) {prefix}row{i}(
        .is_bias_row_idx(row[{width-1}:0]),.is_bias_rows_valid(rows_valid[{width}:0]),
        .is_mode(controls[0]),.acc_data_valid(controls[1]),.init_cfg_ia(controls[2]),
        .send_ia_trigger(controls[3]),.bias_sleep(controls[4]),
        .o_next({prefix}row[{i}][{width-1}:0]));''')
            if width<8:
                instances.append(f"    assign {prefix}row[{i}][7:{width}]='0;")
    bench=out/'four_state.sv'
    bench.write_text('''module tb;
    reg clk,core_rst_n,i_load,ctrl_sa_ready,frame_scheduler_ready,i_direct,i_frame;
    reg [31:0] reuse;reg [7:0] row;reg [8:0] rows_valid;reg [4:0] controls;
    wire [4:0] rv,cv,rf,cf,rm,cm;wire [2:0] rp[5],cp[5];
    wire [31:0] rr[5],cr[5];wire [7:0] rrow[6],crow[6];
    integer reserve_checks=0,row_checks=0,submissions=0,code;
'''+'\n'.join(instances)+'''
    initial begin
        clk=0;core_rst_n=0;i_load=0;ctrl_sa_ready=0;frame_scheduler_ready=0;
        reuse=0;i_direct=0;i_frame=0;row=0;rows_valid=0;controls=0;
        #1;clk=1;#1;clk=0;
        for(integer sample=0;sample<20000;sample++)begin
            core_rst_n=(sample%173)!=0;i_load=($urandom%4)!=0;
            ctrl_sa_ready=($urandom%3)!=0;frame_scheduler_ready=($urandom%5)!=0;
            reuse=$urandom;i_direct=$urandom;i_frame=$urandom;
            case(sample%8)
                0:reuse='0;
                1:reuse='1;
                2:reuse[sample%32]=1'bx;
                3:reuse[sample%32]=1'bz;
                4:i_direct=1'bx;
                5:i_direct=1'bz;
                6:i_frame=1'bx;
                7:i_frame=1'bz;
            endcase
            row=$urandom;rows_valid=$urandom;code=sample%1024;
            for(integer bit_i=0;bit_i<5;bit_i++)begin
                case(code%4)
                    0:controls[bit_i]=1'b0;
                    1:controls[bit_i]=1'b1;
                    2:controls[bit_i]=1'bx;
                    3:controls[bit_i]=1'bz;
                endcase
                code=code/4;
            end
            case(sample%6)
                0:row[sample%8]=1'bx;
                1:row[sample%8]=1'bz;
                2:rows_valid[sample%9]=1'bx;
                3:rows_valid[sample%9]=1'bz;
                4:begin row='0;rows_valid='0;end
                5:begin row='1;rows_valid='1;end
            endcase
            #1;
            for(integer i=0;i<6;i++)begin
                if(rrow[i]!==crow[i])$fatal(1,"Row propagation differs sample=%0d profile=%0d",sample,i);
                row_checks++;
            end
            if(rf[0])submissions++;
            clk=1;#1;
            if(core_rst_n)for(integer i=0;i<5;i++)begin
                if({rv[i],rf[i],rp[i],rm[i]}!=={cv[i],cf[i],cp[i],cm[i]})
                    $fatal(1,"Configuration cycle differs sample=%0d profile=%0d",sample,i);
                if(!cv[i])begin
                    if(rr[i]!==cr[i])$fatal(1,"Reserve propagation differs sample=%0d profile=%0d",sample,i);
                    reserve_checks++;
                end
            end
            clk=0;#1;
        end
        $display("OUTPUT_CONTROL_FOUR_STATE_PASS reserve_checks=%0d row_checks=%0d submissions=%0d",
            reserve_checks,row_checks,submissions);$finish;
    end
endmodule
''')
    with (out/'four_state_compile.log').open('w') as stream:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(out/'four_state_sim'),
                        *map(str,files),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True)
    result=subprocess.run(['vvp',str(out/'four_state_sim')],capture_output=True,text=True,check=True)
    log=out/'four_state.log';log.write_text(result.stdout+result.stderr)
    match=re.search(r'OUTPUT_CONTROL_FOUR_STATE_PASS reserve_checks=(\d+) row_checks=(\d+) submissions=(\d+)',result.stdout)
    if not match:
        raise RuntimeError('四态检查未完成')
    return {'passed':True,'cycles':20000,'reserve_checks':int(match[1]),
            'row_checks':int(match[2]),'submissions':int(match[3]),
            'strict_case_equality':True,'bench_sha256':digest(bench),'log_sha256':digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-ref', default='aa0a169c')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    reference=(str(args.reference_root.resolve()) if args.reference_root else
               subprocess.check_output(['git','rev-parse',args.reference_ref],cwd=ROOT,text=True).strip())
    reference_path=args.reference_root.resolve()/TOP if args.reference_root else out/'reference_input.sv'
    if not args.reference_root:
        reference_path.write_bytes(subprocess.check_output(['git','show',f'{reference}:{TOP}'],cwd=ROOT))
    paths={'reference':reference_path,
           'candidate':args.source_root.resolve()/TOP,
           'helper':ROOT/HELPER}
    hashes={k:digest(v) for k,v in paths.items()}
    files=[]
    for label in ('reference','candidate'):
        source=paths[label].read_text()
        target=out/(label+'.sv')
        target.write_text(reserve_model(source,label)+'\n'+row_model(source,label+'_row'))
        files.append(target)
    harness=out/'formal.sv'
    harness.write_text('''module reserve_formal #(parameter int REG_WIDTH=32,SIZE=16)(
    input wire clk,core_rst_n,i_load,ctrl_sa_ready,frame_scheduler_ready,
    input wire [REG_WIDTH-1:0] i_reuse,input wire i_direct,i_frame,output wire bad);
    wire rv,cv,rf,cf,rm,cm;wire [2:0] rp,cp;wire [31:0] rr,cr;
    reference #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) r(.*,.cfg_stage2_valid(rv),
        .cfg_stage2_fire(rf),.cfg_capacity_phase(rp),.o_reserve(rr),.frame_mode_q(rm));
    candidate #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) c(.*,.cfg_stage2_valid(cv),
        .cfg_stage2_fire(cf),.cfg_capacity_phase(cp),.o_reserve(cr),.frame_mode_q(cm));
    assign bad=core_rst_n && ({rv,rf,rp,rm}!={cv,cf,cp,cm} || (!cv && rr!=cr));
endmodule
module row_formal #(parameter int IS_BIAS_ROW_W=5,IS_BIAS_VALID_W=IS_BIAS_ROW_W+1)(
    input wire [IS_BIAS_ROW_W-1:0] is_bias_row_idx,
    input wire [IS_BIAS_VALID_W-1:0] is_bias_rows_valid,
    input wire is_mode,acc_data_valid,init_cfg_ia,send_ia_trigger,bias_sleep,
    output wire correct);
    wire [IS_BIAS_ROW_W-1:0] r,c;
    reference_row #(.IS_BIAS_ROW_W(IS_BIAS_ROW_W),.IS_BIAS_VALID_W(IS_BIAS_VALID_W))
        u_reference(.*,.o_next(r));
    candidate_row #(.IS_BIAS_ROW_W(IS_BIAS_ROW_W),.IS_BIAS_VALID_W(IS_BIAS_VALID_W))
        u_candidate(.*,.o_next(c));
    assign correct=r==c;
endmodule
''')
    files += [harness,paths['helper']]
    report={'passed':False,'reference':reference,'source_sha256':hashes,'reserve_profiles':[],'row_profiles':[],
            'scope':'实际配置相位、预留计数计算和寄存赋值；比较配置提交后的预留值及全部相位和启动周期；偏置行状态比较覆盖全部组合输入',
            'qualifications':'相位二和三保存的帧资格、直接输出资格为任意输入值；计算表达式保持原样',
            'reset':'首周期复位，之后复位、背压及配置输入均任意'}
    for width,size in ((1,4),(8,8),(16,16),(32,16),(32,32)):
        script=out/f'reserve_w{width}_s{size}.ys';log=script.with_suffix('.log')
        script.write_text('read_slang --top reserve_formal '+
            f'-GREG_WIDTH={width} -GSIZE={size} '+shlex.join(map(str,files))+
            '\nprep -top reserve_formal -flatten\nasync2sync\nopt -full\n'+
            'sat -seq 2 -tempinduct -maxsteps 12 -set-at 1 core_rst_n 0 '
            '-prove bad 0 -verify -timeout 120\n')
        run(script,log)
        assert 'Induction step proven: SUCCESS!' in log.read_text()
        report['reserve_profiles'].append({'REG_WIDTH':width,'SIZE':size,'passed':True,
            'script_sha256':digest(script),'log_sha256':digest(log)})
    for width in (1,2,4,5,6,8):
        script=out/f'row_w{width}.ys';log=script.with_suffix('.log')
        script.write_text('read_slang --top row_formal '+f'-GIS_BIAS_ROW_W={width} '+
            shlex.join(map(str,files))+'\nprep -top row_formal -flatten\n'+
            'sat -prove correct 1 -verify -show-inputs -show-outputs\n')
        run(script,log)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        report['row_profiles'].append({'row_width':width,'valid_width':width+1,'passed':True,
            'script_sha256':digest(script),'log_sha256':digest(log)})
    report['four_state']=four_state(out,files)
    assert hashes=={k:digest(v) for k,v in paths.items()}
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'reserve_profiles':5,'row_profiles':6}))


if __name__=='__main__':
    main()
