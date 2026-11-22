#!/usr/bin/env python3
"""使用实际 SoC 缓存参数比较普通 RTL 存储推断的资源和组合级数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_formal import CASES, SOURCES

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = CASES['production']
    cases, hashes = {}, {}
    for label, root in (('reference', args.reference_root.resolve()),
                        ('current', args.source_root.resolve())):
        sources = [root / relative for relative in SOURCES]
        sources += sorted(path for path in (root / 'rtl/common').iterdir()
                          if path.suffix in ('.v', '.sv'))
        archived, hashes[label] = [], {}
        for source in sources:
            relative = source.relative_to(root)
            target = out / 'sources' / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            hashes[label][str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
            if str(relative) in SOURCES:
                archived.append(str(target))
        cases[label] = {
            'top': 'conv_windowed_cache', 'sources': archived,
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] + [
                f'-G{name}={value}' for name, value in parameters.items()],
            'parameters': parameters,
            'configuration': '16 组、2 路、128 字节缓存行、64 位数据、2 项需求队列',
        }
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + '\n')
    for relative in hashes['current']:
        if relative.startswith('rtl/common/') and hashes['reference'][relative] != hashes['current'][relative]:
            raise RuntimeError('缓存比较需要相同的公共模块: ' + relative)
    with (out / 'measurement.log').open('w') as stream:
        subprocess.run([
            sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--source-root', str(out / 'sources/current'),
            '--case-config', str(config), '--cases', 'reference', 'current',
            '--out', str(out / 'native'), *(['--resume'] if args.resume else []),
        ], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    results = {}
    for label in cases:
        metrics = json.loads((out / 'native' / label / 'metrics.json').read_text())
        results[label] = {'resources': metrics['resources'],
                          'paths': metrics['paths']}
    result = {'passed': True, 'parameters': parameters, 'source_sha256': hashes,
              'synthesis_flow': 'default',
              'measurement_scope': 'independent conv_windowed_cache synthesis before placement',
              'results': results}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    for label, measured in results.items():
        print(label, json.dumps(measured['resources']), flush=True)


if __name__ == '__main__':
    main()
