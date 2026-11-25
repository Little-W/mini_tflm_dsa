#!/usr/bin/env python3
"""验证实际流式范围表达式的全部输入组合及四态选择行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path('rtl/npu/conv/conv_im2col_stream.sv')
HELPERS = ('rtl/common/onehot_mux.sv', 'rtl/common/borrow_select_subtract.sv',
           'rtl/common/increment_equal.sv', 'rtl/npu/conv/conv_channel_range_compare.sv')


def model(text, name):
    first = text.index('      if (source == 5) begin : g_stream_advance\n')
    first = text.index('\n', first) + 1
    last = text.index('      end else begin : g_direct_range', first)
    body = text[first:last]
    first = body.index('        // 输出阶段准备组范围')
    last = body.index('        // 剩余数量只依赖当前坐标', first)
    body = body[:first] + body[last:]
    body = body.replace('        logic [p_lanes:0] transfer_selected;\n', '')
    replacements = {'i_c.group_c': 'group_c', 'o_ch_q': 'channel',
                    'o_chunk_selected': 'chunk_selected',
                    'o_group_range_next[source]': 'advanced_range',
                    'o_group_range_next[0]': 'initial_range'}
    for before, after in replacements.items():
        body = body.replace(before, after)
    if 'group_transfer_range[lane] =' in body:
        # 每个通道采用独立标量输出，再连接到端口的对应位。
        body = body.replace('group_transfer_range[lane] =', 'selected_transfer_value =')
        body = body.replace('begin : g_select_lane\n',
                            'begin : g_select_lane\n' +
                            '          logic selected_transfer_value;\n' +
                            '          assign group_transfer_range[lane] = selected_transfer_value;\n')
    return f'''module {name} #(
 parameter int p_lanes=8,
 localparam int p_saved_group_lanes=p_lanes<=4 ? 4 : (1<<$clog2(p_lanes))
)(
 input logic [15:0] group_c,channel,
 input logic [p_lanes:0] chunk_selected,transfer_selected,
 input logic [p_saved_group_lanes:0] group_range_q,initial_range,
 output logic [p_saved_group_lanes:0] advanced_range,group_transfer_range
);
{body}
endmodule
'''


def proof():
    return '''module proof #(parameter int p_lanes=8,
 localparam int WIDTH=(p_lanes<=4?4:(1<<$clog2(p_lanes)))+1)(
 input logic [15:0] group_c,channel,
 input logic [p_lanes:0] chunk_selected,transfer_selected,
 input logic [WIDTH-1:0] group_range_q,initial_range,
 output logic equivalent
);
 logic [WIDTH-1:0] actual_advanced,expected_advanced,actual_transfer,expected_transfer;
 current #(.p_lanes(p_lanes)) u_current(.advanced_range(actual_advanced),
  .group_transfer_range(actual_transfer),.*);
 reference #(.p_lanes(p_lanes)) u_reference(.advanced_range(expected_advanced),
  .group_transfer_range(expected_transfer),.*);
 assign equivalent=actual_advanced==expected_advanced && actual_transfer==expected_transfer;
endmodule
'''


def bench(lanes):
    width = max(4, 1 << (lanes-1).bit_length()) + 1
    return f'''module tb;
 localparam int p_lanes={lanes}, WIDTH={width};
 logic [15:0] group_c,channel;
 logic [p_lanes:0] chunk_selected,transfer_selected;
 logic [WIDTH-1:0] group_range_q,initial_range;
 logic [WIDTH-1:0] actual_advanced,expected_advanced,actual_transfer,expected_transfer;
 integer seed=32'h416a37f2;
 current #(.p_lanes(p_lanes)) u_current(.advanced_range(actual_advanced),
  .group_transfer_range(actual_transfer),.*);
 reference #(.p_lanes(p_lanes)) u_reference(.advanced_range(expected_advanced),
  .group_transfer_range(expected_transfer),.*);
 function automatic logic random_bit(input integer mode);
  integer value;
  value=$urandom_range(0,31);
  if (mode!=0 && value==0) random_bit=1'bx;
  else if (mode!=0 && value==1) random_bit=1'bz;
  else random_bit=value[0];
 endfunction
 initial begin
  seed=$urandom(seed);
  for(integer sample=0;sample<4096;sample++)begin
   for(integer bit_index=0;bit_index<16;bit_index++)begin
    group_c[bit_index]=random_bit(sample%4==1);
    channel[bit_index]=random_bit(sample%4==1);
   end
   if(sample%8==0)begin group_c=16'(sample);channel=group_c-16'(sample%32);end
   for(integer bit_index=0;bit_index<=p_lanes;bit_index++)begin
    chunk_selected[bit_index]=random_bit(sample%4==2);
    transfer_selected[bit_index]=random_bit(sample%4==2);
   end
   for(integer bit_index=0;bit_index<WIDTH;bit_index++)begin
    group_range_q[bit_index]=random_bit(sample%4==3);
    initial_range[bit_index]=random_bit(sample%4==3);
   end
   #1;
   if(actual_advanced!==expected_advanced || actual_transfer!==expected_transfer)
    $fatal(1,"TRANSFER_RANGE_MISMATCH lanes=%0d sample=%0d",p_lanes,sample);
  end
  $display("TRANSFER_RANGE_PASS checks=4096");
  $finish;
 end
endmodule
'''


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=900)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='2247144937c2fd04039b9b005151f371d6b51f8f')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / SOURCE, *(ROOT / value for value in HELPERS)]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    original = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                       cwd=ROOT, text=True)
    rtl = out / 'model.sv'
    rtl.write_text(model(paths[0].read_text(), 'current') + model(original, 'reference') + proof())
    rows = []
    for lanes in (1, 2, 4, 8, 16):
        script, log = out / f'lanes{lanes}.ys', out / f'lanes{lanes}.log'
        script.write_text(f'read_slang --top proof -D SYNTHESIS=1 -Gp_lanes={lanes} ' +
                          shlex.join(map(str, [*paths[1:], rtl])) +
                          '\nprep -top proof -flatten\ncheck -assert\n' +
                          'sat -set-def-inputs -verify -prove equivalent 1\n')
        run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('流式范围组合证明未完成')
        tb, binary = out / f'lanes{lanes}.sv', out / f'lanes{lanes}.vvp'
        tb.write_text(bench(lanes))
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *paths[1:], rtl, tb],
            out / f'lanes{lanes}_build.log')
        simulation = out / f'lanes{lanes}_four_state.log'
        run(['vvp', binary], simulation)
        if 'TRANSFER_RANGE_PASS checks=4096' not in simulation.read_text():
            raise RuntimeError('流式范围四态比较未完成')
        rows.append(dict(lanes=lanes, formal_passed=True, four_state_checks=4096))
        print('TRANSFER_RANGE_CHOICE_PASS', lanes, flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in paths}:
        raise RuntimeError('验证期间源文件发生变化')
    result = dict(passed=True, reference=args.reference, source_sha256=hashes,
                  input_assumptions=[], selection_vectors='Independent arbitrary bit vectors',
                  compared_outputs='All advanced and transfer range bits', cases=rows)
    (out / 'summary.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
