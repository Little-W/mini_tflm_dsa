#!/usr/bin/env python3
"""验证完整请求索引模块的输出等价性、四态传播及综合结果。"""
from __future__ import annotations

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
SOURCE = Path('rtl/npu/conv/conv_im2col_request_index.sv')
CHECKS = 8192


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=180)


def inputs(width):
    return {'i_short_pixel': 1, 'i_index_shift': 5, 'i_descriptor': 1,
            'i_row': 1, 'i_tap': 1, 'i_incoming_select': 10,
            'i_incoming_pixel': 320, 'i_incoming_y': 10*width,
            'i_saved_pixel': 32, 'i_running_pixel': 96,
            'i_running_y': 3*width, 'i_current_index': 32}


def model(width, registered):
    ports = inputs(width)
    declarations = ',\n'.join(f'input logic [{bits-1}:0] {name}'
                              for name, bits in ports.items())
    connections = ','.join(f'.{name}({name})' for name in ports)
    result_width = 64+width
    text = f'module proof({declarations},\noutput logic equivalent,\n'
    text += f'output logic [{result_width-1}:0] actual_value, expected_value);\n'
    for label, module in [('actual', 'conv_im2col_request_index'),
                          ('expected', 'reference_request_index')]:
        text += f'{module} #(.p_coord_width({width}),.p_register_descriptor({registered})) '
        text += f'u_{label}({connections},.o_incoming_index({label}_value[31:0]),'
        text += f'.o_request_index({label}_value[63:32]),'
        text += f'.o_request_y({label}_value[{result_width-1}:64]));\n'
    return text + 'assign equivalent=actual_value===expected_value;\nendmodule\n'


def bench():
    ports = {'i_short_pixel': 1, 'i_index_shift': 5,
             'incoming_pixel': 32, 'request_pixel': 32}
    bits = sum(ports.values())
    padded = (bits+31)//32*32
    names = ','.join(ports)
    declarations = '\n'.join(f'logic [{count-1}:0] {name};' for name, count in ports.items())
    return f'''module tb;
{declarations}
logic equivalent;
logic [63:0] actual_value,expected_value;
logic [{padded-1}:0] pattern;
logic [{bits-1}:0] applied,seen_x='0,seen_z='0;
integer known=0,unknown=0;
shift_proof dut(.*);
initial begin
 for(integer sample=0;sample<{CHECKS};sample++)begin
  for(integer word_index=0;word_index<{padded//32};word_index++)
   pattern[32*word_index+:32]=$urandom;
  {{{names}}}=pattern;
  if(sample%4==0)begin incoming_pixel='0;request_pixel='0;end
  if(sample%4==1)begin incoming_pixel='1;request_pixel='1;end
  if(sample%4==2)request_pixel=incoming_pixel;
  if(sample%11==0)begin
   incoming_pixel=32'h8000_0001;request_pixel=32'hffff_0000;
  end
  if(sample%13==0)i_index_shift='0;
  if(sample%17==0)i_index_shift='1;
  applied={{{names}}};
  if(sample%3==0)applied[(sample/3)%{bits}]=1'bx;
  if(sample%5==0)applied[(sample/5)%{bits}]=1'bz;
  {{{names}}}=applied;
  for(integer bit_index=0;bit_index<{bits};bit_index++)begin
   if(applied[bit_index]===1'bx)seen_x[bit_index]=1'b1;
   if(applied[bit_index]===1'bz)seen_z[bit_index]=1'b1;
  end
  #1;
  if(equivalent!==1'b1)$fatal(1,"Request index mismatch sample=%0d",sample);
  if((^applied)===1'bx)unknown++;else known++;
 end
 if(seen_x!=='1||seen_z!=='1)$fatal(1,"Incomplete input coverage");
 if(known<1000||unknown<1000)$fatal(1,"Incomplete four-state coverage");
 $display("REQUEST_INDEX_SHIFT_PASS checks={CHECKS} known=%0d unknown=%0d",known,unknown);
 $finish;
end
endmodule
'''


def shift_model(current, reference):
    first = current.index('    assign effective_shift =')
    last = current.index('\n    always_comb begin\n      o_incoming_index', first)
    actual = current[first:last]
    expected = '\n'.join(re.findall(r'    assign (?:incoming_shared|request_shared) =[^;]+;', reference))
    if expected.count('assign') != 2:
        raise ValueError('参考模块缺少完整索引移位表达式')
    text = ''
    for name, body in [('actual_shared', actual), ('expected_shared', expected)]:
        text += f'''module {name}(
input logic i_short_pixel,
input logic [4:0] i_index_shift,
input logic [31:0] incoming_pixel,request_pixel,
output logic [63:0] result);
logic [31:0] incoming_shared,request_shared;
logic [4:0] effective_shift;
{body}
assign result={{request_shared,incoming_shared}};
endmodule
'''
    text += '''module shift_proof(
input logic i_short_pixel,
input logic [4:0] i_index_shift,
input logic [31:0] incoming_pixel,request_pixel,
output logic equivalent,
output logic [63:0] actual_value,expected_value);
actual_shared actual(.result(actual_value),.*);
expected_shared expected(.result(expected_value),.*);
assign equivalent=actual_value===expected_value;
endmodule
'''
    return text


def mapping_wrapper():
    ports = inputs(35)
    outputs = {'o_incoming_index': 32, 'o_request_index': 32, 'o_request_y': 35}
    declarations = ',\n'.join(f'input logic [{width-1}:0] {name}' for name, width in ports.items())
    declarations += ',\n'+',\n'.join(f'output logic [{width-1}:0] {name}' for name, width in outputs.items())
    text = 'module request_index_registered(input logic clk,\n'+declarations+');\n'
    text += '\n'.join(f'logic [{width-1}:0] registered_{name};' for name, width in {**ports, **outputs}.items())+'\n'
    text += 'always_ff @(posedge clk) begin\n'
    text += '\n'.join(f'registered_{name}<={name};' for name in ports)+'\n'
    text += '\n'.join(f'{name}<=registered_{name};' for name in outputs)+'\nend\n'
    text += 'conv_im2col_request_index #(.p_coord_width(35),.p_register_descriptor(0)) u_dut(\n'
    text += ',\n'.join(f'.{name}(registered_{name})' for name in {**ports, **outputs})+');\nendmodule\n'
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    parser.add_argument('--measure', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT/'test'))
    from reference_sources import read_reference_file
    source = read_reference_file(ROOT, args.reference, str(SOURCE), text=True)
    reference = out/'reference_request_index.sv'
    reference.write_text(re.sub(r'\bconv_im2col_request_index\b', 'reference_request_index', source))
    dependency = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependency([ROOT/SOURCE, reference], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    results = []
    for width in (16, 35, 48):
        for registered in (0, 1):
            for synthesis in (0, 1):
                folder = out/f'w{width}_registered{registered}_synthesis{synthesis}'
                folder.mkdir(exist_ok=True)
                generated = folder/'model.sv'
                generated.write_text(model(width, registered))
                definitions = ['-DSYNTHESIS=1'] if synthesis else []
                script = folder/'formal.ys'
                script.write_text('read_slang --top proof '+shlex.join(definitions+list(map(str, [*sources, generated])))+
                    '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                    'prep -top proof -flatten\ncheck -assert\n'
                    'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
                formal = folder/'formal.log'
                execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], formal)
                if 'SAT proof finished - no model found: SUCCESS!' not in formal.read_text():
                    raise RuntimeError(f'形式比较未完成：{formal}')
                results.append({'coordinate_width': width, 'registered_descriptor': bool(registered),
                                'synthesis': bool(synthesis), 'formal_passed': True,
                                'compared_output_bits': 64+width,
                                'formal_log_sha256': digest(formal)})
                print(folder.name+': PASS', flush=True)
    generated = out/'shared_shift.sv'
    generated.write_text(shift_model((ROOT/SOURCE).read_text(), source))
    test, binary = out/'shared_shift_tb.sv', out/'shared_shift.vvp'
    test.write_text(bench())
    execute(['iverilog', '-g2012', '-s', 'tb', '-o', binary, generated, test], out/'four_state_compile.log')
    simulation = out/'four_state.log'
    execute(['vvp', binary], simulation)
    if f'REQUEST_INDEX_SHIFT_PASS checks={CHECKS}' not in simulation.read_text():
        raise RuntimeError(f'四态比较未完成：{simulation}')
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError('验证期间源码发生变化')
    report = {'passed': True, 'reference': args.reference, 'inputs_constrained': False,
              'reference_source_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'source_sha256': hashes, 'cases': results,
              'four_state_checks': CHECKS, 'four_state_scope': '生产源提取的两路完整索引变换',
              'all_transform_input_bits_x_z': True, 'simulation_log_sha256': digest(simulation)}
    reference_exact = out/'reference_exact.sv'
    reference_exact.write_text(source)
    wrapper = out/'request_index_registered.sv'
    wrapper.write_text(mapping_wrapper())
    mapping = {name: {'top': 'request_index_registered', 'options': ['-DSYNTHESIS=1'],
                      'sources': [str(path), str(wrapper)],
                      'configuration': '全部输入和输出寄存，三十五位坐标和直接描述符模式'}
               for name, path in [('reference', reference_exact), ('current', ROOT/SOURCE)]}
    case_file = out/'mapping_cases.json'
    case_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2)+'\n')
    if args.measure:
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--case-config', case_file,
                 '--cases', 'reference', 'current', '--out', out/'synthesis',
                 '--native-combinational-helpers'], out/'synthesis.log')
        report['synthesis'] = {
            name: json.loads((out/'synthesis'/name/'metrics.json').read_text())
            for name in ('reference', 'current')}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
