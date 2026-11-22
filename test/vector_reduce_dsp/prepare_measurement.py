#!/usr/bin/env python3
"""生成归约单元与完整引擎的综合输入。"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
runpy.run_path(str(ROOT / 'test/conv_portable/prepare_measurement.py'), run_name="__main__")
