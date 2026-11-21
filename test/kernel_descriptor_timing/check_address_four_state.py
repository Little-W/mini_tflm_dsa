#!/usr/bin/env python3
"""对生产权重地址表达式检查二值、未知值和高阻值的完整结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/kernel_loader_ctrl.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(path): digest(root / path) for path in (SOURCE, HELPER)}
    source = (root / SOURCE).read_text()
    start = source.index('  logic [REG_WIDTH-1:0] dma_address_sum,')
    end = source.index('  logic [3:0][CNT_W-1:0] traversal_i_value', start)
    body = source[start:end].replace('always_comb', 'always @*')
    model = out / 'candidate.sv'
    model.write_text('''module candidate #(parameter int REG_WIDTH=32) (
  input logic [REG_WIDTH-1:0] group_base_addr, row_addr_offset, col_addr_offset,
  output logic [REG_WIDTH-1:0] result
);
''' + body + '  assign result = dma_address_next;\nendmodule\n')
    bench = out / 'testbench.sv'
    bench.write_text('''module check_width #(parameter int WIDTH=32) (output logic done=0);
  logic [WIDTH-1:0] group_base_addr, row_addr_offset, col_addr_offset;
  wire [WIDTH-1:0] result;
  wire [WIDTH-1:0] expected = group_base_addr + row_addr_offset + col_addr_offset;
  int checks=0;
  candidate #(.REG_WIDTH(WIDTH)) u_dut (.*);
  task automatic compare;
    #1;
    if (result !== expected)
      $fatal(1, "Address comparison width=%0d expected=%h actual=%h", WIDTH, expected, result);
    checks++;
  endtask
  task automatic randomize_values;
    group_base_addr = WIDTH'({$urandom, $urandom});
    row_addr_offset = WIDTH'({$urandom, $urandom});
    col_addr_offset = WIDTH'({$urandom, $urandom});
  endtask
  initial begin
    for (int trial=0; trial<20000; trial++) begin
      randomize_values();
      compare();
    end
    for (int pattern=0; pattern<8; pattern++) begin
      group_base_addr = {WIDTH{pattern[0]}};
      row_addr_offset = {WIDTH{pattern[1]}};
      col_addr_offset = {WIDTH{pattern[2]}};
      compare();
      for (int bit_index=0; bit_index<WIDTH; bit_index++) begin
        group_base_addr[bit_index] = 1'bx; compare();
        group_base_addr[bit_index] = 1'bz; compare();
        group_base_addr[bit_index] = pattern[0];
        row_addr_offset[bit_index] = 1'bx; compare();
        row_addr_offset[bit_index] = 1'bz; compare();
        row_addr_offset[bit_index] = pattern[1];
        col_addr_offset[bit_index] = 1'bx; compare();
        col_addr_offset[bit_index] = 1'bz; compare();
        col_addr_offset[bit_index] = pattern[2];
      end
    end
    $display("KERNEL_ADDRESS_FOUR_STATE_PASS width=%0d checks=%0d", WIDTH, checks);
    done=1;
  end
endmodule
module tb;
  wire [3:0] done;
  check_width #(.WIDTH(1)) u_one (.done(done[0]));
  check_width #(.WIDTH(16)) u_half (.done(done[1]));
  check_width #(.WIDTH(32)) u_word (.done(done[2]));
  check_width #(.WIDTH(64)) u_double (.done(done[3]));
  initial begin wait (&done); $finish; end
endmodule
''')
    binary = out / 'sim.vvp'
    for command, name in [
        (['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
          str(root / HELPER), str(model), str(bench)], 'build.log'),
        (['vvp', str(binary)], 'run.log')]:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        (out / name).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'权重地址四态检查未完成：{out / name}')
    matches = re.findall(r'KERNEL_ADDRESS_FOUR_STATE_PASS width=(\d+) checks=(\d+)',
                         (out / 'run.log').read_text())
    rows = [dict(width=int(width), checks=int(count), passed=True) for width, count in matches]
    if len(rows) != 4 or hashes != {str(path): digest(root / path) for path in (SOURCE, HELPER)}:
        raise RuntimeError('四态检查配置不完整或源文件发生变化')
    report = dict(passed=True, strict_four_state=True, source_sha256=hashes,
        candidate_model_sha256=digest(model), testbench_sha256=digest(bench),
        runs=rows, checks=sum(row['checks'] for row in rows), log_sha256=digest(out / 'run.log'))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': report['checks']}))


if __name__ == '__main__':
    main()
