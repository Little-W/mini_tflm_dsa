#!/usr/bin/env python3
"""用独立双项队列证明实际 DMA 寄存缓冲的有序传输和容量行为。"""
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
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/dma/axi_dual_block_dma.sv'
    rtl = re.search(r'module dma_register_buffer\b.*?endmodule', source.read_text(), re.S).group(0)
    observed_rtl = rtl.replace('    output logic [p_width-1:0] o_data\n);',
        '    output logic [p_width-1:0] o_data,\n' +
        '    output wire [p_width-1:0] formal_tail_data\n);')
    observed_rtl = observed_rtl.replace('endmodule',
        '    assign formal_tail_data = tail_data;\nendmodule')
    model = out / 'comparison.sv'
    model.write_text(observed_rtl + '''
module buffer_comparison #(parameter integer WIDTH=45)(
    input wire clk,rst_n,i_valid,i_ready,
    input wire [WIDTH-1:0] i_data,
    output wire correct
);
    wire o_valid,o_ready;
    wire [WIDTH-1:0] o_data,formal_tail_data;
    dma_register_buffer #(.p_width(WIDTH)) dut(
        .clk,.rst_n,.i_valid,.i_ready,.i_data,.o_valid,.o_ready,.o_data,.formal_tail_data);
    reg [1:0] count;
    reg read_index,write_index;
    reg [WIDTH-1:0] data[2];
    wire push=i_valid && count!=2;
    wire pop=i_ready && count!=0;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            count<=0;read_index<=0;write_index<=0;
        end else begin
            case({push,pop})
                2'b10:count<=count+1'b1;
                2'b01:count<=count-1'b1;
                default:begin end
            endcase
            if(push)write_index<=~write_index;
            if(pop)read_index<=~read_index;
        end
    end
    always @(posedge clk)if(push)data[write_index]<=i_data;
    assign correct=(count<=2) && ((read_index^write_index)==(count==1)) &&
        (o_ready==(count!=2)) && (o_valid==(count!=0)) &&
        (!o_valid || o_data==data[read_index]) &&
        (count!=2 || formal_tail_data==data[!read_index]);
endmodule
''')
    report = {'passed': False, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'module_sha256': hashlib.sha256(rtl.encode()).hexdigest(),
              'inputs_constrained': False, 'profiles': []}
    for width in (1, 13, 45, 73, 129):
        script, log = out / f'w{width}.ys', out / f'w{width}.log'
        script.write_text(f'read_verilog -sv {shlex.quote(str(model))}\n' +
            f'chparam -set WIDTH {width} buffer_comparison\n' +
            'prep -top buffer_comparison -flatten\nasync2sync\nmemory_map\nopt -full\n' +
            'sat -seq 2 -tempinduct -maxsteps 8 -set-at 1 rst_n 0 -prove correct 1 -verify\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise RuntimeError('DMA 寄存缓冲的归纳证明未完成')
        report['profiles'].append({'width': width, 'passed': True,
                                  'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(json.dumps(report['profiles'][-1]), flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
