#!/usr/bin/env python3
"""综合生产缓存配置，记录填充选择逻辑的资源与寄存器间组合级数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    'rtl/npu/dma/cache/conv_read_cache.sv',
    'rtl/npu/dma/cache/conv_sdp_ram.sv',
    'rtl/npu/conv/conv_axi_span_reader.sv',
)
PARAMETERS = {
    'SETS': 128, 'WAYS': 2, 'BUS_WIDTH': 64, 'READ_WIDTH': 64,
    'LINE_BYTES': 16, 'DEMAND_DEPTH': 2, 'p_defer_retire_shift': 1,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='ef0dc75')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        folder = out / 'sources' / label
        folder.mkdir(parents=True, exist_ok=True)
        hashes[label] = {}
        for source in SOURCES:
            target = folder / Path(source).name
            if label == 'reference' and source == SOURCES[0]:
                content = subprocess.check_output(
                    ['git', 'show', f'{args.reference}:{source}'], cwd=ROOT)
                target.write_bytes(content)
            else:
                shutil.copyfile(ROOT / source, target)
            hashes[label][source] = hashlib.sha256(target.read_bytes()).hexdigest()
        cases[label] = {
            'top': 'conv_windowed_cache',
            'sources': [str(folder / Path(source).name) for source in SOURCES],
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                       [f'-G{name}={value}' for name, value in PARAMETERS.items()],
            'parameters': PARAMETERS,
            'configuration': '128 sets, 2 ways, 64-bit input and output, 2 queued responses',
        }
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    with (out / 'measurement.log').open('w') as stream:
        subprocess.run([
            sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--case-config', str(config), '--cases', 'reference', 'current',
            '--out', str(out / 'native'), *(['--resume'] if args.resume else []),
        ], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    results = {}
    for label in cases:
        metrics = json.loads((out / 'native' / label / 'metrics.json').read_text())
        results[label] = {
            'resources': metrics['resources'],
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'graph_complete': metrics['paths']['graph_complete'],
            'endpoint_port_maximum_depth_histogram':
                metrics['paths']['endpoint_port_maximum_depth_histogram'],
        }
    for source, digest in hashes['current'].items():
        if hashlib.sha256((ROOT / source).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'综合期间源码变化: {source}')
    result = {
        'reference': args.reference, 'parameters': PARAMETERS,
        'synthesis_flow': 'default',
        'source_sha256': hashes, 'results': results,
        'measurement_scope': 'independent conv_windowed_cache synthesis before placement',
    }
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
