#!/usr/bin/env python3
"""检查权重加载器地址、列位置、行列尾状态与公开输出的逐周期关系。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/loaders/kernel_loader_ctrl.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='8b3728c0')
    parser.add_argument('--profiles', nargs='+', default=['4:8', '16:29'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(
        ['git', 'rev-parse', args.reference + '^{commit}'], cwd=root, text=True).strip()
    archive = subprocess.check_output(['git', 'archive', reference, 'rtl'], cwd=root)
    reference_root = out / 'reference'
    reference_root.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
        source.extractall(reference_root, filter='data')
    resolver = runpy.run_path(str(root / 'scripts/rtl/source_files.py'))['with_dependencies']
    source_sets = {}
    hashes = {}
    for label, folder in [('reference', reference_root), ('current', root)]:
        source_sets[label] = resolver([folder / RTL], folder)
        for path in source_sets[label]:
            hashes[f'{label}/{path.relative_to(folder)}'] = digest(path)
    # 数学观察量表示参考状态的模宽和值，不改变参考状态或外部输入。
    original = (reference_root / RTL).read_text()
    marker = '  logic [REG_WIDTH-1:0] dma_address_sum,'
    if original.count(marker) != 1:
        raise ValueError('参考控制器的地址组合表达式不唯一')
    observation = (
        '  (* keep = "true" *) wire [REG_WIDTH-1:0] row_base_address_q = '
        'group_base_addr + row_addr_offset;\n'
        '  (* keep = "true" *) wire [REG_WIDTH-1:0] dma_address_q = '
        'group_base_addr + row_addr_offset + col_addr_offset;\n'
        '  (* keep = "true" *) wire [CNT_W-1:0] column_position_q = '
        'group_base_col + load_col_in_group;\n'
        '  (* keep = "true" *) wire last_col_saved_q = last_col_in_group;\n'
        '  (* keep = "true" *) wire row_last_observed = last_tile_row;\n'
        '  (* keep = "true" *) wire rows_positive = 1\'b1;\n')
    observed = out / 'reference_observed.sv'
    observed.write_text(original.replace(marker, observation + marker, 1))
    source_sets['reference'] = [observed if path == reference_root / RTL else path
                                for path in source_sets['reference']]
    # 归约行数在复位和配置接收时均保持正值，此状态关系与全部输出一并证明。
    current_observed = out / 'current_observed.sv'
    current_observed.write_text((root / RTL).read_text().replace('endmodule',
        '  (* keep = "true" *) wire rows_positive = tile_rows_total != 0;\n'
        '  (* keep = "true" *) wire row_last_observed = last_row_saved_q;\nendmodule', 1))
    source_sets['current'] = [current_observed if path == root / RTL else path
                             for path in source_sets['current']]
    report = {'passed': False, 'reference': reference, 'source_sha256': hashes,
              'external_input_value_constraints': None,
              'reset': '第一拍低有效复位，随后复位及全部输入自由变化',
              'method': '完整公共信号断言与时序归纳，包含两个地址状态、列位置、行列尾资格和行数为正的状态关系',
              'runs': []}
    for profile in args.profiles:
        size, count_width = map(int, profile.split(':'))
        folder = out / f's{size}_c{count_width}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, sources in source_sets.items():
            commands += [
                f'read_slang --top kernel_loader_ctrl -DSYNTHESIS=1 -DXILINX_FPGA=1 '
                f'-GSIZE={size} -GCOUNT_WIDTH={count_width} ' + shlex.join(map(str, sources)),
                'prep -top kernel_loader_ctrl -flatten', 'memory_map', 'async2sync', 'opt_clean -purge',
                f'rename kernel_loader_ctrl {label}', f'design -stash {label}',
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make -make_assert reference current equivalent',
            'hierarchy -top equivalent', 'opt_clean -purge',
            'sat -verify -prove-asserts -tempinduct -seq 3 -set-init-zero -set-at 1 rst_n 0',
        ]
        script, log = folder / 'proof.ys', folder / 'proof.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run(
                [sys.executable, str(root / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                cwd=root, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
        text = log.read_text()
        if result.returncode or 'Induction step proven: SUCCESS!' not in text:
            raise RuntimeError(f'地址状态证明未完成：{log}')
        steps = [int(value) for value in re.findall(r'\[induction step (\d+)\]', text)]
        row = {'parameters': {'SIZE': size, 'COUNT_WIDTH': count_width}, 'passed': True,
               'induction_depth': max(steps), 'script_sha256': digest(script),
               'log_sha256': digest(log)}
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    for label, folder in [('reference', reference_root), ('current', root)]:
        for path in resolver([folder / RTL], folder):
            if hashes[f'{label}/{path.relative_to(folder)}'] != digest(path):
                raise RuntimeError('证明期间 RTL 源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
