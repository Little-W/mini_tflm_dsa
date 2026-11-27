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
from source_sections import read_module, dependencies
SOURCE = Path('rtl/npu/conv/conv_im2col_frontend.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source(root: Path):
    """读取流式控制和通道范围模块，统一提取模型的局部信号名称。"""
    stream_path, stream = read_module(root, 'stream')
    range_path, ranges = read_module(root, 'group_ranges')
    aliases = {'cfg_group_c': 'cfg.group_c', 'group_c': 'c.group_c',
               'channel': 'ch_q', 'channel_source': 'group_range_channel',
               'range': 'group_range_q', 'active_lane': 'active_lane_allowed_q',
               'column_lane': 'column_lane_allowed_q', 'word_lane': 'word_lane_allowed',
               'chunk_lane': 'chunk_lane_allowed', 'cfg_range': 'group_range_cfg',
               'next_range': 'group_range_next', 'transfer_range': 'group_transfer_range'}
    pattern = r'(?<![\w.$])(' + '|'.join(sorted(aliases, key=len, reverse=True)) + r')\b'
    ranges = re.sub(pattern, lambda match: aliases[match[0]], ranges)
    return [stream_path, range_path], stream + '\n' + ranges


def unit(source: str, lanes: int) -> str:
    first = source.index('      if (source == 5) begin : g_stream_advance\n')
    first = source.index('\n', first) + 1
    last = source.index('      end else begin : g_direct_range', first)
    body = source[first:last].replace('c.group_c', 'group_c').replace('group_range_next[source]', 'actual').replace('group_range_next[0]', 'initial_range')
    qualifier_start = body.index('        for (genvar lane = 0; lane < LANES; lane++) begin : g_transfer_lane')
    qualifier_end = body.index('        borrow_select_subtract #', qualifier_start) if '        borrow_select_subtract #' in body else body.index('        assign remaining =', qualifier_start)
    body = (body[:qualifier_start] + body[qualifier_end:]).replace('        logic [LANES:0] transfer_selected;\n', '').replace(
        'transfer_selected', 'chunk_selected')
    return f'''module comparison #(
  parameter int LANES={lanes},
  parameter int p_saved_group_lanes=LANES<=4 ? 4 : (1 << $clog2(LANES)),
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


def direct_range_unit(source: str, lanes: int) -> str:
    first = source.index('    localparam int p_lane_compare_width = $clog2(p_saved_group_lanes+1);')
    last = source.index('    // 配置及译码来源', first)
    configured = source[first:last].replace('cfg.group_c', 'group_c')
    first = source.index('      end else begin : g_direct_range\n', last)
    first = source.index('\n', first) + 1
    last = source.index('\n      end\n    end\n', first)
    direct = source[first:last].replace('c.group_c', 'group_c').replace(
        'group_range_channel[source]', 'ch_q').replace('group_range_next[source]', 'actual')
    return f'''module comparison #(
parameter int LANES={lanes},p_saved_group_lanes=LANES<=4?4:(1 << $clog2(LANES))
)(
input logic[15:0] group_c,ch_q,
output logic equivalent
);
logic[p_saved_group_lanes:0] group_range_cfg,actual,expected;
logic[16:0] expected_remaining;
assign expected_remaining={{1'b0,group_c}}-{{1'b0,ch_q}};
{configured}
{direct}
for(genvar lane=0;lane<=p_saved_group_lanes;lane++)begin:g_expected
 assign expected[lane]=17'(lane)<expected_remaining;
end
assign equivalent=group_range_cfg==expected && actual==expected;
endmodule
'''


def column_range_unit(source: str, lanes: int, size: int) -> str:
    first = source.index('  for (genvar lane = 0; lane <= LANES; lane++) begin : g_active_lane_update')
    first = source.index('        for (genvar step = 0; step <= LANES; step++) begin : g_length', first)
    last = source.index('        assign candidate_allowed[source]', first)
    body = source[first:last]
    return f'''module comparison #(
parameter int SIZE={size},LANES={lanes},TILE_COUNT_W=$clog2(SIZE+1)
)(
input logic[TILE_COUNT_W-1:0] active_remaining,col_remaining,
output logic equivalent
);
logic[LANES:0] lane_equivalent;
for(genvar lane=0;lane<=LANES;lane++)begin:g_lane
 logic[LANES:0] active_allowed,remaining_allowed,expected_active,expected_remaining;
{body}
 for(genvar step=0;step<=LANES;step++)begin:g_expected
  logic[TILE_COUNT_W-1:0] active_count,remaining_count;
  assign active_count=active_remaining-TILE_COUNT_W'(step);
  assign remaining_count=col_remaining-TILE_COUNT_W'(step);
  assign expected_active[step]=TILE_COUNT_W'(lane)<active_count;
  assign expected_remaining[step]=TILE_COUNT_W'(lane)<remaining_count;
 end
 assign lane_equivalent[lane]=active_allowed==expected_active && remaining_allowed==expected_remaining;
end
assign equivalent=&lane_equivalent;
endmodule
'''


def channel_step_unit(source: str, lanes: int) -> str:
    first = source.index('  if (LANES <= 16 && CHUNK_COUNT_W < 16) begin : g_channel_step')
    last = source.index('  assign {unused_channel_position_carry, next_channel}', first)
    body = source[first:last]
    return f'''module comparison #(
parameter int LANES={lanes},CHUNK_COUNT_W=$clog2(LANES+1)
)(
input logic[15:0] ch_q,
input logic[CHUNK_COUNT_W-1:0] chunk_count,
output logic equivalent
);
logic[LANES:0] chunk_selected;
logic[16:0] channel_position_sum,expected_sum;
for(genvar step=0;step<=LANES;step++)begin:g_select
 assign chunk_selected[step]=chunk_count==CHUNK_COUNT_W'(step);
end
{body}
assign expected_sum={{1'b0,ch_q}}+17'(chunk_count);
assign equivalent=int'(chunk_count)>LANES || channel_position_sum==expected_sum;
endmodule
'''


def tile_group_unit(source: str, size: int) -> str:
    first = source.index('  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range')
    last = source.index('  assign incoming_tap_wrap =', first)
    body = source[first:last].replace('c.group_c', 'group_c')
    start = body.index('      logic context_configure;')
    end = body.index('      conv_tile_group_range_result u_result', start)
    body = body[:start] + '''      // 此组合性质以保存的高段关系与当前通道一致为前提。
      assign high_before = first_channel[15:TILE_COUNT_W] < group_c[15:TILE_COUNT_W];
      assign high_equal = first_channel[15:TILE_COUNT_W] == group_c[15:TILE_COUNT_W];
      assign high_next_equal = (16-TILE_COUNT_W)'(first_channel[15:TILE_COUNT_W]+1'b1) ==
          group_c[15:TILE_COUNT_W];
''' + body[end:]
    return f'''module comparison #(
parameter int SIZE={size},TILE_COUNT_W=$clog2(SIZE+1),RW=TILE_COUNT_W
)(
input logic[15:0] group_c,ch0_q,window_next_ch,
input logic[RW-1:0] tile_cols,
output logic equivalent
);
logic[16:0] window_group_remaining_q,initial_group_remaining,columns;
logic[1:0] incoming_tile_group_fits,expected;
assign window_group_remaining_q={{1'b0,group_c}}-{{1'b0,window_next_ch}};
assign initial_group_remaining={{1'b0,group_c}}-{{1'b0,ch0_q}};
assign columns=tile_cols=='0?17'(SIZE):17'(tile_cols);
{body}
assign expected[0]={{1'b0,window_next_ch}}+columns<={{1'b0,group_c}};
assign expected[1]={{1'b0,ch0_q}}+columns<={{1'b0,group_c}};
assign equivalent=incoming_tile_group_fits==expected;
endmodule
'''


def guard_unit(source: str, lanes: int, contiguous: bool, narrow_lanes: int) -> str:
    first = source.index('        for (genvar lane = 0; lane < LANES; lane++) begin : g_transfer_lane')
    last = source.index('        borrow_select_subtract #', first) if '        borrow_select_subtract #' in source[first:] else source.index('        assign remaining =', first)
    transfer = source[first:last]
    first = source.index('  assign chunk_selected[0]')
    following = ('  logic incoming_request', '  if (CHUNK_COUNT_W + 1 < 32)')
    last = min(source.index(marker, first) for marker in following if marker in source[first:])
    selection = source[first:last]
    context = re.search(r'    assign lane_context_allowed\[lane\] =.*?;', source, re.S).group(0)
    data = re.search(r'    assign chunk_data_allowed\[lane\] =.*?;', source, re.S).group(0)
    actual = re.search(r'      chunk_lane_allowed\[lane\] =.*?;', source, re.S).group(0).strip()
    return f'''module comparison #(
parameter int LANES={lanes},NARROW_LANES={narrow_lanes},p_saved_group_lanes=LANES<=4?4:(1 << $clog2(LANES)),
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
    return f'''module comparison #(
parameter int LANES={lanes},NARROW_LANES={narrow_lanes}
)(
input logic [LANES-1:0] group_lane_allowed,word_s8,word_s16,
input logic [LANES:0] active_lane_allowed_q,column_lane_allowed_q,
input logic narrow_output,word_output_q,past_active_q,input_s16,
output logic actual_end,expected_end,equivalent
);
logic [LANES-1:0] expected_s8,expected_s16;
conv_stream_chunk_end #(.p_lanes(LANES),.p_narrow_lanes(NARROW_LANES)) u_actual (
 .i_column_lane(column_lane_allowed_q),.i_group_lane(group_lane_allowed),
 .i_active_lane(active_lane_allowed_q[LANES-1:0]),.i_word_s8(word_s8),.i_word_s16(word_s16),
 .i_narrow_output(narrow_output),.i_past_active(past_active_q),
 .i_word_output(word_output_q),.i_input_s16(input_s16),.o_end(actual_end)
);
for(genvar lane=0;lane<LANES;lane++)begin:g_lane
 assign expected_s8[lane]=(!narrow_output||lane<NARROW_LANES)&&
    (past_active_q||(group_lane_allowed[lane]&&active_lane_allowed_q[lane]))&&
    column_lane_allowed_q[lane]&&!column_lane_allowed_q[lane+1]&&(!word_output_q||word_s8[lane]);
 assign expected_s16[lane]=(!narrow_output||lane<NARROW_LANES)&&
    (past_active_q||(group_lane_allowed[lane]&&active_lane_allowed_q[lane]))&&
    column_lane_allowed_q[lane]&&!column_lane_allowed_q[lane+1]&&(!word_output_q||word_s16[lane]);
end
assign expected_end=!column_lane_allowed_q[0]||(input_s16?(|expected_s16):(|expected_s8));
assign equivalent=actual_end===expected_end;
endmodule
'''


def four_state(source: str, out: Path, root: Path) -> dict:
    rtl = out / 'row_four_state.sv'
    text = []
    for lanes in (1, 2, 4, 8, 16):
        text.append(row_unit(source, lanes, min(lanes, 4)).replace('module comparison #(', f'module comparison_{lanes} #('))
    text.append('''module tb;
logic [15:0] group_lane,word_s8,word_s16;
logic [16:0] active_lane,column_lane;
logic narrow,word_output,past_active,input_s16;
logic [4:0] actual_end,expected_end,equivalent;
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
    for index, lanes in enumerate((1, 2, 4, 8, 16)):
        text.append(f'''comparison_{lanes} u_lanes_{lanes}(
.group_lane_allowed(group_lane[{lanes-1}:0]),.word_s8(word_s8[{lanes-1}:0]),.word_s16(word_s16[{lanes-1}:0]),
.active_lane_allowed_q(active_lane[{lanes}:0]),.column_lane_allowed_q(column_lane[{lanes}:0]),
.narrow_output(narrow),.word_output_q(word_output),.past_active_q(past_active),.input_s16(input_s16),
.actual_end(actual_end[{index}]),.expected_end(expected_end[{index}]),.equivalent(equivalent[{index}]));
''')
    text.append('''initial begin
 seed=$urandom(seed);
 for(integer sample=0;sample<100000;sample++)begin
  for(integer bit_index=0;bit_index<16;bit_index++)begin
   group_lane[bit_index]=random_bit();word_s8[bit_index]=random_bit();word_s16[bit_index]=random_bit();
  end
  for(integer bit_index=0;bit_index<17;bit_index++)begin
   active_lane[bit_index]=random_bit();column_lane[bit_index]=random_bit();
  end
  narrow=random_bit();word_output=random_bit();past_active=random_bit();input_s16=random_bit();
  #1;
  if(equivalent!==5'b11111)$fatal(1,"row completion four-state mismatch");
  comparisons+=5;
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
        subprocess.run([shutil.which('iverilog') or 'iverilog', '-g2012', '-s', 'tb', '-o', str(simulator), *map(str, dependencies(root, [rtl]))],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    with run_log.open('w') as stream:
        subprocess.run([shutil.which('vvp') or 'vvp', str(simulator)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    if 'FRONTEND_ROW_FOUR_STATE_PASS comparisons=500000' not in run_log.read_text():
        raise RuntimeError('行末四态比较未完成')
    return {'passed': True, 'comparisons': 500000, 'rtl_sha256': digest(rtl),
            'run_log_sha256': digest(run_log)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_paths, source = load_source(root)
    checked_sources = set(source_paths)
    rows = []
    cases = [(f'lanes_{lanes}', lanes, unit(source, lanes)) for lanes in range(1, 17)]
    cases += [(f'direct_range_lanes_{lanes}', lanes, direct_range_unit(source, lanes))
              for lanes in (1, 4, 8, 16)]
    cases += [(f'column_range_size_{size}_lanes_{lanes}', lanes, column_range_unit(source, lanes, size))
              for size in (1, 2, 3, 4, 8, 16, 32, 64, 256)
              for lanes in (1, 4, 8, 16)]
    cases += [(f'channel_step_lanes_{lanes}', lanes, channel_step_unit(source, lanes))
              for lanes in range(1,17)]
    cases += [(f'tile_group_size_{size}_given_context', 0, tile_group_unit(source,size))
              for size in (1,2,3,4,7,8,16,31,32,256)]
    cases += [(f'guard_lanes_{lanes}_narrow_{narrow_lanes}_contiguous_{int(contiguous)}', lanes,
               guard_unit(source, lanes, contiguous, narrow_lanes))
              for lanes in range(1, 17) for narrow_lanes in sorted({min(4,lanes), min(8,lanes)})
              for contiguous in (False, True)]
    cases += [(f'row_lanes_{lanes}_narrow_{narrow_lanes}', lanes, row_unit(source, lanes, narrow_lanes))
              for lanes in range(1,17) for narrow_lanes in sorted({min(4,lanes),min(8,lanes)})]
    for name, lanes, text in cases:
        rtl, script, log = [out / (name + ext) for ext in ('.sv', '.ys', '.log')]
        rtl.write_text(text)
        sources = dependencies(root, [rtl])
        checked_sources.update(path for path in sources if path != rtl)
        script.write_text(f'read_slang --top comparison {shlex.join(map(str, sources))}\n'
                          'setattr -mod -unset keep_hierarchy\n'
                          'setattr -unset keep_hierarchy\n'
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
        'scope': 'All 16-bit group and channel values; transfer count from zero through LANES; '
                 'all active and column counts for the tested tile widths',
        'tile_range_scope': 'Combinational range result given saved high-part comparisons consistent with current channels; state consistency is checked by test/descriptor_group_context/run.py',
        'channel_arithmetic': '16-bit wrapping increment followed by a 17-bit wrapping subtraction',
        'source_sha256': {str(path.relative_to(root)): digest(path) for path in sorted(checked_sources)},
        'range_compare_sha256': digest(root / 'rtl/npu/conv/conv_channel_range_compare.sv'),
        'arithmetic_helper_sha256': {name: digest(root / 'rtl/common' / name)
                                    for name in ('add_equal.sv', 'borrow_select_subtract.sv', 'increment_equal.sv', 'onehot_mux.sv')}, 'cases': rows,
        'row_four_state': four_state(source, out, root),
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
