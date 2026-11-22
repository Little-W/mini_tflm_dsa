#!/usr/bin/env python3
"""同时证明 FIFO 目标银行选择、完整周期行为及六项保存状态关系。"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--tool-root', type=Path, default=Path(__file__).resolve().parents[2])
    args, remaining = parser.parse_known_args()
    root = args.tool_root.resolve()
    sys.argv = [sys.argv[0], *remaining]
    if '--reference' not in remaining and '--reference-file' not in remaining:
        sys.argv += ['--reference', '8aa34632']
    spec = importlib.util.spec_from_file_location(
        'fifo_saved_formal', root / 'test/fifo_write_blocked/run_formal.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    calls = 0

    def observed_source(source):
        nonlocal calls
        text = helper.observed_source(source)
        if calls == 0:
            # 参照实现的关系端口固定为一，当前实现的关系与所有共同状态一起从复位证明。
            # 功能输入保持自由，独热位置及有效范围均为待证明的结论。
            text, count = re.subn(
                r'    assign formal_saved_state\[0\] =.*?    assign formal_saved_state\[5\] =.*?;',
                "    assign formal_saved_state = 6'b111111;", text, flags=re.S)
            if count != 1 and "assign formal_saved_state = 6'b111111;" not in text:
                raise ValueError('无法定位参照实现的状态关系输出')
        calls += 1
        return text

    helper.base.observed_source = observed_source
    helper.base.main()
    if calls != 2:
        raise RuntimeError('等价检查需要分别观察参照实现和当前实现')


if __name__ == '__main__':
    main()
