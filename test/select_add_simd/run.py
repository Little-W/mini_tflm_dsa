#!/usr/bin/env python3
"""运行选择加法与四通道模加的功能验证。"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    for script, folder in [('test/select_add/run_formal.py', 'scalar'),
                           ('test/ia_packed_add/run.py', 'lanes')]:
        subprocess.run([sys.executable, str(ROOT / script), '--out', str(args.out / folder)],
                       cwd=ROOT, check=True)

if __name__ == '__main__':
    main()
