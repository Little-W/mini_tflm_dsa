#!/usr/bin/env python3
"""验证分组相等判断及矩阵权重预测的完整条件。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1, 2, 3, 4, 16, 31, 32, 64, 128)
SOURCE = 'rtl/common/parallel_equal.sv'
PARENT = 'rtl/npu/top/npu_matrix_engine.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(text):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='c42f5ff9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = tokens(subprocess.check_output(['git', 'show', args.reference+':'+PARENT], cwd=ROOT, text=True))
    current = tokens((ROOT/PARENT).read_text())
    old = 'wireprediction_start=o_frame_mode_q&&frame_command_active&&frame_execution_started&&frame_lookahead_valid&&(frame_lookahead_column!=frame_command_column||frame_lookahead_q0!=frame_command_q0);'
    new = 'wiresame_prediction;parallel_equal#(.p_width(64))u_prediction_equal(.i_a({frame_lookahead_column,frame_lookahead_q0}),.i_b({frame_command_column,frame_command_q0}),.o_equal(same_prediction));wireprediction_start=o_frame_mode_q&&frame_command_active&&frame_execution_started&&frame_lookahead_valid&&!same_prediction;'
    if original.count(old) != 1 or current.count(new) != 1 or original.replace(old, '') != current.replace(new, ''):
        raise RuntimeError('矩阵预测条件以外的功能代码不同')
    sha = digest(ROOT/SOURCE)
    proof = out/'proof.sv'
    proof.write_text('''module proof #(parameter WIDTH=64)(input logic[WIDTH-1:0]a,b,input logic[3:0]enable,output logic equal);
logic result;parallel_equal #(.p_width(WIDTH)) dut(.i_a(a),.i_b(b),.o_equal(result));
assign equal=(result===(a==b))&&(((&enable)&&!result)==(((&enable)&&(a!=b))));
endmodule
''')

    def prove(width):
        script, log = out/f'w{width}.ys', out/f'w{width}.log'
        script.write_text(f'read_slang --top proof -GWIDTH={width} {ROOT/SOURCE} {proof}\n'+
            'setattr -mod -unset keep_hierarchy\nprep -top proof -flatten\ncheck -assert\n'+
            'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('相等判断形式检查未完成')
        return {'width': width, 'passed': True, 'inputs_constrained': False, 'log_sha256': digest(log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        formal = list(pool.map(prove, WIDTHS))
    tb = ['module tb;logic[127:0]a,b;logic[3:0]enable;integer checks=0;']
    for width in WIDTHS:
        tb += [f'wire result{width};parallel_equal #(.p_width({width})) u_{width}(.i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.o_equal(result{width}));']
    tb += ['initial begin for(integer sample=0;sample<32768;sample++)begin',
        'a={$urandom,$urandom,$urandom,$urandom};b=sample[0]?a:{$urandom,$urandom,$urandom,$urandom};enable=sample[5:2];',
        'case(sample%12)', "0:a[(sample/12)%128]=1'bx;", "1:a[(sample/12)%128]=1'bz;",
        "2:b[(sample/12)%128]=1'bx;", "3:b[(sample/12)%128]=1'bz;",
        "4:begin a=b;a[(sample/12)%128]=1'bx;end", "5:begin a=b;a[(sample/12)%128]=~b[(sample/12)%128];end",
        "6:begin a='x;b='z;end", "7:enable[(sample/12)%4]=1'bx;", 'default:begin end', 'endcase', '#1;']
    for width in WIDTHS:
        tb += [f'if(result{width}!==(a[{width-1}:0]==b[{width-1}:0]))$fatal(1,"相等判断四态结果不同 width={width}");',
            f'if(((&enable)&&!result{width})!==(((&enable)&&(a[{width-1}:0]!=b[{width-1}:0]))))$fatal(1,"预测资格四态结果不同");checks+=2;']
    tb += ['end $display("PASS checks=%0d",checks);$finish;end endmodule']
    bench, binary = out/'tb.sv', out/'tb.vvp'
    bench.write_text('\n'.join(tb)+'\n')
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, ROOT/SOURCE, bench],
            check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.check_output(['vvp', binary], text=True, timeout=120)
    (out/'four_state.log').write_text(result)
    count = 2*len(WIDTHS)*32768
    if f'PASS checks={count}' not in result or sha != digest(ROOT/SOURCE):
        raise RuntimeError('相等判断检查未完成或源码发生变化')
    report = {'passed': True, 'source_sha256': sha, 'formal': formal,
        'four_state_comparisons': count, 'parent': {'reference': args.reference,
        'source_sha256': digest(ROOT/PARENT), 'remaining_functional_tokens_identical': True,
        'complete_coordinates_and_enable_inputs_verified': True}}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(count, 'four-state comparisons PASS', flush=True)


if __name__ == '__main__':
    main()
