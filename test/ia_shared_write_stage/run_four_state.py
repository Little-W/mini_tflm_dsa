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
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'rtl/npu/loaders/ia_loader_cache_mgr.sv').read_text()
    start = source.index('    always_ff @(posedge clk) begin', source.index('    // 写命令'))
    end = source.index('    wire [RAM_WORD_ADDR_WIDTH-1:0] write_row_word', start)
    tb = out / 'tb_four_state.sv'
    tb.write_text('''module tb_four_state;
    localparam int SIZE=16, DATA_WIDTH=16, RAM_WORD_ADDR_WIDTH=12;
    localparam bit p_shared_write_stage=1;
    logic clk=0, rst_n;
    logic [1:0] write_en, ram_port_wr_en;
    logic [11:0] write_addr [2], ram_port_wr_addr [2];
    logic [127:0] write_data [2], ram_port_wr_data [2], ram_shared_wr_data;
    logic [15:0] write_mask [2], ram_port_wr_mask [2];
    int comparisons=0;
''' + source[start:end] + '''
    initial begin
        for(int sample=0;sample<100004;sample++) begin
            clk=0;
            rst_n=sample>3 && sample%97!=0;
            write_en=sample[1:0];
            for(int port_index=0;port_index<2;port_index++) begin
                write_addr[port_index]=12'($urandom);
                write_data[port_index]={$urandom,$urandom,$urandom,$urandom};
                write_mask[port_index]=16'($urandom);
                for(int byte_index=0;byte_index<16;byte_index++) begin
                    case($urandom_range(0,7))
                        0: write_data[port_index][byte_index*8+:8]='x;
                        1: write_data[port_index][byte_index*8+:8]='z;
                        2: write_data[port_index][byte_index*8+:8]=8'hff;
                        3: write_data[port_index][byte_index*8+:8]=8'h00;
                        default: begin end
                    endcase
                end
            end
            #1; clk=1; #1;
            if(ram_port_wr_en[1]) begin
                if(ram_shared_wr_data !== ram_port_wr_data[1]) $fatal(1,"Second write port data differs");
                comparisons++;
            end else if(ram_port_wr_en[0]) begin
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
                  payload_states=['0', '1', 'x', 'z'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
