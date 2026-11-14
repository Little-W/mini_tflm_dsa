#!/usr/bin/env python3
"""Generate an NPU test case using the shared verification generator."""
from pathlib import Path
import runpy
import sys

shared = Path(__file__).resolve().parents[2] / "veri/top_regression"
sys.path.insert(0, str(shared))
runpy.run_path(str(shared / "gen_mem.py"), run_name="__main__")
