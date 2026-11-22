#!/usr/bin/env python3
"""运行普通 RTL 选择加法的完整输入空间与四态验证。"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, str(ROOT / 'test/select_add_simd/run.py'),
                    '--out', str(args.out)], cwd=ROOT, check=True)

if __name__ == '__main__':
    main()
