#!/usr/bin/env python3
"""比较生产短通道范围模块与参照流式逻辑的完整组合结果。"""
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
CASES = ((1, 1, 1), (2, 1, 1), (3, 2, 1), (4, 4, 1),
         (8, 8, 1), (8, 4, 0), (16, 8, 1))
RENAMES = {
    'i_cfg.group_c': 'i_cfg_group_c', 'i_c.group_c': 'i_group_c',
    'o_ch_q': 'i_channel', 'o_group_range_channel': 'i_channel_source',
    'group_range_q': 'i_range', 'active_lane_allowed_q': 'i_active_lane',
    'column_lane_allowed_q': 'i_column_lane', 'word_lane_allowed': 'i_word_lane',
    'o_chunk_selected': 'i_chunk_selected', 'o_chunk_lane_allowed': 'i_chunk_lane',
    'group_transfer_range': 'o_transfer_range', 'group_range_cfg': 'o_cfg_range',
    'o_group_range_next': 'o_next_range', 'group_lane_allowed': 'o_lane_allowed',
    'group_after_chunk': 'o_after_chunk',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, timeout=300, check=True)


def range_body(text):
    first = text.index('  if (p_lanes <= 16) begin : g_short_group_lane\n')
    first = text.index('\n', first)+1
    last = text.index('  end else if (p_lanes <= 32768) begin : g_group_lane_range', first)
    result = text[first:last]
    for old, new in RENAMES.items():
        result = result.replace(old, new)
    return result


def declarations(ports, direction, prefix=''):
    result = []
    for line in ports.splitlines():
        clean = line.split('//')[0].strip().rstrip(',')
        if not clean.startswith(direction+' '):
            continue
        clean = re.sub(r'^(input|output)\s+(wire\s+)?logic\s+', '', clean)
        name = re.search(r'\b([io]_\w+)$', clean).group(1)
        result.append(('wire '+clean[:-len(name)]+prefix+name+';', name))
    return result


def model(header, current_body, reference_body):
    parameters, ports = re.search(r'module\s+conv_im2col_group_ranges\s*#\((.*?)\)\s*\((.*?)\);',
                                  header, re.S).groups()
    parameter_names = re.findall(r'\bparameter\s+\w+\s+(p_\w+)\s*=', parameters)
    params = ','.join(f'.{name}({name})' for name in parameter_names)
    inputs = declarations(ports, 'input')
    outputs = declarations(ports, 'output')
    input_connections = ','.join('.'+name+'('+name+')' for _, name in inputs)
    actual_connections = ','.join('.'+name+'('+name+')' for _, name in outputs)
    reference_connections = ','.join('.'+name+'(reference_'+name+')' for _, name in outputs)
    result = 'module ranges_actual #(\n'+parameters+') (\n'+ports+');\n'+current_body+'endmodule\n'
    result += 'module ranges_reference #(\n'+parameters+') (\n'+ports+');\n'+reference_body+'endmodule\n'
    result += 'module ranges_proof #(\n'+parameters+') (\n'+ports+', output logic equivalent);\n'
    result += '\n'.join(decl for decl, _ in declarations(ports, 'output', 'reference_'))+'\n'
    result += f'ranges_actual #({params}) u_actual({input_connections},{actual_connections});\n'
    result += f'ranges_reference #({params}) u_reference({input_connections},{reference_connections});\n'
    result += 'assign equivalent='+ '&&'.join(
        f'({name}===reference_{name})' for _, name in outputs)+';\nendmodule\n'
    return result, ports


def bench(ports, lanes, narrow, contiguous):
    saved = max(4, 1 << (lanes-1).bit_length())
    inputs = declarations(ports, 'input')
    outputs = declarations(ports, 'output')
    declarations_text = '\n'.join(decl for decl, _ in inputs+outputs)
    bits = 150+saved+5*lanes
    words = (bits+31)//32
    parameter_values = f'.p_lanes({lanes}),.p_narrow_lanes({narrow}),.p_saved_group_lanes({saved}),.p_contiguous_chunk({contiguous})'
    names = ','.join(name for _, name in inputs)
    return f'''module tb;
localparam integer p_lanes={lanes},p_narrow_lanes={narrow},p_saved_group_lanes={saved};
{declarations_text}
logic [{bits-1}:0] stimulus,known_stimulus;
logic [{words*32-1}:0] random_value;
wire equivalent;
integer checks=0;
assign {{{names}}}=stimulus;
ranges_proof #({parameter_values}) dut(.*);
task automatic check;
 #1;
 if(equivalent!==1'b1)$fatal(1,"Group ranges differ lanes={lanes} input=%h",stimulus);
 checks++;
endtask
initial begin
 stimulus='0;check();stimulus='1;check();
 for(integer trial=0;trial<16;trial++)begin
  for(integer word_index=0;word_index<{words};word_index++)
   random_value[32*word_index+:32]=$urandom;
  stimulus=random_value;known_stimulus=stimulus;check();
  for(integer bit_index=0;bit_index<{bits};bit_index++)begin
   stimulus=known_stimulus;stimulus[bit_index]=1'bx;check();
   stimulus=known_stimulus;stimulus[bit_index]=1'bz;check();
  end
  stimulus='x;check();stimulus='z;check();
 end
 $display("GROUP_RANGES_PASS checks=%0d",checks);$finish;
end
endmodule
''', 2+16*(2*bits+3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, nargs='*', default=[])
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    overrides = {path.name: path.resolve() for path in args.candidate}
    names = ('conv_im2col_group_ranges.sv', 'conv_channel_increment_match.sv',
             'conv_group_range_select.sv', 'conv_group_high_compare.sv',
             'conv_group_lane_range.sv', 'conv_descriptor_match.sv')
    sources = [overrides.get(name, ROOT/'rtl/npu/conv'/name) for name in names]
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies(sources+[ROOT/'rtl/common/onehot_mux.sv',
                                   ROOT/'rtl/common/increment_equal.sv'], ROOT)
    stream = overrides.get('conv_im2col_stream.sv', ROOT/'rtl/npu/conv/conv_im2col_stream.sv')
    helper = overrides.get(names[0], ROOT/'rtl/npu/conv'/names[0])
    reference = subprocess.check_output(['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_stream.sv'],
                                        cwd=ROOT, text=True)
    generated = out/'ranges_proof.sv'
    code, ports = model(helper.read_text(), range_body(stream.read_text()), range_body(reference))
    generated.write_text(code)
    hashes = {str(path): digest(path) for path in [*sources, stream]}
    formal, simulations = [], []
    simulation_sources = []
    for path in sources:
        target = out/('simulation_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    for lanes, narrow, contiguous in CASES:
        saved = max(4, 1 << (lanes-1).bit_length())
        name = f'lanes{lanes}_narrow{narrow}_contiguous{contiguous}'
        script, log = out/(name+'.ys'), out/(name+'_formal.log')
        options = [f'-Gp_lanes={lanes}', f'-Gp_narrow_lanes={narrow}',
                   f'-Gp_saved_group_lanes={saved}', f'-Gp_contiguous_chunk={contiguous}']
        script.write_text(slang_command()+'--top ranges_proof '+shlex.join(
            [*options, *map(str, sources), str(generated)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top ranges_proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('通道范围形式证明未完成')
        formal.append(dict(name=name, passed=True, log_sha256=digest(log)))
        test, checks = bench(ports, lanes, narrow, contiguous)
        generated_bench = out/(name+'_tb.sv')
        generated_bench.write_text(test)
        binary = out/(name+'.vvp')
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *simulation_sources,
             generated, generated_bench], out/(name+'_compile.log'))
        log = out/(name+'_simulation.log')
        run(['vvp', binary], log)
        if f'GROUP_RANGES_PASS checks={checks}' not in log.read_text():
            raise ValueError('通道范围四态检查未完成')
        simulations.append(dict(name=name, checks=checks, passed=True, log_sha256=digest(log)))
        print(name+': PASS', flush=True)
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], reference=args.reference,
                  source_sha256=hashes, formal=formal, four_state=simulations,
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest())
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
