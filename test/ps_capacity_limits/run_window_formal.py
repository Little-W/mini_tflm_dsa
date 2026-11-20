#!/usr/bin/env python3
"""Prove the actual bounded column count for every field value and prepare measurements."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def extract(text, name):
    first = text.index('        wire [63:0] ps_output_column_tiles =')
    last = text.index('        wire [63:0] ps_live_frames =', first)
    return f'''module {name} #(
    parameter int REG_WIDTH=32, SIZE=16, CAP_FRAMES_W=5, W_REUSE_W=5
) (
    input logic [REG_WIDTH-1:0] cfg_stream_m_s2,
    input logic [W_REUSE_W-1:0] ext_w_small,
    input logic ext_w_legal,
    output logic [CAP_FRAMES_W-1:0] ps_frames_bounded_calc
);
    localparam int SIZE_SHIFT=$clog2(SIZE);
''' + text[first:last] + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = ROOT / 'rtl/npu/top/npu_top.sv'
    reference = read_rtl_source(args.reference + ':rtl/npu/top/npu_top.sv', cwd=ROOT, text=True)
    for label, source in (('reference', reference), ('candidate', path.read_text())):
        (out / (label + '.sv')).write_text(extract(source, label))
    harness = out / 'formal.sv'
    harness.write_text('''module window_formal #(
    parameter int REG_WIDTH=32, SIZE=16, CAP_FRAMES_W=5, W_REUSE_W=5
) (
    input logic [REG_WIDTH-1:0] cfg_stream_m_s2,
    input logic [W_REUSE_W-1:0] ext_w_small,
    input logic ext_w_legal,
    output logic o_equal
);
    logic [CAP_FRAMES_W-1:0] reference_count, candidate_count;
    reference #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE),.CAP_FRAMES_W(CAP_FRAMES_W),.W_REUSE_W(W_REUSE_W))
        u_reference (.*, .ps_frames_bounded_calc(reference_count));
    candidate #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE),.CAP_FRAMES_W(CAP_FRAMES_W),.W_REUSE_W(W_REUSE_W))
        u_candidate (.*, .ps_frames_bounded_calc(candidate_count));
    assign o_equal = reference_count == candidate_count;
endmodule
''')
    files = [out / 'reference.sv', out / 'candidate.sv', harness]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(reference=args.reference, source_sha256=digest(path), inputs_constrained=False, runs=[])
    profiles = [(width, size, 5, 5) for width in (4,16,32,64) for size in (1,3,16,32)]
    profiles += [(32,16,1,3), (64,17,8,8), (64,16,4,6)]
    for width, size, capacity, window in profiles:
        folder = out / f'w{width}_s{size}_c{capacity}_r{window}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('read_slang --top window_formal ' +
                          f'-GREG_WIDTH={width} -GSIZE={size} -GCAP_FRAMES_W={capacity} -GW_REUSE_W={window} ' +
                          shlex.join(map(str, files)) + '\nprep -top window_formal -flatten\ncheck -assert\n' +
                          'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError(f'Proof did not complete: {log}')
        report['runs'].append(dict(width=width, size=size, capacity_bits=capacity,
                                  window_bits=window, passed=True, log_sha256=digest(log)))
        print(f'width={width} size={size} capacity={capacity} window={window}: PASS', flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    cases = {}
    for label in ('reference', 'candidate'):
        path = out / (label + '_measure.sv')
        path.write_text(f'''module window_measure (
    input logic clk,
    input logic [31:0] i_columns,
    input logic [4:0] i_window,
    input logic i_legal,
    output logic [4:0] o_count
);
    logic [31:0] cfg_stream_m_s2;
    logic [4:0] ext_w_small, count;
    logic ext_w_legal;
    always_ff @(posedge clk) begin
        cfg_stream_m_s2 <= i_columns;
        ext_w_small <= i_window;
        ext_w_legal <= i_legal;
        o_count <= count;
    end
    {label} u_window (.*, .ps_frames_bounded_calc(count));
endmodule
''')
        cases[label] = dict(top='window_measure', options=['-D', 'SYNTHESIS=1'],
                            sources=[str(out / (label + '.sv')), str(path)],
                            configuration='32-bit columns, 16 columns per tile, five-bit window count')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
