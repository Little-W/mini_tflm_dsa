#!/usr/bin/env python3
"""证明线性 DMA 的同步计数资格、公开输出和完整时钟状态。"""
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


def observed(source, candidate):
    marker = '    output logic wr_error\n);'
    if source.count(marker) != 1:
        raise RuntimeError('无法唯一识别线性 DMA 的公开端口')
    source = source.replace(marker, '''    output logic wr_error,
    output logic formal_context_nonempty,
    output logic formal_context_space
);''')
    nonempty = "rd_context_nonempty_q" if candidate else "rd_context_count != '0"
    space = "rd_context_space_q" if candidate else "rd_context_count < context_count_t'(RD_CTX_DEPTH)"
    relation = f'''\n    assign formal_context_nonempty = {nonempty};
    assign formal_context_space = {space};
'''
    end = source.index('endmodule')
    return source[:end] + relation + source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', default=[16])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {'reference': args.reference.resolve(), 'candidate': args.candidate.resolve()}
    inputs = {name: {'path': str(path), 'sha256': digest(path)} for name, path in sources.items()}
    generated = {}
    for name, path in sources.items():
        target = out / (name + '_observed.sv')
        target.write_text(observed(path.read_text(), name == 'candidate'))
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
        'relations': ['rd_context_nonempty_q == (rd_context_count != 0)',
                      'rd_context_space_q == (rd_context_count < RD_CTX_DEPTH)'],
        'method': 'Expose both registered flags and reference count comparisons as proof outputs; compare every public output, shared state, expanded memory, and both derived relations',
        'generated_source_sha256': {name: digest(path) for name, path in generated.items()},
        'complete_dma': result,
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out / 'summary.json')


if __name__ == '__main__':
    main()
