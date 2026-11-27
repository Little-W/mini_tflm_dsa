#!/usr/bin/env python3
"""在真实 FIFO 控制中逐周期比较全部输入的四态传播与存储端口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess

from run_formal import ROOT, SOURCE, PROFILES, digest, observed_source

STATE = ('bank_ready', 'ready_bank_count_q', 'active_read_count_q', 'write_bank',
         'read_bank', 'write_ptr', 'read_ptr', 'beat_idx', 'last_beat_idx_q',
         'valid_columns_q', 'stream_active', 'data_valid', 'ram_read_valid_q')
OUTPUTS = ('oa_fifo_req', 'output_valid', 'output_row_switch', 'output_mask',
           'output_data', 'fifo_full_flag', 'formal_write_enable', 'formal_write_address',
           'formal_write_data', 'formal_read_enable', 'formal_read_address', 'formal_bank_counts', 'o_issue_full')


def pair_source():
    text = '''// 比较两份完整时序控制，并记录真实写入、释放和同时读写事件。
module fifo_pair #(
    parameter VLEN=16, BANKS=4, BUS_WIDTH=64, WATERMARK=1, INDEX=0
)(
    input wire logic clk, // 工作时钟。
    input wire logic check_now, // 当前输入和输出已经稳定。
    input wire logic [1099:0] stimulus, // 全部功能输入的独立刺激位。
    output longint unsigned checks=0, // 已完成的状态与端口比较数量。
    output longint unsigned writes=0, // 实际写入数据行数量。
    output longint unsigned releases=0, // 完成输出的银行数量。
    output longint unsigned simultaneous=0, // 同拍完成写入和释放的次数。
    output longint unsigned wraps=0, // 写银行循环推进的次数。
    output longint unsigned blocked=0 // 存储已占用时的输入周期。
);
    wire rst_n=stimulus[1096], in_valid=stimulus[1095], in_tile_done=stimulus[1094];
    wire output_ready=stimulus[1093];
    wire [31:0] reserve_banks=stimulus[1092:1061], threshold=stimulus[1060:1029];
    wire [$clog2(VLEN)-1:0] columns=stimulus[1028:1024];
    wire [VLEN*16-1:0] input_data=stimulus[1023:512], ram_data=stimulus[511:0];
'''
    for label in ('reference', 'current'):
        text += f'''
    fifo_{label} #(.VLEN(VLEN),.BANKS(BANKS),.BUS_WIDTH(BUS_WIDTH),
        .p_precomputed_watermark(WATERMARK)) u_{label}(
        .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_tile_done(in_tile_done),
        .in_vec_s16(input_data),.reserve_banks(reserve_banks),
        .i_ready_bank_threshold(threshold),.vec_valid_num_col(columns),
        .output_ready(output_ready),.formal_ram_data(ram_data),
        .i_full_select(stimulus[1099]),.i_output_pending(stimulus[1098]),.i_other_full(stimulus[1097]));
'''
    text += '    always @(posedge check_now) begin\n'
    for name in (*STATE, *OUTPUTS):
        text += f'''        if(u_current.{name} !== u_reference.{name})
            $fatal(1,"FIFO_S16_STATE profile=%0d field={name}",INDEX);
        checks++;
'''
    for name, expression in {
        'write_bank_blocked_q': 'u_current.bank_ready[u_current.write_bank]',
        'next_write_bank_blocked_q': 'u_current.bank_ready[u_current.next_bank(u_current.write_bank)]',
        'partial_write_q': "(u_current.write_ptr != '0)",
    }.items():
        text += f'''        if(u_current.{name} !== {expression})
            $fatal(1,"FIFO_S16_RELATION profile=%0d field={name}",INDEX);
        checks++;
'''
    text += '''    end
    always @(posedge clk) begin
        if(rst_n === 1'b1) begin
            if(u_current.formal_write_enable === 1'b1) writes++;
            if(u_current.last_row_in_bank === 1'b1) releases++;
            if(u_current.last_row_in_bank === 1'b1 &&
               u_current.finish_write_bank === 1'b1 && u_current.write_bank_blocked === 1'b0)
                simultaneous++;
            if(u_current.finish_write_bank === 1'b1 && u_current.write_bank_blocked === 1'b0 &&
               u_current.write_bank == BANKS-1) wraps++;
            if(in_valid === 1'b1 && u_current.write_bank_blocked === 1'b1) blocked++;
        end
    end
endmodule
'''
    return text


def bench_source(cycles):
    profiles = [(v, b, w, t) for v, b, w in PROFILES for t in (0, 1)]
    text = pair_source()+'''// 包含每个实际输入位的 0、1、X、Z，以及连续输入和随机总线等待。
module tb;
    logic clk=0, check_now=0;
    logic [1099:0] stimulus='0;
    integer seed=261127, coverage[1100][4];
    integer cycle_count=0;
    longint unsigned total_checks=0;
    function automatic logic four(input integer value);
        case(value)
            0:four=1'b0;
            1:four=1'b1;
            2:four=1'bx;
            default:four=1'bz;
        endcase
    endfunction
    task automatic tick;
        #1;check_now=1;#1;check_now=0;
        clk=1;#1;clk=0;#1;check_now=1;#1;check_now=0;
        for(integer bit_index=0;bit_index<1100;bit_index++)begin
            case(stimulus[bit_index])
                1'b0:coverage[bit_index][0]++;
                1'b1:coverage[bit_index][1]++;
                1'bx:coverage[bit_index][2]++;
                1'bz:coverage[bit_index][3]++;
            endcase
        end
        cycle_count++;
    endtask
    task automatic random_binary;
        for(integer first=0;first<1088;first+=32)stimulus[first+:32]=$random(seed);
        stimulus[1099:1088]=12'($random(seed));
    endtask
'''
    for index, (vlen, banks, bus, watermark) in enumerate(profiles):
        text += (f'    fifo_pair #(.VLEN({vlen}),.BANKS({banks}),.BUS_WIDTH({bus}),'
                 f'.WATERMARK({watermark}),.INDEX({index})) u_{index}(.clk,.check_now,.stimulus);\n')
    text += '''    initial begin
        if($bits(stimulus)!=1100)$fatal(1,"FIFO_S16_INPUT_WIDTH");
        for(integer bit_index=0;bit_index<1100;bit_index++)
            for(integer symbol=0;symbol<4;symbol++)coverage[bit_index][symbol]=0;
        #1;clk=1;#1;clk=0;#1;
        for(integer cycle=0;cycle<1024;cycle++)begin
            random_binary();
            stimulus[1096:1094]=3'b111;
            stimulus[1093]=(cycle%3)!=0;
            stimulus[1092:1061]=32'd1;
            stimulus[1060:1029]=32'd3;
            stimulus[1028:1024]=5'd0;
            tick();
        end
'''
    text += f'''        for(integer cycle=0;cycle<{cycles};cycle++)begin
            random_binary();stimulus[1096]=1;
            if(cycle%257==0)stimulus[1096]=0;
            stimulus[1094]=(cycle%11)==0;
            if(cycle%5==0)begin
                for(integer bit_index=0;bit_index<1100;bit_index++)
                    if(($random(seed)&31)==0)stimulus[bit_index]=four($random(seed)&3);
            end
            tick();
        end
'''
    text += '''        for(integer bit_index=0;bit_index<1100;bit_index++)begin
            for(integer symbol=0;symbol<4;symbol++)begin
                random_binary();stimulus[1096:1093]=4'b1111;
                stimulus[bit_index]=four(symbol);tick();
            end
        end
        for(integer bit_index=0;bit_index<1100;bit_index++)
            for(integer symbol=0;symbol<4;symbol++)
                if(coverage[bit_index][symbol]==0)$fatal(1,"FIFO_S16_COVERAGE bit=%0d state=%0d",bit_index,symbol);
'''
    for index, _ in enumerate(profiles):
        text += f'''        if(u_{index}.writes==0 || u_{index}.releases==0 || u_{index}.wraps==0 || u_{index}.blocked==0)
            $fatal(1,"FIFO_S16_EVENTS profile={index}");
        $display("FIFO_S16_PROFILE index={index} checks=%0d writes=%0d releases=%0d simultaneous=%0d wraps=%0d blocked=%0d",
            u_{index}.checks,u_{index}.writes,u_{index}.releases,u_{index}.simultaneous,u_{index}.wraps,u_{index}.blocked);
        total_checks+=u_{index}.checks;
'''
    text += '''        $display("FIFO_S16_FOUR_STATE_PASS cycles=%0d profiles=20 input_bits=1100 symbols_per_bit=4 checks=%0d",cycle_count,total_checks);
        $finish;
    end
endmodule
'''
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference',default='4927debf')
    parser.add_argument('--cycles',type=int,default=8192)
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args();source=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    old=subprocess.check_output(['git','show',args.reference+':'+SOURCE],cwd=source,text=True)
    current=(source/SOURCE).read_text();models=[]
    for label,text in (('reference',old),('current',current)):
        model=out/(label+'.sv')
        model.write_text(observed_source(text).replace('vec_s16_to_fifo','fifo_'+label).replace('always_comb','always @*'))
        models.append(model)
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    common=resolve([source/'rtl/npu/writeback/fifo_bank_watermark.sv',
                    source/'rtl/npu/writeback/fifo_s16_issue_full.sv'],source)
    bench=out/'tb.sv';bench.write_text(bench_source(args.cycles))
    checked=[source/SOURCE,*common,Path(__file__),ROOT/'test/fifo_s16_pressure/run_formal.py']
    hashes={str(path):digest(path) for path in checked}
    commands=[[args.iverilog,'-g2012','-s','tb','-o',str(out/'simulation'),*map(str,models+common+[bench])],
              [args.vvp,str(out/'simulation')]]
    for command,name in zip(commands,('compile.log','run.log')):
        with(out/name).open('w') as stream:
            subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
    text=(out/'run.log').read_text()
    match=re.search(r'FIFO_S16_FOUR_STATE_PASS cycles=(\d+) profiles=(\d+) input_bits=(\d+) symbols_per_bit=(\d+) checks=(\d+)',text)
    if not match or hashes!={str(path):digest(path) for path in checked}:
        raise RuntimeError('完整四态比较或固定源码检查没有完成')
    report=dict(passed=True,source_sha256=hashes,reference_source_sha256=hashlib.sha256(old.encode()).hexdigest(),
                commands=commands,**dict(zip(('cycles','profiles','input_bits','symbols_per_bit','checks'),map(int,match.groups()))),
                events=[line for line in text.splitlines() if line.startswith('FIFO_S16_PROFILE')],
                log_sha256=digest(out/'run.log'))
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
