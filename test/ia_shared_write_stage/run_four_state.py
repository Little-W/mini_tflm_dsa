#!/usr/bin/env python3
"""从实际写命令寄存 RTL 检查预选数据的四态传递与复位使能。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from helpers import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.source_root.resolve() / 'rtl/npu/loaders/ia_loader_cache_mgr.sv'
    source = source_path.read_text()
    start = source.index('    always_ff @(posedge clk) begin', source.index('    // 写命令'))
    end = source.index('    wire [RAM_WORD_ADDR_WIDTH-1:0] write_row_word', start)
    tb = out / 'tb_four_state.sv'
    tb.write_text('''module tb_four_state;
    localparam int SIZE=16, DATA_WIDTH=16, RAM_WORD_ADDR_WIDTH=12, DMA_LANES=8;
    localparam bit p_shared_write_stage=1;
    logic clk=0, rst_n;
    logic [1:0] write_en, ram_port_wr_en;
    logic [11:0] write_addr [2], ram_port_wr_addr [2];
    logic [127:0] write_data [2], ram_port_wr_data [2], ram_shared_wr_data;
    logic [15:0] write_mask [2], ram_port_wr_mask [2];
    logic compact_mode, second_port_valid;
    logic signed [15:0] compact_offset;
    logic [3:0] wr_col_base;
    logic signed [15:0] wr_data [DMA_LANES];
    logic wr_valid [DMA_LANES];
    logic [7:0] compact_empty_byte;
    logic [255:0] source_words, shifted_words;
    logic [127:0] source_bytes, shifted_bytes;
    logic [15:0] source_mask, shifted_mask;
    logic [7:0] compact_write_byte [16];
    logic signed [15:0] ram_wr_data [16];
    logic [127:0] expected_shared_data;
    logic [127:0] expected_port_data [2];
    int comparisons=0;
    assign compact_empty_byte = 8'(0 - compact_offset);
    for (genvar lane=0; lane<16; lane++) begin : g_source
        if (lane<DMA_LANES) begin : g_input
            assign source_words[lane*16+:16] = wr_valid[lane] ? wr_data[lane] : 16'd0;
            assign source_bytes[lane*8+:8] = 8'(wr_data[lane][7:0] + compact_empty_byte);
            assign source_mask[lane] = wr_valid[lane];
        end else begin : g_padding
            assign source_words[lane*16+:16] = 16'd0;
            assign source_bytes[lane*8+:8] = 8'd0;
            assign source_mask[lane] = 1'b0;
        end
        assign ram_wr_data[lane] = shifted_words[lane*16+:16];
        assign compact_write_byte[lane] = shifted_mask[lane] ? shifted_bytes[lane*8+:8] : compact_empty_byte;
    end
    assign shifted_words = source_words << (int'(wr_col_base)*16);
    assign shifted_bytes = source_bytes << (int'(wr_col_base)*8);
    assign shifted_mask = source_mask << wr_col_base;
    for (genvar lane=0; lane<8; lane++) begin : g_input_data
        assign write_data[0][lane*16+:16] = compact_mode ?
            {compact_write_byte[lane*2+1], compact_write_byte[lane*2]} : ram_wr_data[lane];
        assign write_data[1][lane*16+:16] = ram_wr_data[lane+8];
    end
    always_ff @(posedge clk) begin
        if (|write_en)
            expected_shared_data <= write_en[1] ? write_data[1] : write_data[0];
        for (int port_index=0; port_index<2; port_index++)
            if (write_en[port_index]) expected_port_data[port_index] <= write_data[port_index];
    end
''' + source[start:end] + '''
    initial begin
        for(int sample=0;sample<100004;sample++) begin
            clk=0;
            rst_n=sample>3 && sample%97!=0;
            compact_mode=sample[2];
            compact_offset=16'($urandom);
            wr_col_base=4'($urandom);
            second_port_valid=sample[1];
            if (sample%31==0) compact_mode=1'bx;
            if (sample%37==0) compact_mode=1'bz;
            if (sample%41==0) second_port_valid=1'bx;
            if (sample%47==0) compact_offset[3]=1'bx;
            if (sample%53==0) wr_col_base[1]=1'bx;
            write_en[0]=sample[0];
            write_en[1]=!compact_mode && second_port_valid;
            if (sample%43==0) write_en[0]=1'bx;
            for(int port_index=0;port_index<2;port_index++) begin
                write_addr[port_index]=12'($urandom);
                write_mask[port_index]=16'($urandom);
            end
            for(int lane=0;lane<DMA_LANES;lane++) begin
                wr_data[lane]=16'($urandom);
                wr_valid[lane]=1'($urandom);
                if (sample%59==0) wr_valid[lane]=1'bx;
                for(int byte_index=0;byte_index<2;byte_index++) begin
                    case($urandom_range(0,7))
                        0: wr_data[lane][byte_index*8+:8]='x;
                        1: wr_data[lane][byte_index*8+:8]='z;
                        2: wr_data[lane][byte_index*8+:8]=8'hff;
                        3: wr_data[lane][byte_index*8+:8]=8'h00;
                        default: begin end
                    endcase
                end
            end
            #1; clk=1; #1;
            if ((|ram_port_wr_en) === 1'b1) begin
                if (ram_shared_wr_data !== expected_shared_data)
                    $fatal(1,"Shared write data differs at sample %0d",sample);
                comparisons++;
            end
            for (int port_index=0; port_index<2; port_index++) begin
                if (ram_port_wr_en[port_index] === 1'b1) begin
                    if (ram_port_wr_data[port_index] !== expected_port_data[port_index])
                        $fatal(1,"Write port data differs at sample %0d port %0d",sample,port_index);
                    comparisons++;
                end
            end
            if(ram_port_wr_en[1] === 1'b1) begin
                if(ram_shared_wr_data !== ram_port_wr_data[1]) $fatal(1,"Second write port data differs");
                comparisons++;
            end else if(ram_port_wr_en[1] === 1'b0 && ram_port_wr_en[0] === 1'b1) begin
                if(ram_shared_wr_data !== ram_port_wr_data[0]) $fatal(1,"First write port data differs");
                comparisons++;
            end
            if(!rst_n && ram_port_wr_en !== 2'b0) $fatal(1,"Reset write enable differs");
        end
        $display("IA_SHARED_WRITE_FOUR_STATE_PASS samples=100004 comparisons=%0d",comparisons);
        $finish;
    end
endmodule
''')
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb_four_state', '-o', str(out / 'sim'), str(tb)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(['vvp', str(out / 'sim')], capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    if result.returncode or 'IA_SHARED_WRITE_FOUR_STATE_PASS' not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    import re
    comparisons = int(re.search(r'comparisons=(\d+)', result.stdout)[1])
    report = dict(passed=True, samples=100004, comparisons=comparisons,
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  source_path=str(source_path),
                  payload_states=['0', '1', 'x', 'z'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
