#!/usr/bin/env python3
"""Prove the actual IS bias group arithmetic for all input values and prepare measurements."""
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
    first = text.index('        wire [REG_WIDTH-1:0] is_bias_group_rows_target_ext =')
    last = text.index('        wire [REG_WIDTH-1:0] is_bias_group_base_plus', first)
    return f'''module {name} #(
    parameter int REG_WIDTH=32, IS_BIAS_VALID_W=10
) (
    input logic [31:0] exec_m,
    input logic [IS_BIAS_VALID_W-1:0] is_bias_group_rows_target,
    output logic [REG_WIDTH+2*IS_BIAS_VALID_W-1:0] result
);
''' + text[first:last] + (
        '\nassign result={is_bias_last_group_base_calc,is_bias_tail_rows_calc,is_bias_first_rows_valid};\nendmodule\n')


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
    harness.write_text('''module group_formal #(
    parameter int REG_WIDTH=32, IS_BIAS_VALID_W=10
) (
    input logic [31:0] exec_m,
    input logic [IS_BIAS_VALID_W-1:0] is_bias_group_rows_target,
    output logic o_equal
);
    logic [REG_WIDTH+2*IS_BIAS_VALID_W-1:0] reference_result, candidate_result;
    reference #(.REG_WIDTH(REG_WIDTH),.IS_BIAS_VALID_W(IS_BIAS_VALID_W))
        u_reference (.*, .result(reference_result));
    candidate #(.REG_WIDTH(REG_WIDTH),.IS_BIAS_VALID_W(IS_BIAS_VALID_W))
        u_candidate (.*, .result(candidate_result));
    assign o_equal = reference_result == candidate_result;
endmodule
''')
    compare = ROOT / 'rtl/common/unsigned_compare.sv'
    files = [compare, out / 'reference.sv', out / 'candidate.sv', harness]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(reference=args.reference, source_sha256=digest(path), inputs_constrained=False, runs=[])
    profiles = [(4,1),(4,4),(8,6),(16,8),(32,1),(32,5),(32,10),(32,16),
                (32,32),(40,10),(40,32),(64,10),(64,20),(64,24),(64,32)]
    for fpga in (False, True):
        for width, count in profiles:
            folder = out / f'{"fpga" if fpga else "generic"}_w{width}_c{count}'
            folder.mkdir(exist_ok=True)
            script, log = folder / 'run.ys', folder / 'formal.log'
            script.write_text('read_slang --top group_formal ' + ('-D XILINX_FPGA ' if fpga else '') +
                              f'-GREG_WIDTH={width} -GIS_BIAS_VALID_W={count} ' +
                              shlex.join(map(str, files)) + '\nprep -top group_formal -flatten\ncheck -assert\n' +
                              'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise RuntimeError(f'Proof did not complete: {log}')
            report['runs'].append(dict(width=width, count_bits=count, fpga=fpga, passed=True, log_sha256=digest(log)))
            print(f'width={width} count_bits={count}: PASS', flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    cases = {}
    for label in ('reference', 'candidate'):
        path = out / (label + '_measure.sv')
        path.write_text(f'''module group_measure (
    input logic clk,
    input logic [31:0] i_rows,
    input logic [9:0] i_target,
    output logic [51:0] o_result
);
    logic [31:0] exec_m;
    logic [9:0] is_bias_group_rows_target;
    logic [51:0] result;
    always_ff @(posedge clk) begin
        exec_m <= i_rows;
        is_bias_group_rows_target <= i_target;
        o_result <= result;
    end
    {label} u_group (.*);
endmodule
''')
        cases[label] = dict(top='group_measure', options=['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'],
                            sources=[str(compare), str(out / (label + '.sv')), str(path)],
                            configuration='32-bit geometry and ten-bit group size')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
