#!/usr/bin/env python3
"""启用行释放移位，比较完整缓存的全部输出和寄存状态。"""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]


def main():
    runner = runpy.run_path(str(ROOT/'test/cache_queued_preview/check_parent.py'))
    namespace = runner['main'].__globals__
    profiles = [*namespace['PROFILES'],
        dict(SETS=256,WAYS=2,LINE_BYTES=128,BUS_WIDTH=64,READ_WIDTH=128,DEMAND_DEPTH=2)]
    namespace['PROFILES'] = tuple(dict(**profile,p_defer_retire_shift=1) for profile in profiles)
    return runner['main']()


if __name__ == '__main__':
    raise SystemExit(main())
