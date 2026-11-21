#!/usr/bin/env python3
"""证明线性 DMA 返回列资格与全部公开输出、状态和存储逐周期一致。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed(source):
    marker = '    output logic wr_error\n);'
    if source.count(marker) != 1:
        raise RuntimeError('无法唯一识别线性 DMA 的公开端口')
    source = source.replace(marker, '''    output logic wr_error,
    output logic [BUS_WIDTH/8-1:0] formal_lane_in_data
);''')
    relation = '''
    for (genvar formal_lane = 0; formal_lane < BUS_WIDTH/8; formal_lane++) begin : g_formal_lane
        assign formal_lane_in_data[formal_lane] = g_unpack_lane[formal_lane].lane_in_data;
    end
'''
    end = source.index('endmodule')
    return source[:end] + relation + source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', default=[16, 64])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {'reference': args.reference.resolve(), 'candidate': args.candidate.resolve()}
    inputs = {name: {'path': str(path), 'sha256': digest(path)} for name, path in sources.items()}
    generated = {}
    for name, path in sources.items():
        target = out / (name + '_observed.sv')
        target.write_text(observed(path.read_text()))
        generated[name] = target
    result_dir = out / 'equivalence'
    subprocess.run([sys.executable, str(Path(__file__).with_name('linear_check.py')),
                    '--reference', str(generated['reference']), '--candidate', str(generated['candidate']),
                    '--sizes', *map(str, args.sizes), '--out', str(result_dir)], cwd=ROOT, check=True)
    result = json.loads((result_dir / 'summary.json').read_text())
    if not result['passed']:
        raise RuntimeError('完整线性 DMA 关系未全部通过')
    if any(digest(path) != inputs[name]['sha256'] for name, path in sources.items()):
        raise RuntimeError('证明期间输入源码发生变化')
    report = {
        'passed': True, 'inputs': inputs, 'input_assumptions': [],
        'relations': ['Every registered lane qualification equals the reference expression of the captured column metadata on every cycle'],
        'method': 'Expose the actual lane_in_data of both implementations as proof outputs; compare every public output, shared clocked state, expanded memory, and every derived lane qualification',
        'generated_source_sha256': {name: digest(path) for name, path in generated.items()},
        'complete_dma': result,
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out / 'summary.json')


if __name__ == '__main__':
    main()
