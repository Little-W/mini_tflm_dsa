#!/usr/bin/env python3
"""逐周期比较权重缓存的全部输出以及槽位释放时机。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/kernel_loader_buffer.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='aa2ef9a3')
    parser.add_argument('--out', type=Path, default=ROOT/'build/kernel_buffer_equivalence')
    parser.add_argument('--cycles', type=int, default=100000)
    parser.add_argument('--profiles', nargs='+', default=['3:8', '4:16', '16:8', '16:16', '32:16'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    reference = out/'kernel_loader_buffer_ref.sv'
    reference.write_text(original.replace('kernel_loader_buffer', 'kernel_loader_buffer_ref').replace(
        'kernel_loader_row_ram', 'kernel_loader_row_ram_ref'))
    sources = [ROOT/SOURCE, ROOT/'rtl/common/regfile.v', Path(__file__).with_name('tb_buffer_equivalence.sv')]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    reports = []
    for profile in args.profiles:
        size, width = map(int, profile.split(':'))
        folder = out/f'n{size}_w{width}'
        folder.mkdir(exist_ok=True)
        command = ['verilator', '--binary', '--timing', '-Wno-fatal', '-j', '1',
                   '--top-module', 'tb_kernel_buffer_equivalence', '--Mdir', str(folder/'obj'),
                   f'-GSIZE={size}', f'-GDATA_WIDTH={width}', f'-GRANDOM_CYCLES={args.cycles}',
                   *map(str, sources), str(reference)]
        with (folder/'compile.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = folder/'obj/Vtb_kernel_buffer_equivalence'
        result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
        (folder/'run.log').write_text(result.stdout + result.stderr)
        if result.returncode or 'KERNEL_BUFFER_EQ_PASS' not in result.stdout:
            raise RuntimeError(result.stdout + result.stderr)
        match = re.search(r'KERNEL_BUFFER_EQ_PASS (.*)', result.stdout)
        counters = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match.group(1))}
        reports.append(dict(size=size, data_width=width, passed=True, binary_sha256=digest(binary), **counters))
        print(json.dumps(reports[-1]), flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('Sources changed during verification')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, reference=args.reference,
        source_sha256=hashes, reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        compared_scalar_outputs=8, compared_weight_lanes='SIZE', profiles=reports), indent=2) + '\n')


if __name__ == '__main__':
    main()
