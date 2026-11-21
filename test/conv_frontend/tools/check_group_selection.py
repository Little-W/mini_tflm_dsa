#!/usr/bin/env python3
"""验证三种组范围数据来源的并行选择及四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def module(text, name):
    first = text.index('  logic [p_saved_group_lanes:0] group_range_stream_value;')
    block = text[first:text.index('  // 流式范围的保存资格', first)]
    return f'''module {name} #(parameter int p_saved_group_lanes=8)(
 input logic chunk_reaches_end,group_end_o_equal,
 input logic[5:0][p_saved_group_lanes:0]group_range_next,
 output logic[p_saved_group_lanes:0]result);
''' + block + '\nassign result=group_range_stream_value;\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    paths = [root / 'rtl/npu/conv/conv_im2col_frontend.sv'
             for root in (args.source_root, args.reference_root)]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    sv = args.out / 'group_selection.sv'
    sv.write_text(module(paths[0].read_text(), 'current') + module(paths[1].read_text(), 'reference') + '''
module proof #(parameter int WIDTH=8)(input logic chunk_reaches_end,group_end_o_equal,
 input logic[5:0][WIDTH:0]group_range_next,output logic equivalent);
 wire[WIDTH:0]actual,expected;
 current #(WIDTH) u_current(.result(actual),.*);
 reference #(WIDTH) u_reference(.result(expected),.*);
 assign equivalent=actual===expected;
endmodule
module tb;
 parameter int WIDTH=8;
 logic chunk_reaches_end,group_end_o_equal;
 logic[5:0][WIDTH:0]group_range_next;
 logic[6*(WIDTH+1)+1:0]pattern;
 wire equivalent;
 proof #(WIDTH) dut(.*);
 initial begin
  for(integer sample=0;sample<20000;sample++)begin
   for(integer bit_index=0;bit_index<$bits(pattern);bit_index++)
    case($urandom_range(0,3))
     0:pattern[bit_index]=1'b0;1:pattern[bit_index]=1'b1;
     2:pattern[bit_index]=1'bx;3:pattern[bit_index]=1'bz;
    endcase
   {chunk_reaches_end,group_end_o_equal,group_range_next}=pattern;
   #1;if(equivalent!==1'b1)$fatal(1,"group selection four-state sample %0d",sample);
  end
  $display("GROUP_SELECTION_FOUR_STATE_PASS checks=20000");$finish;
 end
endmodule
''')
    results = []
    for width in (1, 4, 8, 16):
        ys, log = args.out / f'w{width}.ys', args.out / f'w{width}.log'
        ys.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 ' +
                      f'-GWIDTH={width} ' + shlex.quote(str(sv)) +
                      '\nprep -top proof -flatten\ncheck -assert\n' +
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(ys)], stdout=stream, stderr=subprocess.STDOUT,
                           timeout=120, check=True)
        assert 'SUCCESS!' in log.read_text()
        binary = args.out / f'w{width}.vvp'
        subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb',
                        f'-Ptb.WIDTH={width}', '-o', str(binary), str(sv)],
                       capture_output=True, check=True)
        run = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)],
                             capture_output=True, text=True, timeout=120, check=True)
        event_log = args.out / f'w{width}.event.log'
        event_log.write_text(run.stdout + run.stderr)
        assert 'checks=20000' in run.stdout
        results.append({'saved_lanes': width, 'passed': True, 'four_state_checks': 20000,
                        'formal_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
                        'event_log_sha256': hashlib.sha256(event_log.read_bytes()).hexdigest()})
    assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    report = {'passed': True, 'source_sha256': hashes, 'input_constraints': [],
              'runs': results, 'four_state_checks': 80000}
    (args.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_profiles': 4, 'four_state_checks': 80000}))


if __name__ == '__main__':
    main()
