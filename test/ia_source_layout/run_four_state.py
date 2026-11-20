#!/usr/bin/env python3
"""检查实际分组排列 RTL 对四态数据的逐位传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/loaders/ia_loader_cache_mgr.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_text()
    compact_start = source.index('    if (p_dma_source_layout &&')
    compact_end = source.index('    // 写命令', compact_start)
    word_start = source.index('  if (p_dma_source_layout &&', compact_end)
    word_end = source.index('  assign write_shifted_mask', word_start)
    rtl = source[compact_start:compact_end] + source[word_start:word_end]
    tb = out / 'tb_four_state.sv'
    tb.write_text('''module tb_four_state;
    localparam bit p_dma_source_layout = 1'b1;
    localparam int SIZE=16, DATA_WIDTH=16, BUS_WIDTH=64;
    logic wr_use_16bits;
    logic [3:0] wr_col_base;
    logic [127:0] raw_words;
    logic [63:0] raw_bytes;
    logic [7:0] input_valid, compact_empty;
    logic [255:0] write_source_data, write_shifted_data, reference_words;
    logic [127:0] compact_source_bytes, compact_shifted_bytes, reference_bytes;
    logic [127:0] selected_bytes, selected_reference_bytes;
    logic [15:0] shifted_valid;
    assign compact_source_bytes = {64'd0, raw_bytes};
    assign reference_words = write_source_data << (int'(wr_col_base)*16);
    assign reference_bytes = compact_source_bytes << (int'(wr_col_base)*8);
    assign shifted_valid = {8'd0, input_valid} << wr_col_base;
    for (genvar lane=0; lane<16; lane++) begin : g_source
        if (lane<8) begin : g_input
            assign write_source_data[lane*16+:16] = input_valid[lane] ? raw_words[lane*16+:16] : 16'd0;
        end else begin : g_padding
            assign write_source_data[lane*16+:16] = 16'd0;
        end
        assign selected_bytes[lane*8+:8] = shifted_valid[lane] ? compact_shifted_bytes[lane*8+:8] : compact_empty;
        assign selected_reference_bytes[lane*8+:8] = shifted_valid[lane] ? reference_bytes[lane*8+:8] : compact_empty;
    end
''' + rtl + '''
    initial begin
        for (int sample=0; sample<100002; sample++) begin
            wr_use_16bits = sample[0];
            wr_col_base = sample[4:1];
            if (!wr_use_16bits) wr_col_base[2:0] = 3'd0;
            input_valid = 8'($urandom);
            if (wr_use_16bits) input_valid[7:4] = 4'd0;
            compact_empty = 8'($urandom);
            raw_words = {$urandom, $urandom, $urandom, $urandom};
            raw_bytes = {$urandom, $urandom};
            for (int lane=0; lane<8; lane++) begin
                case ($urandom_range(0, 7))
                    0: begin raw_words[lane*16+:16] = 'x; raw_bytes[lane*8+:8] = 'x; end
                    1: begin raw_words[lane*16+:16] = 'z; raw_bytes[lane*8+:8] = 'z; end
                    2: begin raw_words[lane*16+:16] = 16'hffff; raw_bytes[lane*8+:8] = 8'hff; end
                    3: begin raw_words[lane*16+:16] = 16'h0000; raw_bytes[lane*8+:8] = 8'h00; end
                    default: begin end
                endcase
            end
            #1;
            if (write_shifted_data !== reference_words)
                $fatal(1, "Word layout differs at sample %0d", sample);
            if (selected_bytes !== selected_reference_bytes)
                $fatal(1, "Compact layout differs at sample %0d", sample);
        end
        $display("IA_SOURCE_LAYOUT_FOUR_STATE_PASS samples=100002 comparisons=200004");
        $finish;
    end
endmodule
''')
    command = ['iverilog', '-g2012', '-s', 'tb_four_state', '-o', str(out / 'sim'), str(tb)]
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(['vvp', str(out / 'sim')], capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    if result.returncode or 'IA_SOURCE_LAYOUT_FOUR_STATE_PASS' not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    if source != SOURCE.read_text():
        raise RuntimeError('RTL changed during verification')
    report = dict(passed=True, samples=100002, comparisons=200004,
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  payload_states=['0', '1', 'x', 'z'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
