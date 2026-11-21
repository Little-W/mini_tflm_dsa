#!/usr/bin/env python3
"""证明连续通道范围的掩码和末通道选择，并检查四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    text = source.read_text()
    selection = text[text.index('  localparam bit p_contiguous_chunk ='):
                     text.index('  logic incoming_request, incoming_context')]
    word_start = text.index('  for (genvar lane = 0; lane < LANES; lane++) begin : g_word_lane')
    word_stop = text.index('  if (TILE_COUNT_W >= CHUNK_COUNT_W) begin : g_direct_chunk_end', word_start)
    word = text[word_start:word_stop]
    end_stop = text.index('  // 偏移高字节', word_stop)
    chunk_end = text[word_stop:end_stop]
    output_start = text.index('  for (genvar output_lane = 0; output_lane < LANES; output_lane++) begin : g_output_mask')
    output_stop = text.index('  always_comb begin', output_start)
    output = text[output_start:output_stop]
    lane_assignment = '    assign ' + re.search(r'chunk_lane_allowed\[lane\] = .*?;', text, re.S)[0]
    proof = out / 'chunk_mask.sv'
    proof.write_text('''module chunk_mask_proof #(
    parameter int SIZE=16,
    parameter int LANES=8,
    parameter int NARROW_LANES=4
) (
    input logic [21:0] state,
    input logic input_s16, past_active_q, narrow_output, group_has_channel,
    input logic [LANES-1:0] group_short,
    input logic [$clog2(SIZE+1)-1:0] active_remaining, col_remaining,
    input logic [31:0] addr,
    output logic equivalent,
    output logic [LANES-1:0] wr_mask, reference_mask,
    output logic [LANES:0] chunk_selected, reference_selected,
    output logic chunk_reaches_end, reference_reaches_end
);
    localparam int TILE_COUNT_W=$clog2(SIZE+1), CHUNK_COUNT_W=$clog2(LANES+1);
    localparam int p_cache_read_bytes=LANES<=4 ? 4 : (1 << $clog2(LANES));
    localparam int p_word_shift=$clog2(p_cache_read_bytes);
    localparam logic [21:0] WAIT_WORD=22'h080000, STREAM=22'h100000;
    typedef struct packed {logic input_s16;} config_t;
    config_t c;
    logic [LANES-1:0] group_lane_allowed, word_lane_allowed, chunk_end_lane;
    logic [LANES-1:0] chunk_data_allowed, chunk_lane_allowed;
    logic [LANES:0] active_lane_allowed_q, column_lane_allowed_q;
    logic [CHUNK_COUNT_W-1:0] chunk_count;
    assign c.input_s16=input_s16;
    // 通道范围在配置、解码与描述符阶段均由边界前缀生成。
    // 任意边界位组合覆盖寄存范围的所有连续前缀。
    for (genvar lane=0;lane<LANES;lane++) begin : g_range
        if (lane==0) assign group_lane_allowed[lane]=group_has_channel;
        else assign group_lane_allowed[lane]=group_has_channel && !(|group_short[lane-1:0]);
''' + lane_assignment + '''
        assign reference_mask[lane]=|chunk_lane_allowed[LANES-1:lane];
    end
    for (genvar lane=0;lane<=LANES;lane++) begin : g_active
        assign active_lane_allowed_q[lane]=TILE_COUNT_W'(lane)<active_remaining;
        assign column_lane_allowed_q[lane]=TILE_COUNT_W'(lane)<col_remaining;
    end
    assign reference_selected[0]=!(|chunk_lane_allowed);
    always_comb begin
        chunk_count='0;
        for (int lane=0;lane<LANES;lane++)
            if (chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
    end
    for (genvar step=1;step<=LANES;step++) begin : g_reference_select
        if (step==LANES) assign reference_selected[step]=chunk_lane_allowed[step-1];
        else assign reference_selected[step]=chunk_lane_allowed[step-1] &&
            !(|chunk_lane_allowed[LANES-1:step]);
    end
''' + selection + word + chunk_end + output + '''
    assign reference_reaches_end = TILE_COUNT_W'(chunk_count) == col_remaining;
    assign equivalent=(wr_mask==reference_mask) && (chunk_selected==reference_selected) &&
        (chunk_reaches_end==reference_reaches_end);
endmodule
''')
    result = {'passed': True, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'proof_sha256': hashlib.sha256(proof.read_bytes()).hexdigest(),
              'range_invariants': ['group flags form a continuous prefix',
                                   'active flags are stored with their column count'],
              'input_constraints': [], 'runs': []}
    for size in (2, 4, 8, 16):
        for lanes in (1, 2, 4, 8, 16):
            name = f's{size}_l{lanes}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('read_slang --top chunk_mask_proof -GSIZE=' + str(size) +
                ' -GLANES=' + str(lanes) + ' ' + shlex.quote(str(proof)) + '\n' +
                'prep -top chunk_mask_proof -flatten\ncheck -assert\n' +
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
            assert 'SUCCESS' in log.read_text(), log
            result['runs'].append({'size': size, 'lanes': lanes, 'passed': True})
    tb = out / 'tb_four_state.sv'
    tb.write_text('''module tb_four_state;
    reg [21:0] state;
    reg input_s16, past_active_q, narrow_output, group_has_channel;
    reg [7:0] group_short;
    reg [4:0] active_remaining, col_remaining;
    reg [31:0] addr;
    wire equivalent;
    wire [7:0] wr_mask, reference_mask;
    wire [8:0] chunk_selected, reference_selected;
    wire chunk_reaches_end, reference_reaches_end;
    chunk_mask_proof dut (.*);
    reg [75:0] pattern;
    integer index, bit_index;
    initial begin
        for (index=0;index<20000;index=index+1) begin
            pattern={$random,$random,$random};
            if (index%3==0) pattern[index%76]=1'bx;
            if (index%5==0) pattern[(index*7)%76]=1'bz;
            {state,input_s16,past_active_q,narrow_output,group_has_channel,
             group_short,active_remaining,col_remaining,addr}=pattern;
            #1;
            if (wr_mask!==reference_mask || chunk_selected!==reference_selected)
                $fatal(1,"chunk mask comparison at sample %0d",index);
        end
        $display("CHUNK_MASK_FOUR_STATE_PASS samples=20000");
        $finish;
    end
endmodule
''')
    binary = out / 'four_state.vvp'
    compile_log = out / 'four_state_compile.log'
    with compile_log.open('w') as stream:
        subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb_four_state',
                        '-o', str(binary), str(proof), str(tb)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    run = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)], capture_output=True, text=True, check=True)
    (out / 'four_state.log').write_text(run.stdout + run.stderr)
    assert 'CHUNK_MASK_FOUR_STATE_PASS' in run.stdout
    result['four_state_samples'] = 20000
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
