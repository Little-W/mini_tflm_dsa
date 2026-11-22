#!/usr/bin/env python3
"""验证向量引擎同步数据保存、输入选择及参数分支的完整逐周期等价性。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import CASES, run_stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', choices=('production', 'generic'),
                        default=['production'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    sources = CASES['vector_engine']['sources']
    hashes = {label: {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                      for name in sources} for label, root in roots.items()}
    runs = []
    for profile in args.profiles:
        folder = out / profile
        folder.mkdir(exist_ok=True)
        options = '-GTILE=16 -GPE_COUNT=8 -D XILINX_FPGA=1'
        options += (' -GBUS_WIDTH=64 -GWINDOW_LANES=8 -GSHARED_STORAGE_ENABLE=1'
                    if profile == 'production' else
                    ' -GBUS_WIDTH=32 -GWINDOW_LANES=4 -GSHARED_STORAGE_ENABLE=0')
        commands = []
        for label, root in roots.items():
            commands += [f'read_slang --top vector_engine {options} ' +
                         ' '.join(shlex.quote(str(root / name)) for name in sources),
                         'prep -top vector_engine -flatten', 'memory_map',
                         'async2sync', 'opt_clean',
                         f'rename vector_engine {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current comparison', 'hierarchy -top comparison',
                     'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                     'equiv_status -assert']
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        stage = run_stage(script, log, dict(os.environ))
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and 0 are unproven', text)
        if not match or 'Equivalence successfully proven' not in text:
            raise RuntimeError(f'形式检查没有完成：{log}')
        result = {'profile': profile, 'passed': True, 'equivalent_bits': int(match[1]),
                  'stage': stage, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        (folder / 'summary.json').write_text(json.dumps({'passed': True, 'inputs_constrained': False,
            'all_public_outputs_compared': True, 'source_sha256': hashes, 'run': result},
            ensure_ascii=False, indent=2) + '\n')
        runs.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    assert hashes == {label: {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                              for name in sources} for label, root in roots.items()}
    (out / 'summary.json').write_text(json.dumps({
        'passed': True, 'inputs_constrained': False, 'all_public_outputs_compared': True,
        'source_sha256': hashes, 'runs': runs}, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
