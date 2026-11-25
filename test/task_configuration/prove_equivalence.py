#!/usr/bin/env python3
"""证明任务配置模块在任意输入及使能序列下的全部输出等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from compare_four_state import REFERENCE_REVISION, ROOT, with_dependencies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate_path = ROOT / 'rtl/npu/top/npu_task_configuration.sv'
    original = subprocess.check_output(
        ['git', 'show', f'{REFERENCE_REVISION}:rtl/npu/top/npu_task_configuration.sv'],
        cwd=ROOT, text=True)
    candidate = candidate_path.read_text()
    partials = {'rhs_product_ll', 'rhs_product_lh', 'rhs_product_hl', 'rhs_product_hh'}
    # 部分积保持共同的比较点，归并表示的中间信号分别命名。
    for name in sorted(set(re.findall(r'\brhs_product_\w+\b', candidate)) - partials,
                       key=len, reverse=True):
        candidate = re.sub(rf'\b{name}\b', 'candidate_' + name, candidate)
    reference_file, candidate_file = out / 'reference.sv', out / 'candidate.sv'
    reference_file.write_text(original)
    candidate_file.write_text(candidate)
    dependencies = [path for path in with_dependencies([candidate_path], ROOT)
                    if path != candidate_path]
    defines = ['SYNTHESIS=1', 'XILINX_FPGA=1', 'GEMMORA_PS_POOL_BYTES=49152',
               'GEMMORA_PS_FORCE_RAW=1', 'GEMPACT_PS_COMPRESS=1']
    report = {'reference_revision': REFERENCE_REVISION,
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'candidate_sha256': hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
              'inputs_constrained': False, 'profiles': []}
    for name, parameters in [('production', []), ('tile8', ['-Gp_size=8', '-Gp_size_shift=3'])]:
        folder = out / name
        folder.mkdir(exist_ok=True)
        script = folder / 'run.ys'
        commands = []
        for design, path in [('reference', reference_file), ('candidate', candidate_file)]:
            arguments = ['read_slang', '--top', 'npu_task_configuration']
            arguments += [item for define in defines for item in ('-D', define)]
            arguments += parameters + list(map(str, dependencies)) + [str(path)]
            commands.append(shlex.join(arguments))
            commands += ['prep -top npu_task_configuration -flatten', 'memory_map',
                         'async2sync', 'opt_clean', f'rename npu_task_configuration {design}',
                         f'design -stash {design}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate comparison', 'hierarchy -top comparison',
                     'equiv_simple -seq 3', 'opt_clean', 'equiv_induct -seq 6',
                     'equiv_status -assert']
        script.write_text('\n'.join(commands) + '\n')
        log = folder / 'formal.log'
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=180)
        result = log.read_text()
        if 'Equivalence successfully proven!' not in result:
            raise RuntimeError(f'Equivalence proof did not finish: {log}')
        count = re.findall(r'Of those cells (\d+) are proven and 0 are unproven', result)
        report['profiles'].append({'name': name, 'passed': True,
                                   'proven_points': int(count[-1]), 'parameters': parameters})
        print(f'{name}: complete module equivalence passed', flush=True)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
