#!/usr/bin/env python3
"""证明实际 DMA 输出寄存器的占用守恒、内容保持和完成排空关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_dual_block_dma.sv')


def unit(source):
    declaration_start = source.index('    logic fe_output_valid,')
    declaration_end = source.index('\n\n', declaration_start)
    body_start = source.index('    // 图像输出在同一边沿保存数据与位置')
    body_end = source.index('    // 线性读取的末次输出', body_start)
    return '''module output_check #(
  parameter int WINDOW_LANES=4, SLOT_W=2, CONV_CW=4
)(
  input logic clk, rst_n, fe_wr_valid, win_frontend_active,
  input logic win_frontend_rsp_ready, fe_error, fe_tile_error, fe_wr_last,
  input logic [SLOT_W-1:0] fe_slot,
  input logic [CONV_CW-1:0] fe_row, fe_col,
  input logic signed [15:0] fe_data[WINDOW_LANES],
  input logic [WINDOW_LANES-1:0] fe_mask,
  output logic equivalent
);
''' + source[declaration_start:declaration_end] + '\n' + source[body_start:body_end] + '''
  localparam int PAYLOAD_W=2+SLOT_W+2*CONV_CW+17*WINDOW_LANES;
  logic [PAYLOAD_W-1:0] input_payload, output_payload, expected_payload;
  logic [WINDOW_LANES*16-1:0] input_data_bits, output_data_bits;
  logic [1:0] queued_items;
  logic accept, deliver;
  assign input_data_bits={>>{fe_data}};
  assign output_data_bits={>>{fe_output_data}};
  assign input_payload={win_frontend_active,fe_wr_last,fe_slot,fe_row,fe_col,
                        fe_mask,input_data_bits};
  assign output_payload={fe_output_window,fe_output_last,fe_output_slot,
                         fe_output_row,fe_output_col,fe_output_mask,output_data_bits};
  assign accept=fe_wr_valid && fe_input_ready;
  assign deliver=fe_output_valid && fe_output_ready;
  // 独立计数模型记录已接收且尚未发送的事务数量。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) queued_items <= 0;
    else queued_items <= queued_items + 2'(accept) - 2'(deliver);
  end
  always_ff @(posedge clk) begin
    if (accept) expected_payload <= input_payload;
  end
  assign equivalent = queued_items <= 1 &&
    fe_output_valid == (queued_items == 1) &&
    (!fe_output_valid || output_payload == expected_payload) &&
    (fe_input_ready == (queued_items == 0 || fe_output_ready)) &&
    (fe_output_drained == (queued_items == 0 || deliver)) &&
    (!fe_window_error || queued_items == 0);
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_path = args.source_root.resolve() / SOURCE
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'output_check.sv'
    target.write_text(unit(source_path.read_text()))
    records = []
    for lanes, slot_width, coordinate_width in ((1, 1, 2), (4, 2, 4), (8, 3, 6)):
        name = f'lanes{lanes}_slot{slot_width}_coordinate{coordinate_width}'
        script = out / (name + '.ys')
        log = out / (name + '.log')
        script.write_text(
            f'read_slang --top output_check -GWINDOW_LANES={lanes} '
            f'-GSLOT_W={slot_width} -GCONV_CW={coordinate_width} '
            + shlex.quote(str(target)) + '\n'
            'prep -top output_check -flatten\nasync2sync\ndffunmap\n'
            'sat -seq 4 -tempinduct -prove equivalent 1 -set-init-zero -verify '
            '-show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT,
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        records.append({'case': name, 'passed': True, 'log': str(log)})
        print('DMA_OUTPUT_INDUCTION_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({
        'passed': True, 'cases': records,
        'source_sha256': {str(source_path): hashlib.sha256(source_path.read_bytes()).hexdigest()},
        'properties': ['单项占用守恒', '事务内容与顺序', '背压时数据保持',
                       '空闲或当前事务发送后允许完成', '终止错误等待已保存数据发送']
    }, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
