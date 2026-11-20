#!/usr/bin/env python3
"""从预测器 RTL 提取坐标运算，证明预计算与完整有符号运算逐位一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/cache/conv_next_use_predictor.sv'


def expression(source, name):
    match = re.search(r'\b' + name + r'\s*(?:<=|=)\s*([^;]+);', source)
    if match is None:
        raise ValueError(f'coordinate assignment missing: {name}')
    return match.group(1)


def coordinate_module(source, name):
    width = re.search(r'logic signed \[(\d+):0\] ny_s0, nx_s0;', source)
    if width is None:
        raise ValueError('coordinate declaration missing')
    high = int(width.group(1))
    if 'logic [32:0] y_pad_q, x_pad_q;' in source:
        saved = 'logic [32:0] y_pad_q, x_pad_q;\n'
        for axis in ('y', 'x'):
            match = re.search(r'\b' + axis + r'_pad_q\s*<=\s*([^;]*input_' + axis + r'[^;]*);', source)
            if match is None:
                raise ValueError(f'start coordinate assignment missing: {axis}')
            saved += 'assign ' + axis + '_pad_q = ' + match.group(1) + ';\n'
    else:
        saved = 'logic [31:0] y_q, x_q;\nassign y_q = input_y;\nassign x_q = input_x;\n'
    assignments = '\n'.join(f'assign {signal} = {expression(source, signal)};'
                            for signal in ('ny_s0', 'nx_s0', 'oy_s0', 'ox_s0', 'coordinate_good_s0'))
    return f'''module {name} (
  input logic [31:0] input_y, input_x, mul_y_s0, mul_x_s0, y_limit_q, x_limit_q,
  input logic [15:0] ph_q, pw_q, h_mask_q, w_mask_q,
  input logic [5:0] h_shift_q, w_shift_q,
  output logic signed [63:0] o_y_numerator, o_x_numerator,
  output logic [31:0] o_y, o_x,
  output logic o_good
);
{saved}
logic signed [{high}:0] ny_s0, nx_s0;
logic [31:0] oy_s0, ox_s0;
logic coordinate_good_s0;
{assignments}
assign o_y_numerator = ny_s0;
assign o_x_numerator = nx_s0;
assign o_y = oy_s0;
assign o_x = ox_s0;
assign o_good = coordinate_good_s0;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='aa2ef9a3')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    (out / 'reference_predictor.sv').write_text(old)
    (out / 'current_predictor.sv').write_text(current)
    proof = out / 'coordinate_miter.sv'
    proof.write_text(coordinate_module(old, 'coordinate_reference') +
                     coordinate_module(current, 'coordinate_current') + '''
module coordinate_miter (
  input logic [31:0] input_y, input_x, mul_y_s0, mul_x_s0, y_limit_q, x_limit_q,
  input logic [15:0] ph_q, pw_q, h_mask_q, w_mask_q,
  input logic [5:0] h_shift_q, w_shift_q,
  output logic o_equivalent
);
  logic signed [63:0] old_y_numerator, old_x_numerator, new_y_numerator, new_x_numerator;
  logic [31:0] old_y, old_x, new_y, new_x;
  logic old_good, new_good;
  coordinate_reference u_reference (.o_y_numerator(old_y_numerator), .o_x_numerator(old_x_numerator),
    .o_y(old_y), .o_x(old_x), .o_good(old_good), .*);
  coordinate_current u_current (.o_y_numerator(new_y_numerator), .o_x_numerator(new_x_numerator),
    .o_y(new_y), .o_x(new_x), .o_good(new_good), .*);
  assign o_equivalent = {old_y_numerator,old_x_numerator,old_y,old_x,old_good} ==
                        {new_y_numerator,new_x_numerator,new_y,new_x,new_good};
endmodule
''')
    script = out / 'run.ys'
    script.write_text('read_slang --top coordinate_miter ' + shlex.quote(str(proof)) + '\n' +
                      'prep -top coordinate_miter -flatten\n' +
                      'sat -verify -prove o_equivalent 1 -show-inputs -show-outputs\n')
    log_path = out / 'proof.log'
    with log_path.open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
    if 'SAT proof finished - no model found: SUCCESS!' not in log_path.read_text():
        raise AssertionError('SAT success marker missing')
    result = {'passed': True, 'reference_ref': args.reference_ref,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(old.encode()).hexdigest(),
              'scope': 'all input bit patterns for both coordinate numerators, shifts and validity',
              'inputs_constrained': False}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PREDICTOR_ARITHMETIC_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
