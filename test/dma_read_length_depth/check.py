#!/usr/bin/env python3
"""对实际 DMA 后续读长度表达式检查任意二值输入及严格四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit(text, name):
    begin = text.index('    assign rd_next_cmd_offset =')
    end = text.index('    for (genvar segment = 0; segment < 2; segment++) begin : g_read_segment', begin)
    preparation = text[begin:end]
    begin = end + len('    for (genvar segment = 0; segment < 2; segment++) begin : g_read_segment')
    end = text.index('        if (segment == 0) begin : g_first_address', begin)
    page = text[begin:end]
    begin = text.index('        logic [7:0] remaining_len, page_len, page_last_full_word;', end)
    end = text.index('        for (genvar candidate = 0; candidate < p_address_candidates;', begin)
    length = text[begin:end]
    body = preparation + '\n    for (genvar segment = 1; segment < 2; segment++) begin : g_read_segment\n' + page + length + '\n    end\n'
    # Icarus 使用等值的非负整数常量类型，数据和控制表达式保持提取文本。
    body = body.replace('localparam int unsigned', 'localparam integer')
    return f'''module {name} #(
    parameter integer ADDR_LSB=3, MAX_BURST_BEATS=256
) (
    input logic [8:0] rd_follow_beats,
    input logic [31:0] rd_follow_addr, rd_cmd_row_addr,
    input logic [7:0] rd_cfg_burst_len_m1,
    input logic rd_cfg_linear_read,
    output logic [7:0] o_length
);
    localparam integer REG_WIDTH=32;
    typedef logic [8:0] beat_count_t;
    logic [ADDR_LSB-1:0] rd_next_cmd_offset;
    logic [31:0] rd_next_cmd_addr;
    beat_count_t rd_next_cmd_beats, rd_next_row_beats;
    logic [31:0] rd_segment_addr [2];
    beat_count_t rd_segment_remaining [2], rd_segment_beats [2];
    logic [7:0] rd_segment_len [2];
    wire [31:0] rd_first_ar_addr=32'd0, rd_merged_beats=32'd0;
    wire [8:0] rd_first_span_beats=9'd0, rd_first_beats=9'd0;
    wire rd_merge_rows=1'b0;
{body}
    assign o_length=rd_segment_len[1];
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = out / 'length_units.sv'
    source.write_text(unit(args.reference.read_text(), 'reference_length') +
                      unit(args.candidate.read_text(), 'current_length'))
    cases = list(itertools.product((1, 2, 3, 4), (1, 2, 4, 8, 16, 32, 64, 128, 256)))
    proof = out / 'proof.sv'
    proof.write_text('''module proof #(
    parameter integer ADDR_LSB=3, MAX_BURST_BEATS=256
) (
    input logic [8:0] rd_follow_beats,
    input logic [31:0] rd_follow_addr, rd_cmd_row_addr,
    input logic [7:0] rd_cfg_burst_len_m1,
    input logic rd_cfg_linear_read,
    output logic equal
);
    logic [7:0] reference_result, current_result;
    reference_length #(.ADDR_LSB(ADDR_LSB),.MAX_BURST_BEATS(MAX_BURST_BEATS)) a (
        .rd_follow_beats,.rd_follow_addr,.rd_cmd_row_addr,.rd_cfg_burst_len_m1,
        .rd_cfg_linear_read,.o_length(reference_result));
    current_length #(.ADDR_LSB(ADDR_LSB),.MAX_BURST_BEATS(MAX_BURST_BEATS)) b (
        .rd_follow_beats,.rd_follow_addr,.rd_cmd_row_addr,.rd_cfg_burst_len_m1,
        .rd_cfg_linear_read,.o_length(current_result));
    assign equal=reference_result==current_result;
endmodule
''')
    result = dict(passed=False, source_sha256={'reference': digest(args.reference),
        'current': digest(args.candidate)}, input_constraints=[], profiles=[])
    for lsb, maximum in cases:
        script = out / f'lsb{lsb}_max{maximum}.ys'
        script.write_text('read_slang --top proof ' + f'-GADDR_LSB={lsb} -GMAX_BURST_BEATS={maximum} ' +
            shlex.join([str(source), str(proof)]) + '\nprep -top proof -flatten\nopt -full\n'
            'sat -verify -set-def-inputs -prove equal 1 -show-inputs -show-outputs\n')
        log = script.with_suffix('.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('长度表达式检查不完整：' + str(log))
        result['profiles'].append(dict(address_lsb=lsb, maximum_burst_beats=maximum, passed=True,
            script_sha256=digest(script), log_sha256=digest(log)))
    tb = out / 'tb.sv'
    instances = []
    for index, (lsb, maximum) in enumerate(cases):
        for label in ('reference', 'current'):
            instances.append(f'''{label}_length #(.ADDR_LSB({lsb}),.MAX_BURST_BEATS({maximum})) u_{label}_{index} (
      .rd_follow_beats,.rd_follow_addr,.rd_cmd_row_addr,.rd_cfg_burst_len_m1,.rd_cfg_linear_read,
      .o_length({label}_result[{8*index}+:8]));''')
    tb.write_text(f'''module tb;
    logic [8:0] rd_follow_beats;
    logic [31:0] rd_follow_addr, rd_cmd_row_addr;
    logic [7:0] rd_cfg_burst_len_m1;
    logic rd_cfg_linear_read;
    wire [{8*len(cases)-1}:0] reference_result, current_result;
{chr(10).join(instances)}
    initial begin
      for (integer sample=0; sample<32768; sample++) begin
        rd_follow_addr=$urandom;
        rd_cmd_row_addr=$urandom;
        rd_follow_beats=9'($urandom);
        rd_cfg_burst_len_m1=8'($urandom);
        rd_cfg_linear_read=sample[0];
        case (sample%16)
          0: rd_follow_beats=0;
          1: rd_follow_beats=1;
          2: rd_follow_beats=256;
          3: rd_follow_beats=511;
          4: rd_follow_addr[sample%32]=1'bx;
          5: rd_cmd_row_addr[sample%32]=1'bz;
          6: begin rd_follow_beats=0; rd_follow_beats[(sample/16)%9]=1'bx; end
          7: begin rd_follow_beats=0; rd_follow_beats[(sample/16)%9]=1'bz; end
          8: rd_follow_beats[(sample/16)%9]=1'bx;
          9: rd_cfg_burst_len_m1[(sample/16)%8]=1'bz;
          10: rd_cfg_linear_read=1'bx;
          11: begin rd_follow_addr='x; rd_cmd_row_addr='z; end
          default: begin end
        endcase
        #1;
        if (reference_result !== current_result)
          $fatal(1,"DMA read length differs sample=%0d follow=%b reference=%h current=%h",
              sample,rd_follow_beats,reference_result,current_result);
      end
      $display("DMA_READ_LENGTH_FOUR_STATE_PASS samples=32768 profiles={len(cases)}");
      $finish;
    end
endmodule
''')
    executable = out / 'sim'
    with (out / 'four_state_compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable), str(source), str(tb)],
            stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out / 'four_state.log').open('w') as stream:
        subprocess.run(['vvp', str(executable)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    if 'DMA_READ_LENGTH_FOUR_STATE_PASS' not in (out / 'four_state.log').read_text():
        raise RuntimeError('四态长度检查不完整')
    result.update(passed=True, four_state_samples=32768, four_state_comparisons=32768*len(cases),
                  extracted_source_sha256=digest(source), testbench_sha256=digest(tb),
                  runner_sha256=digest(Path(__file__).resolve()))
    if result['source_sha256'] != {'reference': digest(args.reference), 'current': digest(args.candidate)}:
        raise RuntimeError('验证期间输入源码发生变化')
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, profiles=len(cases), four_state_comparisons=result['four_state_comparisons'])))


if __name__ == '__main__':
    main()
