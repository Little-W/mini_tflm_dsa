#!/usr/bin/env python3
"""执行并发读错误、写握手、中止排空和连续恢复的真实 DMA 测试。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--bus-width', type=int, choices=[32,64], default=32)
    parser.add_argument('--size', type=int, default=8)
    parser.add_argument('--dma-size', type=int, default=8)
    parser.add_argument('--cache-blocks', type=int, choices=[4,64], default=4)
    parser.add_argument('--data-width', type=int, choices=[8,16], default=8)
    parser.add_argument('--outstanding', type=int, choices=[1,4], default=1)
    parser.add_argument('--fpga', action='store_true')
    parser.add_argument('--prepare-abort', action='store_true',
                        help='检查已接收读取命令在两个准备周期内发生中止或复位')
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    packages = [source / 'rtl/npu/conv/conv_im2col_pkg.sv', source / 'rtl/npu/conv/vector_engine_pkg.sv']
    paths = packages + [path for path in sorted((source / 'rtl/npu/conv').rglob('*.sv')) if path not in packages]
    paths += sorted((source / 'rtl/npu/dma').rglob('*.sv'))
    paths += sorted((source / 'rtl/common').glob('*.sv'))
    paths += [source / 'rtl/common/regfile.v', source / 'rtl/common/pseudo_dual_port_ram.v',
              HERE / 'top.sv', HERE / 'main.cpp']
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    hashes = {str(path): digest(path) for path in paths}
    options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if args.fpga else []
    commands = [
        [args.verilator, '--cc', '--exe', '--timing', '--assert', '-DNPU_SIM_ASSERT',
         '-Wno-fatal', '-Wno-PINMISSING', '--top-module', 'dma_abort_top',
         '--Mdir', str(out / 'obj'), '--output-groups', '0', '--output-split', '12000',
         f'-GBUS_WIDTH={args.bus_width}', f'-GSIZE={args.size}', f'-GDMA_SIZE={args.dma_size}',
         f'-GCACHE_BLOCKS={args.cache_blocks}',
         f'-GDATA_WIDTH={args.data_width}', f'-GOUTSTANDING={args.outstanding}',
         '-CFLAGS', f'-std=c++20 -fsanitize=undefined -fno-sanitize-recover=undefined -DTEST_BUS_WIDTH={args.bus_width} -DTEST_PREPARE_ABORT={int(args.prepare_abort)}',
         '-LDFLAGS', '-fsanitize=undefined', *options, *map(str, paths)],
        ['make', '-C', str(out / 'obj'), '-f', 'Vdma_abort_top.mk', '-j', str(args.jobs),
         'OPT_FAST=-O1', 'OPT_SLOW=-O0', 'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E'],
        [str(out / 'obj/Vdma_abort_top')]]
    for command, filename in zip(commands, ('generate.log', 'compile.log', 'run.log')):
        with (out / filename).open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out / filename).read_text()[-8000:])
    if hashes != {str(path): digest(path) for path in paths}:
        raise RuntimeError('RTL changed while verifying DMA transactions')
    log = (out / 'run.log').read_text()
    cases = 24 if args.prepare_abort else 16
    if f'DMA_ABORT_BOUNDARY_PASS cases={cases}' not in log:
        raise RuntimeError(log)
    (out / 'summary.json').write_text(json.dumps({
        'passed': True, 'source_sha256': hashes, 'cases': cases,
        'bus_width':args.bus_width, 'size':args.size, 'dma_size':args.dma_size,
        'cache_blocks':args.cache_blocks,
        'data_width':args.data_width, 'outstanding':args.outstanding,
        'fpga':args.fpga, 'undefined_behavior_sanitizer':True,
        'prepare_abort':args.prepare_abort,
        'binary_sha256': digest(out / 'obj/Vdma_abort_top'),
        'results': log.splitlines(), 'commands': commands
    }, ensure_ascii=False, indent=2) + '\n')
    print(log, end='')


if __name__ == '__main__':
    main()
