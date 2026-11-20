#!/usr/bin/env python3
"""使用 Yosys 官方算术与 DSP 模型证明宽算术映射的全部输出。"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


HERE = Path(__file__).resolve().parent
CONFIGURATIONS = [
    (1, 1, 1, 0, 0), (17, 17, 17, 0, 0),
    (32, 32, 32, 0, 0), (48, 48, 48, 0, 0),
    (8, 13, 24, 0, 0), (8, 13, 24, 1, 1),
    (8, 13, 24, 1, 0), (8, 13, 24, 0, 1),
    (48, 32, 24, 0, 0), (48, 32, 24, 1, 1),
    (1, 17, 48, 1, 1), (48, 1, 48, 1, 1),
    (0, 0, 1, 0, 0), (0, 6, 34, 0, 0), (8, 0, 9, 0, 0),
    (0, 16, 34, 1, 1), (16, 0, 34, 1, 1), (0, 0, 48, 1, 1),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_case(folder, configuration, mapping, models):
    """导入真实空端口或非空端口，比较 JSON 改写后的全部 X、Y、CO。"""
    import map_wide_alu

    a_width, b_width, y_width, a_signed, b_signed = configuration
    module = {'attributes': {}, 'ports': {}, 'cells': {}, 'netnames': {}}
    connections = {}
    next_bit = 2
    widths = {'A': a_width, 'B': b_width, 'CI': 1, 'BI': 1,
              'X': y_width, 'Y': y_width, 'CO': y_width}
    directions = {name: ('input' if name in ('A', 'B', 'CI', 'BI') else 'output')
                  for name in widths}
    for name, width in widths.items():
        bits = list(range(next_bit, next_bit + width))
        next_bit += width
        module['ports'][name] = {'direction': directions[name], 'bits': bits}
        module['netnames'][name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
        connections[name] = bits
    keys = ('A_WIDTH', 'B_WIDTH', 'Y_WIDTH', 'A_SIGNED', 'B_SIGNED')
    module['cells']['alu'] = {
        'hide_name': 0, 'type': '$alu', 'attributes': {},
        'parameters': {key: format(value, '032b') for key, value in zip(keys, configuration)},
        'port_directions': directions, 'connections': connections,
    }
    current = copy.deepcopy(module)
    selection = map_wide_alu.select_cells(current, 1, minimum_width=1)
    if len(selection['selected']) != 1:
        raise RuntimeError('参数测试必须选择一个完整算术单元')
    map_wide_alu.apply_mapping(current, selection)
    commands = []
    for label, contents in (('reference', module), ('current', current)):
        design = {'modules': {'alu_case': contents}}
        netlist = folder / (label + '.json')
        netlist.write_text(json.dumps(design, indent=2) + '\n')
        autoidx = folder / (label + '.autoidx.il')
        autoidx.write_text('autoidx ' + str(map_wide_alu.next_autoidx(design)) + '\n')
        commands.extend(['read_json ' + shlex.quote(str(netlist)),
                         'read_rtlil ' + shlex.quote(str(autoidx))])
        if label == 'current':
            commands.extend(['verilog_defaults -push', 'verilog_defaults -add -sv',
                             'techmap -map ' + shlex.quote(str(mapping)),
                             'verilog_defaults -pop'])
        commands.extend(['read_verilog -sv -D VERIFIC ' + shlex.quote(str(models)),
                         'prep -top alu_case -flatten', 'check -assert',
                         'rename alu_case ' + label, 'design -stash ' + label])
    commands.extend(['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -make_assert reference current comparison',
                     'prep -top comparison -flatten', 'chformal -lower',
                     'opt -full', 'check -assert',
                     'sat -prove-asserts -verify -set-def-inputs -show-inputs -show-outputs'])
    return '\n'.join(commands) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--selected-netlist', type=Path,
                        help='pre_alu.json used by the production mapping selection')
    parser.add_argument('--selection', type=Path, help='wide_alu_mapping.json to verify')
    parser.add_argument('--top', default='soc_top')
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return

    import pyosys
    share = Path(pyosys.__file__).parent / 'share'
    library = share / 'xilinx/cells_sim.v'
    arithmetic = share / 'simlib.v'
    mapping = HERE / 'techmap/wide_alu_dsp.sv'
    configurations = CONFIGURATIONS
    selected_inputs = None
    if args.selected_netlist or args.selection:
        if not args.selected_netlist or not args.selection:
            parser.error('--selected-netlist and --selection are required together')
        # 压缩文件按解压后的 JSON 内容核对生产选择报告。
        netlist_bytes = args.selected_netlist.read_bytes()
        if args.selected_netlist.suffix == '.gz':
            netlist_bytes = gzip.decompress(netlist_bytes)
        netlist_sha256 = hashlib.sha256(netlist_bytes).hexdigest()
        cells = json.loads(netlist_bytes)['modules'][args.top]['cells']
        del netlist_bytes
        selection = json.loads(args.selection.read_text())
        if selection['input_sha256'] != netlist_sha256:
            raise RuntimeError('Selection does not describe the supplied arithmetic netlist')
        values = []
        for item in selection['selected']:
            parameters = cells[item['cell']]['parameters']
            config = tuple(value if isinstance(value, int) else int(value, 2)
                           for value in (parameters[key] for key in ('A_WIDTH', 'B_WIDTH', 'Y_WIDTH', 'A_SIGNED', 'B_SIGNED')))
            values.append(config)
        configurations = sorted(set(values))
        selected_inputs = {'selected_netlist_sha256': netlist_sha256,
                           'selection_sha256': digest(args.selection), 'selected_cell_count': len(values)}
        del cells
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    dsp_model = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(),
                          re.MULTILINE | re.DOTALL).group(0)
    dsp_model = re.sub(r'\bspecify\b.*?\bendspecify\b', '', dsp_model, flags=re.DOTALL)
    alu_model = re.search(r'^module \\\$alu\s.*?^endmodule', arithmetic.read_text(),
                          re.MULTILINE | re.DOTALL).group(0)
    alu_model = alu_model.replace('module \\$alu ', 'module reference_alu ', 1)
    models = folder / 'official_models.sv'
    models.write_text(dsp_model + '\n\n' + alu_model + '\n')
    summary = {
        'method': '全部已定义输入的组合 SAT；原生 Yosys $alu、官方 simlib 及 DSP48E1 模型',
        'properties': ['X equality', 'Y equality', 'all CO bits equality'],
        'source_sha256': {str(mapping): digest(mapping), str(library): digest(library),
                          str(arithmetic): digest(arithmetic),
                          str(HERE / 'map_wide_alu.py'): digest(HERE / 'map_wide_alu.py'),
                          str(Path(__file__).resolve()): digest(Path(__file__).resolve())},
        'runs': [],
        'selected_inputs': selected_inputs,
    }
    for a_width, b_width, y_width, a_signed, b_signed in configurations:
        name = f'a{a_width}_b{b_width}_y{y_width}_s{a_signed}{b_signed}'
        run = folder / name
        run.mkdir(exist_ok=True)
        script = run / 'formal.ys'
        if a_signed == b_signed:
            # 原生 $alu 要求两个有符号参数相同；零位连接保留为空列表。
            script.write_text(json_case(run, (a_width, b_width, y_width, a_signed, b_signed),
                                        mapping, models))
            reference_kind = '原生 $alu；实际 JSON 选择、改写及 techmap'
        else:
            # 不同符号参数用官方 simlib 检查 helper 的共同无符号扩展规则。
            harness = run / 'formal.sv'
            params = (f'.A_WIDTH({a_width}), .B_WIDTH({b_width}), .Y_WIDTH({y_width}), '
                      f'.A_SIGNED({a_signed}), .B_SIGNED({b_signed})')
            harness.write_text(
                f'module formal_alu(input [{a_width-1}:0] A, input [{b_width-1}:0] B, input CI, BI);\n'
                f'wire [{y_width-1}:0] actual_x, actual_y, actual_co, reference_x, reference_y, reference_co;\n'
                f'fpga_dsp_alu #({params}) actual (.A(A), .B(B), .CI(CI), .BI(BI), '
                '.X(actual_x), .Y(actual_y), .CO(actual_co));\n'
                f'reference_alu #({params}) reference (.A(A), .B(B), .CI(CI), .BI(BI), '
                '.X(reference_x), .Y(reference_y), .CO(reference_co));\n'
                'always @* begin\nassert(actual_x == reference_x);\n'
                'assert(actual_y == reference_y);\nassert(actual_co == reference_co);\nend\nendmodule\n')
            script.write_text('read_verilog -formal -sv -D VERIFIC ' +
                              ' '.join(shlex.quote(str(path)) for path in (mapping, models, harness)) + '\n'
                              'prep -top formal_alu -flatten\nchformal -lower\nopt_clean\ncheck -assert\n'
                              'sat -prove-asserts -verify -set-def-inputs -show-inputs -show-outputs\n')
            reference_kind = '官方 simlib $alu'
        with (run / 'formal.log').open('w') as output:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--out', str(folder),
                                      '--worker', str(script)], stdout=output, stderr=subprocess.STDOUT)
        log = (run / 'formal.log').read_text()
        passed = process.returncode == 0 and 'SAT proof finished - no model found: SUCCESS' in log
        summary['runs'].append({'case': name, 'a_width': a_width, 'b_width': b_width, 'y_width': y_width,
                                'a_signed': a_signed, 'b_signed': b_signed,
                                'defined_input_bits': a_width + b_width + 2,
                                'reference_model': reference_kind, 'connected_inputs_checked': passed,
                                'compared_output_bits': 3 * y_width,
                                'log_sha256': digest(run / 'formal.log'), 'passed': passed})
        summary['passed'] = all(item['passed'] for item in summary['runs'])
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary['runs'][-1]), flush=True)
        if not passed:
            print(log[-10000:])
            raise SystemExit(1)
    if not configurations:
        summary['passed'] = True
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
