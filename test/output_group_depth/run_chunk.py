#!/usr/bin/env python3
"""Prove parallel output chunk selection against the original production expression."""
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


def extract(text, name):
    group = text[text.index('    localparam int OA_REUSE_ROWS_WIDTH='):]
    extra = ''
    marker = '    logic [3:0] oa_cfg_chunk_fit;'
    if marker in group:
        first = group.index(marker)
        last = group.index('    wire oa_ws_coalesce_pre', first)
        extra = group[first:last]
    body = group.split("3'd1: begin", 1)[1].split("3'd2: begin", 1)[0].rsplit('end', 1)[0]
    body = re.sub(r'oa_chunk_cols_pre\s*<=', 'oa_chunk_cols_pre =', body)
    return f'''module {name} #(
    parameter int REG_WIDTH=32, OA_FIFO_BANKS=32,
    parameter int OA_REUSE_ROWS_WIDTH=$clog2(OA_FIFO_BANKS+2)
) (
    input logic [REG_WIDTH-1:0] cfg_k_s2, cfg_m_s2, cfg_w_reuse_eff_s2,
    input logic [OA_REUSE_ROWS_WIDTH-1:0] oa_ws_reuse_rows_pre,
    output logic [4:0] oa_chunk_cols_pre
);
''' + extra + '    always_comb begin\n' + body + '    end\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = ROOT / 'rtl/npu/top/npu_top.sv'
    reference = read_rtl_source(args.reference + ':rtl/npu/top/npu_top.sv', cwd=ROOT, text=True)
    for label, text in (('reference', reference), ('candidate', path.read_text())):
        (out / (label + '.sv')).write_text(extract(text, label))
    harness = out / 'formal.sv'
    harness.write_text('''module chunk_formal #(
    parameter int REG_WIDTH=32, OA_FIFO_BANKS=32,
    parameter int OA_REUSE_ROWS_WIDTH=$clog2(OA_FIFO_BANKS+2)
) (
    input logic [REG_WIDTH-1:0] cfg_k_s2, cfg_m_s2, cfg_w_reuse_eff_s2,
    input logic [OA_REUSE_ROWS_WIDTH-1:0] oa_ws_reuse_rows_pre,
    output logic o_equal
);
    logic [4:0] reference_cols, candidate_cols;
    reference #(.REG_WIDTH(REG_WIDTH), .OA_FIFO_BANKS(OA_FIFO_BANKS))
        u_reference (.*, .oa_chunk_cols_pre(reference_cols));
    candidate #(.REG_WIDTH(REG_WIDTH), .OA_FIFO_BANKS(OA_FIFO_BANKS))
        u_candidate (.*, .oa_chunk_cols_pre(candidate_cols));
    assign o_equal = reference_cols == candidate_cols;
endmodule
''')
    files = [out / 'reference.sv', out / 'candidate.sv', harness]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(reference=args.reference, source_sha256=digest(path), inputs_constrained=False, runs=[])
    for width, banks in [(32, n) for n in (1,2,3,7,16,31,32,33,64,128,256,512)] + [(4,32),(16,32),(64,32)]:
        folder = out / f'w{width}_b{banks}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('read_slang --top chunk_formal ' +
                          f'-GREG_WIDTH={width} -GOA_FIFO_BANKS={banks} ' +
                          shlex.join(map(str, files)) + '\nprep -top chunk_formal -flatten\ncheck -assert\n' +
                          'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError(f'Proof did not complete: {log}')
        report['runs'].append(dict(width=width, banks=banks, passed=True, log_sha256=digest(log)))
        print(f'width={width} banks={banks}: PASS', flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    cases = {}
    for label in ('reference', 'candidate'):
        path = out / (label + '_measure.sv')
        path.write_text(f'''module chunk_measure (
    input logic clk,
    input logic [31:0] i_k, i_m, i_reuse,
    input logic [5:0] i_rows,
    output logic [4:0] o_cols
);
    logic [31:0] cfg_k_s2, cfg_m_s2, cfg_w_reuse_eff_s2;
    logic [5:0] oa_ws_reuse_rows_pre;
    logic [4:0] cols;
    always_ff @(posedge clk) begin
        cfg_k_s2 <= i_k;
        cfg_m_s2 <= i_m;
        cfg_w_reuse_eff_s2 <= i_reuse;
        oa_ws_reuse_rows_pre <= i_rows;
        o_cols <= cols;
    end
    {label} #(.REG_WIDTH(32), .OA_FIFO_BANKS(32)) u_chunk (.*, .oa_chunk_cols_pre(cols));
endmodule
''')
        cases[label] = dict(top='chunk_measure', options=['-D', 'SYNTHESIS=1'],
                            sources=[str(out / (label + '.sv')), str(path)],
                            configuration='32-bit configuration and 32 output banks; registered inputs and outputs')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
