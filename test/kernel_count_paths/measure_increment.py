#!/usr/bin/env python3
"""在输入输出寄存器之间综合完整位宽的权重计数递增器。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from rtl_reference import read_rtl_source
from netlist_metrics import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--widths', nargs='+', type=int, default=[24, 87, 96])
    args = parser.parse_args()
    source = 'rtl/npu/loaders/kernel_loader_ctrl.sv'
    inputs = {'reference': read_rtl_source(args.reference + ':' + source, cwd=ROOT),
              'current': (ROOT / source).read_bytes()}
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'reference': args.reference, 'fpga_family': 'xc7',
              'source_sha256': {label: hashlib.sha256(data).hexdigest() for label, data in inputs.items()},
              'cases': []}
    for width in args.widths:
        if width < 1:
            raise ValueError('计数宽度必须为正整数')
        for label, data in inputs.items():
            folder = out / f'w{width}_{label}'
            folder.mkdir(exist_ok=True)
            helper = re.search(r'^module kernel_count_increment\b.*?^endmodule',
                               data.decode(), re.M | re.S)[0]
            rtl = folder / 'increment.sv'
            rtl.write_text(helper + f'''
module increment_measure(input logic clk, input logic [{width-1}:0] i_value,
    output logic [{width-1}:0] o_value);
    logic [{width-1}:0] value_q, next_value;
    always_ff @(posedge clk) begin
        value_q <= i_value;
        o_value <= next_value;
    end
    kernel_count_increment #(.p_width({width})) u_increment(
        .i_value(value_q), .o_next(next_value));
endmodule
''')
            mapped = folder / 'mapped.json'
            script = folder / 'run.ys'
            script.write_text('read_slang --top increment_measure ' + shlex.quote(str(rtl)) + '\n' +
                'synth_xilinx -top increment_measure -family xc7 -noiopad -noclkbuf -flatten\n' +
                'check -assert\nwrite_json ' + shlex.quote(str(mapped)) + '\n')
            log = folder / 'synthesis.log'
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
            design = json.loads(mapped.read_text())['modules']['increment_measure']
            measured = analyze(design)
            assert measured['paths']['graph_complete']
            entry = {'width': width, 'label': label, 'resources': measured['resources'],
                     'longest_register_path_cells': measured['paths']['longest_register_path_cells'],
                     'rtl_sha256': hashlib.sha256(rtl.read_bytes()).hexdigest(),
                     'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
            report['cases'].append(entry)
            (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'width': width, 'label': label,
                'lut': entry['resources']['logic_lut_cells'], 'carry4': entry['resources']['carry4'],
                'depth': entry['longest_register_path_cells']}), flush=True)
    assert inputs['current'] == (ROOT / source).read_bytes()


if __name__ == '__main__':
    main()
