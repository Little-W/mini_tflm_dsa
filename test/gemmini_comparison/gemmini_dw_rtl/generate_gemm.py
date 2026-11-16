#!/usr/bin/env python3
"""Record GEMM commands from the pinned DWConv fork's C scheduling functions."""

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
COMMON = ROOT.parent / 'gemmini_command_trace'


def main():
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument('--out', type=Path)
    args, _ = options.parse_known_args()
    spec = importlib.util.spec_from_file_location('shared_gemmini_trace', COMMON / 'generate.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    if args.out is not None:
        assets = args.out.resolve() / 'trace_source'
        assets.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'sim/gemm_trace.c', assets / 'trace.c')
        shutil.copyfile(COMMON / 'xcustom.h', assets / 'xcustom.h')
        generator.HERE = assets
    return generator.main()


if __name__ == '__main__':
    sys.exit(main())
