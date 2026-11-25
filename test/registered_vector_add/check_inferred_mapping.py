#!/usr/bin/env python3
"""检查普通半字算术的 DSP 推断，并证明完整映射结果的时序等价性。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / 'rtl/npu/compute/registered_vector_add.sv',
               ROOT / 'test/registered_vector_add/measure.sv']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    with (out / 'synthesis.log').open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--source-root', str(ROOT), '--case-config',
                        str(ROOT / 'test/registered_vector_add/cases.json'),
                        '--cases', 'registered_vector_add', '--out', str(out / 'synthesis')],
                       check=True, stdout=stream, stderr=subprocess.STDOUT, cwd=ROOT)
    folder = out / 'synthesis/registered_vector_add'
    mapped = folder / 'mapped.json'
    metrics = json.loads((folder / 'metrics.json').read_text())
    if not metrics['resources']['dsp48e1']:
        raise RuntimeError('算术结果未完成 DSP 推断')
    top = 'registered_vector_add_measure'
    commands = [
        'read_slang --top ' + top + ' -DSYNTHESIS ' + ' '.join(map(str, sources)),
        'prep -top ' + top + ' -flatten', 'memory_map', 'opt -full',
        'async2sync', 'opt -full', 'rename -hide w:*', 'rename -top reference',
        'design -stash reference', 'read_json ' + str(mapped),
        'delete =A:blackbox', 'read_verilog -overwrite +/xilinx/cells_sim.v',
        'hierarchy -top ' + top, 'rename -top current',
        'setattr -mod -unset keep_hierarchy', 'flatten -wb', 'proc',
        'memory_map', 'async2sync', 'opt -full', 'rename -hide w:*',
        'design -stash current',
        'design -copy-from reference -as reference reference',
        'design -copy-from current -as current current',
        'equiv_make reference current proof', 'hierarchy -top proof',
        'equiv_simple -seq 4', 'opt_clean', 'equiv_induct -seq 8',
        'equiv_status -assert',
    ]
    script, log = out / 'equivalence.ys', out / 'equivalence.log'
    script.write_text('\n'.join(commands) + '\n')
    stage = run_stage(script, log, dict(os.environ))
    if not re.search(r'Of those cells 514 are proven and 0 are unproven', log.read_text()):
        raise RuntimeError('未完成全部 514 位公开输出的时序证明')
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('检查期间源码发生变化')
    summary = dict(passed=True, source_sha256=hashes,
                   mapped_sha256=digest(mapped), test_sha256=digest(Path(__file__)),
                   compared_output_bits=514, unbounded_equivalence=True,
                   resources=metrics['resources'],
                   longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
                   equivalence_stage=stage)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: summary[key] for key in
                     ('passed', 'compared_output_bits', 'unbounded_equivalence',
                      'longest_register_path_cells')}, indent=2))


if __name__ == '__main__':
    main()
