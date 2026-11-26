#!/usr/bin/env python3
"""验证向量归约与 Softmax 分段加法的全部公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = 'f631498f'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    profiles = [('reduce', 'vector_reduce_alu', {})]
    profiles += [(f'softmax_depth{depth}', 'vector_softmax', {
        'MAX_DEPTH': depth, 'MULTIPLIER_LATENCY': latency, 'INPUT_REGISTERED': registered})
        for depth, latency, registered in ((3, 0, 0), (16, 2, 1), (32, 2, 1))]
    results, hashes = [], {}
    for name, module, parameters in profiles:
        source = ROOT / 'rtl/npu/conv' / (module + '.sv')
        reference = out / (name + '_reference.sv')
        reference.write_bytes(subprocess.check_output(
            ['git', 'show', f'{REFERENCE}:{source.relative_to(ROOT)}'], cwd=ROOT))
        for synthesis in (False, True):
            commands = []
            for label, path in [('reference', reference), ('candidate', source)]:
                dependencies = resolve([path], ROOT)
                hashes.update({str(p.relative_to(ROOT)): digest(p) for p in dependencies
                               if p.is_relative_to(ROOT) and not p.is_relative_to(out)})
                options = ['-DSYNTHESIS=1'] if synthesis else []
                options += [f'-G{key}={value}' for key, value in parameters.items()]
                commands += ['read_slang --top ' + module + ' ' +
                             shlex.join(options + list(map(str, dependencies))),
                             'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                             'prep -top ' + module + ' -flatten', 'async2sync', 'opt -full',
                             'rename -top ' + label, 'design -stash ' + label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate proof', 'hierarchy -top proof',
                         'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 3',
                         'equiv_status -assert']
            key = name + ('_synthesis' if synthesis else '_generic')
            script, log = out / (key + '.ys'), out / (key + '.log')
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], cwd=ROOT, check=True, stdout=stream,
                               stderr=subprocess.STDOUT, timeout=180)
            assert 'Equivalence successfully proven' in log.read_text()
            results.append({'module': module, 'parameters': parameters, 'synthesis': synthesis,
                            'passed': True, 'log_sha256': digest(log)})
            print(key + ' PASS', flush=True)
    assert hashes == {name: digest(ROOT / name) for name in hashes}
    report = {'passed': True, 'reference_commit': REFERENCE, 'inputs_constrained': False,
              'all_public_outputs_compared': True, 'source_sha256': hashes, 'profiles': results}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
