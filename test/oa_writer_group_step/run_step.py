#!/usr/bin/env python3
"""比较实际 RTL 中的组步长表达式及其保持、复位和四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/oa_writer.sv')
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from rtl_reference import read_rtl_source
from open_fpga_synth import run_stage


def extract(text, name):
    declarations = '\n'.join(line for line in text.splitlines() if any(
        word in line for word in (
            'logic [REG_WIDTH-1:0] init_group_step_25;',
            'logic [6:0] init_group_factor;',
            'logic [REG_WIDTH-1:0] init_group_product;',
            'logic [2:0] init_group_shift;',
            'logic init_group_by_25;')))
    helper = text[text.index('    assign init_group_step_25 ='):text.index('    assign row_group_next_sum =')]
    start = text.index("        init_group_shift = '0;")
    body = text[start:text.index('`ifdef SYNTHESIS', start)]
    return f'''module {name} #(
    parameter integer REG_WIDTH=32, COUNT_WIDTH=29
) (
    input logic clk, rst_n, enable,
    input logic [REG_WIDTH-1:0] row_addr_step_cur,
    input logic [COUNT_WIDTH-1:0] cfg_ia_reuse_num,
    output logic [REG_WIDTH-1:0] group_row_addr_step_cur
);
    localparam integer CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
    typedef logic [CNT_W-1:0] count_t;
    logic [REG_WIDTH-1:0] init_group_row_addr_step;
'''+declarations+'\n'+helper+'\n    always_comb begin\n'+body+'''    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) group_row_addr_step_cur <= '0;
        else if (enable) group_row_addr_step_cur <= init_group_row_addr_step;
    end
endmodule
'''


def bench(width, count):
    return f'''module tb;
    localparam integer REG_WIDTH={width}, COUNT_WIDTH={count};
    logic clk=0, rst_n=0, enable=0;
    logic [REG_WIDTH-1:0] row_addr_step_cur='0;
    logic [COUNT_WIDTH-1:0] cfg_ia_reuse_num='0;
    wire [REG_WIDTH-1:0] actual, expected;
    writer_step_current #(.REG_WIDTH(REG_WIDTH), .COUNT_WIDTH(COUNT_WIDTH)) dut(
        .group_row_addr_step_cur(actual), .*);
    writer_step_reference #(.REG_WIDTH(REG_WIDTH), .COUNT_WIDTH(COUNT_WIDTH)) ref_dut(
        .group_row_addr_step_cur(expected), .*);
    integer cycles=0;
    reg [31:0] random_state=32'h71a526b9;
    function automatic [31:0] random_word();
        random_state=random_state^(random_state<<13);
        random_state=random_state^(random_state>>17);
        random_state=random_state^(random_state<<5);
        random_word=random_state;
    endfunction
    task tick();
        #1; clk=1; #1;
        if (actual !== expected)
            $fatal(1, "组步长四态比较失败，周期=%0d", cycles);
        cycles=cycles+1; clk=0; #1;
    endtask
    initial begin
        repeat (4) tick();
        for (integer sample=0; sample<12000; sample=sample+1) begin
            rst_n=(sample%43)!=0; enable=random_word();
            row_addr_step_cur=REG_WIDTH'({{random_word(), random_word()}});
            case (sample%12)
                0: cfg_ia_reuse_num=0;
                1: cfg_ia_reuse_num=1;
                2: cfg_ia_reuse_num=2;
                3: cfg_ia_reuse_num=4;
                4: cfg_ia_reuse_num=8;
                5: cfg_ia_reuse_num=16;
                6: cfg_ia_reuse_num=25;
                7: cfg_ia_reuse_num=32;
                8: cfg_ia_reuse_num=64;
                9: cfg_ia_reuse_num=128;
                10: cfg_ia_reuse_num='1;
                default: cfg_ia_reuse_num=COUNT_WIDTH'({{random_word(), random_word()}});
            endcase
            if (sample>=2000) begin
                case (sample%15)
                    0: row_addr_step_cur[sample%REG_WIDTH]=1'bx;
                    1: row_addr_step_cur[sample%REG_WIDTH]=1'bz;
                    2: cfg_ia_reuse_num[sample%COUNT_WIDTH]=1'bx;
                    3: cfg_ia_reuse_num[sample%COUNT_WIDTH]=1'bz;
                    4: enable=1'bx;
                    5: enable=1'bz;
                    6: rst_n=1'bx;
                    7: rst_n=1'bz;
                    8: row_addr_step_cur='x;
                    9: row_addr_step_cur='z;
                    10: cfg_ia_reuse_num='x;
                    11: cfg_ia_reuse_num='z;
                    default: begin end
                endcase
            end
            tick();
        end
        $display("WRITER_STEP_PASS cycles=%0d", cycles); $finish;
    end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl',type=Path,default=ROOT/SOURCE)
    parser.add_argument('--reference',default='ed5c58ab')
    parser.add_argument('--reference-rtl',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--profiles',nargs='+',default=[
        '1:1','4:4','6:6','6:7','7:6','7:7','8:8','16:16','32:7','32:29','32:32','64:64'])
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    current=args.rtl.read_text()
    reference=(args.reference_rtl.read_text() if args.reference_rtl else
               read_rtl_source(f'{args.reference}:{SOURCE}',cwd=ROOT,text=True))
    texts=dict(reference=reference,current=current)
    for label,text in texts.items():
        (out/f'{label}.sv').write_text(extract(text,f'writer_step_{label}'))
    report=dict(passed=True,reference=args.reference,input_value_constraints=None,
                source_sha256={key:hashlib.sha256(value.encode()).hexdigest() for key,value in texts.items()},
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),profiles=[])
    for profile in args.profiles:
        width,count=map(int,profile.split(':'))
        folder=out/f'r{width}_c{count}';folder.mkdir(exist_ok=True)
        script=folder/'proof.ys'
        commands=[]
        for label in ('reference','current'):
            commands += [
                f'read_slang --top writer_step_{label} -GREG_WIDTH={width} -GCOUNT_WIDTH={count} '+shlex.quote(str(out/f'{label}.sv')),
                f'prep -top writer_step_{label} -flatten',
                f'rename writer_step_{label} {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -flatten reference current miter',
                     'prep -top miter -flatten','chformal -lower','opt -full','async2sync','opt_clean',
                     'sat -verify -prove trigger 0 -tempinduct -seq 1 -set-init-zero -set-at 1 in_rst_n 0 -maxsteps 4']
        script.write_text('\n'.join(commands)+'\n')
        stage=run_stage(script,folder/'proof.log',dict(os.environ))
        (folder/'tb.sv').write_text(bench(width,count))
        binary=folder/'simulation.vvp'
        with (folder/'compile.log').open('w') as log:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(out/'reference.sv'),str(out/'current.sv'),str(folder/'tb.sv')],stdout=log,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,check=True,timeout=60)
        (folder/'run.log').write_text(result.stdout+result.stderr)
        match=re.search(r'WRITER_STEP_PASS cycles=(\d+)',result.stdout)
        if not match:raise RuntimeError(result.stdout+result.stderr)
        row=dict(register_width=width,count_width=count,formal_passed=True,four_state_cycles=int(match[1]),**stage)
        report['profiles'].append(row);print(json.dumps(row),flush=True)
    if current!=args.rtl.read_text():raise RuntimeError('验证期间 RTL 内容发生变化')
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
