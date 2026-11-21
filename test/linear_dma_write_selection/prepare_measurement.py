#!/usr/bin/env python3
"""提取实际 DMA 写数据移位逻辑并添加相同的输入输出寄存器。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/dma/axi_linear_block_dma.sv')
HEADER = '''module rotation_measure #(parameter integer BUS_WIDTH=64)(
    input logic clk,
    input logic [BUS_WIDTH-1:0] i_data,
    input logic [BUS_WIDTH/8-1:0] i_mask,
    input logic [$clog2(BUS_WIDTH/8)-1:0] i_offset,
    output logic [2*BUS_WIDTH-1:0] o_data,
    output logic [2*(BUS_WIDTH/8)-1:0] o_mask
);
    localparam integer BYTE_PER_BEAT=BUS_WIDTH/8;
    localparam integer ADDR_LSB=$clog2(BYTE_PER_BEAT);
    logic [BUS_WIDTH-1:0] src_wdata;
    logic [BYTE_PER_BEAT-1:0] src_wmask;
    logic [ADDR_LSB-1:0] wr_row_offset;
    logic [2*BUS_WIDTH-1:0] wr_shifted_data;
    logic [2*BYTE_PER_BEAT-1:0] wr_shifted_mask;
    always_ff @(posedge clk) begin
        src_wdata <= i_data;
        src_wmask <= i_mask;
        wr_row_offset <= i_offset;
        o_data <= wr_shifted_data;
        o_mask <= wr_shifted_mask;
    end
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='0c99ca796e8a8cdd99180bcc8f8e5085abf17bca')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{RTL}'], cwd=ROOT)
    sources = {'reference': reference, 'current': (args.source_root / RTL).read_bytes()}
    cases, hashes = {}, {}
    for label, content in sources.items():
        source = content.decode()
        first = source.index('    // 同一字节旋转')
        last = source.index('    always_comb begin\n        wr_aligned_wdata', first)
        path = out / (label + '.sv')
        path.write_text(HEADER + source[first:last] + '\nendmodule\n')
        hashes[label] = {'rtl_sha256': hashlib.sha256(content).hexdigest(),
                         'model_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        cases[label] = {'top': 'rotation_measure', 'sources': [str(path)],
                        'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                        'configuration': 'Registered 64-bit DMA write data and byte-mask selection'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'sources.json').write_text(json.dumps(hashes, indent=2) + '\n')


if __name__ == '__main__':
    main()
