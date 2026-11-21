#!/usr/bin/env python3
"""证明 IA 物理槽号提前保存后的公开输出和寄存状态逐周期等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/npu/loaders') / (name + '.sv')
           for name in ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr')]
SOURCES.append(Path('rtl/npu/compute/select_add.sv'))
CASES = {
    'production': dict(SIZE=16, BUS_WIDTH=64, COUNT_WIDTH=29, CACHE_BLOCKS=32,
                       EXTERNAL_RAM=1, ORDERED_JOB=1, PS_FRAME_COUNT=16,
                       p_dma_source_layout=1, p_shared_write_stage=1),
    'generic': dict(SIZE=16, BUS_WIDTH=32, COUNT_WIDTH=8, CACHE_BLOCKS=4,
                    EXTERNAL_RAM=1, ORDERED_JOB=0),
    'small': dict(SIZE=4, BUS_WIDTH=32, COUNT_WIDTH=8, CACHE_BLOCKS=2,
                  EXTERNAL_RAM=0, ORDERED_JOB=1),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=list(CASES))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    paths = {}
    for label, root in roots.items():
        paths[label] = [root / path for path in SOURCES] + sorted(
            path for path in (root / 'rtl/common').iterdir() if path.suffix in ('.v', '.sv'))
    hashes = {label: {str(path.relative_to(roots[label])): digest(path)
                     for path in values} for label, values in paths.items()}
    summary = dict(passed=False, inputs_constrained=False,
                   source_sha256=hashes, runs=[])
    for name in args.cases:
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GRAM_WORD_ADDR_WIDTH=12'] + [
            '-G' + key + '=' + str(value) for key, value in CASES[name].items()]
        commands = []
        for label in ('reference', 'current'):
            commands += ['read_slang --top ia_loader ' + shlex.join(options + list(map(str, paths[label]))),
                'prep -top ia_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename ia_loader ' + label, 'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 3', 'equiv_status -assert']
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = dict(name=name, parameters=CASES[name], passed=run.returncode == 0 and
            'Equivalence successfully proven' in text,
            equivalent_bits=int(match[1]) if match else None,
            script_sha256=digest(script), log_sha256=digest(log))
        summary['runs'].append(row)
        summary['passed'] = all(item['passed'] for item in summary['runs'])
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('IA slot-stage proof did not complete: ' + str(log))
    if hashes != {label: {str(path.relative_to(roots[label])): digest(path)
                         for path in values} for label, values in paths.items()}:
        raise RuntimeError('Source changed during IA slot-stage proof')


if __name__ == '__main__':
    main()
