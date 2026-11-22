#!/usr/bin/env python3
"""比较实际读写地址逻辑在全部状态、读取类型和四态输入下的结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def address_model(source, helper_source):
    state = re.search(r'typedef enum logic \[5:0\].*?state_t;', source, re.S)[0]
    load = re.search(r'typedef enum logic \[2:0\].*?load_t;', source, re.S)[0]
    start = source.index('  logic [31:0] ordinary_read_address,')
    end = source.index('  always_comb begin\n    rd_im2col', start)
    body = source[start:end]
    write_start = source.index('  // 写回状态选择完整偏移，公共加法器生成最终输出地址。')
    write_end = source.index('  wire signed [15:0] input_lane', write_start)
    body += source[write_start:write_end].replace(
        'logic [31:0] write_address_offset, write_origin_next;',
        'logic [31:0] write_address_offset;')
    helper = re.search(r'^module vector_read_address_add\b.*?^endmodule',
                       helper_source, re.M | re.S)[0]
    body = body.replace('vector_read_address_add', 'vector_read_address_add_candidate')
    helper = helper.replace('vector_read_address_add', 'vector_read_address_add_candidate')
    return f'''module candidate (
    input logic clk,
    input logic [5:0] state,
    input logic [2:0] load_kind,
    input vector_engine_pkg::vector_engine_cfg_t c,
    input logic [31:0] pool_byte_offset, vector_offset, position_offset,
    input logic [15:0] channel_base,
    input logic [7:0] soft_lut_index_q,
    output logic [31:0] rd_base_addr, write_origin_next
);
    {state}
    {load}
    logic [31:0] read_address_base, read_address_offset;
    logic [15:0] read_address_channel;
    logic [1:0] unused_read_address_carry;
    {body}
endmodule
{helper}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = source_root / SOURCE
    reference, bench = HERE / 'address_reference.sv', HERE / 'address_tb.sv'
    dependencies = [source_root / name for name in (
        'rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/vector_engine_pkg.sv',
        'rtl/common/parallel_prefix_add.sv')]
    helper_source = source_root / 'rtl/npu/conv/vector_read_address_add.sv'
    tracked = [source, helper_source, reference, bench, Path(__file__).resolve()] + dependencies
    hashes = {str(path): digest(path) for path in tracked}
    candidate = out / 'candidate.sv'
    candidate.write_text(address_model(source.read_text(), helper_source.read_text()))
    models = []
    for name, text in [('reference', reference.read_text()), ('candidate', candidate.read_text())]:
        # 两侧的纯组合过程使用相同事件调度形式，表达式与分支保持原样。
        model = out / (name + '_event.sv')
        model.write_text(text.replace('always_comb', 'always @*'))
        models.append(model)
    binary = out / 'sim.vvp'
    commands = [
        ['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
         *map(str, dependencies + models + [bench])],
        ['vvp', str(binary)],
    ]
    for command, name in zip(commands, ('build.log', 'run.log')):
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        (out / name).write_text(process.stdout + process.stderr)
        if process.returncode:
            raise RuntimeError(f'读写地址四态检查未通过：{out / name}')
    count = re.search(r'ADDRESS_FOUR_STATE_PASS checks=(\d+)', (out / 'run.log').read_text())
    if count is None or hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError('读写地址检查未完成或验证期间源文件发生变化')
    report = {
        'passed': True, 'strict_four_state': True, 'checks': int(count[1]),
        'source_root': str(source_root), 'source_sha256': hashes,
        'candidate_model_sha256': digest(candidate),
        'scope': '64种状态、8种读取类型、随机数据、数据未知值与状态未知值；逐位严格比较32位读取地址和32位写回起始地址',
        'commands': commands, 'log_sha256': digest(out / 'run.log'),
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': report['checks']}))


if __name__ == '__main__':
    main()
