#!/usr/bin/env python3
"""比较任务配置模块的全部公开输出和内部状态，不约束外部输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/top/npu_task_configuration.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='df08ac08')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    reference = out/'reference.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show', f'{revision}:{SOURCE}'], cwd=ROOT))
    candidate = out/'candidate.sv'
    candidate.write_bytes((ROOT/SOURCE).read_bytes())
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    report = {'passed': True, 'reference': revision, 'inputs_constrained': False,
        'source_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(), 'profiles': []}
    for synthesis in (False, True):
        name = 'fpga' if synthesis else 'generic'
        commands = []
        for label, path in [('reference', reference), ('candidate', candidate)]:
            options = ['-DGEMMORA_PS_POOL_BYTES=12288', '-I', str(ROOT/'include')]
            if synthesis:
                options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
            else:
                options += ['-USYNTHESIS', '-UXILINX_FPGA']
            commands += ['read_slang --top npu_task_configuration '+
                shlex.join(options+list(map(str, resolve([path], ROOT)))),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top npu_task_configuration -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename npu_task_configuration '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'equiv_make reference candidate equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if not match or int(match[2]) or 'Equivalence successfully proven!' not in text:
            raise RuntimeError(f'完整模块检查未完成：{log}')
        report['profiles'].append({'synthesis': synthesis, 'proven_points': int(match[1]),
            'passed': True, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(name, match[1], 'PASS', flush=True)
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
