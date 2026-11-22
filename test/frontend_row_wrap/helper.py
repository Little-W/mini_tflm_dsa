#!/usr/bin/env python3
"""验证行尾判断使用的完整定宽加法等式。"""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]

if __name__ == '__main__':
    runpy.run_path(str(ROOT / 'test/add_equal/run_formal.py'), run_name='__main__')
