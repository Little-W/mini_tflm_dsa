#!/usr/bin/env python3
"""Verify ordered AXI read descriptors, tags, page splits and error ownership."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=ROOT/'build/linear_dma_context')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--size', type=int, choices=[16,64], default=16)
    parser.add_argument('--cache-blocks', type=int, choices=[4,64], default=4)
    parser.add_argument('--outstanding', type=int, choices=[1, 4], default=4)
    parser.add_argument('--contexts', type=int, choices=[1,4], default=4)
    parser.add_argument('--bus-width', type=int, choices=[32, 64], default=32)
    parser.add_argument('--dma-max-bytes', type=int, help='Optional physical burst limit; default: 256 bus beats')
    parser.add_argument('--fpga', action='store_true')
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    if args.dma_max_bytes is None:
        args.dma_max_bytes = 256 * (args.bus_width // 8)
    if (args.dma_max_bytes < args.bus_width // 8 or args.dma_max_bytes > 256 * (args.bus_width // 8)
        or args.dma_max_bytes & (args.dma_max_bytes - 1)):
        parser.error("DMA limit must be 1 through 256 complete bus beats with a power-of-two byte length")
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=True)
    sources = [source_root/'rtl/npu/dma/axi_linear_block_dma.sv',
               source_root/'rtl/common/regfile.v',
               source_root/'rtl/common/add_equal.sv',
               ROOT/'test/linear_dma_context/linear_dma_4k_top.sv',
               ROOT/'test/linear_dma_context/main.cpp', Path(__file__).resolve()]
    hashes = {str(p): sha(p) for p in sources}
    primitive_library_sha256 = None
    primitive_args = []
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        model = out/'lut6_2.sv'
        model.write_text(re.search(r'^module LUT6_2\b.*?^endmodule', library.read_text(), re.M | re.S).group(0)+'\n')
        primitive_library_sha256 = sha(library)
        primitive_args = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', str(model)]
    generate = [args.verilator, '--cc', '--exe', '--assert', '-Wno-fatal',
                '--top-module', 'linear_dma_4k_top', '--Mdir', str(out/'obj'),
                '--output-groups', '0', '--output-split', '12000',
                f'-GREAD_OUTSTANDING={args.outstanding}', f'-GRD_CONTEXT_DEPTH={args.contexts}',
                f'-GSIZE={args.size}', f'-GCACHE_BLOCKS={args.cache_blocks}',
                f'-GBUS_WIDTH={args.bus_width}', f'-GDMA_MAX_BYTES={args.dma_max_bytes}',
                '-CFLAGS', f'-std=c++20 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096 -fsanitize=undefined -fno-sanitize-recover=undefined -DTEST_DMA_MAX_BYTES={args.dma_max_bytes} -DTEST_BUS_WIDTH={args.bus_width} -DTEST_SIZE={args.size} -DTEST_CACHE_BLOCKS={args.cache_blocks}',
                '-LDFLAGS', '-fsanitize=undefined',
                *primitive_args, *[str(p) for p in sources[:5]]]
    compile_args = ['make', '-C', str(out/'obj'), '-f', 'Vlinear_dma_4k_top.mk', '-j', '1',
                    'OPT_FAST=-O1', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O1',
                    'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E']
    for command, name in [(generate, 'generate.log'), (compile_args, 'compile.log')]:
        with (out/name).open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            print((out/name).read_text()[-6000:]);return result.returncode
    binary = out/'obj/Vlinear_dma_4k_top'
    records = []
    for random in (False, True):
        command = [str(binary), '--outstanding', str(args.outstanding), '--contexts', str(args.contexts)] + (['--random'] if random else [])
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out/('random.log' if random else 'fixed.log')).write_text(result.stdout)
        fields = re.findall(r'(\w+)=(\d+)', result.stdout)
        records.append({'random': random, 'passed': result.returncode == 0 and 'LINEAR_CONTEXT_PASS' in result.stdout,
                        'returncode': result.returncode, 'counters': {k: int(v) for k, v in fields}})
        print(result.stdout.strip())
    unchanged = hashes == {str(p): sha(p) for p in sources}
    passed = unchanged and all(r['passed'] for r in records)
    (out/'summary.json').write_text(json.dumps({'passed': passed, 'outstanding': args.outstanding, 'contexts':args.contexts, 'dma_max_bytes': args.dma_max_bytes, 'bus_width': args.bus_width,
        'size':args.size, 'cache_blocks':args.cache_blocks, 'undefined_behavior_sanitizer':True,
        'source_sha256': hashes, 'sources_unchanged_during_build': unchanged,
        'binary_sha256': sha(binary), 'generate_command': generate, 'compile_command': compile_args,
        'fpga': args.fpga, 'primitive_library_sha256': primitive_library_sha256,
        'runs': records}, indent=2)+'\n')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
