#!/usr/bin/env python3
"""证明实际有符号字节偏移逻辑的全部输入组合。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = source_root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    source = path.read_text()
    first = source.index('  // 偏移高字节的相邻值共用计算')
    last = source.index('  assign stream_word =', first)
    test = out / 'offset.sv'
    test.write_text('''module offset_check #(parameter int LANES=8, WORD_WIDTH=64)(
input logic[WORD_WIDTH-1:0] selected_word,
input logic signed[15:0] input_offset,output logic equivalent);
typedef struct packed {logic signed[15:0] input_offset;} config_t;
config_t c;
logic[7:0] offset_high_plus_one,offset_high_minus_one;
logic unused_offset_high_add_carry,unused_offset_high_sub_carry;
logic[LANES-1:0][7:0] selected_s8_byte,corrected_s8_high;
logic[LANES-1:0][8:0] corrected_s8_low;
logic[LANES-1:0][15:0] corrected_s8_value,expected_value;
assign c.input_offset=input_offset;
''' + source[first:last] + '''
for(genvar lane=0;lane<LANES;lane++)begin:g_expected
 logic signed[7:0] sample;
 assign sample=8'(selected_word>>(8*lane));
 assign expected_value[lane]=16'(sample)+input_offset;
end
assign equivalent=corrected_s8_value==expected_value;
endmodule
''')
    cases = []
    for lanes, width in ((1, 32), (2, 32), (4, 32), (8, 32), (8, 64), (16, 64), (16, 128)):
        name = f'lanes{lanes}_word{width}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text(f'read_slang --top offset_check -GLANES={lanes} -GWORD_WIDTH={width} ' +
            shlex.quote(str(test)) + '\nprep -top offset_check -flatten\n' +
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        cases.append({'lanes': lanes, 'word_width': width, 'passed': True})
        print('FRONTEND_OFFSET_PROOF_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'cases': cases,
        'input_assumptions': [], 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'proof_sha256': hashlib.sha256(test.read_bytes()).hexdigest()}, indent=2) + '\n')


if __name__ == '__main__':
    main()
