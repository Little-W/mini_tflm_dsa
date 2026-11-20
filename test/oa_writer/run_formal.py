#!/usr/bin/env python3
"""运行输出写回预计算的公开输出和状态关系证明。"""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] /
                       'oa_writer_pipeline' / 'run_formal.py'), run_name='__main__')
