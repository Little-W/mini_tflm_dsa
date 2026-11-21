#!/usr/bin/env python3
"""证明共享通道增量与每种步长独立计算的范围标志完全等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
RELATIVE = 'rtl/npu/conv/conv_im2col_frontend.sv'


def range_module(name, source, arithmetic):
    start = source.index('  if (LANES <= 8) begin : g_short_group_lane')
    stop = source.index('  end else if (LANES <= 32768) begin : g_group_lane_range', start)
    actual = source[start:stop] + '\n  end\n'
    return '''module ''' + name + ''' #(
    parameter int LANES=8,
    parameter int p_saved_group_lanes=LANES>4 ? 8 : 4
) (
    input logic [15:0] group_c, ch_q,
    input logic [LANES-1:0] chunk_lane_allowed,
    output logic [p_saved_group_lanes:0] value, configured_value
);
    localparam int CHUNK_COUNT_W=$clog2(LANES+1);
    typedef struct packed {logic [15:0] group_c;} config_t;
    config_t c, cfg;
    logic [5:0][15:0] group_range_channel;
    logic [5:0][p_saved_group_lanes:0] group_range_next;
    logic [p_saved_group_lanes:0] group_range_cfg, group_range_q;
    logic [p_saved_group_lanes:1] group_at_least_q;
    logic [p_saved_group_lanes-1:0][15:0] group_last_channels_q;
    logic [LANES-1:0] group_lane_allowed;
    logic group_after_chunk;
    logic [15:0] next_channel;
    logic [16:0] channel_position_sum;
    logic unused_channel_position_carry;
    logic [CHUNK_COUNT_W-1:0] chunk_count;
    assign c.group_c=group_c;
    assign cfg.group_c=group_c;
    assign group_range_q='0;
    always_comb begin
        chunk_count='0;
        for (int lane=0;lane<LANES;lane++)
            if (chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
    end
''' + arithmetic + '''
    for (genvar boundary=1;boundary<=p_saved_group_lanes;boundary++) begin : g_saved
        assign group_at_least_q[boundary]=group_c>=16'(boundary);
        assign group_last_channels_q[boundary-1]=group_c-16'(boundary);
    end
    for (genvar index=0;index<6;index++) begin : g_source_value
        assign group_range_channel[index]=index==5 ? next_channel : 16'd0;
    end
''' + actual + '''
    assign value=group_range_next[5];
    assign configured_value=group_range_cfg;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default='415a70a')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / RELATIVE
    candidate = source.read_text()
    reference = subprocess.check_output(['git', 'show', args.reference_ref + ':' + RELATIVE],
                                        cwd=ROOT, text=True)
    arithmetic = '\n'.join(re.search(pattern, candidate, re.S)[0] for pattern in (
        r'  assign channel_position_sum = .*?;',
        r'  assign \{unused_channel_position_carry, next_channel\} = .*?;'))
    proof = out / 'channel_ranges.sv'
    proof.write_text(range_module('reference_ranges', reference, arithmetic) +
        range_module('candidate_ranges', candidate, arithmetic) + '''
module channel_ranges_proof #(
    parameter int LANES=8,
    parameter int p_saved_group_lanes=LANES>4 ? 8 : 4
) (
    input logic [15:0] group_c, ch_q,
    input logic [LANES-1:0] chunk_lane_allowed,
    output logic equivalent
);
    wire [p_saved_group_lanes:0] reference_value, candidate_value;
    wire [p_saved_group_lanes:0] reference_configured, candidate_configured;
    reference_ranges #(.LANES(LANES)) u_reference (
        .value(reference_value),.configured_value(reference_configured),.*);
    candidate_ranges #(.LANES(LANES)) u_candidate (
        .value(candidate_value),.configured_value(candidate_configured),.*);
    assign equivalent=reference_value==candidate_value &&
        reference_configured==candidate_configured;
endmodule
''')
    sources = [root / 'rtl/common/add_equal.sv', proof]
    result = {'passed': True, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'reference_ref': args.reference_ref,
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(), 'runs': [],
              'input_constraints': [], 'channel_range_bits': 16}
    for lanes in (1, 2, 4, 8):
        for fpga in (0, 1):
            name = f'l{lanes}_f{fpga}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('read_slang --top channel_ranges_proof -GLANES=' + str(lanes) + ' ' +
                ('-DXILINX_FPGA=1 ' if fpga else '') + shlex.join(map(str, sources)) + '\n' +
                'prep -top channel_ranges_proof -flatten\ncheck -assert\n' +
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            result['runs'].append({'lanes': lanes, 'xilinx_fpga': bool(fpga), 'passed': True})
            print('CHANNEL_RANGES_PASS', name, flush=True)
    if result['source_sha256'] != hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError('Frontend source changed during range proof')
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
