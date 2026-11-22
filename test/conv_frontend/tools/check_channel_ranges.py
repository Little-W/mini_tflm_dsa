#!/usr/bin/env python3
"""验证完整通道范围、传输资格与行末的统一入口。"""
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[3]
if __name__=='__main__':
    runpy.run_path(str(ROOT/'test/frontend_group_feedback/check.py'),run_name='__main__')
