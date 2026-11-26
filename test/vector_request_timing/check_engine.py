#!/usr/bin/env python3
"""比较完整向量引擎的全部公开输出和共有寄存状态。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODES = (
    ('generic', ['-USYNTHESIS', '-UXILINX_FPGA']),
    ('synthesis', ['-DSYNTHESIS=1', '-UXILINX_FPGA']),
    ('fpga', ['-USYNTHESIS', '-DXILINX_FPGA=1']),
    ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']),
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='57b61b24')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    reference_files = []
    for name in ('address', 'control'):
        path = out / f'reference_{name}.sv'
        path.write_bytes(subprocess.check_output(
            ['git', 'show', f'{args.reference}:rtl/npu/conv/vector_engine_{name}.sv'], cwd=ROOT))
        reference_files.append(path)
    engine = ROOT / 'rtl/npu/conv/vector_engine.sv'
    sources = {'reference': resolve([*reference_files, engine], ROOT),
               'current': resolve([engine], ROOT)}
    hashes = {str(path): digest(path) for paths in sources.values() for path in paths}
    jobs = []
    for mode, flags in MODES:
        for lanes in (8, 16):
            name = f'{mode}_lanes{lanes}'
            options = ['-GTILE=16', '-GBUS_WIDTH=64', '-GDMA_SIZE=64',
                       f'-GPE_COUNT={lanes}', f'-GWINDOW_LANES={lanes}',
                       '-GSHARED_STORAGE_ENABLE=1', '-GSHARED_STORAGE_ADDR_WIDTH=12',
                       f'-GSHARED_QUANT_ENABLE={int(lanes == 16)}']
            commands = []
            for label, paths in sources.items():
                commands.extend([
                    'read_slang --top vector_engine ' +
                    shlex.join(flags + options + list(map(str, paths))),
                    'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                    'prep -top vector_engine -flatten', 'memory_map', 'async2sync',
                    'opt -full', 'rename -top ' + label, 'design -stash ' + label,
                ])
            commands.extend([
                'design -copy-from reference -as reference reference',
                'design -copy-from current -as current current',
                'equiv_make reference current proof', 'hierarchy -top proof', 'opt -full',
                'equiv_simple -short -seq 1', 'equiv_induct -seq 2',
                'equiv_simple -seq 1', 'equiv_status -assert',
            ])
            script = out / (name + '.ys')
            script.write_text('\n'.join(commands) + '\n')
            jobs.append((name, mode, flags, lanes, script))

    def prove(job):
        name, mode, flags, lanes, script = job
        log = out / (name + '.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                            '--worker', script], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=1200)
        text = log.read_text()
        assert 'Equivalence successfully proven!' in text
        result = {'mode': mode, 'macro_options': flags, 'pe_count': lanes,
                  'passed': True, 'equivalence_points':
                  int(re.findall(r'Found (\d+) \$equiv cells', text)[-1]),
                  'log_sha256': digest(log)}
        print(json.dumps(result), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        formal = list(pool.map(prove, jobs))
    assert all(digest(path) == expected for path, expected in hashes.items())
    (out / 'summary.json').write_text(json.dumps({
        'passed': True, 'reference_commit': args.reference, 'input_constraints': [],
        'all_parent_outputs_and_state_compared': True, 'formal': formal,
        'source_sha256': hashes, 'runner_sha256': digest(__file__),
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
