#!/usr/bin/env python3
"""验证完整三项地址求和关系。"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.argv[1:1] = ['--only', 'address']
runpy.run_path(str(ROOT / 'test/conv_portable/run.py'), run_name="__main__")
