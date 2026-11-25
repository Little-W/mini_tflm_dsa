#!/usr/bin/env python3
"""检查实际范围比较和读取地址表达式的四态结果，记录未知输入的传播。"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from common import ROOT, REFERENCE, BUFFER, HELPER, PARAMETERS, digest, snapshot


def expression(source, name):
    matches = re.findall(r'  assign ' + name + r'\s*=.*?;', source, flags=re.S)
    assert len(matches) == 1, name
    return matches[0]


def model(source, label, ports):
    start = source.find('  assign load_request_idx =')
    if start < 0:
        start = source.index('  for (genvar b = 0; b < 2; b++) begin : gen_window_hit')
    boundaries = [source.find(marker, start) for marker in (
        '  if (p_register_current_range)', '  assign resident_current')]
    end = min(position for position in boundaries if position >= 0)
    block = source[start:end]
    declarations = ',\n'.join('    input wire ' + (f'[{width-1}:0] ' if width > 1 else '') + name
                             for name, width in ports)
    return f'''module {label}(
{declarations},
    output wire [12:0] result
);
  localparam CNT_W=29, RANGE_WIDTH=30, RANGE_STAGES=$clog2(RANGE_WIDTH);
  localparam BANK_ADDR_W=8, READ_INDEX_W=3, READS_PER_BLOCK=8, WORDS_PER_READ=2;
  localparam p_share_load_index=0;
  wire bank_loaded[2];
  wire [CNT_W-1:0] bank_block_idx[2];
  wire [CNT_W:0] bank_end_q[2];
  wire [CNT_W-1:0] load_request_idx;
  wire [1:0][1:0] window_end_valid;
  wire [1:0] load_window_hit, current_window_hit;
  wire [READ_INDEX_W-1:0] ws_issue_index;
  wire [8:0] read_address;
  for(genvar bank_i=0; bank_i<2; bank_i++) begin:g_input_bank
    assign bank_loaded[bank_i]=bank_loaded_flat[bank_i];
    assign bank_block_idx[bank_i]=bank_block_idx_flat[bank_i*CNT_W+:CNT_W];
    assign bank_end_q[bank_i]=bank_end_flat[bank_i*(CNT_W+1)+:CNT_W+1];
  end
{block}
{expression(source, 'ws_issue_index')}
{expression(source, 'read_address')}
  assign result={{load_window_hit,current_window_hit,read_address}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = snapshot(out / 'source', args.reference)
    ports = [('bank_loaded_flat', 2), ('bank_block_idx_flat', 58), ('bank_end_flat', 60),
             ('load_block_idx', 29), ('current_block_idx', 29), ('group_blocks_needed', 29),
             ('active_bank', 1), ('is_mode', 1), ('scalar_request_bank', 1),
             ('scalar_request_word', 9), ('ws_read_start', 1), ('ws_cache_bank', 1),
             ('ws_read_base', 8), ('ws_issue_count', 4), ('current_block_offset', 5)]
    sources = []
    for label in ['reference', 'current']:
        path = out / f'{label}.sv'
        path.write_text(model((out / 'source' / label / BUFFER).read_text(), label, ports))
        sources.append(path)
    width = sum(width for _, width in ports)
    offset, connections = 0, []
    for name, size in ports:
        connections.append(f'.{name}(stimulus[{offset} +: {size}])')
        offset += size
    connections = ', '.join(connections)
    tb = out / 'tb.sv'
    tb.write_text(f'''module tb;
  localparam W={width};
  reg [W-1:0] stimulus, known;
  wire [12:0] reference_result, current_result;
  integer seed=32'h148e6a2f;
  integer checks=0, known_bits=0, refined_bits=0, unknown_bits=0;
  reference u_reference({connections}, .result(reference_result));
  current u_current({connections}, .result(current_result));
  task check;
    begin
      #1;
      checks=checks+1;
      for(integer bit_i=0;bit_i<13;bit_i=bit_i+1) begin
        if(reference_result[bit_i]===1'b0 || reference_result[bit_i]===1'b1) begin
          known_bits=known_bits+1;
          if(current_result[bit_i]!==reference_result[bit_i])
            $fatal(1,"Known result mismatch bit=%0d input=%h reference=%b current=%b",
                   bit_i,stimulus,reference_result,current_result);
        end else if(current_result[bit_i]===1'b0 || current_result[bit_i]===1'b1)
          refined_bits=refined_bits+1;
        else unknown_bits=unknown_bits+1;
      end
    end
  endtask
  initial begin
    for(integer sample_i=0;sample_i<64;sample_i=sample_i+1) begin
      for(integer bit_i=0;bit_i<W;bit_i=bit_i+1) known[bit_i]=$random(seed);
      if(sample_i==0) known='0;
      if(sample_i==1) known='1;
      stimulus=known; check();
      for(integer bit_i=0;bit_i<W;bit_i=bit_i+1) begin
        stimulus=known; stimulus[bit_i]=1'bx; check();
        stimulus=known; stimulus[bit_i]=1'bz; check();
      end
    end
    for(integer sample_i=0;sample_i<4096;sample_i=sample_i+1) begin
      for(integer bit_i=0;bit_i<W;bit_i=bit_i+1) begin
        case($random(seed)&15)
          0: stimulus[bit_i]=1'bx;
          1: stimulus[bit_i]=1'bz;
          default: stimulus[bit_i]=$random(seed);
        endcase
      end
      check();
    end
    $display("FOUR_STATE_PASS checks=%0d known_bits=%0d refined_bits=%0d unknown_bits=%0d",
             checks,known_bits,refined_bits,unknown_bits);
    $finish;
  end
endmodule
''')
    executable = out / 'four_state.vvp'
    sources.append(out / 'source' / 'current' / HELPER)
    command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable)] + [str(p) for p in sources] + [str(tb)]
    with (out / 'build.log').open('w') as stream:
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.run(['vvp', str(executable)], capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    match = re.search(r'FOUR_STATE_PASS checks=(\d+) known_bits=(\d+) refined_bits=(\d+) unknown_bits=(\d+)', result.stdout)
    assert result.returncode == 0 and match, result.stdout + result.stderr
    report = {'passed': True, 'inputs': inputs, 'parameters': PARAMETERS,
              **dict(zip(['checks', 'known_bits', 'refined_bits', 'unknown_bits'], map(int, match.groups()))),
              'property': 'Every known reference output bit is unchanged; unknown reference bits may resolve',
              'scope': 'Actual range comparators and read address expressions with default independent request indices',
              'strict_four_state_equivalence': False,
              'source_sha256': {p.name: digest(p) for p in sources + [tb]},
              'build_command': command, 'build_log_sha256': digest(out / 'build.log'),
              'run_log_sha256': digest(out / 'run.log')}
    for row in inputs['sources']:
        assert digest(ROOT / row['source']) == row['current_sha256']
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['passed', 'checks', 'known_bits', 'refined_bits', 'unknown_bits']}))


if __name__ == '__main__':
    main()
