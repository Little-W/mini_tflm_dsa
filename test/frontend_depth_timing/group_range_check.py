#!/usr/bin/env python3
"""证明常量通道资格及任意通道掩码的组合选择关系。"""
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
MARKER = '  end else if (LANES <= 32768) begin : g_group_lane_range'
END = '  end else begin : g_group_lane_range_wide'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def group_body(source):
    first = source.index(MARKER)
    last = source.index(END, first)
    return source[source.index('\n', first) + 1:last].replace('c.group_c', 'group_c')


def vector_unit(source, lanes):
    return f'''module group_vector_check #(parameter int LANES={lanes})(
input logic [15:0] group_c,ch_q,
input logic [LANES-1:0] chunk_lane_allowed,
output logic equivalent);
localparam int p_group_low_w=$clog2(LANES),p_group_high_w=16-p_group_low_w;
localparam int CHUNK_COUNT_W=$clog2(LANES+1);
logic [p_group_high_w-1:0] group_high_minus_one_q;
logic [4:0] group_range_cfg;
logic [5:0][4:0] group_range_next;
logic [LANES-1:0] group_lane_allowed,expected_lanes;
logic [CHUNK_COUNT_W-1:0] chunk_count;
logic [16:0] group_remaining;
logic group_after_chunk;
assign group_high_minus_one_q=group_c[15:p_group_low_w]-p_group_high_w'(1);
assign group_remaining={{1'b0,group_c}}-{{1'b0,ch_q}};
always_comb begin
 chunk_count='0;
 for(int lane=0;lane<LANES;lane++)
  if(chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
end
for(genvar lane=0;lane<LANES;lane++)
 assign expected_lanes[lane]=17'(lane)<group_remaining;
{group_body(source)}
assign equivalent=group_lane_allowed==expected_lanes &&
 group_after_chunk==(17'(chunk_count)<group_remaining);
endmodule
'''


def range_unit(source, low_width):
    body = group_body(source)
    first = body.index('    logic high_before_end')
    last = body.index('    for (genvar lane', first)
    high_logic = body[first:last]
    offset = re.search(r"assign lane_last_low = \{1'b0, ch_q\[p_group_low_w-1:0\]\}.*?;", body, re.S)[0]
    compare = re.search(r'assign low_before_end =.*?;', body, re.S)[0]
    value = re.search(r'assign group_range\[lane\] =.*?;', body, re.S)[0]
    value = value.replace('group_range[lane]', 'actual_range')
    return f'''module group_offset_check #(parameter int p_group_low_w={low_width})(
input logic [15:0] group_c,ch_q,
input logic [p_group_low_w:0] lane,
output logic equivalent);
localparam int p_group_high_w=16-p_group_low_w;
logic [p_group_high_w-1:0] group_high_minus_one_q;
logic [p_group_low_w:0] lane_last_low;
logic [16:0] remaining;
logic low_before_end,actual_range;
assign group_high_minus_one_q=group_c[15:p_group_low_w]-p_group_high_w'(1);
assign remaining={{1'b0,group_c}}-{{1'b0,ch_q}};
{high_logic}
{offset}
{compare}
{value}
// 实际生成的常量偏移包含最大通道数，其值始终不超过2的低段宽度次幂。
assign equivalent=lane>(p_group_low_w+1)'(1<<p_group_low_w) ||
 actual_range==(17'(lane)<remaining);
endmodule
'''


SELECTOR = '''module group_selector_check(
input logic [16:0] remaining,previous_count,
input logic [15:0] lane,
input logic selected,
output logic equivalent);
logic prior_range,next_range,candidate,reference,valid_prefix;
assign prior_range=previous_count<remaining;
assign next_range=({1'b0,lane}+17'd1)<remaining;
assign candidate=prior_range && (!selected || next_range);
assign reference=(selected ? ({1'b0,lane}+17'd1) : previous_count)<remaining;
// 逐项处理时，已经选择的项数不会超过当前项的位置。
assign valid_prefix=previous_count<={1'b0,lane} && lane<16'd32768;
assign equivalent=(remaining!=0)==(17'd0<remaining) &&
 (!valid_prefix || candidate==reference);
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = args.reference.read_text()
    candidate = args.candidate.read_text()
    body = group_body(candidate)
    if 'group_range[0] && (&(~chunk_lane_allowed | group_range[LANES:1]))' not in body:
        raise RuntimeError('实际选择表达式与归并关系不一致')
    cases = []
    for lanes in (5, 6, 7, 8, 9, 15, 16, 17, 31, 32, 33, 64, 128, 256):
        cases.append((f'vector_l{lanes}', 'group_vector_check', vector_unit(candidate, lanes)))
    for width in range(3, 16):
        cases.append((f'offset_w{width}', 'group_offset_check', range_unit(candidate, width)))
    cases.append(('selector_induction', 'group_selector_check', SELECTOR))
    rows = []
    for name, top, source in cases:
        rtl, script, log = [out / (name + suffix) for suffix in ('.sv', '.ys', '.log')]
        rtl.write_text(source)
        script.write_text(f'read_slang --top {top} {shlex.quote(str(rtl))}\n'
                          f'prep -top {top} -flatten\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=120)
        passed = completed.returncode == 0 and 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        if not passed:
            raise RuntimeError(f'通道范围证明未完成：{log}\n{log.read_text()[-5000:]}')
        rows.append({'name': name, 'passed': True, 'rtl_sha256': digest(rtl),
                     'script_sha256': digest(script), 'log_sha256': digest(log)})
        print('GROUP_RANGE_SAT_PASS', name, flush=True)
    ref_first, ref_last = reference.index(MARKER), reference.index(END)
    cand_first, cand_last = candidate.index(MARKER), candidate.index(END)
    report = {
        'passed': True, 'input_assumptions': [],
        'reference_sha256': digest(args.reference), 'candidate_sha256': digest(args.candidate),
        'unchanged_outside_group_branch': reference[:ref_first] + reference[ref_last:] ==
                                        candidate[:cand_first] + candidate[cand_last:],
        'scope': 'All 16-bit group/channel values and arbitrary lane masks for 14 complete vector configurations; symbolic constant-offset relations for low widths 3 through 15 and selector induction cover LANES 5 through 32768',
        'configuration_relation': 'group_high_minus_one_q is captured with c from the same accepted configuration; reset sets c.group_c=0 and this register to all ones',
        'cases': rows,
    }
    (out / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
