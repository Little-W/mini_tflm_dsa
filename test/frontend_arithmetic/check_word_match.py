#!/usr/bin/env python3
"""验证保存字地址比较的完整字段相等条件及四态传播。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, timeout=180, check=True)


def model(width):
    return f'''module match_proof(
input logic [{width-1}:0] i_a,i_b,output logic equivalent);
logic direct_equal,grouped_equal,reference_equal;
conv_descriptor_match #(.p_width({width})) u_direct(.i_a,.i_b,.o_equal(direct_equal));
conv_descriptor_match #(.p_width({width}),.p_preserve_groups(1'b1)) u_grouped(
 .i_a,.i_b,.o_equal(grouped_equal));
assign reference_equal=i_a==i_b;
assign equivalent=(direct_equal===reference_equal)&&(grouped_equal===reference_equal);
endmodule
'''


def bench(width):
    bits = 2*width
    words = (bits+31)//32
    return f'''module tb;
logic [{bits-1}:0] stimulus,known_stimulus;
logic [{words*32-1}:0] random_value;
wire [{width-1}:0] i_a=stimulus[{width-1}:0];
wire [{width-1}:0] i_b=stimulus[{bits-1}:{width}];
wire equivalent;
integer checks=0;
match_proof dut(.*);
task automatic check;
 #1;
 if(equivalent!==1'b1)$fatal(1,"Word match differs width={width} input=%h",stimulus);
 checks++;
endtask
initial begin
 stimulus='0;check();stimulus='1;check();
 for(integer trial=0;trial<32;trial++)begin
  for(integer word_index=0;word_index<{words};word_index++)
   random_value[32*word_index+:32]=$urandom;
  stimulus=random_value;known_stimulus=stimulus;check();
  for(integer bit_index=0;bit_index<{bits};bit_index++)begin
   stimulus=known_stimulus;stimulus[bit_index]=1'bx;check();
   stimulus=known_stimulus;stimulus[bit_index]=1'bz;check();
  end
  stimulus='x;check();stimulus='z;check();
 end
 $display("WORD_MATCH_PASS width={width} checks=%0d",checks);$finish;
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/conv/conv_descriptor_match.sv'
    stream = ROOT/'rtl/npu/conv/conv_im2col_stream.sv'
    stream_text = stream.read_text()
    instance = re.search(r'conv_descriptor_match\s*#\([^;]*?\)\s+u_next_tap_word_match\s*\([^;]*?\);',
                         stream_text, re.S)
    if instance is None or ".p_preserve_groups(1'b1)" not in instance.group(0):
        raise ValueError('生产保存字比较实例未启用分组结果')
    hashes = {str(path): digest(path) for path in (source, stream)}
    proofs, simulations = [], []
    for width in (1, 2, 3, 4, 8, 16, 17, 28, 32, 35, 64):
        generated = out/f'match_{width}.sv'
        generated.write_text(model(width))
        script, log = out/f'match_{width}.ys', out/f'formal_{width}.log'
        script.write_text(slang_command()+'--top match_proof '+shlex.join([str(source), str(generated)])+
                         '\nprep -top match_proof -flatten\ncheck -assert\n'
                         'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('字段比较形式证明未完成')
        proofs.append(dict(width=width, passed=True, log_sha256=digest(log)))
    simulation_source = out/'conv_descriptor_match.sv'
    simulation_source.write_text(source.read_text().replace('parameter int unsigned', 'parameter integer'))
    for width in (1, 3, 8, 32, 35, 64):
        generated = out/f'match_{width}.sv'
        generated_bench = out/f'tb_{width}.sv'
        generated_bench.write_text(bench(width))
        binary = out/f'simulation_{width}.vvp'
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, simulation_source,
             generated, generated_bench], out/f'compile_{width}.log')
        log = out/f'simulation_{width}.log'
        run(['vvp', binary], log)
        expected = 2+32*(4*width+3)
        if f'WORD_MATCH_PASS width={width} checks={expected}' not in log.read_text():
            raise ValueError('字段比较四态检查未完成')
        simulations.append(dict(width=width, checks=expected, passed=True, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  formal=proofs, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('WORD_MATCH_PASS formal='+str(len(proofs))+
          ' four_state='+str(sum(item['checks'] for item in simulations)))


if __name__ == '__main__':
    main()
