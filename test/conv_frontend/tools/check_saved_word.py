#!/usr/bin/env python3
"""证明描述符保存字地址后的命中和当前缓存字命中的地址关系。"""
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
    capture = '\n'.join(re.search(pattern, text, re.S)[0] for pattern in (
        r'    preparing_tile.word_address = .*?;',
        r'    preparing_tile.saved_word_valid = .*?;'))
    compare = '\n'.join(re.search(r'  assign ' + name + r' = .*?;', text, re.S)[0] for name in
        ('committing_saved_word_hit', 'committing_live_word_hit'))
    group_start = text.index('  for (genvar target = 0; target < 2; target++) begin : g_commit_word_match')
    group_stop = text.index('  // 当前数据字', group_start)
    compare += '\n' + text[group_start:group_stop]
    start = text.index('  for (genvar address_port = 0; address_port < 2; address_port++) begin : g_commit_address')
    stop = text.index('  always_comb begin\n    preparing_tile =', start)
    address = text[start:stop]
    proof = out / 'saved_word.sv'
    proof.write_text('''module saved_word_proof #(parameter int p_word_shift=3) (
    input logic clk, rst_n, tile_capture, finishing_tile, waiting, word_valid,
    input logic [31:0] base_address, address_delta, group_address, addr, word_addr,
    input logic address_carry,
    output logic equivalent
);
    localparam bit REGISTER_DESCRIPTOR=1;
    localparam logic [21:0] WAIT_WORD=22'h080000;
    logic [21:0] state;
    typedef struct packed {
        logic [31:0] address, group_address, address_delta;
        logic address_carry;
        logic [31-p_word_shift:0] word_address;
        logic saved_word_valid;
    } prepared_t;
    prepared_t preparing_tile, prepared_tile_q;
    logic [1:0][31:0] committing_address;
    logic [1:0] unused_committing_address_carry;
    logic committing_saved_word_hit, reference_hit, reference_hit_q, captured;
    logic prepared_live_word_match, committing_live_word_hit, reference_live_hit,committing_saved_word_match;
    logic[31:0]committing_address_delta;logic committing_address_carry;
    assign committing_address_delta=prepared_tile_q.address_delta;
    assign committing_address_carry=prepared_tile_q.address_carry;
    logic [31:0] reference_address_q;
    logic [p_word_shift:0] low_sum;
    logic high_equal;
    assign state = waiting ? WAIT_WORD : 22'd0;
    always_comb begin
        preparing_tile = '0;
        preparing_tile.address = base_address;
        preparing_tile.group_address = group_address;
        preparing_tile.address_delta = address_delta;
        preparing_tile.address_carry = address_carry;
''' + capture + '''
    end
''' + address + compare + '''
    assign low_sum = {1'b0, base_address[p_word_shift-1:0]} +
        {1'b0, address_delta[p_word_shift-1:0]} + (p_word_shift+1)'(address_carry);
    add_equal #(.p_width(32-p_word_shift)) u_reference (
        .i_a(base_address[31:p_word_shift]), .i_b(address_delta[31:p_word_shift]),
        .i_carry_in(low_sum[p_word_shift]), .i_target(preparing_tile.word_address),
        .o_equal(high_equal)
    );
    assign reference_hit = preparing_tile.saved_word_valid && high_equal;
    always_ff @(posedge clk) begin
        if (!rst_n) captured <= 1'b0;
        else if (tile_capture) captured <= 1'b1;
        if (tile_capture) begin
            prepared_tile_q <= preparing_tile;
            reference_hit_q <= reference_hit;
            reference_address_q <= base_address + address_delta + 32'(address_carry);
        end
    end
    assign reference_live_hit=word_valid && reference_address_q[31:p_word_shift]==word_addr[31:p_word_shift];
    assign equivalent = !captured || (committing_address[0] == reference_address_q &&
                                      committing_saved_word_hit == reference_hit_q &&
                                      committing_live_word_hit == reference_live_hit);
endmodule
''')
    sources = [root / 'rtl/common/parallel_prefix_add.sv', root / 'rtl/common/add_equal.sv', proof]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [source, *sources]}
    result = {'passed': True, 'source_sha256': hashes, 'runs': [],
              'input_constraints': ['rst_n=0 at the first sampled edge'],
              'held_descriptor_checked': True, 'current_word_match_checked': True}
    for shift in (2, 3, 4):
        for fpga in (0, 1):
            name = f'w{shift}_f{fpga}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('read_slang --top saved_word_proof -Gp_word_shift=' + str(shift) + ' ' +
                ('-DXILINX_FPGA=1 ' if fpga else '') + shlex.join(map(str, sources)) + '\n' +
                'prep -top saved_word_proof -flatten\ncheck -assert\n' +
                'sat -seq 2 -set-at 1 rst_n 0 -set-def-inputs -set-init-def -prove-skip 1 -prove equivalent 1 -verify\n' +
                'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -set-def-inputs -set-init-def -prove equivalent 1 -verify\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            if 'Induction step proven: SUCCESS!' not in log.read_text():
                raise RuntimeError('Saved word induction did not complete: ' + str(log))
            result['runs'].append({'word_bytes': 1 << shift, 'xilinx_fpga': bool(fpga), 'passed': True})
            print('SAVED_WORD_PASS', name, flush=True)
    if hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [source, *sources]}:
        raise RuntimeError('Sources changed during saved word proof')
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
