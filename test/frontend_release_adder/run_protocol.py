#!/usr/bin/env python3
"""比较普通十八位加法的窗口数值、握手和逐周期输出。"""
import runpy
from run_formal import ROOT


if __name__ == '__main__':
    runpy.run_path(str(ROOT / 'test/frontend_release_shift/run_protocol.py'), run_name='__main__')
