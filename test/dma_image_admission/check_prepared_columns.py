#!/usr/bin/env python3
"""验证图像列数在命令接收边沿保存后的完整定宽与四态关系。"""
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
ARBITER = ROOT / 'rtl/npu/dma/axi_block_dma_arbiter.sv'
DMA = ROOT / 'rtl/npu/dma/axi_dual_block_dma.sv'
PROFILES = ((1, 2, 2), (2, 3, 4), (5, 16, 32), (16, 7, 64),
            (32, 2, 2), (32, 3, 4), (32, 7, 16), (32, 16, 64),
            (32, 32, 64), (32, 64, 64), (64, 16, 64), (64, 256, 256))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)


def model():
    source, dma = ARBITER.read_text(), DMA.read_text()
    first = source.index('    localparam int p_image_columns_width =')
    last = source.index('    logic [8-1:0] rd_dma_burst_len_m1_q;', first)
    prepared = source[first:last]
    assignments = re.findall(r'rd_dma_valid_cols\s*=\s*([^;]+);', source)
    assert assignments == ["REG_WIDTH'(DMA_SIZE)", 'dw_valid_cols']
    resets = re.findall(r'rd_dma_image_columns_q\s*<=\s*([^;]+);', source)
    assert resets == ["p_image_columns_width'(SIZE)", 'rd_dma_image_columns']
    assert '.p_prepared_image_columns(1\'b1)' in source
    assert '.rd_image_columns   (rd_dma_image_columns_q)' in source
    assert 'assign image_columns = rd_image_columns;' in dma
    reference = re.search(r'assign image_columns = \(rd_valid_cols > 0.*?;', dma, re.S)[0]
    reference = reference.replace('assign image_columns', 'assign expected')
    reference = reference.replace('rd_valid_cols', 'raw_columns_q')
    reference = reference.replace('IM2COL_SIZE', 'SIZE')
    return '''// 命令列数字段的同边沿关系，参照保存原始字段后计算输出。
module comparison #(
 parameter int REG_WIDTH=32,SIZE=16,DMA_SIZE=64,
 localparam int CONV_RW=$clog2(SIZE+1)
)(
 input logic clk, // 命令接收时钟
 input logic rst_n, // 同步低有效复位
 input logic rd_dma_start, // 当前边沿保存新命令
 input logic [2:0] rd_command_client, // 本次命令的客户端编号
 input logic [REG_WIDTH-1:0] dw_valid_cols, // 向量客户端请求的原始列数
 output logic [CONV_RW-1:0] actual, // 命令寄存器保存的图像列数
 output logic [CONV_RW-1:0] expected, // 原始字段经过范围处理后的列数
 output logic equivalent // 两种寄存安排具有相同输出
);
 localparam logic [2:0] C_DW=3'd4;
 logic [REG_WIDTH-1:0] raw_columns,raw_columns_q;
 assign raw_columns=(rd_command_client===C_DW) ? dw_valid_cols : REG_WIDTH'(DMA_SIZE);
 always_ff @(posedge clk)begin
  if(!rst_n)raw_columns_q<='0;
  else if(rd_dma_start)raw_columns_q<=raw_columns;
 end
''' + prepared + f'''
 always_ff @(posedge clk)begin
  if(!rst_n)rd_dma_image_columns_q<={resets[0]};
  else if(rd_dma_start)rd_dma_image_columns_q<={resets[1]};
 end
 {reference}
 assign actual=rd_dma_image_columns_q;
 assign equivalent=actual===expected;
endmodule
'''


def bench(width, size, dma_size):
    bits = width + 5
    return f'''// 覆盖完整输入位的四种逻辑值及连续接收、保持和复位。
module tb;
 localparam int p_bits={bits};
 logic clk=0,rst_n=0,rd_dma_start=0;
 logic [2:0] rd_command_client=0;
 logic [{width-1}:0] dw_valid_cols=0;
 logic [$clog2({size}+1)-1:0] actual,expected;
 logic equivalent;
 logic [p_bits-1:0] stimulus;
 logic [3:0] seen[p_bits];
 integer seed=32'h731942af,checks=0,accepted=0,held=0,resets=0;
 comparison #(.REG_WIDTH({width}),.SIZE({size}),.DMA_SIZE({dma_size})) dut(.*);
 function automatic logic symbol(input integer value);
  case(value%4)0:symbol=0;1:symbol=1;2:symbol=1'bx;default:symbol=1'bz;endcase
 endfunction
 task check;
  #1;
  if(equivalent!==1'b1)$fatal(1,"columns expected=%h actual=%h sample=%0d",expected,actual,checks);
  checks++;
 endtask
 initial begin
  for(integer bit_index=0;bit_index<p_bits;bit_index++)seen[bit_index]=0;
  #1;clk=1;check();clk=0;
  for(integer sample=0;sample<8192;sample++)begin
   if(sample<4*p_bits)begin
    stimulus=(sample%2)==0?'0:'1;
    stimulus[sample/4]=symbol(sample%4);
   end else begin
    for(integer bit_index=0;bit_index<p_bits;bit_index++)
     stimulus[bit_index]=symbol($unsigned($random(seed)));
    if(sample%3!=0)begin
     stimulus='0;
     stimulus[{width-1}:0]=$random(seed);
     stimulus[{width+2}:{width}]=sample%8;
     stimulus[{width+3}]=sample%5!=0;
     stimulus[{width+4}]=sample%29!=0;
    end
   end
   {{rst_n,rd_dma_start,rd_command_client,dw_valid_cols}}=stimulus;
   for(integer bit_index=0;bit_index<p_bits;bit_index++)begin
    case(stimulus[bit_index])
     1'b0:seen[bit_index][0]=1;1'b1:seen[bit_index][1]=1;
     1'bx:seen[bit_index][2]=1;1'bz:seen[bit_index][3]=1;
    endcase
   end
   check();clk=1;check();clk=0;
   if(!rst_n)resets++;else if(rd_dma_start)accepted++;else held++;
  end
  for(integer bit_index=0;bit_index<p_bits;bit_index++)
   if(seen[bit_index]!==4'b1111)$fatal(1,"incomplete input coverage");
  if(accepted==0||held==0||resets==0)$fatal(1,"incomplete event coverage");
  $display("PREPARED_COLUMNS_PASS checks=%0d inputs=%0d accepted=%0d held=%0d resets=%0d",checks,p_bits,accepted,held,resets);
  $finish;
 end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in (ARBITER, DMA)}
    generated = out / 'comparison.sv'
    generated.write_text(model())
    rows = []
    for width, size, dma_size in PROFILES:
        name = f'w{width}_s{size}_d{dma_size}'
        script, formal = out / (name+'.ys'), out / (name+'_formal.log')
        script.write_text('read_slang --top comparison '+
            f'-GREG_WIDTH={width} -GSIZE={size} -GDMA_SIZE={dma_size} '+
            shlex.quote(str(generated))+'\nprep -top comparison -flatten\nopt -full\n'+
            'sat -verify -seq 1 -tempinduct -maxsteps 4 -set-init-zero -set-at 1 rst_n 0 '+
            '-set-def-inputs -prove equivalent 1 -show-inputs -show-outputs\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], formal)
        if 'Induction step proven: SUCCESS!' not in formal.read_text():
            raise RuntimeError(str(formal))
        tb, binary = out / (name+'_tb.sv'), out / (name+'.vvp')
        tb.write_text(bench(width, size, dma_size))
        execute(['iverilog', '-g2012', '-s', 'tb', '-o', binary, generated, tb], out/(name+'_compile.log'))
        simulation = out / (name+'_four_state.log')
        execute(['vvp', binary], simulation)
        result = re.search(r'PREPARED_COLUMNS_PASS checks=(\d+) inputs=(\d+) accepted=(\d+) held=(\d+) resets=(\d+)', simulation.read_text())
        if result is None or int(result[1]) != 16385:
            raise RuntimeError(str(simulation))
        binary.unlink()
        rows.append({'width': width, 'size': size, 'dma_size': dma_size, 'passed': True,
                     'four_state_checks': int(result[1]), 'input_bits': int(result[2]),
                     'all_input_bits_cover_0_1_x_z': True,
                     'accepted': int(result[3]), 'held': int(result[4]), 'reset': int(result[5]),
                     'formal_log_sha256': digest(formal), 'simulation_log_sha256': digest(simulation)})
        print(name, 'PASS', flush=True)
    assert hashes == {str(path.relative_to(ROOT)): digest(path) for path in (ARBITER, DMA)}
    (out/'summary.json').write_text(json.dumps({'passed': True, 'source_sha256': hashes,
        'scope': 'The actual prepared-column selection and existing command capture event; all column bits, client encodings, resets, writes and holds.',
        'unbounded_induction': True, 'cycles_added': 0, 'cases': rows,
        'model_sha256': digest(generated), 'four_state_checks': sum(row['four_state_checks'] for row in rows)},
        ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
