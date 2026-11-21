#!/usr/bin/env python3
"""证明配置允许的八位输入修正值使用完整九位和值。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def formatter(text, name):
    first = text.index('  for (genvar data_lane = 0; data_lane < LANES; data_lane++) begin : g_signed_byte_offset')
    if 'offset_high_plus_one' in text:
        first = text.index('  assign {unused_offset_high_add_carry, offset_high_plus_one}')
    last = text.index('  assign stream_word =', first)
    return '''module ''' + name + '''(
 input logic [63:0] selected_word,
 input logic [15:0] input_offset,
 output logic [7:0][15:0] corrected_s8_value);
 localparam int LANES=8;
 typedef struct packed {logic[15:0]input_offset;} config_t;
 config_t c;
 assign c.input_offset=input_offset;
 logic[7:0]offset_high_plus_one,offset_high_minus_one;
 logic unused_offset_high_add_carry,unused_offset_high_sub_carry;
 logic[LANES-1:0][7:0]selected_s8_byte,corrected_s8_high;
 logic[LANES-1:0][8:0]corrected_s8_low,corrected_s8_sum;
''' + text[first:last] + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    paths = [root/'rtl/npu/conv/conv_im2col_frontend.sv'
             for root in (args.source_root, args.reference_root)]
    current, reference = [path.read_text() for path in paths]
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    validation = []
    for text in (current, reference):
        match = re.search(r'else cfg_basic_valid=cfg_basic_valid && (\$signed\(cfg.input_offset\).*?);', text)
        validation.append(match.group(1).replace('cfg.input_offset', 'input_offset'))
    if validation[0] != validation[1]:
        raise RuntimeError('Configuration range differs')
    source = args.out/'formatter.sv'
    source.write_text(formatter(current, 'current') + formatter(reference, 'reference') + '''
module proof(input logic[63:0]selected_word,input logic[15:0]input_offset,
 output logic equivalent);
 logic[7:0][15:0]current_value,reference_value;
 current u_current(.*,.corrected_s8_value(current_value));
 reference u_reference(.*,.corrected_s8_value(reference_value));
 wire valid_offset=''' + validation[0] + ''';
 assign equivalent=!valid_offset||(current_value==reference_value);
endmodule
''')
    script, log = args.out/'proof.ys', args.out/'proof.log'
    script.write_text('read_slang --top proof ' + shlex.quote(str(source)) +
                      '\nprep -top proof -flatten\ncheck -assert\n'
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w') as stream:
        run = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                              '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                             timeout=120)
    if run.returncode or 'SUCCESS!' not in log.read_text():
        raise RuntimeError(str(log))
    tb = args.out/'exhaustive.sv'
    tb.write_text('''module tb;
 logic[63:0]selected_word;
 logic[15:0]input_offset;
 logic[7:0][15:0]corrected_s8_value;
 current dut(.*);
 integer checks=0;
 integer expected;
 initial begin
  for(integer offset=-127;offset<=128;offset++)begin
   input_offset=16'(offset);
   for(integer sample=0;sample<256;sample++)begin
    for(integer lane=0;lane<8;lane++)selected_word[8*lane+:8]=8'(sample+31*lane);
    #1;
    for(integer lane=0;lane<8;lane++)begin
     expected=$signed(selected_word[8*lane+:8])+offset;
     if($signed(corrected_s8_value[lane])!==expected)$fatal(1,"formatter value");
     checks++;
    end
   end
  end
  $display("S8_FORMATTER_EXHAUSTIVE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
    binary = args.out/'exhaustive.vvp'
    subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb', '-o',
                    str(binary), str(source), str(tb)], capture_output=True, check=True)
    run = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)],
                         capture_output=True, text=True, check=True, timeout=30)
    (args.out/'exhaustive.log').write_text(run.stdout + run.stderr)
    if 'checks=524288' not in run.stdout:
        raise RuntimeError('Exhaustive input coverage')
    if hashes != [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]:
        raise RuntimeError('Source changed during verification')
    report = {'passed': True, 'source_sha256': hashes[0], 'reference_sha256': hashes[1],
              'formal_domain': 'all binary inputs within the accepted S8 offset range',
              'input_offset_min': -127, 'input_offset_max': 128, 'independent_lanes': 8,
              'exhaustive_rtl_values_checked': 524288,
              'validation_expression': validation[0],
              'proof_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
              'exhaustive_log_sha256': hashlib.sha256((args.out/'exhaustive.log').read_bytes()).hexdigest()}
    (args.out/'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('S8_FORMATTER_PASS', report)


if __name__ == '__main__':
    main()
