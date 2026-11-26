#!/usr/bin/env python3
"""测量具有输入和输出寄存器的无符号比较器。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wrapper = out / 'compare_top.sv'
    wrapper.write_text('''// 无符号比较器的寄存器边界测量模块。
module compare_top #(parameter bit p_split_compare=1'b1)(
    input wire clk, // 工作时钟
    input wire [31:0] i_a, // 第一比较操作数
    input wire [31:0] i_b, // 第二比较操作数
    output logic o_less, // 保存的小于结果
    output logic o_equal // 保存的相等结果
);
    logic [31:0] a_q, b_q;
    logic less, equal;
    always_ff @(posedge clk) begin
        a_q <= i_a;
        b_q <= i_b;
        o_less <= less;
        o_equal <= equal;
    end
    unsigned_compare #(.p_width(32), .p_split_compare(p_split_compare)) u_compare (
        .i_a(a_q), .i_b(b_q), .o_less(less), .o_equal(equal)
    );
endmodule
''')
    cases = {name: dict(top='compare_top', sources=[str(wrapper)],
                       options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1', f'-Gp_split_compare={flag}'],
                       configuration=dict(width=32, split_compare=flag))
             for name, flag in [('grouped', 0), ('split', 1)]}
    configuration = out / 'cases.json'
    configuration.write_text(json.dumps(cases, indent=2) + '\n')
    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--source-root', str(ROOT), '--case-config', str(configuration),
                    '--cases', *cases, '--out', str(out / 'mapping'), '--through', 'pre_lut'],
                   check=True)
    report = {}
    for name in cases:
        target = out / 'physical' / name
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/remap_fpga_luts.py'),
                        '--source', str(out / 'mapping' / name), '--out', str(target),
                        '--mode', 'physical-cost', '--delay-target-ps', '6667',
                        '--wire-delay-ps', '300', '--max-lut-inputs', '8'], check=True)
        report[name] = dict(metrics=json.loads((target / 'metrics.json').read_text()),
                            manifest=json.loads((target / 'manifest.json').read_text()))
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
