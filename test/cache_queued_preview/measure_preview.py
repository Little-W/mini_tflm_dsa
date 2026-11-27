#!/usr/bin/env python3
"""按 SoC 缓存参数综合连续预读，保存完整网表、资源数量和寄存器路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def execute(command):
    subprocess.run(list(map(str, command)), cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([ROOT/'rtl/npu/dma/cache/conv_windowed_cache.sv'], ROOT)
    parameters = dict(SETS=16, WAYS=2, LINE_BYTES=128, BUS_WIDTH=64, READ_WIDTH=64,
                      CACHE_POLICY=3, DEMAND_DEPTH=2, p_preview_request=1)
    options = ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1']
    options += [f'-G{name}={value}' for name,value in parameters.items()]
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(dict(preview=dict(
        top='conv_windowed_cache', configuration='4 KiB 双路缓存，128 字节缓存行、64 位数据和两项请求队列',
        parameters=parameters, sources=list(map(str, sources)), options=options)),
        ensure_ascii=False, indent=2)+'\n')
    resume = ['--resume'] if args.resume else []
    execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
             '--case-config', configuration, '--cases', 'preview', '--out', out,
             '--through', 'pre_lut', *resume])
    execute([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
             '--source', out/'preview', '--out', out/'mapped', '--mode', 'physical-cost',
             '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8',
             '--discard-abc9-temporaries', *resume])
    execute([sys.executable, ROOT/'test/cache_queued_preview/inspect_preview_paths.py',
             '--source', out/'preview', '--mapped', out/'mapped', '--out', out/'paths'])


if __name__ == '__main__':
    main()
