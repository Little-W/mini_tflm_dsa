#!/usr/bin/env python3
"""复用完整 NPU 算子测试入口，增加只读缓存周期统计。"""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]


def main():
    runner = runpy.run_path(str(ROOT / 'test/gemmini_comparison/run_storage_operators.py'))
    namespace = runner['main'].__globals__
    original_build = namespace['build']
    observers = [Path(__file__).with_name(name) for name in (
        'conv_cache_throughput_observer.sv', 'conv_frontend_transaction_observer.sv')]

    def build(args, source_runner, profile):
        original_sources = source_runner.source_files
        def source_files():
            sources, includes, tracked = original_sources()
            return [*sources, *observers], includes, [*tracked, *observers, Path(__file__).resolve()]
        source_runner.source_files = source_files
        try:
            return original_build(args, source_runner, profile)
        finally:
            source_runner.source_files = original_sources
    namespace['build'] = build
    return runner['main']()


if __name__ == '__main__':
    raise SystemExit(main())
