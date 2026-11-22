#!/usr/bin/env python3
"""验证寄存向量运算与全部操作码。"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
runpy.run_path(str(ROOT / 'test/vector_extremum/run.py'), run_name="__main__")
