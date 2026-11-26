#!/usr/bin/env python3
"""验证写回初始复用数量检查的完整状态和公开输出。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/writeback/oa_writer.sv'
PROFILES = ((4, 32, 4), (16, 64, 16), (16, 64, 29), (32, 64, 32))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='edbef90e')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, candidate = out/'reference.sv', out/'candidate.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+SOURCE], cwd=ROOT))
    candidate.write_bytes((ROOT/SOURCE).read_bytes())
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in resolve([ROOT/SOURCE], ROOT)}

    def prove(job):
        (lanes, bus, count), synthesis = job
        name = f'n{lanes}_b{bus}_c{count}_fpga{int(synthesis)}'
        options = [f'-GVLEN={lanes}', f'-GBUS_WIDTH={bus}', f'-GCOUNT_WIDTH={count}']
        if synthesis:
            options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        commands = []
        for label, path in (('reference', reference), ('candidate', candidate)):
            commands += ['read_slang --top oa_writer '+shlex.join(options+list(map(str, resolve([path], ROOT)))),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top oa_writer -flatten', 'async2sync', 'opt_clean',
                'rename oa_writer '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'equiv_make reference candidate proof', 'hierarchy -top proof',
            'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        if not match or int(match[2]) or 'Equivalence successfully proven!' not in log.read_text():
            raise RuntimeError('完整写回模块形式检查未完成：'+name)
        print(name, match[1], 'PASS', flush=True)
        return {'lanes': lanes, 'bus_width': bus, 'count_width': count, 'synthesis': synthesis,
            'passed': True, 'proven_points': int(match[1]), 'log_sha256': digest(log)}

    jobs = [(profile, synthesis) for profile in PROFILES for synthesis in (False, True)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(prove, jobs))
    subprocess.run([sys.executable, ROOT/'test/oa_writer_geometry/run_four_state.py',
        '--reference', args.reference, '--out', out/'four_state',
        '--profiles', '4:32:4', '16:64:29', '--scenarios', '1024'], check=True)
    if hashes != {name: digest(ROOT/name) for name in hashes}:
        raise RuntimeError('检查期间源文件发生变化')
    report = {'passed': True, 'reference': args.reference, 'source_sha256': hashes,
        'inputs_constrained': False, 'all_public_outputs_and_common_state_compared': True,
        'formal': checks, 'four_state': json.loads((out/'four_state/summary.json').read_text())}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
