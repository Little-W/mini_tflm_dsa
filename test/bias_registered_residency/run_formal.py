#!/usr/bin/env python3
"""验证完整偏置加载器的同步驻留判断、公开输出及存储操作。"""
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
sys.path.insert(0, str(ROOT / 'test/bias_read_depth'))
from common import abstract_storage, abstract_wrapper

FILES = ('rtl/npu/loaders/bias_loader.sv',
         'rtl/npu/loaders/bias_loader_ctrl.sv',
         'rtl/npu/loaders/bias_loader_buffer.sv',
         'rtl/common/parallel_prefix_add.sv',
         'rtl/common/parallel_unsigned_compare.sv',
         'rtl/common/add_equal.sv')
PROFILES = ((4, 32, 1, 1), (8, 32, 8, 3), (16, 32, 12, 4),
            (16, 64, 29, 32), (16, 64, 32, 64))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='2247144937c2fd04039b9b005151f371d6b51f8f')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {name: digest(ROOT / name) for name in FILES}
    sources = {}
    for version in ('reference', 'current'):
        paths = []
        for name in FILES:
            data = (subprocess.check_output(['git', 'show', args.reference + ':' + name], cwd=ROOT)
                    if version == 'reference' else (ROOT / name).read_bytes())
            source = out / 'sources' / version / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data)
            model = out / 'models' / version / Path(name).name
            model.parent.mkdir(parents=True, exist_ok=True)
            content = data.decode()
            if name.endswith('/bias_loader.sv'):
                content = abstract_wrapper(content)
            elif name.endswith('/bias_loader_buffer.sv'):
                content = abstract_storage(content)
            model.write_text(content)
            paths.append(model)
        sources[version] = paths
    report = {'passed': False, 'reference_commit': args.reference,
              'external_input_assumptions': [],
              'memory_return': 'Common arbitrary 64-bit value in every cycle',
              'comparison': 'Complete loader state, public outputs and synchronous memory operations',
              'source_sha256': hashes, 'profiles': []}
    for size, bus, count, groups in PROFILES:
        folder = out / f's{size}_b{bus}_c{count}_g{groups}'
        folder.mkdir(exist_ok=True)
        options = f'-GSIZE={size} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count} -GGROUP_BLOCKS_MAX={groups}'
        commands = []
        for version in ('reference', 'current'):
            commands += [f'read_slang --top bias_loader {options} ' +
                         ' '.join(shlex.quote(str(p)) for p in sources[version]),
                         'prep -top bias_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename bias_loader {version}', f'design -stash {version}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 8',
                     'equiv_status -assert']
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=300)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        passed = result.returncode == 0 and 'Equivalence successfully proven' in text
        row = dict(SIZE=size, BUS_WIDTH=bus, COUNT_WIDTH=count, GROUP_BLOCKS_MAX=groups,
                   passed=passed, equivalent_bits=int(match[1]) if match else None,
                   script_sha256=digest(script), log_sha256=digest(log))
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
        if not passed:
            raise RuntimeError(text[-6000:])
    report['sources_unchanged'] = hashes == {name: digest(ROOT / name) for name in FILES}
    report['passed'] = report['sources_unchanged'] and all(row['passed'] for row in report['profiles'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
