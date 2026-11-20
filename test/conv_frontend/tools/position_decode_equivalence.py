#!/usr/bin/env python3
"""证明保存的位置解码在全部消费条件下等价，并核对快速请求的资格关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[3]
SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'
POSITION_NOTE = '  // 位置解码使用已接受的描述符，快速请求的资格条件保证输入位置与保存位置相同。\n'
REFERENCE_ASSIGNMENT = '    p_decode=(state==P_DECODE || state==P_START || state==P_WAIT) ? p0 : tile_p0;'
NAMES = ('p_decode', 'p_fast_valid', 'p_fast_x', 'p_fast_y', 'p_cache_select')


def normalize_position_source(source):
    return source.replace(POSITION_NOTE, '').replace('    p_decode=p0;', REFERENCE_ASSIGNMENT)


def block(source):
    start = source.index('  always_comb begin\n    p_decode=')
    end = source.index('  always_comb begin\n    current_q_times11=', start)
    return source[start:end]


def expression(source, name):
    return re.search(r'\b' + name + r'\s*=\s*([^;]+);', source).group(1)


def audit_consumers(source):
    remaining = source.replace(block(source), '')
    for state, following in (('P_DECODE', 'P_START'), ('P_WAIT', 'Q_DECODE')):
        pattern = r'^\s*' + state + r':.*?(?=^\s*' + following + r':)'
        remaining, count = re.subn(pattern, '', remaining, flags=re.M | re.S)
        if count != 1:
            raise ValueError('Decode consumer state missing: ' + state)
    request = expression(source, 'request_output_y')
    if request != 'incoming_context ? p_fast_y : oy':
        raise ValueError('Request output-row consumer changed')
    remaining = re.sub(r'^\s*request_output_y=[^;]+;\n', '', remaining, flags=re.M)
    names = '|'.join(NAMES)
    remaining = re.sub(r'^\s*logic [^;\n]*\b(?:' + names + r')\b[^;\n]*;\n',
                       '', remaining, flags=re.M)
    remaining = re.sub(r'//[^\n]*|/\*.*?\*/', '', remaining, flags=re.S)
    if re.search(r'\b(?:' + names + r')\b', remaining):
        raise ValueError('An additional position-decode consumer requires verification')


def helper(source, name):
    enum = re.search(r'typedef enum logic \[4:0\] \{.*?\} st_t;', source, re.S).group(0)
    fields = lambda text: text.replace('c.output_w', 'cfg_output_w').replace(
        'c.group_c', 'cfg_group_c').replace('c.windowed', 'cfg_windowed')
    return f'''module {name} #(parameter int SIZE=16, CACHE_POLICY=3) (
  input logic [4:0] state_bits,
  input logic [31:0] p0, tile_p0, last_p, last_p_limit,
  input logic [15:0] last_x, last_y, cfg_output_w, cfg_group_c, ch0_q, oy_q,
  input logic [3:0] p_cache_valid,
  input logic [31:0] p_cache_key[4],
  input logic [15:0] p_cache_x[4], p_cache_y[4],
  input logic last_p_valid, cfg_windowed, row_base_valid, coordinate_address_valid,
  input logic [$clog2(SIZE+1)-1:0] rows_q, tile_rows, cols_q,
  input logic incoming_q_fast, tile_valid, wr_last,
  output logic [99:0] observations
);
localparam int CW=$clog2(SIZE);
{enum}
st_t state;
logic [31:0] p_decode, p_fast_x, p_fast_y, ch0, oy, request_output_y;
logic p_fast_valid, incoming_fast, incoming_context, qualified_position;
logic [1:0] p_cache_select;
logic [15:0] p_delta;
logic [16:0] p_sum;
assign state = st_t'(state_bits);
assign ch0 = 32'(ch0_q);
assign oy = 32'(oy_q);
assign incoming_fast = {fields(expression(source, 'incoming_fast'))};
assign incoming_context = {expression(source, 'incoming_context')};
assign request_output_y = {expression(source, 'request_output_y')};
assign qualified_position = !incoming_context || p0 == tile_p0;
{fields(block(source))}
assign observations = {{qualified_position,
    ((state == P_DECODE || state == P_WAIT) ? p_cache_select : 2'd0),
    ((state == P_DECODE) ? {{p_fast_valid,p_fast_x,p_fast_y}} : 65'd0), request_output_y}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='05be5b8')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference_ref + ':' + SOURCE, cwd=ROOT, text=True)
    if expression(current, 'p_decode') != 'p0' or block(normalize_position_source(current)) != block(reference):
        raise ValueError('Additional changes in position decoding require verification')
    for name in ('incoming_fast', 'incoming_context', 'request_output_y'):
        if expression(current, name) != expression(reference, name):
            raise ValueError('Position-decode qualification changed: ' + name)
    for state, following in (('P_DECODE', 'P_START'), ('P_WAIT', 'Q_DECODE')):
        pattern = r'^\s*' + state + r':.*?(?=^\s*' + following + r':)'
        if re.search(pattern, current, re.M | re.S).group(0) != re.search(pattern, reference, re.M | re.S).group(0):
            raise ValueError('Position-decode consumer statements changed: ' + state)
    for source in (reference, current):
        audit_consumers(source)
    top = '''module position_decode_proof #(parameter int SIZE=16, CACHE_POLICY=3) (
  input logic [4:0] state_bits,
  input logic [31:0] p0, tile_p0, last_p, last_p_limit,
  input logic [15:0] last_x, last_y, cfg_output_w, cfg_group_c, ch0_q, oy_q,
  input logic [3:0] p_cache_valid,
  input logic [31:0] p_cache_key[4],
  input logic [15:0] p_cache_x[4], p_cache_y[4],
  input logic last_p_valid, cfg_windowed, row_base_valid, coordinate_address_valid,
  input logic [$clog2(SIZE+1)-1:0] rows_q, tile_rows, cols_q,
  input logic incoming_q_fast, tile_valid, wr_last,
  output logic equivalent
);
logic [99:0] reference_observations, current_observations;
reference_decode #(.SIZE(SIZE),.CACHE_POLICY(CACHE_POLICY)) u_reference (
  .observations(reference_observations), .*
);
current_decode #(.SIZE(SIZE),.CACHE_POLICY(CACHE_POLICY)) u_current (
  .observations(current_observations), .*
);
assign equivalent = (reference_observations == current_observations) &&
                    reference_observations[99] && current_observations[99];
endmodule
'''
    rtl = out / 'position_decode.sv'
    rtl.write_text(helper(reference, 'reference_decode') + helper(current, 'current_decode') + top)
    cases = []
    for size in (4, 8, 16):
        for policy in (0, 1, 2, 3):
            name = f'size{size}_policy{policy}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text(f'read_slang --top position_decode_proof -GSIZE={size} -GCACHE_POLICY={policy} ' +
                              shlex.quote(str(rtl)) + '\n' +
                              'prep -top position_decode_proof -flatten\n' +
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise RuntimeError('Position decoding proof incomplete: ' + name)
            cases.append({'size': size, 'policy': policy, 'passed': True,
                          'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    result = {'passed': True, 'reference_ref': args.reference_ref,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'proof_source_sha256': hashlib.sha256(rtl.read_bytes()).hexdigest(),
              'inputs_constrained': False, 'observed_bits': 100,
              'qualified_request_implies_equal_positions': True,
              'consumer_audit': ['P_DECODE', 'P_WAIT', 'request_output_y'],
              'scope': 'position decoding, consumer statements and incoming-context qualification',
              'position_body_identical_except_input_selection': True, 'cases': cases}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('FRONTEND_POSITION_DECODE_EQUIVALENCE_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
