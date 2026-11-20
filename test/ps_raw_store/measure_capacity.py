#!/usr/bin/env python3
"""比较帧容量判断及完整部分和存储模块的 FPGA 资源和组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/ps_compact/ps_frame_store.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='b8b34d5')
    parser.add_argument('--scopes', nargs='+', choices=['capacity', 'store'], default=['capacity', 'store'])
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_bytes()
    reference = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT)
    reference_source = out / 'reference.sv'
    reference_source.write_bytes(reference)
    cases = {}
    for scope in args.scopes:
        for version in ['reference', 'current']:
            if scope == 'capacity':
                cases[f'{scope}_{version}'] = {
                    'top': 'ps_frame_capacity_measure',
                    'sources': [str(SOURCE), 'test/ps_raw_store/capacity.sv'],
                    'options': [f'-GREFERENCE={int(version == "reference")}'],
                    'configuration': '14-bit initial row, 10-bit bank depth, 4-bit bank count, 32-bit row requests',
                }
            else:
                cases[f'{scope}_{version}'] = {
                    'top': 'ps_frame_store',
                    'sources': [str(reference_source) if version == 'reference' else str(SOURCE)],
                    'options': ['-GMAX_FRAME_ROWS=512', '-GFRAME_COUNT=16', '-GPOOL_BYTES=49152',
                                '-GBANK_BYTES=8192', '-GEXTERNAL_RAM=1'],
                    'configuration': '512 rows/frame, 16 frames, 49152-byte pool, 8192-byte banks',
                }
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
               '--case-config', str(config), '--cases', *cases,
               '--out', str(out / 'results')]
    if args.lock_file:
        command += ['--lock-file', str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)
    assert current == (ROOT / SOURCE).read_bytes()
    manifest = {'reference': args.reference,
                'source_sha256': hashlib.sha256(current).hexdigest(),
                'reference_sha256': hashlib.sha256(reference).hexdigest(),
                'configuration_sha256': hashlib.sha256(config.read_bytes()).hexdigest()}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
