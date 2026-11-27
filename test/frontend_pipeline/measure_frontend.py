#!/usr/bin/env python3
"""按 SoC 的实际前端参数综合并检查全部相连的寄存器路径。"""
from pathlib import Path
import argparse
import json
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = dict(SIZE=16, LANES=8, BUS_WIDTH=64, SLOT_W=6,
        CACHE_SETS=16, CACHE_WAYS=2, LINE_BYTES=128, CACHE_POLICY=3,
        REGISTER_DESCRIPTOR=1, REGISTER_ROW_ADDRESS=1, REGISTER_CACHE_REQUEST=1,
        CACHE_RESPONSE_DEPTH=2, DMA_MAX_BYTES=2048)
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([source / 'rtl/npu/conv/conv_im2col_pkg.sv',
                       source / 'rtl/npu/conv/conv_im2col_frontend.sv'], source)
    case = dict(top='conv_im2col_frontend', parameters=parameters,
        configuration='16 行、8 通道、64 位读取、4 KiB 缓存、2 项需求队列的完整前端',
        options=['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1', '-I' + str(source / 'include')] +
                [f'-G{name}={value}' for name, value in parameters.items()],
        sources=list(map(str, sources)))
    config = out / 'cases.json'
    config.write_text(json.dumps({'frontend': case}, ensure_ascii=False, indent=2) + '\n')
    commands = [
        [sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--source-root', source,
         '--case-config', config, '--cases', 'frontend', '--out', out / 'pre', '--through', 'pre_lut'],
        [sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py', '--source', out / 'pre/frontend',
         '--out', out / 'physical', '--mode', 'physical-cost', '--delay-target-ps', '6667',
         '--wire-delay-ps', '300', '--max-lut-inputs', '8', '--discard-abc9-temporaries'],
        [sys.executable, ROOT / 'scripts/fpga/netlist_metrics.py', out / 'physical/mapped.json',
         '--top', 'conv_im2col_frontend', '--out', out / 'physical/critical_paths.json',
         '--register-origins', out / 'pre/frontend/pre_lut.il', '--path-limit', '20000',
         '--group-limit', '20000', '--minimum-path-cells', '11'],
    ]
    for index, command in enumerate(commands):
        if args.resume and index < 2:
            command.append('--resume')
        with (out / f'driver_{index}.log').open('w') as log:
            subprocess.run(list(map(str, command)), cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
    summary = json.loads((out / 'physical/summary.json').read_text())
    print(json.dumps({key: summary[key] for key in
                      ('resources', 'longest_register_path_cells', 'register_path_requirement')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
