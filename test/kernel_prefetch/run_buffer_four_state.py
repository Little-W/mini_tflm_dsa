#!/usr/bin/env python3
"""比较权重缓存的四态数据、任意控制组合和全部公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='2247144937c2fd04039b9b005151f371d6b51f8f')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=['3:8', '4:16', '16:8', '16:16', '32:16'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/loaders/kernel_loader_buffer.sv'
    original = read_rtl_source(
        f'{args.reference}:rtl/npu/loaders/kernel_loader_buffer.sv', cwd=ROOT, text=True)
    reference = out / 'reference.sv'
    reference.write_text(original.replace('module kernel_loader_buffer #(',
                                         'module kernel_loader_buffer_ref #(', 1))
    sources = [source, ROOT / 'rtl/common/regfile.v', reference,
               Path(__file__).with_name('tb_buffer_equivalence.sv')]
    hashes = {str(path): digest(path) for path in sources}
    profiles = []
    for profile in args.profiles:
        size, width = map(int, profile.split(':'))
        folder = out / f'n{size}_w{width}'
        folder.mkdir(exist_ok=True)
        binary = folder / 'compare.vvp'
        command = ['iverilog', '-g2012', '-s', 'tb_kernel_buffer_equivalence',
                   f'-Ptb_kernel_buffer_equivalence.SIZE={size}',
                   f'-Ptb_kernel_buffer_equivalence.DATA_WIDTH={width}',
                   '-Ptb_kernel_buffer_equivalence.FOUR_STATE=1',
                   '-o', str(binary), *map(str, sources)]
        with (folder / 'compile.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                                check=True, timeout=180)
        (folder / 'run.log').write_text(result.stdout + result.stderr)
        states = re.search(r'KERNEL_BUFFER_FOUR_STATE_PASS known_weight_samples=(\d+)', result.stdout)
        behavior = re.search(r'KERNEL_BUFFER_EQ_PASS (.*)', result.stdout)
        if states is None or behavior is None:
            raise RuntimeError(f'Incomplete buffer comparison: {folder}')
        counters = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', behavior[1])}
        profiles.append({'size': size, 'data_width': width, 'passed': True,
                         'known_weight_samples': int(states[1]), **counters})
        print(json.dumps(profiles[-1]), flush=True)
    if hashes != {str(path): digest(path) for path in sources}:
        raise RuntimeError('Sources changed during buffer comparison')
    report = {'passed': True, 'reference': args.reference, 'source_sha256': hashes,
              'compared_scalar_outputs': 8, 'compared_weight_lanes': 'SIZE', 'profiles': profiles}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
