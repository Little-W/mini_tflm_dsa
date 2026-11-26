#!/usr/bin/env python3
"""对完整流式模块执行输出和寄存状态的时序等价证明。"""
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


def proof_model(source):
    match = re.search(r'module conv_im2col_stream\s*#\((.*?)\)\s*\((.*?)\);', source, re.S)
    if match is None:
        raise ValueError('流式模块接口未找到')
    parameters, ports = match.groups()
    inputs, outputs, declarations = [], [], []
    port_pattern = (r'^(input|output)\s+(?:wire\s+)?(?:logic(?:\s+signed)?|[\w:]+)\s*'
                    r'(?:\[[^\]]+\]\s*)*([io]_\w+)')
    for line in ports.splitlines():
        clean = line.split('//')[0].strip().rstrip(',')
        port = re.match(port_pattern, clean)
        if port is None:
            continue
        direction, name = port.groups()
        if direction == 'input':
            inputs.append(name)
        else:
            outputs.append(name)
            declaration = re.sub(r'^output\s+', '', clean)
            declarations.append(re.sub(r'\b'+name+r'\b', 'reference_'+name, declaration)+';')
    parameter_names = re.findall(r'\bparameter\s+(?:int|bit)\s+(p_\w+)\s*=', parameters)
    parameter_connections = ','.join('.'+name+'('+name+')' for name in parameter_names)
    input_connections = ','.join('.'+name+'('+name+')' for name in inputs)
    actual_input_connections = input_connections
    if 'i_stream_operation_accept' in inputs:
        input_connections = ','.join('.'+name+'('+name+')' for name in inputs
                                     if name not in ('i_stream_operation_accept', 'i_stream_transfer_accept'))
        actual_input_connections = input_connections + (
            ',.i_stream_operation_accept(i_wr_valid && i_wr_ready && !i_tile_commit)')
    if 'i_stream_transfer_accept' in inputs:
        actual_input_connections += (',.i_stream_transfer_accept(i_wr_valid && i_wr_ready && '
            '(!i_tile_commit || (u_actual.o_chunk_reaches_end && i_row_last_q)))')
    actual_connections = ','.join('.'+name+'('+name+')' for name in outputs)
    reference_connections = ','.join('.'+name+'(reference_'+name+')' for name in outputs)
    states = ('group_range_q', 'o_ch_q', 'o_addr', 'word_available_q', 'addr_word_hit_q',
              'col_remaining', 'active_remaining', 'active_lane_allowed_q', 'column_lane_allowed_q',
              'g_tile_group_range[1].g_short_remaining.u_group_context.range_flags')
    comparisons = [f'({name}===reference_{name})' for name in outputs if name != 'o_wr_data']
    comparisons += [f'(u_actual.{name}===u_reference.{name})' for name in states]
    comparisons += ['(&sample_matches)']
    return ('module stream_proof #(\n'+parameters+') (\n'+ports+', output logic equivalent);\n'+
            '\n'.join(declarations)+'\nlogic [p_lanes-1:0] sample_matches;\n'+
            f'conv_im2col_stream #({parameter_connections}) u_actual({actual_input_connections},{actual_connections});\n'+
            f'reference_stream #({parameter_connections}) u_reference({input_connections},{reference_connections});\n'+
            'for(genvar lane=0;lane<p_lanes;lane++)begin:g_sample\n'
            ' assign sample_matches[lane]=o_wr_data[lane]===reference_o_wr_data[lane];\nend\n'+
            'assign equivalent='+'&&\n'.join(comparisons)+';\nendmodule\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, nargs='*', default=[])
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    overrides = {path.name: path.resolve() for path in args.candidate}
    names = ('conv_im2col_stream.sv', 'conv_im2col_group_ranges.sv',
             'conv_channel_increment_match.sv', 'conv_group_range_select.sv',
             'conv_group_high_compare.sv', 'conv_group_lane_range.sv', 'conv_word_step_match.sv')
    sources = [overrides.get(name, ROOT/'rtl/npu/conv'/name) for name in names]
    sources += [path for name, path in overrides.items() if name not in names]
    stream = sources[0]
    reference = subprocess.check_output(['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_stream.sv'],
                                        cwd=ROOT, text=True)
    reference_path = out/'reference_stream.sv'
    reference_path.write_text(re.sub(r'\bconv_im2col_stream\b', 'reference_stream', reference))
    generated = out/'stream_proof.sv'
    generated.write_text(proof_model(stream.read_text()))
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies([*sources, reference_path, generated], ROOT)
    include = ROOT/'include'
    hashes = {str(path): digest(path) for path in sources}
    hashes[str(include/'conv_im2col_prepared_tile.svh')] = digest(include/'conv_im2col_prepared_tile.svh')
    results = []
    for lanes, registered, synthesis in ((8, 1, 1), (8, 1, 0), (8, 0, 1), (4, 1, 1), (16, 1, 1)):
        name = f'lanes{lanes}_registered{registered}_synthesis{synthesis}'
        script, log = out/(name+'.ys'), out/(name+'.log')
        options = [f'-Gp_lanes={lanes}', f'-Gp_register_descriptor={registered}',
                   f'-Gp_register_row_address={registered}', '-Gp_line_bytes=128', '-Gp_bus_width=64']
        if synthesis:
            options.append('-DSYNTHESIS=1')
        script.write_text(slang_command(options)+'--top stream_proof -I'+str(include)+' '+shlex.join(
            [*options, *map(str, sources)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top stream_proof -flatten\nasync2sync\nopt\ncheck -assert\n'
            'sat -verify -tempinduct -seq 1 -maxsteps 4 -set-init-zero -prove equivalent 1 -show-ports\n')
        with log.open('w') as output:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, timeout=600, check=True)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise ValueError('完整流式模块的时序证明未完成')
        results.append(dict(name=name, passed=True, log_sha256=digest(log)))
        print(name+': PASS', flush=True)
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], reference=args.reference,
                  initial_state='两份电路使用同一零初值，归纳条件包含全部保存状态的相等关系。',
                  source_sha256=hashes, temporal_induction=results,
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest())
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
