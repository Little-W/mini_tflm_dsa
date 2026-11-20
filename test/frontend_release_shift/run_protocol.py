#!/usr/bin/env python3
"""比较普通行释放元数据与延后移位元数据的真实窗口协议和持续吞吐。"""
import importlib.util
import sys

from run_formal import ROOT, REFERENCE, SOURCE, prepare, source_pair


def main():
    spec = importlib.util.spec_from_file_location('release_prepare_protocol',
        ROOT / 'test/frontend_release_prepare/run_protocol.py')
    program = importlib.util.module_from_spec(spec)
    saved = sys.modules['run_formal']
    try:
        sys.modules['run_formal'] = prepare
        spec.loader.exec_module(program)
    finally:
        sys.modules['run_formal'] = saved

    def sources(reference):
        contents, bodies = source_pair(reference)
        return contents[SOURCE], bodies

    program.sources = sources
    program.REFERENCE = REFERENCE
    program.MAIN = program.MAIN.replace('{1u,2u,4u}', '{1u,2u,3u,4u}')
    program.EXPECTED_SCENARIOS = 64
    program.EXPECTED_REQUESTS = 1536
    program.main()


if __name__ == '__main__':
    main()
