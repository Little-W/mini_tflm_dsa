#!/usr/bin/env python3
"""验证共享权重标签比较及写入寄存阶段的数值和事务行为。"""
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
ENGINE = Path('rtl/npu/conv/vector_engine.sv')
PROFILES = ((1, 1), (3, 2), (6, 6), (10, 6), (12, 8), (17, 16))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, cwd):
    with log.open('w') as handle:
        handle.write('$ ' + shlex.join(map(str, command)) + '\n')
        handle.flush()
        result = subprocess.run(list(map(str, command)), cwd=cwd,
                                stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('验证失败：' + str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    source = args.source_root.resolve() / ENGINE
    source_hash = digest(source)
    text = source.read_text()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    tag_start = text.index('    localparam int TAG_GROUPS =')
    tag_end = text.index('    // 当前权重和下一核位置', tag_start)
    tag_body = text[tag_start:tag_end]
    for name in ('return_matches', 'saved_matches'):
        match = re.search(r'assign ' + name + r'\s*=\s*.*?;', text, re.S)
        assert match is not None
        tag_body += match[0] + '\n'
    tags = out / 'tag_comparison.sv'
    tags.write_text('''module tag_comparison #(
    parameter integer SHARED_STORAGE_ADDR_WIDTH=10, TAP_COUNT_W=6
)(
    input logic [SHARED_STORAGE_ADDR_WIDTH-1:0] return_tap, saved_tap,
    input logic [TAP_COUNT_W-1:0] tap,
    input logic i_weight_read_valid, saved_valid,
    output wire [1:0] original, selected,
    output wire equal
);
logic return_matches, saved_matches;
''' + tag_body + '''
assign original = {i_weight_read_valid && return_tap == SHARED_STORAGE_ADDR_WIDTH'(tap),
                   saved_valid && saved_tap == SHARED_STORAGE_ADDR_WIDTH'(tap)};
assign selected = {return_matches, saved_matches};
assign equal = original == selected;
endmodule
''')

    stage_start = text.index('    assign write_capture =')
    stage_end = text.index('    assign weights_o_rd_data =', stage_start)
    stage_body = text[stage_start:stage_end]
    stage = out / 'write_stage.sv'
    stage.write_text('''module write_stage #(
    parameter integer SHARED_STORAGE_ADDR_WIDTH=10
)(
    input logic clk, rst_n, weights_i_wr_en, i_storage_error, state_failed,
    input logic [31:0] weights_i_wr_tap,
    input logic [127:0] weights_i_wr_data,
    input logic [15:0] weights_i_wr_mask,
    output logic shared_weight_write_pending, o_weight_write_en,
    output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_weight_write_addr,
    output logic [127:0] o_weight_write_data,
    output logic [15:0] o_weight_write_mask
);
logic write_capture, write_valid_q;
logic [SHARED_STORAGE_ADDR_WIDTH-1:0] write_tap_q;
logic [127:0] write_data_q;
logic [15:0] write_mask_q;
''' + stage_body + 'endmodule\n')

    proof = out / 'write_stage_proof.sv'
    proof.write_text('''module write_stage_proof (
    input logic clk, rst_n, weights_i_wr_en, i_storage_error, state_failed,
    input logic [31:0] weights_i_wr_tap,
    input logic [127:0] weights_i_wr_data,
    input logic [15:0] weights_i_wr_mask,
    output wire equal
);
wire shared_weight_write_pending, o_weight_write_en;
wire [9:0] o_weight_write_addr;
wire [127:0] o_weight_write_data;
wire [15:0] o_weight_write_mask;
write_stage dut (.*);
logic pending;
logic [153:0] delayed_payload;
always @(posedge clk) begin
    delayed_payload <= {weights_i_wr_tap[9:0], weights_i_wr_data, weights_i_wr_mask};
end
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) pending <= 1'b0;
    else begin
        pending <= 1'b0;
        if (weights_i_wr_en && weights_i_wr_mask != 0 && !i_storage_error && !state_failed)
            pending <= 1'b1;
    end
end
wire expected_valid = pending && !i_storage_error && !state_failed;
assign equal = shared_weight_write_pending == pending && o_weight_write_en == expected_valid &&
    (!expected_valid || {o_weight_write_addr, o_weight_write_data, o_weight_write_mask} == delayed_payload);
endmodule
''')
    proofs = []
    for width, tap_width in PROFILES:
        name = f'tag_a{width}_t{tap_width}'
        script = out / (name + '.ys')
        script.write_text(f'read_slang --top tag_comparison -GSHARED_STORAGE_ADDR_WIDTH={width} '
                          f'-GTAP_COUNT_W={tap_width} {shlex.quote(str(tags))}\n'
                          'prep -top tag_comparison -flatten\n'
                          'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        log = script.with_suffix('.log')
        run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log, ROOT)
        proofs.append({'name': name, 'passed': True, 'log_sha256': digest(log)})
    script = out / 'write_stage.ys'
    script.write_text('read_slang --top write_stage_proof ' + shlex.join(map(str, (stage, proof))) + '\n'
                      'prep -top write_stage_proof -flatten\nasync2sync\n'
                      'sat -verify -seq 8 -set-at 1 rst_n 0 -prove equal 1 -show-inputs -show-outputs\n')
    log = script.with_suffix('.log')
    run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log, ROOT)
    proofs.append({'name': 'write_stage_arbitrary_8_cycles', 'passed': True, 'log_sha256': digest(log)})

    bench = '''module tb;
logic [16:0] return_tap, saved_tap;
logic [15:0] tap;
logic i_weight_read_valid, saved_valid;
logic clk=0, rst_n=0, weights_i_wr_en=0, i_storage_error=0, state_failed=0;
logic [31:0] weights_i_wr_tap;
logic [127:0] weights_i_wr_data;
logic [15:0] weights_i_wr_mask;
wire shared_weight_write_pending, o_weight_write_en;
wire [9:0] o_weight_write_addr;
wire [127:0] o_weight_write_data;
wire [15:0] o_weight_write_mask;
write_stage dut (.*);
logic expected_pending=0;
logic [153:0] expected_payload;
integer seed, seed_result, iteration, bit_index, tag_checks=0, stage_checks=0;
integer published=0, cancelled=0, consecutive=0, reset_cycles=0;
logic previous_published=0;
'''
    for index, (width, tap_width) in enumerate(PROFILES):
        bench += f'''wire [1:0] original{index}, selected{index};
tag_comparison #(.SHARED_STORAGE_ADDR_WIDTH({width}), .TAP_COUNT_W({tap_width})) tag{index} (
 .return_tap(return_tap[{width-1}:0]), .saved_tap(saved_tap[{width-1}:0]),
 .tap(tap[{tap_width-1}:0]), .i_weight_read_valid(i_weight_read_valid), .saved_valid(saved_valid),
 .original(original{index}), .selected(selected{index}), .equal());
'''
    bench += '''task check_tags;
    #1;
'''
    for index in range(len(PROFILES)):
        bench += f'    if (original{index} !== selected{index}) $fatal(1, "tag profile {index} sample %0d", iteration);\n'
    bench += f'    tag_checks = tag_checks + {len(PROFILES)};\nendtask\n'
    bench += '''initial begin
    rst_n=1;
    #1;
    rst_n=0;
    #1;
    seed=32'h1e8a4d53;
    seed_result=$urandom(seed);
    for (iteration=0; iteration<32768; iteration=iteration+1) begin
        return_tap=$urandom(); saved_tap=$urandom(); tap=$urandom();
        i_weight_read_valid=1'($urandom()); saved_valid=1'($urandom());
        case (iteration%7)
            1: begin return_tap[$urandom()%17]=1'bx; saved_tap[$urandom()%17]=1'bz; end
            2: tap[$urandom()%16]=1'bx;
            3: begin i_weight_read_valid=1'bx; saved_valid=1'bz; end
            4: begin return_tap={1'b0,tap}; saved_tap={1'b0,tap}; return_tap[$urandom()%17]=1'bz; end
            5: begin return_tap='x; saved_tap='z; end
            6: begin tap='x; i_weight_read_valid=1'b0; saved_valid=1'b1; end
            default: begin end
        endcase
        check_tags();
    end
    for (iteration=0; iteration<20000; iteration=iteration+1) begin
        clk=0;
        rst_n=iteration%257!=0;
        weights_i_wr_en=iteration%3!=0;
        weights_i_wr_tap=$urandom();
        weights_i_wr_data={$urandom(),$urandom(),$urandom(),$urandom()};
        weights_i_wr_mask=iteration%7==0 ? 16'd0 : 16'($urandom());
        i_storage_error=iteration%31==0;
        state_failed=iteration%17==0;
        #1;
        if (!rst_n) begin
            expected_pending=0;
            reset_cycles=reset_cycles+1;
        end
        if (shared_weight_write_pending !== expected_pending ||
            o_weight_write_en !== (expected_pending && !i_storage_error && !state_failed))
            $fatal(1, "write stage valid cycle %0d", iteration);
        if (o_weight_write_en) begin
            if ({o_weight_write_addr,o_weight_write_data,o_weight_write_mask} !== expected_payload)
                $fatal(1, "write stage payload cycle %0d", iteration);
            published=published+1;
            if (previous_published) consecutive=consecutive+1;
        end
        if (expected_pending && (i_storage_error || state_failed)) cancelled=cancelled+1;
        previous_published=o_weight_write_en;
        expected_pending=rst_n && weights_i_wr_en && weights_i_wr_mask!=0 && !i_storage_error && !state_failed;
        expected_payload={weights_i_wr_tap[9:0],weights_i_wr_data,weights_i_wr_mask};
        clk=1;
        #1;
        stage_checks=stage_checks+1;
    end
    if (published==0 || consecutive==0 || cancelled==0 || reset_cycles==0) $fatal(1,"write stage coverage");
    $display("VECTOR_WEIGHT_PIPELINE_PASS tag_checks=%0d stage_checks=%0d published=%0d cancelled=%0d consecutive=%0d resets=%0d",
        tag_checks,stage_checks,published,cancelled,consecutive,reset_cycles);
    $finish;
end
endmodule
'''
    testbench = out / 'four_state.sv'
    testbench.write_text(bench)
    binary = out / 'four_state.vvp'
    run([args.iverilog, '-g2012', '-s', 'tb', '-o', binary, tags, stage, testbench], out / 'compile.log', ROOT)
    run([args.vvp, binary], out / 'four_state.log', ROOT)
    matches = re.search(r'VECTOR_WEIGHT_PIPELINE_PASS (.*)', (out / 'four_state.log').read_text())
    assert matches is not None
    counts = {name: int(value) for name, value in re.findall(r'(\w+)=(\d+)', matches[1])}
    assert digest(source) == source_hash
    report = {'passed': True, 'source_sha256': {str(ENGINE): source_hash},
              'formal': proofs, 'simulation': counts,
              'test_sha256': digest(Path(__file__)), 'simulation_log_sha256': digest(out / 'four_state.log')}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
