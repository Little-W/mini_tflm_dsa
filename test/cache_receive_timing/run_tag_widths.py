#!/usr/bin/env python3
"""证明实际响应表达式在全部 1 至 32 位标签宽度下保持一致。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from run import prove_response
from support import check_sources, prepare_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    _, paths, _, manifest = prepare_inputs(out, args.reference, args.candidate)
    rows = prove_response(out, paths, payload_when_valid=True,
                          profiles=[(2, 64, 1, 32 - width) for width in range(1, 33)])
    check_sources(manifest)
    report = {
        'passed': True, 'inputs': manifest, 'input_assumptions': [],
        'scope': 'Actual combinational response expressions with tag widths 1 through 32; this checks tag partition boundaries and does not elaborate physical cache storage',
        'profiles': rows,
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out / 'summary.json')


if __name__ == '__main__':
    main()
