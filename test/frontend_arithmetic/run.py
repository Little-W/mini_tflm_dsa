#!/usr/bin/env python3
"""验证前端定宽加法、坐标检查及完整描述符提交模块。"""
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


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, log, timeout=240):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       cwd=ROOT, check=True, timeout=timeout)


def arithmetic_model(width):
    text = f'''module arithmetic_proof(
input logic [{width-1}:0] i_a,i_b,input logic i_carry,
input logic [15:0] i_limit,output logic equivalent);
logic [{width-1}:0] actual_sum,reference_sum;
logic [{width-1}:0] grouped_sum,reference_grouped;
logic unused_grouped_carry;
logic add_equal,coordinate_equal,movement_equal;
conv_descriptor_add #(.p_width({width})) u_add(.i_a,.i_b,.i_carry,.o_sum(actual_sum));
conv_descriptor_address_add #(.p_width({width})) u_grouped(
 .i_a,.i_b,.i_carry,.o_sum(grouped_sum));
parallel_prefix_add #(.p_width({width}),.p_group_width(8),.p_preserve_groups(1'b1)) u_grouped_reference(
 .i_a,.i_b,.i_carry,.o_sum(reference_grouped),.o_carry(unused_grouped_carry));
assign reference_sum=i_a+i_b+{width}'(i_carry);
assign add_equal=(actual_sum===reference_sum)&&(grouped_sum===reference_grouped);
'''
    if width > 16:
        text += f'''logic [{width-1}:0] coordinate_sum,coordinate_reference;
logic coordinate_valid;
conv_coordinate_step #(.p_width({width})) u_coordinate(
 .i_base(i_a),.i_delta(i_b),.i_limit,.o_sum(coordinate_sum),.o_valid(coordinate_valid));
assign coordinate_reference=i_a+i_b;
assign coordinate_equal={{coordinate_sum,coordinate_valid}}===
 {{coordinate_reference,coordinate_reference<{width}'(i_limit)}};
'''
    else:
        text += "assign coordinate_equal=1'b1;\n"
    if width >= 32:
        text += '''logic [31:0] movement_sum,movement_reference;
conv_geometry_movement_add u_movement(
 .i_base(i_a[31:0]),.i_delta(i_b[31:0]),.o_sum(movement_sum));
assign movement_reference=i_a[31:0]+i_b[31:0];
`ifdef SYNTHESIS
assign movement_equal=movement_sum==movement_reference;
`else
// 几何模块在未知输入时采用定宽算术的四态传播规则。
always_comb begin
 movement_equal=1'b1;
 case (^{i_a[31:0],i_b[31:0]})
  1'b0,1'b1: movement_equal=movement_sum===movement_reference;
  default: ;
 endcase
end
`endif
'''
    else:
        text += "assign movement_equal=1'b1;\n"
    return text + 'assign equivalent=add_equal&&coordinate_equal&&movement_equal;\nendmodule\n'


def four_state_bench(width):
    bits = 2*width+17
    words = (bits+31)//32
    return f'''module tb;
logic [{bits-1}:0] stimulus,known_stimulus;
logic [{words*32-1}:0] random_value;
wire [{width-1}:0] i_a=stimulus[{width-1}:0];
wire [{width-1}:0] i_b=stimulus[{2*width-1}:{width}];
wire i_carry=stimulus[{2*width}];
wire [15:0] i_limit=stimulus[{bits-1}:{2*width+1}];
wire equivalent;
integer checks=0;
arithmetic_proof dut(.*);
task automatic check;
 #1;
 if(equivalent!==1'b1)$fatal(1,"Arithmetic result differs width={width} input=%h",stimulus);
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
 $display("FRONTEND_ARITHMETIC_PASS width={width} checks=%0d",checks);$finish;
end
endmodule
'''


def commit_model(source):
    match = re.search(r'module conv_descriptor_commit\s*#\((.*?)\)\s*\((.*?)\);', source, re.S)
    if match is None:
        raise ValueError('描述符提交模块的端口声明未找到')
    parameters, ports = match.groups()
    names = re.findall(r'\binput\s+[^\n]*?\b(i_\w+)\s*[,/]', ports)
    if len(names) != 17:
        raise ValueError(f'描述符输入端口数量改变：{len(names)}')
    parameter_names = re.findall(r'\bparameter\s+\w+\s+(p_\w+)\s*=', parameters)
    parameter_connections = ','.join(f'.{name}({name})' for name in parameter_names)
    connections = ','.join(f'.{name}({name})' for name in names)
    return 'module commit_proof #(\n'+parameters+') (\n'+ports+''',
output logic equivalent);
logic [p_prepared_tile_width-1:0] reference_tile;
logic [1:0] reference_valid;
'''+f'''conv_descriptor_commit #({parameter_connections}) u_actual(
 {connections},.o_committing_tile_packed,.o_coordinate_valid);
reference_descriptor_commit #({parameter_connections}) u_reference(
 {connections},.o_committing_tile_packed(reference_tile),.o_coordinate_valid(reference_valid));
assign equivalent={{o_committing_tile_packed,o_coordinate_valid}}==={{reference_tile,reference_valid}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    parser.add_argument('--candidate', type=Path, nargs='*', default=[])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    overrides = {path.name: path.resolve() for path in args.candidate}
    production = ['conv_descriptor_add.sv', 'conv_descriptor_address_add.sv', 'conv_descriptor_commit.sv',
                  'conv_geometry_movement_add.sv', 'conv_coordinate_step.sv']
    sources = [overrides.get(name, ROOT/'rtl/npu/conv'/name) for name in production]
    dependency = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependency(sources, ROOT)
    include = ROOT/'include'
    hashes = {str(path): digest(path) for path in sources}
    hashes[str(include/'conv_im2col_prepared_tile.svh')] = digest(include/'conv_im2col_prepared_tile.svh')
    formal_results, simulation_results = [], []

    def prove(name, top, generated, options=()):
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text(slang_command(options)+'--top '+top+' -I'+str(include)+' '+
            shlex.join([*options, *map(str, sources), str(generated)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top '+top+' -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('形式证明未完成：'+name)
        formal_results.append(dict(name=name, passed=True, log_sha256=digest(log)))
        print(name+': PASS', flush=True)

    for width in (16, 31, 32, 33, 35, 48):
        model = out/f'arithmetic_{width}.sv'
        model.write_text(arithmetic_model(width))
        for synthesis in (0, 1):
            options = ['-DSYNTHESIS=1'] if synthesis else []
            prove(f'arithmetic_{width}_synthesis{synthesis}', 'arithmetic_proof', model, options)

    reference = subprocess.check_output(['git', 'show', args.reference+':rtl/npu/conv/conv_descriptor_commit.sv'],
                                        cwd=ROOT, text=True)
    reference_path = out/'reference_descriptor_commit.sv'
    reference_path.write_text(re.sub(r'\bconv_descriptor_commit\b', 'reference_descriptor_commit', reference))
    commit_path = overrides.get('conv_descriptor_commit.sv', ROOT/'rtl/npu/conv/conv_descriptor_commit.sv')
    model = out/'commit_proof.sv'
    model.write_text(commit_model(commit_path.read_text()))
    sources.append(reference_path)
    for width, registered, synthesis in ((35, 1, 1), (35, 1, 0), (32, 1, 1), (48, 1, 1), (35, 0, 1)):
        options = [f'-Gp_coord_w={width}', f'-Gp_register_descriptor={registered}', '-Gp_lanes=8', '-Gp_line_bytes=128']
        if synthesis:
            options.append('-DSYNTHESIS=1')
        prove(f'commit_{width}_registered{registered}_synthesis{synthesis}', 'commit_proof', model, options)

    simulation_sources = []
    for path in sources:
        if path.name in ('conv_descriptor_commit.sv', 'reference_descriptor_commit.sv') or 'pkg' in path.name:
            continue
        target = out/('simulation_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    for width in (16, 32, 35, 48):
        model = out/f'arithmetic_{width}.sv'
        bench, binary = out/f'bench_{width}.sv', out/f'simulation_{width}.vvp'
        bench.write_text(four_state_bench(width))
        execute(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *simulation_sources, model, bench],
                out/f'simulation_{width}_compile.log')
        log = out/f'simulation_{width}.log'
        execute(['vvp', binary], log)
        expected = 2+32*(2*(2*width+17)+3)
        if f'FRONTEND_ARITHMETIC_PASS width={width} checks={expected}' not in log.read_text():
            raise ValueError('四态检查未完成：'+str(width))
        simulation_results.append(dict(width=width, checks=expected, passed=True, log_sha256=digest(log)))
        print(f'four_state_{width}: PASS checks={expected}', flush=True)
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, reference=args.reference, input_assumptions=[],
                  source_sha256=hashes, formal=formal_results, four_state=simulation_results,
                  four_state_scope='带进位加法和坐标范围；地址推进的四态控制由几何模块处理',
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest())
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
