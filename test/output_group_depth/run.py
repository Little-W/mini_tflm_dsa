#!/usr/bin/env python3
"""Prove the actual output grouping expression and prepare ordinary RTL measurements."""
from __future__ import annotations

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
from rtl_reference import read_rtl_source

TOP = 'rtl/npu/top/npu_top.sv'


def extract(source, name):
    """Use the production declarations, assignments, and phase-zero input expression."""
    group = source[source.index('    localparam int OA_REUSE_ROWS_WIDTH='):]
    width = group.split(';', 1)[0] + ';\n'
    first = re.search(r'    (?:wire|logic) \[[^\n]+\] oa_cfg_row_tiles', group).start()
    last = group.index('    logic [OA_REUSE_ROWS_WIDTH-1:0] oa_ws_reuse_rows_pre;')
    body = group[first:last]
    phase = group.split("3'd0: begin", 1)[1].split("3'd1:", 1)[0]
    result = re.search(r'oa_ws_reuse_rows_pre\s*<=\s*(.*?);', phase, re.S)[1]
    return f'''module {name} #(
    parameter int REG_WIDTH=32, OA_FIFO_BANKS=32,
    parameter int p_result_width=$clog2(OA_FIFO_BANKS+2)
) (
    input logic [REG_WIDTH-1:0] cfg_k_s2, cfg_ia_reuse_eff_s2,
    output logic [p_result_width-1:0] o_rows
);
''' + width + body + '\n    assign o_rows = ' + result + ';\nendmodule\n'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(args.reference + ':' + TOP, cwd=ROOT, text=True)
    candidate = (ROOT / TOP).read_text()
    sources = []
    for label, text in (('reference', reference), ('candidate', candidate)):
        path = out / (label + '.sv')
        path.write_text(extract(text, label))
        sources.append(path)
    harness = out / 'formal.sv'
    harness.write_text('''module output_group_formal #(
    parameter int REG_WIDTH=32, OA_FIFO_BANKS=32,
    parameter int p_result_width=$clog2(OA_FIFO_BANKS+2)
) (
    input logic [REG_WIDTH-1:0] cfg_k_s2, cfg_ia_reuse_eff_s2,
    output logic o_equal
);
    logic [p_result_width-1:0] reference_rows, candidate_rows;
    reference #(.REG_WIDTH(REG_WIDTH), .OA_FIFO_BANKS(OA_FIFO_BANKS))
        u_reference (.*, .o_rows(reference_rows));
    candidate #(.REG_WIDTH(REG_WIDTH), .OA_FIFO_BANKS(OA_FIFO_BANKS))
        u_candidate (.*, .o_rows(candidate_rows));
    assign o_equal = reference_rows == candidate_rows;
endmodule
''')
    sources.append(harness)
    configurations = [(32, n) for n in (1, 2, 3, 7, 15, 16, 31, 32, 33, 63, 64, 128, 256, 512)]
    configurations += [(4, 1), (4, 15), (4, 16), (8, 255), (8, 256),
                       (16, 32), (64, 32), (64, 1024)]
    report = {'reference': args.reference, 'inputs_constrained': False,
              'source_sha256': {TOP: digest(ROOT / TOP),
                                str(Path(__file__).relative_to(ROOT)): digest(Path(__file__))},
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'generated_sha256': {p.name: digest(p) for p in sources}, 'runs': []}
    for width, banks in configurations:
        folder = out / f'w{width}_b{banks}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('read_slang --top output_group_formal ' +
                          f'-GREG_WIDTH={width} -GOA_FIFO_BANKS={banks} ' +
                          shlex.join(map(str, sources)) + '\n' +
                          'prep -top output_group_formal -flatten\ncheck -assert\n' +
                          'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=120, check=True)
        passed = 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        report['runs'].append(dict(width=width, banks=banks, passed=passed, log_sha256=digest(log)))
        if not passed:
            raise RuntimeError(f'Proof did not complete: {log}')
        print(f'width={width} banks={banks}: PASS', flush=True)
    report['passed'] = all(run['passed'] for run in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    cases = {}
    for label in ('reference', 'candidate'):
        path = out / (label + '_measure.sv')
        path.write_text(f'''module output_group_measure (
    input logic clk,
    input logic [31:0] i_k, i_reuse,
    output logic [5:0] o_rows
);
    logic [31:0] cfg_k_s2, cfg_ia_reuse_eff_s2;
    logic [5:0] rows;
    always_ff @(posedge clk) begin
        cfg_k_s2 <= i_k;
        cfg_ia_reuse_eff_s2 <= i_reuse;
        o_rows <= rows;
    end
    {label} #(.REG_WIDTH(32), .OA_FIFO_BANKS(32)) u_group (.*, .o_rows(rows));
endmodule
''')
        cases[label] = dict(top='output_group_measure', options=['-D', 'SYNTHESIS=1'],
                            sources=[str(out / (label + '.sv')), str(path)],
                            configuration='32-bit configuration, 32 output banks, registered inputs and result')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
