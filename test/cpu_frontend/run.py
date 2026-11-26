#!/usr/bin/env python3
"""比较前端分模块前后的完整 PicoRV32 状态、外部接口与指令执行结果。"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import re
import shlex
import sys
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def formal(out, sources, helper):
    """保存两侧综合网表，按前端的明确层次变更匹配对应状态。"""
    out.mkdir()
    results = []
    for profile, parameters in enumerate(helper.PROFILES):
        folder = out / f'profile{profile}'
        folder.mkdir()
        options = ' '.join(f'-G{name}={value}' for name, value in parameters.items())
        models = {}
        for label, source in sources.items():
            script = folder / f'{label}_prepare.ys'
            script.write_text('\n'.join([
                'read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top picorv32 ' + options + ' ' + shlex.quote(str(source)),
                'setattr -mod -unset keep_hierarchy', 'prep -top picorv32 -flatten',
                'memory_map', 'async2sync', 'opt_clean',
                'write_json ' + shlex.quote(str(folder / f'{label}.json')),
                'write_rtlil ' + shlex.quote(str(folder / f'{label}.il')),
            ]) + '\n')
            helper.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], folder / f'{label}_prepare.log')
            models[label] = json.loads((folder / f'{label}.json').read_text())['modules']['picorv32']
        reference_names = models['reference']['netnames']
        current_names = models['current']['netnames']
        renames = {}
        for name in sorted(current_names):
            if not name.startswith('u_frontend.'):
                continue
            short = name.removeprefix('u_frontend.')
            if short in reference_names and short not in current_names:
                if len(current_names[name]['bits']) != len(reference_names[short]['bits']):
                    raise RuntimeError(f'对应状态的位宽不一致：{name}')
                renames[name] = short
        commands = ['read_rtlil ' + shlex.quote(str(folder / 'current.il')), 'cd picorv32']
        commands += [f'rename {old} {new}' for old, new in renames.items()]
        commands += ['cd', 'rename picorv32 current', 'design -stash current',
                     'read_rtlil ' + shlex.quote(str(folder / 'reference.il')),
                     'rename picorv32 reference', 'design -stash reference',
                     'design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 3', 'equiv_status -assert']
        script = folder / 'compare.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = folder / 'compare.log'
        text = helper.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], log)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if not match or int(match[2]):
            raise RuntimeError(f'CPU 等价检查未完成：{log}')
        result = {'passed': True, 'profile': profile, 'parameters': parameters,
                  'equivalent_bits': int(match[1]), 'state_renames': renames,
                  'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        results.append(result)
        print(json.dumps({'formal': {'profile': profile, 'equivalent_bits': int(match[1]), 'state_renames': len(renames)}}), flush=True)
    return {'passed': True, 'profiles': results, 'input_constraints': []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--stages', nargs='+', choices=['formal', 'execution'], default=['formal', 'execution'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    prior = out / 'reference_tree'
    prior.mkdir()
    archive = subprocess.check_output(['git', 'archive', args.reference, 'rtl/soc', 'rtl/common', 'include'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(prior, filter='data')
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = {}
    hashes = {}
    for label, folder in [('reference', prior), ('current', ROOT)]:
        files = resolve([folder / 'rtl/soc/picorv32_npu.v'], folder)
        sources[label] = out / f'{label}.sv'
        sources[label].write_bytes(b'\n'.join(path.read_bytes() for path in files))
        hashes[label] = {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    spec = importlib.util.spec_from_file_location('complete_cpu', ROOT / 'test/pico_pc_arithmetic/run.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    report = {'reference_commit': args.reference, 'source_sha256': hashes, 'stages': {}}
    (out / 'inputs.json').write_text(json.dumps(report, indent=2) + '\n')
    if 'formal' in args.stages:
        report['stages']['formal'] = formal(out / 'formal', sources, helper)
    if 'execution' in args.stages:
        report['stages']['execution'] = helper.execution(out / 'execution', sources, ROOT / 'test/pico_pc_arithmetic/tb_execution.sv')
    for name, expected in hashes['current'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'检查期间源码发生变化：{name}')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'out': str(out)}))


if __name__ == '__main__':
    main()
