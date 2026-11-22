#!/usr/bin/env python3
"""验证前端通道递增后范围的完整模运算关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'test/frontend_pipeline'))
from source_sections import read_module
SOURCE = Path('rtl/npu/conv/conv_im2col_frontend.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit(source: str, lanes: int) -> str:
    first = source.index('      if (source == 5) begin : g_stream_advance\n')
    first = source.index('\n', first) + 1
    last = source.index('      end else begin : g_direct_range', first)
    body = source[first:last].replace('c.group_c', 'group_c').replace('group_range_next[source]', 'actual').replace('group_range_next[0]', 'initial_range')
    qualifier_start = body.index('        for (genvar lane = 0; lane < LANES; lane++) begin : g_transfer_lane')
    qualifier_end = body.index('        assign remaining =', qualifier_start)
    body = (body[:qualifier_start] + body[qualifier_end:]).replace(
        'transfer_selected[step] &&', 'chunk_selected[step] &&')
    return f'''module comparison #(
  parameter int LANES={lanes},
  parameter int p_saved_group_lanes=LANES>4 ? 8 : 4,
  parameter int CHUNK_COUNT_W=$clog2(LANES+1)
) (
  input logic [15:0] group_c,ch_q,
  input logic [CHUNK_COUNT_W-1:0] chunk_count,
  input logic [p_saved_group_lanes:0] group_range_q,initial_range,
  output logic equivalent
);
  logic [LANES:0] chunk_selected;
  logic [p_saved_group_lanes:0] actual,expected,group_transfer_range,expected_transfer;
  logic [LANES:0] selected_group_end;
  logic [15:0] next_channel;
  logic unused_channel_carry;
  logic [16:0] expected_remaining;
  assign {{unused_channel_carry,next_channel}}={{1'b0,ch_q}}+17'(chunk_count);
  assign expected_remaining={{1'b0,group_c}}-{{1'b0,next_channel}};
  for(genvar step=0;step<=LANES;step++) begin : g_step_select
    assign chunk_selected[step]=chunk_count==CHUNK_COUNT_W'(step);
    if(step==0)begin:g_zero
      assign selected_group_end[step]=chunk_selected[step]&&!group_range_q[0];
    end else begin:g_nonzero
      assign selected_group_end[step]=chunk_selected[step]&&group_range_q[step-1]&&!group_range_q[step];
    end
  end
  for(genvar lane=0;lane<=p_saved_group_lanes;lane++) begin : g_reference
    assign expected[lane]=17'(lane)<expected_remaining;
  end
{body}
  assign expected_transfer=(|selected_group_end)?initial_range:expected;
  assign equivalent=(int'(chunk_count)>LANES)||
      ((actual==expected)&&(group_transfer_range==expected_transfer));
endmodule
'''


def guard_unit(source: str, lanes: int, contiguous: bool, narrow_lanes: int) -> str:
    first = source.index('        for (genvar lane = 0; lane < LANES; lane++) begin : g_transfer_lane')
    last = source.index('        assign remaining =', first)
    transfer = source[first:last]
    first = source.index('  assign chunk_selected[0]')
    following = ('  logic incoming_request', '  if (CHUNK_COUNT_W + 1 < 32)')
    last = min(source.index(marker, first) for marker in following if marker in source[first:])
    selection = source[first:last]
    context = re.search(r'    assign lane_context_allowed\[lane\] =.*?;', source, re.S).group(0)
    data = re.search(r'    assign chunk_data_allowed\[lane\] =.*?;', source, re.S).group(0)
    actual = re.search(r'      chunk_lane_allowed\[lane\] =.*?;', source, re.S).group(0).strip()
    return f'''module comparison #(
parameter int LANES={lanes},NARROW_LANES={narrow_lanes},p_saved_group_lanes=LANES>4?8:4,
parameter bit p_contiguous_chunk=1'b{int(contiguous)}
)(
input logic [p_saved_group_lanes:0] group_range_q,
input logic [LANES:0] active_lane_allowed_q,column_lane_allowed_q,
input logic [LANES-1:0] word_lane_allowed,
input logic narrow_output,word_output_q,past_active_q,
input logic chunk_reaches_end,active_after_chunk,
output logic equivalent
);
logic [LANES-1:0] group_lane_allowed,lane_context_allowed,chunk_data_allowed,chunk_lane_allowed,transfer_lane_allowed;
logic [LANES:0] chunk_selected,transfer_selected;
assign group_lane_allowed=group_range_q[LANES-1:0];
for(genvar lane=0;lane<LANES;lane++)begin:g_actual
{context}
{data}
assign {actual}
end
{selection}
{transfer}
// 递增范围仅在有效列尚未结束时保存，换行使用独立的行首范围。
assign equivalent=chunk_reaches_end||past_active_q||!active_after_chunk||
                  (chunk_selected==transfer_selected);
endmodule
'''


def row_unit(source: str, lanes: int, narrow_lanes: int) -> str:
    start = source.index('    if (TILE_COUNT_W >= CHUNK_COUNT_W) begin : g_complete_column')
    end = source.index('    end else begin : g_wrapped_column', start)
    actual_lane = source[start:end]
    actual_lane = actual_lane[actual_lane.index('      // 数据区和补零区'):]
    start = source.index('  if (TILE_COUNT_W >= CHUNK_COUNT_W) begin : g_direct_chunk_end')
    end = source.index('  end else begin : g_narrow_chunk_end', start)
    actual_end = source[source.index('\n', start)+1:end].replace('c.input_s16', 'input_s16')
    return f'''module comparison #(
parameter int LANES={lanes},NARROW_LANES={narrow_lanes}
)(
input logic [LANES-1:0] group_lane_allowed,word_s8,word_s16,
input logic [LANES:0] active_lane_allowed_q,column_lane_allowed_q,
input logic narrow_output,word_output_q,past_active_q,input_s16,
output logic actual_end,expected_end,equivalent
);
logic [LANES-1:0] chunk_end_s8,chunk_end_s16,chunk_padding_end_s8,chunk_padding_end_s16;
logic [LANES-1:0] expected_s8,expected_s16,chunk_end_lane;
logic chunk_reaches_end;
assign chunk_end_lane='0;
for(genvar lane=0;lane<LANES;lane++)begin:g_lane
 logic allowed_s8,allowed_s16;
 assign allowed_s8=word_s8[lane];
 assign allowed_s16=word_s16[lane];
{actual_lane}
 assign expected_s8[lane]=(!narrow_output||lane<NARROW_LANES)&&
    (past_active_q||(group_lane_allowed[lane]&&active_lane_allowed_q[lane]))&&
    column_lane_allowed_q[lane]&&!column_lane_allowed_q[lane+1]&&(!word_output_q||allowed_s8);
 assign expected_s16[lane]=(!narrow_output||lane<NARROW_LANES)&&
    (past_active_q||(group_lane_allowed[lane]&&active_lane_allowed_q[lane]))&&
    column_lane_allowed_q[lane]&&!column_lane_allowed_q[lane+1]&&(!word_output_q||allowed_s16);
end
{actual_end}
assign actual_end=chunk_reaches_end;
assign expected_end=!column_lane_allowed_q[0]||(input_s16?(|expected_s16):(|expected_s8));
assign equivalent=actual_end===expected_end;
endmodule
'''


def four_state(source: str, out: Path) -> dict:
    rtl = out / 'row_four_state.sv'
    text = []
    for lanes in (1, 2, 4, 8):
        text.append(row_unit(source, lanes, min(lanes, 4)).replace('module comparison #(', f'module comparison_{lanes} #('))
    text.append('''module tb;
logic [7:0] group_lane,word_s8,word_s16;
logic [8:0] active_lane,column_lane;
logic narrow,word_output,past_active,input_s16;
logic [3:0] actual_end,expected_end,equivalent;
integer seed=32'h64a193d7;
integer comparisons=0;
function automatic logic random_bit;
 case($urandom_range(0,3))
  0: random_bit=1'b0;
  1: random_bit=1'b1;
  2: random_bit=1'bx;
  3: random_bit=1'bz;
 endcase
endfunction
''')
    for index, lanes in enumerate((1, 2, 4, 8)):
        text.append(f'''comparison_{lanes} u_lanes_{lanes}(
.group_lane_allowed(group_lane[{lanes-1}:0]),.word_s8(word_s8[{lanes-1}:0]),.word_s16(word_s16[{lanes-1}:0]),
.active_lane_allowed_q(active_lane[{lanes}:0]),.column_lane_allowed_q(column_lane[{lanes}:0]),
.narrow_output(narrow),.word_output_q(word_output),.past_active_q(past_active),.input_s16(input_s16),
.actual_end(actual_end[{index}]),.expected_end(expected_end[{index}]),.equivalent(equivalent[{index}]));
''')
    text.append('''initial begin
 seed=$urandom(seed);
 for(integer sample=0;sample<100000;sample++)begin
  for(integer bit_index=0;bit_index<8;bit_index++)begin
   group_lane[bit_index]=random_bit();word_s8[bit_index]=random_bit();word_s16[bit_index]=random_bit();
  end
  for(integer bit_index=0;bit_index<9;bit_index++)begin
   active_lane[bit_index]=random_bit();column_lane[bit_index]=random_bit();
  end
  narrow=random_bit();word_output=random_bit();past_active=random_bit();input_s16=random_bit();
  #1;
  if(equivalent!==4'b1111)$fatal(1,"row completion four-state mismatch");
  comparisons+=4;
 end
 $display("FRONTEND_ROW_FOUR_STATE_PASS comparisons=%0d",comparisons);
 $finish;
end
endmodule
''')
    rtl.write_text('\n'.join(text))
    simulator = out / 'row_four_state.vvp'
    build_log, run_log = out / 'row_four_state_build.log', out / 'row_four_state_run.log'
    with build_log.open('w') as stream:
        subprocess.run([shutil.which('iverilog') or 'iverilog', '-g2012', '-s', 'tb', '-o', str(simulator), str(rtl)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    with run_log.open('w') as stream:
        subprocess.run([shutil.which('vvp') or 'vvp', str(simulator)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    if 'FRONTEND_ROW_FOUR_STATE_PASS comparisons=400000' not in run_log.read_text():
        raise RuntimeError('行末四态比较未完成')
    return {'passed': True, 'comparisons': 400000, 'rtl_sha256': digest(rtl),
            'run_log_sha256': digest(run_log)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path, source = read_module(root, 'stream')
    rows = []
    cases = [(f'lanes_{lanes}', lanes, unit(source, lanes)) for lanes in range(1, 9)]
    cases += [(f'guard_lanes_{lanes}_narrow_{narrow_lanes}_contiguous_{int(contiguous)}', lanes,
               guard_unit(source, lanes, contiguous, narrow_lanes))
              for lanes in range(1, 9) for narrow_lanes in sorted({min(4,lanes), min(8,lanes)})
              for contiguous in (False, True)]
    cases += [(f'row_lanes_{lanes}_narrow_{narrow_lanes}', lanes, row_unit(source, lanes, narrow_lanes))
              for lanes in range(1,9) for narrow_lanes in sorted({min(4,lanes),min(8,lanes)})]
    for name, lanes, text in cases:
        rtl, script, log = [out / (name + ext) for ext in ('.sv', '.ys', '.log')]
        rtl.write_text(text)
        script.write_text(f'read_slang --top comparison {shlex.quote(str(rtl))}\n'
                          'prep -top comparison -flatten\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            completed = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        passed = completed.returncode == 0 and 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        if not passed:
            raise RuntimeError(f'范围关系验证未完成：{log}\n{log.read_text()[-5000:]}')
        rows.append({'name': name, 'lanes': lanes, 'passed': True, 'rtl_sha256': digest(rtl),
                     'script_sha256': digest(script), 'log_sha256': digest(log)})
        print('FRONTEND_GROUP_FEEDBACK_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({
        'passed': True,
        'scope': 'All 16-bit group and channel values; transfer count from zero through LANES',
        'channel_arithmetic': '16-bit wrapping increment followed by a 17-bit wrapping subtraction',
        'source_sha256': digest(source_path), 'cases': rows,
        'row_four_state': four_state(source, out),
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
