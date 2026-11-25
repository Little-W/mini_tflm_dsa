#!/usr/bin/env python3
"""检查读取来源选择和完整地址运算的四态行为。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-revision', default='7ddc0d8d')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    reports = {}
    for name, script in (('sources', 'check_registered_sources.py'),
                         ('arithmetic', 'check_arithmetic.py')):
        target = args.out / name
        subprocess.run([sys.executable, str(ROOT / 'test/vector_read_address_phase' / script),
                        '--source-root', str(args.source_root), '--reference-revision',
                        args.reference_revision, '--out', str(target)], cwd=ROOT, check=True)
        reports[name] = json.loads((target / 'summary.json').read_text())
    (args.out / 'summary.json').write_text(json.dumps(dict(passed=True,
        source_selection_cases=reports['sources']['four_state_cases'],
        address_comparisons=reports['arithmetic']['four_state_comparisons'],
        reports=reports), indent=2)+'\n')


if __name__ == '__main__':
    main()
