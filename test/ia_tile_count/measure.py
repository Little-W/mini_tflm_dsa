#!/usr/bin/env python3
"""测量配置来源选择、余数判断和分块数量计算的完整寄存器间路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-ref', default='1470a963')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, ROOT/'test/ia_tile_count/prepare_measurement.py',
        '--reference-ref', args.reference_ref, '--out', out/'source'], check=True, cwd=ROOT)
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
        '--case-config', out/'source/cases.json', '--cases', 'reference', 'current',
        '--out', out/'mapping', '--through', 'pre_lut'], check=True, cwd=ROOT)
    rows = {}
    for name in ('reference', 'current'):
        source, cost = out/'mapping'/name, out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py', '--source', source,
            '--out', cost, '--mode', 'physical-cost', '--delay-target-ps', '6667',
            '--wire-delay-ps', '300', '--max-lut-inputs', '8', '--discard-abc9-temporaries'], check=True, cwd=ROOT)
        rows[name] = {'manifest': json.loads((cost/'manifest.json').read_text()),
            'summary': json.loads((cost/'summary.json').read_text()),
            'mapped_sha256': hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest()}
        print(name, rows[name]['summary']['resources']['lut_sites_nominal_before_packing'],
              rows[name]['summary']['longest_register_path_cells'], flush=True)
    report = {'reference_commit': subprocess.check_output(['git', 'rev-parse', args.reference_ref],
        cwd=ROOT, text=True).strip(), 'source_sha256': json.loads((out/'source/source_sha256.json').read_text()),
        'parameters': {'REG_WIDTH': 32, 'SIZE': 16}, 'cases': rows}
    (out/'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
