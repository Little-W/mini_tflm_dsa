#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify page-safe AXI write segmentation and logical source consumption."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(rtl, out, outstanding, args):
    out.mkdir(parents=True, exist_ok=True)
    sources = [rtl, args.source_root/'rtl/common/regfile.v', args.source_root/'rtl/common/add_equal.sv',
               Path(__file__).with_name('linear_dma_write_4k_top.sv'),
               Path(__file__).with_name('main.cpp'), Path(__file__).resolve()]
    hashes = {str(p): sha(p) for p in sources}
    options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if args.fpga else []
    generate = [args.verilator, '--cc', '--exe', '--assert', '-Wno-fatal',
                '--top-module', 'linear_dma_write_4k_top', '--Mdir', str(out/'obj'),
                '--output-groups', '0', '--output-split', '12000',
                f'-GWRITE_OUTSTANDING={outstanding}',
                f'-GSIZE={args.size}', f'-GCACHE_BLOCKS={args.cache_blocks}',
                f'-GBUS_WIDTH={args.bus_width}', f'-GDMA_MAX_BYTES={args.dma_max_bytes}',
                '-CFLAGS', f'-std=c++20 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096 -fsanitize=undefined -fno-sanitize-recover=undefined -DTEST_DMA_MAX_BYTES={args.dma_max_bytes} -DTEST_BUS_WIDTH={args.bus_width}',
                '-LDFLAGS', '-fsanitize=undefined', *options,
                *map(str, sources[:5])]
    compile_command = ['make', '-C', str(out/'obj'), '-f', 'Vlinear_dma_write_4k_top.mk',
                       '-j', str(args.jobs), 'OPT_FAST=-O1', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O1',
                       'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E']
    for command, filename in [(generate, 'generate.log'), (compile_command, 'compile.log')]:
        with (out/filename).open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/filename).read_text()[-6000:])
    binary = out/'obj/Vlinear_dma_write_4k_top'
    manifest = dict(bus_width=args.bus_width, dma_max_bytes=args.dma_max_bytes, size=args.size,
                    cache_blocks=args.cache_blocks, fpga=args.fpga, undefined_behavior_sanitizer=True,
                    source_sha256=hashes, binary_sha256=sha(binary),
                    sources_unchanged_during_build=hashes == {str(p): sha(p) for p in sources},
                    generate_command=generate, compile_command=compile_command)
    (out/'build.json').write_text(json.dumps(manifest, indent=2)+'\n')
    if not manifest['sources_unchanged_during_build']:
        raise RuntimeError('source changed during compilation')
    return binary


def run(binary, out, outstanding, random, single):
    command = [str(binary), '--outstanding', str(outstanding)]
    if random: command.append('--random')
    if single: command.append('--single-segment')
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    name = ('single_' if single else '') + ('random' if random else 'fixed')
    (out/(name+'.log')).write_text(result.stdout)
    records = []
    for line in result.stdout.splitlines():
        if line.startswith('CASE '):
            fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
            records.append({key: value if key == 'name' else int(value) for key, value in fields.items()})
    summary_line = next((line for line in result.stdout.splitlines() if line.startswith('LINEAR_DMA_WRITE_4K_PASS')), '')
    counters = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', summary_line)}
    passed = result.returncode == 0 and bool(summary_line)
    print(summary_line if passed else result.stdout[-4000:], flush=True)
    return dict(passed=passed, random=random, single_segment=single, command=command,
                returncode=result.returncode, counters=counters, cases=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=ROOT/'build/linear_dma_write_4k')
    parser.add_argument('--outstanding', type=int, nargs='+', choices=[1, 4], default=[1, 4])
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--source-root', type=Path, default=ROOT,
                        help='包含待验证 RTL 的独立源码目录')
    parser.add_argument('--reference-rtl', type=Path)
    parser.add_argument('--size', type=int, choices=[16,64], default=16)
    parser.add_argument('--cache-blocks', type=int, choices=[4,64], default=4)
    parser.add_argument('--fpga', action='store_true')
    parser.add_argument('--bus-width', type=int, choices=[32, 64], default=32)
    parser.add_argument('--dma-max-bytes', type=int, help='Optional physical burst limit; default: 256 bus beats')
    args = parser.parse_args()
    args.source_root = args.source_root.resolve()
    if args.dma_max_bytes is None:
        args.dma_max_bytes = 256 * (args.bus_width // 8)
    if (args.dma_max_bytes < args.bus_width // 8 or args.dma_max_bytes > 256 * (args.bus_width // 8)
        or args.dma_max_bytes & (args.dma_max_bytes - 1)):
        parser.error("DMA limit must be 1 through 256 complete bus beats with a power-of-two byte length")
    args.out = args.out.resolve();args.out.mkdir(parents=True, exist_ok=True)
    records = []
    rtl = args.source_root/'rtl/npu/dma/axi_linear_block_dma.sv'
    for outstanding in args.outstanding:
        out = args.out/f'outs{outstanding}'
        binary = build(rtl, out, outstanding, args)
        runs = [run(binary, out, outstanding, random, False) for random in (False, True)]
        entry = dict(outstanding=outstanding, build_manifest=str(out/'build.json'), runs=runs)
        if args.reference_rtl and all(r['passed'] for r in runs):
            reference_out = out/'reference'
            reference = build(args.reference_rtl.resolve(), reference_out, outstanding, args)
            comparisons = []
            for random in (False, True):
                current = run(binary, out, outstanding, random, True)
                original = run(reference, reference_out, outstanding, random, True)
                equal = current['passed'] and original['passed'] and current['cases'] == original['cases']
                comparisons.append(dict(passed=equal, current=current, reference=original))
            entry['single_segment_comparison'] = comparisons
        records.append(entry)
        if not all(r['passed'] for r in runs): break
    passed = all(all(run['passed'] for run in record['runs']) and
                 all(c['passed'] for c in record.get('single_segment_comparison', [])) for record in records)
    summary = dict(passed=passed, bus_width=args.bus_width, dma_max_bytes=args.dma_max_bytes, rtl_sha256=sha(rtl), configurations=records)
    (args.out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(args.out/'summary.json', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
