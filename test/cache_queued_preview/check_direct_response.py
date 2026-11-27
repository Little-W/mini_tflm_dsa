#!/usr/bin/env python3
"""执行缓存响应队列的完整返回数据与四态检查。"""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1]/'cache_response_ready/check_return.py'),run_name='__main__')
