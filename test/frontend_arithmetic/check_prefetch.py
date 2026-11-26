#!/usr/bin/env python3
"""比较生产预取模块的五路准备加法，覆盖完整输入空间与四态传播。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/conv_im2col_prefetch.sv')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       cwd=ROOT, check=True, timeout=180)


def extracted_module(source, name):
    first = source.index('  for (genvar source = 0; source < 3; source++) begin : g_prefetch_prepare')
    last = source.index('  // 两种横坐标', first)
    selected = source[first:last]
    for instance in ('u_prefetch_x', 'u_prefetch_wrapped_x'):
        match = re.search(r'  parallel_prefix_add\s*#\([^;]*?\)\s+'+instance+r'\s*\([^;]*?\);', source, re.S)
        if match is None:
            raise ValueError('预取算术实例未找到：'+instance)
        selected += match.group(0)+'\n'
    return f'''module {name}(
input logic [2:0][31:0] pf_prepare_i_a,pf_prepare_i_b,
input logic [1:0][34:0] accepted_coordinate_q,
input logic [31:0] prefetch_wrap_base_q,pf_step_q,
output logic [159:0] result);
logic pf_prepare_i_carry;
logic [2:0][31:0] pf_prepare_o_sum;
logic [2:0] unused_pf_prepare_carry,unused_prefetch_x_carry;
logic [31:0] prefetch_next_x,prefetch_wrapped_x;
assign pf_prepare_i_carry=1'b0;
'''+selected+'''assign result={prefetch_wrapped_x,prefetch_next_x,pf_prepare_o_sum};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/SOURCE)
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    reference = subprocess.check_output(['git', 'show', args.reference+':'+str(SOURCE)], cwd=ROOT, text=True)
    model = out/'prefetch_proof.sv'
    model.write_text(extracted_module(source.read_text(), 'prefetch_actual')+
                     extracted_module(reference, 'prefetch_reference')+'''module prefetch_proof(
input logic [2:0][31:0] pf_prepare_i_a,pf_prepare_i_b,
input logic [1:0][34:0] accepted_coordinate_q,
input logic [31:0] prefetch_wrap_base_q,pf_step_q,output logic equivalent);
logic [159:0] actual_result,reference_result;
prefetch_actual u_actual(.result(actual_result),.*);
prefetch_reference u_reference(.result(reference_result),.*);
assign equivalent=actual_result===reference_result;
endmodule
''')
    dependency = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    helpers = dependency([ROOT/'rtl/common/parallel_prefix_add.sv'], ROOT)
    hashes = {str(path): digest(path) for path in [source, *helpers]}
    proofs = []
    for synthesis in (0, 1):
        script, log = out/f'formal_{synthesis}.ys', out/f'formal_{synthesis}.log'
        definitions = ['-DSYNTHESIS=1'] if synthesis else []
        script.write_text(slang_command(definitions)+'--top prefetch_proof '+shlex.join(
            [*definitions, *map(str, helpers), str(model)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top prefetch_proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('预取算术形式证明未完成')
        proofs.append(dict(synthesis=bool(synthesis), passed=True, log_sha256=digest(log)))
    simulation_sources = []
    for path in helpers:
        target = out/path.name
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    bench, binary, log = out/'tb.sv', out/'simulation.vvp', out/'simulation.log'
    bench.write_text('''module tb;
logic [325:0] stimulus,known_stimulus;
wire [2:0][31:0] pf_prepare_i_a=stimulus[95:0];
wire [2:0][31:0] pf_prepare_i_b=stimulus[191:96];
wire [1:0][34:0] accepted_coordinate_q=stimulus[261:192];
wire [31:0] prefetch_wrap_base_q=stimulus[293:262];
wire [31:0] pf_step_q=stimulus[325:294];
wire equivalent;
integer checks=0;
prefetch_proof dut(.*);
task automatic check;
 #1;if(equivalent!==1'b1)$fatal(1,"Prefetch arithmetic differs input=%h",stimulus);checks++;
endtask
initial begin
 stimulus='0;check();stimulus='1;check();
 for(integer trial=0;trial<32;trial++)begin
  for(integer bit_index=0;bit_index<326;bit_index++)stimulus[bit_index]=1'($urandom);
  known_stimulus=stimulus;check();
  for(integer bit_index=0;bit_index<326;bit_index++)begin
   stimulus=known_stimulus;stimulus[bit_index]=1'bx;check();
   stimulus=known_stimulus;stimulus[bit_index]=1'bz;check();
  end
  stimulus='x;check();stimulus='z;check();
 end
 $display("PREFETCH_ARITHMETIC_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *simulation_sources, model, bench], out/'compile.log')
    run(['vvp', binary], log)
    if 'PREFETCH_ARITHMETIC_PASS checks=20962' not in log.read_text():
        raise ValueError('预取算术四态检查未完成')
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, reference=args.reference, input_assumptions=[],
                  source_sha256=hashes, formal=proofs, four_state_checks=20962,
                  four_state_all_input_bits_x_z=True, simulation_log_sha256=digest(log),
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest())
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(passed=True, formal_cases=2, four_state_checks=20962)))


if __name__ == '__main__':
    main()
