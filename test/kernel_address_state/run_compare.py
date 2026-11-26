#!/usr/bin/env python3
"""证明保存地址与三项地址比较在完整位宽下相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
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
    rtl = ROOT / 'rtl/npu/loaders/kernel_loader.sv'
    text = rtl.read_text()
    start = text.index('  add3_equal #(.p_width(REG_WIDTH)) u_address_equal')
    body = text[start:text.index('  // 控制器提供未发起的需求', start)]
    model = out / 'comparison.sv'
    model.write_text('''// 地址保存关系由控制器状态证明提供，比较使用生产表达式。
module comparison #(parameter int REG_WIDTH=32) (
    input logic [REG_WIDTH-1:0] address_equal_i_a, // 分组起点
    input logic [REG_WIDTH-1:0] address_equal_i_b, // 行偏移
    input logic [REG_WIDTH-1:0] address_equal_i_c, // 列偏移
    input logic [REG_WIDTH-1:0] address_equal_i_target, // 候选描述符地址
    output logic equivalent // 两种比较的结果相同
);
    logic address_equal_o_equal, address_equal_four_state;
    logic [REG_WIDTH-1:0] dma_tile_base_addr;
    assign dma_tile_base_addr=address_equal_i_a+address_equal_i_b+address_equal_i_c;
''' + body + '''
    assign equivalent=(address_equal_o_equal===address_equal_four_state);
endmodule
''')
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([model], ROOT)
    runs = []
    for width in (8, 32, 64):
        script, log = out / f'w{width}.ys', out / f'w{width}.log'
        script.write_text(f'read_slang --top comparison -GREG_WIDTH={width} ' + shlex.join(map(str, sources)) +
                          '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('保存地址比较证明未完成')
        runs.append({'width': width, 'passed': True, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    report = {'passed': True, 'input_constraints': None,
              'source_sha256': hashlib.sha256(rtl.read_bytes()).hexdigest(), 'runs': runs}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
