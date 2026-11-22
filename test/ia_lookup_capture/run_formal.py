#!/usr/bin/env python3
"""证明 IA 同拍请求比较的完整模块状态与公开输出等价。"""
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
SOURCES = tuple(Path('rtl/npu/loaders') / (name + '.sv') for name in
                ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr'))
CASES = {
    'production': ['-GSIZE=16', '-GBUS_WIDTH=64', '-GDMA_LANES=8', '-GCOUNT_WIDTH=29',
                   '-GCACHE_BLOCKS=32', '-GEXTERNAL_RAM=1', '-GORDERED_JOB=1',
                   '-GRAM_WORD_ADDR_WIDTH=12',
                   '-Gp_register_dma_request=1', '-Gp_dma_source_layout=1', '-Gp_shared_write_stage=1'],
    'generic': ['-GSIZE=16', '-GBUS_WIDTH=32', '-GCOUNT_WIDTH=8', '-GCACHE_BLOCKS=4',
                '-GEXTERNAL_RAM=1', '-GORDERED_JOB=0'],
    'small': ['-GSIZE=3', '-GBUS_WIDTH=32', '-GCOUNT_WIDTH=8', '-GCACHE_BLOCKS=4',
              '-GEXTERNAL_RAM=0', '-GORDERED_JOB=1'],
    'wide_cache': ['-GSIZE=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=32', '-GCACHE_BLOCKS=64',
                   '-GEXTERNAL_RAM=1', '-GORDERED_JOB=1', '-Gp_register_dma_request=1'],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=['production'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    snapshots, hashes = {}, {}
    for label, root in roots.items():
        snapshot = out / label
        snapshot.mkdir(exist_ok=True)
        common = sorted(path.relative_to(root) for path in (root / 'rtl/common').iterdir()
                        if path.suffix in ('.v', '.sv'))
        relatives = [*SOURCES, Path('rtl/npu/compute/select_add.sv'), *common]
        snapshots[label], hashes[label] = [], {}
        for relative in relatives:
            source = root / relative
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            snapshots[label].append(target)
            hashes[label][str(relative)] = digest(target)
    report = {'passed': True, 'external_inputs_constrained': False,
              'compared_outputs': 'all public outputs and common internal state',
              'source_sha256': hashes, 'profiles': []}
    for name in args.cases:
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', *CASES[name]]
        commands = []
        for label in ('reference', 'current'):
            commands += [
                'read_slang --top ia_loader ' + shlex.join(options + [str(p) for p in snapshots[label]]),
                'prep -top ia_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename ia_loader ' + label, 'design -stash ' + label,
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current comparison', 'hierarchy -top comparison',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert',
        ]
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            completed = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        passed = completed.returncode == 0 and 'Equivalence successfully proven' in text
        count = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        record = {'name': name, 'passed': passed, 'options': options,
                  'equivalent_bits': int(count[1]) if count else None,
                  'log_sha256': digest(log)}
        report['profiles'].append(record)
        report['passed'] &= passed
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(record), flush=True)
        if not passed:
            raise RuntimeError('完整模块等价证明未完成: ' + str(log))
    for label, root in roots.items():
        for relative, expected in hashes[label].items():
            if digest(root / relative) != expected:
                raise RuntimeError('形式验证期间源码变化: ' + str(root / relative))


if __name__ == '__main__':
    main()
