#!/usr/bin/env python3
"""证明输出掩码及组末选择对任意通道资格向量的等价性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = source_root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    source = path.read_text()
    first = source.index('  logic [16:0] group_end_i_a')
    last = re.search(r'  if \(LANES <= \d+\) begin : g_short_group_lane', source).start()
    group = source[first:last]
    first = source.index('  for (genvar output_lane = 0; output_lane < LANES; output_lane++) begin : g_output_mask')
    last = source.index('  always_comb begin', first)
    mask = source[first:last]
    test = out / 'selection.sv'
    test.write_text('''module selection #(parameter int LANES=8,CHUNK_COUNT_W=$clog2(LANES+1))(
input conv_im2col_pkg::conv_cfg_t c,input logic[15:0] ch_q,
input logic[LANES-1:0] chunk_lane_allowed,output logic equivalent);
localparam int p_saved_group_lanes=LANES>4 && LANES<=8 ? 8 : 4;
logic[p_saved_group_lanes:0] group_range_q;
for(genvar boundary=0;boundary<=p_saved_group_lanes;boundary++)
 assign group_range_q[boundary]=17'(boundary)<({1'b0,c.group_c}-{1'b0,ch_q});
logic[CHUNK_COUNT_W-1:0] chunk_count;
logic[LANES-1:0] wr_mask,expected_mask;
always_comb begin
 chunk_count='0;
 for(int lane=0;lane<LANES;lane++)
  if(chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
end
for(genvar lane=0;lane<LANES;lane++) assign expected_mask[lane]=32'(lane)<chunk_count;
''' + group + mask + '''
assign equivalent=wr_mask==expected_mask &&
 group_end_o_equal==(({1'b0,ch_q}+17'(chunk_count))=={1'b0,c.group_c});
endmodule
''')
    results = []
    for lanes in (1, 2, 4, 5, 7, 8, 9, 16, 32, 64):
        name = f'lanes{lanes}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        paths = [source_root / 'rtl/npu/conv/conv_im2col_pkg.sv',
                 source_root / 'rtl/common/add_equal.sv', test]
        script.write_text(f'read_slang --top selection -GLANES={lanes} ' +
            ' '.join(shlex.quote(str(item)) for item in paths) +
            '\nprep -top selection -flatten\n' +
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        results.append({'case': name, 'passed': True})
        print('FRONTEND_STREAM_SELECTION_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'cases': results,
        'input_assumptions': [],
        'frontend_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, indent=2) + '\n')


if __name__ == '__main__':
    main()
