#!/usr/bin/env python3
"""在实际向量引擎状态机上证明通道组末项寄存值的消费关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ENGINE = Path('rtl/npu/conv/vector_engine.sv')
SOURCES = [Path('rtl/npu/conv') / name for name in (
    'conv_im2col_pkg.sv', 'vector_engine_pkg.sv', 'vector_config_check.sv',
    'vector_writeback.sv', 'vector_round_shift.sv', 'vector_scalar_multiplier.sv',
    'vector_pe.sv', 'vector_softmax.sv', 'vector_quant_params.sv')]
SOURCES += [
    Path('rtl/common') / name for name in (
        'add3_equal.sv', 'add_equal.sv', 'onehot_check.sv', 'parallel_prefix_add.sv',
        'pseudo_dual_port_ram.v', 'regfile.v', 'single_port_ram.v')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--profiles', nargs='+',
        default=['4:1:0:0', '4:4:0:0', '16:8:0:0', '16:8:1:0', '16:16:0:1', '32:8:0:0'],
        help='TILE:PE:共享存储使能:共享量化使能')
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(path): digest(root / path) for path in [ENGINE] + SOURCES}
    source = (root / ENGINE).read_text()
    if source.count('  input logic clk, rst_n,') != 1:
        raise RuntimeError('无法定位向量引擎端口')
    source = source.replace('  input logic clk, rst_n,',
        '  output wire formal_group_valid,\n  input logic clk, rst_n,', 1)
    check = '''
  assign formal_group_valid = (state != EXECUTE_COMMIT) ||
      (compute_group_last_q == (compute_index + 32'(PE_COUNT) >= active));
'''
    source = source.replace('\nendmodule', check + '\nendmodule', 1)
    model = out / 'engine.sv'
    model.write_text(source)
    report = dict(passed=False, source_sha256=hashes,
        scope='实际引擎状态更新、通道计数与末项寄存器；证明每个提交周期的寄存判断与直接计算相同',
        assumptions=['首周期复位'], abstracted_signals=[], model_sha256=digest(model), runs=[])
    for profile in args.profiles:
        values = list(map(int, profile.split(':')))
        if len(values) == 2:
            values += [0, 0]
        if len(values) != 4 or any(value not in (0, 1) for value in values[2:]):
            raise ValueError('参数配置应包含 TILE、PE 数量和两个布尔使能')
        tile, pe, storage, quant = values
        folder = out / f'tile{tile}_pe{pe}_storage{storage}_quant{quant}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'run.ys', folder / 'formal.log'
        commands = [
            'read_slang -D ASIC_SYNTHESIS=1 --top vector_engine '
            f'-GTILE={tile} -GPE_COUNT={pe} -GBUS_WIDTH=64 -GWINDOW_LANES=8 '
            f'-GSHARED_STORAGE_ENABLE={storage} -GSHARED_QUANT_ENABLE={quant} '
            + shlex.join(map(str, [root / p for p in SOURCES] + [model])),
            'prep -top vector_engine -flatten',
            'delete -output vector_engine/w:*',
            'expose vector_engine/w:formal_group_valid',
            'setattr -unset keep', 'opt_clean -purge',
            'async2sync', 'memory_map', 'opt -full',
            'sat -seq 2 -tempinduct -maxsteps 6 -set-at 1 rst_n 0 '
            '-prove formal_group_valid 1 -verify -timeout 120',
        ]
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                timeout=300)
        log_text = log.read_text()
        row = dict(tile=tile, pe_count=pe, shared_storage=bool(storage), shared_quant=bool(quant),
            passed=result.returncode == 0 and
            'Induction step proven: SUCCESS!' in log_text,
            script_sha256=digest(script), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'通道组末项时序证明未完成：{log}')
    if hashes != {str(path): digest(root / path) for path in [ENGINE] + SOURCES}:
        raise RuntimeError('验证期间源文件发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
