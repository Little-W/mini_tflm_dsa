#!/usr/bin/env python3
"""逐周期比较预测器公开输出及全部数组化阶段的四态结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from run_formal import ARRAYS, PREDICTOR, ROOT


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference_root, source_root = args.reference_root.resolve(), args.source_root.resolve()
    old = (reference_root / PREDICTOR).read_text()
    current = (source_root / PREDICTOR).read_text()
    original_declarations = (
        '  logic [4:0] tap_s0, tap_s1;',
        '  logic coordinate_good_s0, coordinate_good_s1;',
        '  logic coordinate_good_s2, candidate_good_s3, candidate_good_s4, candidate_good_s5, candidate_good_s6;',
        '  logic [31:0] block_s3, local_s3, block_s4, group_s4, local_s4, local_s5;',
    )
    array_declarations = (
        '  logic [4:0] tap_pipe [0:1];', '  logic coordinate_good [0:2];',
        '  logic candidate_good [3:6];', '  logic [31:0] block_pipe [3:4];',
        '  logic [31:0] local_pipe [3:5];', '  logic [31:0] group_s4;',
    )
    a, b = old, current
    for declaration in original_declarations:
        if a.count(declaration) != 1:
            raise ValueError(f'参考阶段声明不唯一：{declaration}')
        a = a.replace(declaration, '')
    for declaration in array_declarations:
        if b.count(declaration) != 1:
            raise ValueError(f'数组阶段声明不唯一：{declaration}')
        b = b.replace(declaration, '')
    for name, (array, _) in ARRAYS.items():
        b = b.replace(array, name)
    def tokens(text):
        return re.sub(r'\s+', '', re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S))
    if tokens(a) != tokens(b):
        raise ValueError('阶段字段声明和引用之外存在代码差异')

    reference = out / 'reference.sv'
    reference.write_text(old.replace('module conv_next_use_predictor', 'module reference_predictor'))
    sources = []
    for relative in ('rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/common/onehot_check.sv',
                     'rtl/common/parallel_prefix_add.sv'):
        if (reference_root / relative).read_bytes() != (source_root / relative).read_bytes():
            raise ValueError(f'两侧依赖内容不同：{relative}')
        sources.append(source_root / relative)
    sources += [reference, source_root / PREDICTOR]
    stage_bits = sum(width for _, width in ARRAYS.values())
    original_fields = ','.join('reference_dut.' + name for name in ARRAYS)
    array_fields = ','.join('current_dut.' + value[0] for value in ARRAYS.values())
    bench = out / 'tb.sv'
    bench.write_text(f'''module tb;
  logic clk=0,rst_n=0,cfg_valid=0,start=0;
  conv_im2col_pkg::conv_cfg_t cfg;
  logic [31:0] cfg_r=2,cfg_groups=2,input_y=0,input_x=0,channel=0;
  logic [31:0] current_p=0,current_q=0,current_group=0;
  wire [36:0] a,b;
  wire [{stage_bits-1}:0] old_stages,current_stages;
  wire reference_busy,reference_cfg_busy;
  integer checks=0,known_bits=0,unknown_bits=0;
  reg [31:0] random_state=32'h5467de2b;
  reference_predictor reference_dut(
    .cfg_eligible(a[36]),.cfg_busy(a[35]),.enabled(a[34]),.busy(a[33]),.done(a[32]),.next_rank(a[31:0]),.*);
  conv_next_use_predictor current_dut(
    .cfg_eligible(b[36]),.cfg_busy(b[35]),.enabled(b[34]),.busy(b[33]),.done(b[32]),.next_rank(b[31:0]),.*);
  assign old_stages={{{original_fields}}};
  assign current_stages={{{array_fields}}};
  function automatic [31:0] step(input [31:0] value);
    reg [31:0] next_value;
    begin next_value=value^(value<<13);next_value=next_value^(next_value>>17);
      step=next_value^(next_value<<5);end
  endfunction
  task configure;
    begin
      cfg='0;cfg.input_base=32'h10000;cfg.input_h=8;cfg.input_w=8;cfg.input_c=32;
      cfg.group_c=16;cfg.kernel_h=3;cfg.kernel_w=3;cfg.output_h=8;cfg.output_w=8;
      cfg.stride_h=1;cfg.stride_w=1;cfg.dilation_h=1;cfg.dilation_w=1;
      cfg.pad_top=1;cfg.pad_left=1;cfg_r=2;cfg_groups=2;
    end
  endtask
  task check;
    reg [{stage_bits+36}:0] results;
    begin
      #1;checks++;
      if(a!==b || old_stages!==current_stages)
        $fatal(1,"Predictor four-state mismatch check=%0d",checks);
      results={{a,old_stages}};
      for(integer index=0;index<{stage_bits+37};index++)
        if(results[index]===1'b0 || results[index]===1'b1)known_bits++;
        else unknown_bits++;
    end
  endtask
  task cycle;
    begin check();clk=1;check();clk=0;end
  endtask
  initial begin
    configure();cycle();rst_n=1;cfg_valid=1;cycle();cfg_valid=0;
    for(integer sample=0;sample<10000;sample++)begin
      random_state=step(random_state);
      rst_n=1;cfg_valid=0;start=0;
      input_y=random_state[2:0];input_x=random_state[6:4];channel=0;
      current_p=random_state[13:8];current_q=32'(random_state[14])*16;
      current_group=32'(random_state[15]);
      if(sample%127==0)begin configure();cfg_valid=1;end
      else if(!a[35] && !a[33]) start=1;
      if(sample>=2000)begin
        case(sample%17)
          0:input_y[sample%32]=1'bx;
          1:input_x[sample%32]=1'bz;
          2:current_p[sample%32]=1'bx;
          3:current_q[sample%32]=1'bz;
          4:current_group[sample%32]=1'bx;
          5:channel[sample%32]=1'bz;
          6:start=1'bx;
          7:start=1'bz;
          8:cfg_valid=1'bx;
          9:cfg_valid=1'bz;
          10:rst_n=1'bx;
          11:rst_n=1'bz;
          12:begin cfg_valid=1;cfg.input_h=16'hxxxx;end
          13:begin cfg_valid=1;cfg.stride_w=16'hzzzz;end
          default:begin end
        endcase
      end
      cycle();
    end
    $display("PREDICTOR_FOUR_STATE_PASS checks=%0d known_bits=%0d unknown_bits=%0d",checks,known_bits,unknown_bits);
    $finish;
  end
endmodule
''')
    binary = out / 'run.vvp'
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), *map(str, sources), str(bench)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out / 'run.log').open('w') as stream:
        subprocess.run(['vvp', str(binary)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=240)
    text = (out / 'run.log').read_text()
    match = re.search(r'PREDICTOR_FOUR_STATE_PASS checks=(\d+) known_bits=(\d+) unknown_bits=(\d+)', text)
    if not match:
        raise RuntimeError('预测器四态检查结果缺失')
    report = {'passed': True, 'only_stage_representation_changed': True,
              'strict_four_state_equivalence': True, 'observed_bits': stage_bits + 37,
              **dict(zip(['checks', 'known_bits', 'unknown_bits'], map(int, match.groups()))),
              'source_sha256': digest(source_root / PREDICTOR),
              'reference_sha256': digest(reference_root / PREDICTOR), 'log_sha256': digest(out / 'run.log')}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
