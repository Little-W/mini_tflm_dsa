#!/usr/bin/env python3
"""证明实际流式状态分支的组内范围保存、保持与三类下一值选择。"""
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
BOOLEAN_INPUTS = (
    'cache_rsp_valid cache_rsp_error wr_valid wr_ready chunk_reaches_end '
    'row_last_q row_wrap row_base_valid geometry_tile next_row_padding '
    'next_row_word_hit next_row_request cache_req_ready row_coordinate_valid '
    'past_active_q group_end_o_equal coordinate_address_valid tap_wrap '
    'next_tap_padding next_word_o_equal pad_q current_coordinate_valid '
    'ix_step_below_limit word_boundary stream_next_request'
).split()


def unit(source):
    state_type = re.search(r'  typedef enum logic \[21:0\].*?  } st_t;', source, re.S).group(0)
    start = source.index("      end else case (1'b1)",
                         source.index('  // 保存前端配置、描述符和坐标状态。'))
    start += len('      end else ')
    end = source.index('      endcase', start) + len('      endcase')
    original = source[start:end]

    # 保留实际分支控制，仅将所证明寄存器的赋值转换为组合下一值。
    def assignment(match):
        target, expression = match.groups()
        if target == 'group_range_q':
            return 'actual = ' + expression + ';'
        return ';'

    body = re.sub(r'\b([a-zA-Z_]\w*(?:\[[^\]\n]+\])?)\s*<=\s*([^;]+);',
                  assignment, original)
    helper = ''
    if 'group_range_stream_value' in source:
        start = source.index('  // 行切换、组切换和通道递增先选择范围')
        end = source.index('  // 当前通道和新描述符并行准备', start)
        helper = source[start:end]
    ports = [
        'input logic[21:0] state', 'input conv_im2col_pkg::conv_cfg_t c',
        'input logic[CHUNK_COUNT_W-1:0] chunk_count',
        'input logic[TILE_COUNT_W-1:0] active_remaining',
        'input logic[p_saved_group_lanes:0] group_range_q',
        'input logic[5:0][p_saved_group_lanes:0] group_range_next',
        *('input logic ' + name for name in BOOLEAN_INPUTS),
        'output logic equivalent',
    ]
    text = '''module comparison #(
parameter int SIZE=16,LANES=8,TILE_COUNT_W=$clog2(SIZE+1),
CHUNK_COUNT_W=$clog2(LANES+1),p_saved_group_lanes=LANES>4 && LANES<=8 ? 8 : 4
)(\n''' + ',\n'.join(ports) + ');\n' + state_type + '\n' + helper + '''
logic[p_saved_group_lanes:0] actual,expected;
always_comb begin
 actual=group_range_q;
''' + body + '''
end
always_comb begin
 expected=group_range_q;
 if ((state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]) &&
     !(state[$clog2(WAIT_WORD)] && cache_rsp_valid && cache_rsp_error) && wr_valid && wr_ready) begin
  if(chunk_reaches_end) begin
   if(!row_last_q) expected=group_range_next[1];
  end else if(!(past_active_q || TILE_COUNT_W'(chunk_count)>=active_remaining)) begin
   expected=group_end_o_equal ? group_range_next[0] : group_range_next[5];
  end
 end
end
assign equivalent=actual==expected;
endmodule
'''
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    test = out / 'range_state.sv'
    test.write_text(unit(source.read_text()))
    cases = []
    for size, lanes in ((2, 1), (2, 4), (2, 16), (16, 4), (16, 5),
                        (16, 8), (16, 16), (64, 8)):
        name = f's{size}_l{lanes}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        files = [root / 'rtl/npu/conv/conv_im2col_pkg.sv', test]
        script.write_text(f'read_slang --top comparison -GSIZE={size} -GLANES={lanes} ' +
                          shlex.join(map(str, files)) +
                          '\nprep -top comparison -flatten\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError(f'组内范围状态证明未完成: {log}')
        cases.append({'case': name, 'passed': True,
                      'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print('FRONTEND_RANGE_STATE_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({
        'passed': True, 'cases': cases, 'input_assumptions': [],
        'state_encodings': 'All 22-bit input values',
        'scope': 'Stream-state range update and hold for arbitrary next-range values',
        'frontend_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'proof_source_sha256': hashlib.sha256(test.read_bytes()).hexdigest(),
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
