#!/usr/bin/env python3
"""从实际 FIFO 源码检查截断乘积、分段行比较及其四态语义。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/vec_s8_to_fifo.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_models(source: str) -> tuple[str, str]:
    """保留候选实现，仅增加独立输入、参考表达式和观察输出。"""
    start = source.index('  logic [BANK_COUNT_WIDTH-1:0] co_tiles;')
    end = source.index('  logic [4:0] co_nonzero_terms;', start)
    product = '''module product #(parameter BANK_COUNT_WIDTH=6)(
  input logic [31:0] coalesce_rows, coalesce_cols,
  output logic [BANK_COUNT_WIDTH-1:0] candidate, reference_result,
  output logic equivalent);
''' + source[start:end] + '''
  assign candidate = co_tiles;
  assign reference_result = BANK_COUNT_WIDTH'(coalesce_rows[4:0] * coalesce_cols[4:0]);
  assign equivalent = candidate == reference_result;
endmodule
'''
    selection = re.search(
        r'  wire \[COUNT_WIDTH-1:0\] output_row_count =\n.*?;', source, re.S)
    if selection is None:
        raise RuntimeError('无法定位输出行数选择表达式')
    start = source.index('  (* keep = 1 *) logic read_row_count_last;')
    end = source.index('  wire last_row_in_bank', start)
    row = '''module row_compare #(parameter COUNT_WIDTH=5)(
  input logic [COUNT_WIDTH-1:0] read_row_limit_q, active_read_count, transpose_row_count_q,
  input logic transpose_mode_tmp,
  output logic candidate, reference_result, normal_result, transpose_result, equivalent);
''' + selection.group() + '\n' + source[start:end] + '''
  assign candidate = read_row_count_last;
  assign reference_result = read_row_limit_q >= output_row_count;
  assign normal_result = read_normal_row_last;
  assign transpose_result = read_transpose_row_last;
  assign equivalent = candidate == reference_result;
endmodule
'''
    return product, row


SYMBOL = '''
  function automatic logic symbol(input integer value);
    case (value & 3)
      0: symbol = 1'b0;
      1: symbol = 1'b1;
      2: symbol = 1'bx;
      3: symbol = 1'bz;
    endcase
  endfunction
'''


def product_bench() -> str:
    return '''module tb;
  logic [31:0] coalesce_rows=0, coalesce_cols=0;
  wire [0:0] candidate1, reference1;
  wire [5:0] candidate6, reference6;
  wire [31:0] candidate32, reference32;
  product #(.BANK_COUNT_WIDTH(1)) w1(coalesce_rows,coalesce_cols,candidate1,reference1,);
  product #(.BANK_COUNT_WIDTH(6)) w6(coalesce_rows,coalesce_cols,candidate6,reference6,);
  product #(.BANK_COUNT_WIDTH(32)) w32(coalesce_rows,coalesce_cols,candidate32,reference32,);
  integer value, scan, bit_index;
''' + SYMBOL + '''
  initial begin
    // 穷举两个五位输入的全部四态组合，覆盖窄截断、生产宽度及宽扩展。
    for (value=0; value<1048576; value=value+1) begin
      scan=value;
      for (bit_index=0; bit_index<5; bit_index=bit_index+1) begin
        coalesce_rows[bit_index]=symbol(scan); scan=scan>>2;
        coalesce_cols[bit_index]=symbol(scan); scan=scan>>2;
      end
      #1;
      if (candidate1 !== reference1 || candidate6 !== reference6 || candidate32 !== reference32)
        $fatal(1,"Product mismatch input=%0d rows=%b cols=%b",value,coalesce_rows,coalesce_cols);
      if (value%65536==65535) begin
        $display("PROGRESS inputs=%0d",value+1);
        $fflush();
      end
    end
    $display("PRODUCT_FOUR_STATE_PASS inputs=1048576 comparisons=3145728");
    $finish;
  end
endmodule
'''


def row_bench() -> str:
    return '''module tb;
  logic [4:0] read_row_limit_q, active_read_count, transpose_row_count_q;
  logic transpose_mode_tmp=1'b0;
  wire candidate, reference_result, normal_result, transpose_result, equivalent;
  row_compare #(.COUNT_WIDTH(5)) dut(.*);
  integer value, scan, bit_index;
''' + SYMBOL + '''
  initial begin
    // 对生产参数的两个五位比较操作数执行完整四态穷举。
    for (value=0; value<1048576; value=value+1) begin
      scan=value;
      for (bit_index=0; bit_index<5; bit_index=bit_index+1) begin
        read_row_limit_q[bit_index]=symbol(scan); scan=scan>>2;
        active_read_count[bit_index]=symbol(scan); scan=scan>>2;
      end
      transpose_row_count_q=active_read_count;
      #1;
      if (candidate !== reference_result || normal_result !== reference_result ||
          transpose_result !== reference_result)
        $fatal(1,"Row mismatch input=%0d left=%b right=%b",value,read_row_limit_q,active_read_count);
      if (value%65536==65535) begin
        $display("PROGRESS inputs=%0d",value+1);
        $fflush();
      end
    end
    // 方向未知时，检查不同和相同行数分支的选择语义。
    read_row_limit_q=5'd3; active_read_count=5'd1; transpose_row_count_q=5'd2;
    transpose_mode_tmp=1'bx; #1;
    if (candidate !== reference_result || candidate !== 1'bx) $fatal(1,"Unknown mode mismatch");
    transpose_mode_tmp=1'bz; #1;
    if (candidate !== reference_result || candidate !== 1'bx) $fatal(1,"High impedance mode mismatch");
    transpose_row_count_q=5'd1; transpose_mode_tmp=1'bx; #1;
    if (candidate !== reference_result || candidate !== 1'b1) $fatal(1,"Equal row counts mismatch");
    read_row_limit_q=5'd0; transpose_mode_tmp=1'bz; #1;
    if (candidate !== reference_result || candidate !== 1'b0) $fatal(1,"Equal row counts limit mismatch");
    $display("ROW_FOUR_STATE_PASS inputs=1048580 comparisons=3145732");
    $finish;
  end
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--timeout', type=int, default=900,
                        help='每个组合仿真的执行上限，单位为秒')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout 必须为正整数')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.source_root.resolve() / SOURCE
    source = read_rtl_text(source_path)
    helper = args.source_root.resolve() / 'rtl/common/parallel_prefix_add.sv'
    product, row = source_models(source)
    models = out / 'models.sv'
    models.write_text(product + '\n' + row)
    commands = []
    for top, parameter in (('product', 'BANK_COUNT_WIDTH'), ('row_compare', 'COUNT_WIDTH')):
        for width in range(1, 33):
            commands += ['design -reset',
                         f'read_slang -D SYNTHESIS=1 --top {top} -G{parameter}={width} {models} {helper}',
                         f'prep -top {top} -flatten',
                         'opt -full', 'sat -prove equivalent 1 -verify -show-inputs']
    script = out / 'binary.ys'
    script.write_text('\n'.join(commands) + '\n')
    with (out / 'binary.log').open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=args.timeout)
    print('BINARY_PASS product_widths=1..32 row_widths=1..32 all_inputs=true', flush=True)
    report = {'passed': True, 'source_sha256': digest(source_path),
              'expanded_source_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'arithmetic_helper_sha256': digest(helper), 'runner_sha256': digest(Path(__file__)),
              'binary_all_input_widths': list(range(1, 33)), 'binary_proofs': 64,
              'generated_models_sha256': digest(models), 'binary_log_sha256': digest(out / 'binary.log'),
              'four_state': []}
    for name, bench_text, inputs, comparisons, widths in (
            ('product', product_bench(), 1048576, 3145728, [1, 6, 32]),
            ('row_compare', row_bench(), 1048580, 3145732, [5])):
        bench = out / (name + '_tb.sv')
        bench.write_text(bench_text)
        executable = out / (name + '.vvp')
        with (out / (name + '_build.log')).open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
                            str(models), str(helper), str(bench)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=args.timeout)
        log = out / (name + '.log')
        with log.open('w') as stream:
            subprocess.run(['vvp', str(executable)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=args.timeout)
        if '_FOUR_STATE_PASS' not in read_rtl_text(log):
            raise RuntimeError('组合四态检查未完成：' + name)
        report['four_state'].append({'name': name, 'widths': widths, 'inputs': inputs,
                                    'comparisons': comparisons, 'passed': True,
                                    'bench_sha256': digest(bench), 'log_sha256': digest(log)})
        print(json.dumps(report['four_state'][-1]), flush=True)
    if source != read_rtl_text(source_path):
        raise RuntimeError('验证期间 FIFO 源码发生变化')
    report['four_state_comparisons'] = sum(row['comparisons'] for row in report['four_state'])
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
