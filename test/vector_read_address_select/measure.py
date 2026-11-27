#!/usr/bin/env python3
"""对同一向量引擎分别装载参考地址选择与当前地址选择，比较完整映射结果。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '7c6599e002c9abb8906b73554c65a74b0fe8d780'


def execute(command):
    subprocess.run(list(map(str, command)), cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out/'reference_address.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show',
        REFERENCE+':rtl/npu/conv/vector_engine_address.sv'], cwd=ROOT))
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GTILE=16', '-GBUS_WIDTH=64',
               '-GPE_COUNT=8', '-GWINDOW_LANES=8', '-GSHARED_STORAGE_ENABLE=1',
               '-GSHARED_QUANT_ENABLE=0', '-GSHARED_STORAGE_ADDR_WIDTH=12']
    engine = ROOT/'rtl/npu/conv/vector_engine.sv'
    cases = {name: dict(top='vector_engine', configuration='16通道、8PE、64位总线、共享存储、本地量化',
                       sources=[str(path) for path in resolve(files, ROOT)], options=options)
             for name, files in [('reference', [reference, engine]), ('candidate', [engine])]}
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    mapping = out/'mapping'
    resume = ['--resume'] if args.resume else []
    execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
             '--case-config', configuration, '--cases', 'reference', 'candidate',
             '--out', mapping, '--through', 'pre_lut', *resume])
    for name in cases:
        execute([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
                 '--source', mapping/name, '--out', mapping/(name+'_cost'),
                 '--mode', 'physical-cost', '--delay-target-ps', '6667',
                 '--wire-delay-ps', '300', '--max-lut-inputs', '8', *resume])
    execute([sys.executable, ROOT/'test/vector_read_address_select/inspect_paths.py',
             '--mapping-root', mapping])


if __name__ == '__main__':
    main()
