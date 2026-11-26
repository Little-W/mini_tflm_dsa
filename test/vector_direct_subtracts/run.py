#!/usr/bin/env python3
"""验证分段直接减法的完整算术和公开模块逐周期行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '84d2374a'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common = ROOT/'test/parallel_prefix_grouped_unknowns/run.py'
    parents = ROOT/'test/vector_selected_subtracts/run_formal.py'
    commands = [
        [sys.executable, str(common), '--out', str(out/'arithmetic'),
         '--direct-subtract', '--jobs', str(args.jobs)],
        [sys.executable, str(parents), '--out', str(out/'parents'),
         '--reference', REFERENCE, '--jobs', str(args.jobs), '--profiles',
         'address', 'predictor', 'geometry_lanes2', 'geometry_lanes8'],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    report = {'passed': True, 'arithmetic': json.loads((out/'arithmetic/summary.json').read_text()),
              'parents': json.loads((out/'parents/summary.json').read_text()),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
