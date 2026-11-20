#!/usr/bin/env python3
"""使用完整前端比较十八位加法两侧的寄存路径和资源。"""
import runpy
from run_formal import ROOT


if __name__ == '__main__':
    runpy.run_path(str(ROOT / 'test/frontend_release_shift/measure.py'), run_name='__main__')
