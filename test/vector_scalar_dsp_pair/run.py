#!/usr/bin/env python3
"""验证完整标量乘积、可选输入寄存、统一使能和四态传播。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv')
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, reference = args.source.resolve(), args.reference.resolve()
    common = ROOT / 'rtl/common/parallel_prefix_add.sv'
    source_hashes = {str(p): digest(p) for p in [source, reference, common, HERE / 'tb_four_state.sv', Path(__file__)]}
    report = {'source_sha256': source_hashes, 'formal': []}
    for a_registered in (0, 1):
        for b_registered in (0, 1):
            for use_dsp in (0, 1):
                commands = []
                for label, path in [('gold', reference), ('gate', source)]:
                    commands += [
                        'read_verilog -formal -sv -D XILINX_FPGA ' +
                        ' '.join(shlex.quote(str(p)) for p in [path, common]),
                        f'chparam -set p_input_register {a_registered} '
                        f'-set p_b_input_register {b_registered} -set p_use_dsp {use_dsp} registered_multiplier_s32',
                        'prep -top registered_multiplier_s32 -flatten', 'wreduce', 'opt -full',
                        f'rename -top {label}', f'design -stash {label}']
                commands += ['design -copy-from gold -as gold gold', 'design -copy-from gate -as gate gate',
                             'equiv_make gold gate proof', 'hierarchy -top proof',
                             'equiv_simple -seq 3', 'equiv_induct -seq 4', 'equiv_status -assert']
                script = out / f'a{a_registered}_b{b_registered}_dsp{use_dsp}.ys'
                script.write_text('\n'.join(commands) + '\n')
                result = run_stage(script, script.with_suffix('.log'), dict(os.environ))
                report['formal'].append({'input_a_registered': a_registered,
                                        'input_b_registered': b_registered,
                                        'use_dsp': use_dsp, 'passed': True, **result})
                print(f'FORMAL_PASS a={a_registered} b={b_registered} dsp={use_dsp}', flush=True)
    reference_text = reference.read_text()
    for name in ['vector_scalar_multiplier', 'registered_multiplier_s32']:
        reference_text = re.sub(r'\b' + name + r'\b', name + '_reference', reference_text)
    renamed = out / 'reference.sv'
    renamed.write_text(reference_text)
    executable = out / 'four_state.vvp'
    with (out / 'four_state_compile.log').open('w') as log:
        subprocess.run([args.iverilog, '-g2012', '-s', 'tb_scalar_dsp_pair', '-o', str(executable),
                        str(source), str(renamed), str(common), str(HERE / 'tb_four_state.sv')],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    with (out / 'four_state.log').open('w') as log:
        subprocess.run([args.vvp, str(executable)], stdout=log, stderr=subprocess.STDOUT, check=True)
    text = (out / 'four_state.log').read_text()
    matched = re.search(r'SCALAR_FOUR_STATE_PASS samples=(\d+) checks=(\d+)', text)
    if not matched:
        raise RuntimeError(text)
    report['four_state'] = {'samples': int(matched[1]), 'checks': int(matched[2]), 'passed': True}
    assert all(digest(Path(name)) == value for name, value in source_hashes.items())
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(text, end='')


if __name__ == '__main__':
    main()
