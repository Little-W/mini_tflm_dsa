#!/usr/bin/env python3
"""检查生产几何模块中五路地址推进的完整定宽结果与四态传播。"""
from __future__ import annotations

from formal_compilation import slang_command

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
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       cwd=ROOT, check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    geometry = ROOT/'rtl/npu/conv/conv_im2col_geometry.sv'
    helper = ROOT/'rtl/npu/conv/conv_geometry_movement_add.sv'
    source = geometry.read_text()
    first = source.index('  for (genvar source = 0; source < 5; source++) begin : g_movement_sum')
    last = source.index('  // 配置阶段保存乘积', first)
    model = out/'movement_proof.sv'
    model.write_text('''module movement_proof(
input logic [4:0][31:0] movement_i_a,movement_step_delta,movement_wrap_delta,
input logic [4:0] movement_wrap_select,output logic equivalent);
logic [4:0][31:0] movement_i_b,movement_o_sum,expected_sum;
for(genvar index=0;index<5;index++)begin:g_expected
 assign movement_i_b[index]=movement_wrap_select[index]?movement_wrap_delta[index]:movement_step_delta[index];
 assign expected_sum[index]=movement_i_a[index]+movement_i_b[index];
end
'''+source[first:last]+"assign equivalent=movement_o_sum===expected_sum;\nendmodule\n")
    dependency = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    helpers = dependency([helper], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in [geometry, *helpers]}
    proofs = []
    for synthesis in (0, 1):
        script, log = out/f'formal_{synthesis}.ys', out/f'formal_{synthesis}.log'
        definitions = ['-DSYNTHESIS=1'] if synthesis else []
        script.write_text(slang_command(definitions)+'--top movement_proof '+shlex.join(
            [*definitions, *map(str, helpers), str(model)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top movement_proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('地址推进形式证明未完成')
        proofs.append(dict(synthesis=bool(synthesis), passed=True, log_sha256=digest(log)))
    simulation_sources = []
    for path in helpers:
        target = out/path.name
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    bench, binary, log = out/'tb.sv', out/'simulation.vvp', out/'simulation.log'
    bench.write_text('''module tb;
logic [484:0] stimulus,known_stimulus;
wire [4:0][31:0] movement_i_a=stimulus[159:0];
wire [4:0][31:0] movement_step_delta=stimulus[319:160];
wire [4:0][31:0] movement_wrap_delta=stimulus[479:320];
wire [4:0] movement_wrap_select=stimulus[484:480];
wire equivalent;
integer checks=0;
movement_proof dut(.*);
task automatic check;
 #1;if(equivalent!==1'b1)$fatal(1,"Movement result differs input=%h",stimulus);checks++;
endtask
initial begin
 stimulus='0;check();stimulus='1;check();
 for(integer trial=0;trial<32;trial++)begin
  for(integer bit_index=0;bit_index<485;bit_index++)stimulus[bit_index]=1'($urandom);
  known_stimulus=stimulus;check();
  for(integer bit_index=0;bit_index<485;bit_index++)begin
   stimulus=known_stimulus;stimulus[bit_index]=1'bx;check();
   stimulus=known_stimulus;stimulus[bit_index]=1'bz;check();
  end
  stimulus='x;check();stimulus='z;check();
 end
 $display("MOVEMENT_SUMS_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *simulation_sources, model, bench], out/'compile.log')
    run(['vvp', binary], log)
    if 'MOVEMENT_SUMS_PASS checks=31138' not in log.read_text():
        raise ValueError('地址推进四态检查未完成')
    if any(digest(ROOT/path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  formal=proofs, four_state_checks=31138,
                  four_state_all_input_bits_x_z=True, simulation_log_sha256=digest(log))
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(passed=True, formal_cases=2, four_state_checks=31138)))


if __name__ == '__main__':
    main()
