#!/usr/bin/env python3
"""检查分组完成比较与计数递增的任意输入和四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='142a7226')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out/'kernel_count_increment_reference.sv'
    original = subprocess.check_output(['git', 'show', args.reference+
        ':rtl/npu/loaders/kernel_count_increment.sv'], cwd=ROOT, text=True)
    reference.write_text(original.replace('module kernel_count_increment #',
                                         'module kernel_count_increment_reference #'))
    model = out/'arithmetic_check.sv'
    model.write_text('''// 比较完整模宽边界和逐位递增结果。
module arithmetic_check #(parameter W=29)(
 input logic [W-1:0] value, // 任意当前计数
 input logic [W-1:0] limit, // 任意完成边界
 output logic equal // 两项运算均符合完整定宽语义
);
wire [W-1:0] next_value,reference_next;
wire [W-1:0] native_next=value+W'(1);
wire reaches;
kernel_count_next_reaches #(.p_width(W)) u_reaches(
 .i_value(value),.i_limit(limit),.o_reaches(reaches));
kernel_count_increment #(.p_width(W)) u_increment(
 .i_value(value),.o_next(next_value));
kernel_count_increment_reference #(.p_width(W)) u_reference(
 .i_value(value),.o_next(reference_next));
assign equal=(reaches===(native_next>=limit))&&(next_value===reference_next);
endmodule
''')
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([model, reference], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    checks = []
    for width in (1, 4, 16, 29, 32, 64):
        for synthesis in (False, True):
            name = f'w{width}_fpga{int(synthesis)}'
            options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else ['-USYNTHESIS', '-UXILINX_FPGA']
            script, log = out/(name+'.ys'), out/(name+'_formal.log')
            script.write_text('read_slang --top arithmetic_check '+
                shlex.join([f'-GW={width}', *options, *map(str, sources)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'+
                'prep -top arithmetic_check -flatten\nsat -verify -prove equal 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
                    '--worker', script], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise RuntimeError('任意输入比较未完成：'+name)
            bench, binary = out/(name+'_tb.sv'), out/(name+'.vvp')
            bench.write_text(f'''module tb;
localparam W={width};
logic [W-1:0] value,limit;wire equal;
arithmetic_check #(.W(W)) dut(.*);
initial begin
 for(integer sample=0;sample<8192;sample++)begin
  value={{$urandom,$urandom}};limit={{$urandom,$urandom}};
  case(sample%8)
   0:value[(sample/8)%W]=1'bx;
   1:value[(sample/8)%W]=1'bz;
   2:limit[(sample/8)%W]=1'bx;
   3:limit[(sample/8)%W]=1'bz;
   4:begin value='1;limit=0;end
   5:begin value='1;limit=1;end
   6:limit=value+W'(1);
   default:begin end
  endcase
  #1;if(equal!==1'b1)$fatal(1,"Count arithmetic differs width=%0d sample=%0d",W,sample);
 end
 $display("COUNT_ARITHMETIC_PASS width=%0d checks=8192",W);$finish;
end
endmodule
''')
            flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
            with (out/(name+'_compile.log')).open('w') as stream:
                subprocess.run(['iverilog', '-g2012', '-s', 'tb', *flags, '-o', binary,
                    *sources, bench], stdout=stream, stderr=subprocess.STDOUT, check=True)
            result = subprocess.check_output(['vvp', binary], text=True, timeout=120)
            (out/(name+'_four_state.log')).write_text(result)
            if f'COUNT_ARITHMETIC_PASS width={width} checks=8192' not in result:
                raise RuntimeError('四态比较未完成：'+name)
            checks.append({'width': width, 'synthesis': synthesis, 'passed': True,
                'arbitrary_inputs_proven': True, 'formal_log_sha256': digest(log),
                'four_state_comparisons': 8192,
                'four_state_log_sha256': digest(out/(name+'_four_state.log'))})
            print(name, 'PASS', flush=True)
    if any(digest(Path(path)) != expected for path, expected in hashes.items()):
        raise RuntimeError('检查期间源文件发生变化')
    (out/'validation.json').write_text(json.dumps({'passed': True, 'reference': args.reference,
        'inputs_constrained': False, 'source_sha256': hashes, 'checks': checks,
        'formal_checks': len(checks), 'four_state_comparisons': 8192*len(checks)}, indent=2)+'\n')


if __name__ == '__main__':
    main()
