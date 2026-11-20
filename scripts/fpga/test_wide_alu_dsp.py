#!/usr/bin/env python3
"""使用 Yosys 官方算术与 DSP 模型证明宽算术映射的全部输出。"""
from __future__ import annotations

import argparse
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
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        cells = json.loads(args.selected_netlist.read_text())['modules'][args.top]['cells']
        selection = json.loads(args.selection.read_text())
        if selection['input_sha256'] != digest(args.selected_netlist):
            raise RuntimeError('Selection does not describe the supplied arithmetic netlist')
        values = []
        for item in selection['selected']:
            parameters = cells[item['cell']]['parameters']
            config = tuple(value if isinstance(value, int) else int(value, 2)
                           for value in (parameters[key] for key in ('A_WIDTH', 'B_WIDTH', 'Y_WIDTH', 'A_SIGNED', 'B_SIGNED')))
            values.append(config)
        configurations = sorted(set(values))
        selected_inputs = {'selected_netlist_sha256': digest(args.selected_netlist),
                           'selection_sha256': digest(args.selection), 'selected_cell_count': len(values)}
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
        'method': 'Combinational SAT over every defined input; official Yosys $alu and DSP48E1 models',
        'properties': ['X equality', 'Y equality', 'all CO bits equality'],
        'source_sha256': {str(mapping): digest(mapping), str(library): digest(library),
                          str(arithmetic): digest(arithmetic)},
        'runs': [],
        'selected_inputs': selected_inputs,
    }
    for a_width, b_width, y_width, a_signed, b_signed in configurations:
        name = f'a{a_width}_b{b_width}_y{y_width}_s{a_signed}{b_signed}'
        run = folder / name
        run.mkdir(exist_ok=True)
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
        script = run / 'formal.ys'
        script.write_text('read_verilog -formal -sv -D VERIFIC ' +
                          ' '.join(shlex.quote(str(path)) for path in (mapping, models, harness)) + '\n'
                          'prep -top formal_alu -flatten\nchformal -lower\nopt_clean\n'
                          'sat -prove-asserts -verify -set-def-inputs -show-inputs -show-outputs\n')
        with (run / 'formal.log').open('w') as output:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--out', str(folder),
                                      '--worker', str(script)], stdout=output, stderr=subprocess.STDOUT)
        log = (run / 'formal.log').read_text()
        passed = process.returncode == 0 and 'SAT proof finished - no model found: SUCCESS' in log
        summary['runs'].append({'case': name, 'a_width': a_width, 'b_width': b_width, 'y_width': y_width,
                                'a_signed': a_signed, 'b_signed': b_signed,
                                'defined_input_bits': a_width + b_width + 2, 'passed': passed})
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
