#!/usr/bin/env python3
"""证明权重加载器的完整状态、控制输出和接收边沿描述符保持一致。"""
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
SOURCE = Path('rtl/npu/loaders/kernel_loader.sv')
PAYLOAD = ('im2col', 'p0', 'q0', 'group', 'base_addr', 'row_stride',
           'rows_to_read', 'burst_len_m1', 'use_16bits', 'lhs_zp')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observed(source, label):
    """比较全部控制与状态，并在描述符接收边沿比较完整载荷。"""
    for suffix in PAYLOAD:
        name = 'ext_dma_' + suffix
        pattern = r'(assign\s+' + name + r'\s*=)\s*(.*?);'
        source, count = re.subn(pattern, lambda match:
            match[1] + " dma_start ? (" + match[2] + ") : '0;", source, flags=re.S)
        if count != 1:
            raise ValueError(f'找不到唯一输出赋值：{name}')
    # 两个组合候选在无接收事件时不被消费，各自保留完整驱动表达式。
    for name in ('port_descriptor', 'dma_burst_len_m1'):
        source = re.sub(r'\b' + name + r'\b', label + '_' + name, source)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--reference', default='422090be')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    dependencies = [ROOT / 'rtl/npu/loaders/kernel_loader_ctrl.sv',
                    ROOT / 'rtl/npu/loaders/kernel_loader_buffer.sv']
    dependencies += sorted(path for path in (ROOT / 'rtl/common').iterdir()
                           if path.suffix in ('.sv', '.v'))
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in [ROOT / SOURCE, *dependencies]}
    snapshots = {}
    for label, source in (('reference', reference), ('candidate', current)):
        path = out / f'{label}.sv'
        path.write_text(observed(source, label))
        snapshots[label] = path
    report = dict(passed=False, reference=args.reference, source_sha256=hashes,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  inputs_constrained=False,
                  scope='All sequential state and control outputs; full descriptor payload on ext_dma_start.',
                  runs=[])
    for size, count_width, bus_width in ((4, 8, 32), (16, 29, 64), (16, 32, 128)):
        folder = out / f's{size}_c{count_width}_b{bus_width}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, path in snapshots.items():
            commands += [f'read_slang --top kernel_loader -GSIZE={size} -GCOUNT_WIDTH={count_width} '
                         f'-GBUS_WIDTH={bus_width} -GDATA_WIDTH=16 ' +
                         shlex.join(map(str, [path, *dependencies])),
                         'prep -top kernel_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename kernel_loader {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate comparison', 'hierarchy -top comparison',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                     '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = dict(size=size, count_width=count_width, bus_width=bus_width,
                   passed=result.returncode == 0 and 'Equivalence successfully proven' in text,
                   compared_bits=int(match[1]) if match else None,
                   script_sha256=digest(script), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'权重描述符比较未完成：{log}')
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in [ROOT / SOURCE, *dependencies]}:
        raise RuntimeError('验证期间输入源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
