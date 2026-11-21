#!/usr/bin/env python3
"""使用独立卷积数值及握手检查验证前端的可变请求延迟。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys

from compare_frontend import ROOT, TEST_ROOT, HERE, reviewed_warnings, run, widen_memory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default=shutil.which('verilator') or 'verilator')
    parser.add_argument('--lanes', type=int, nargs='+', choices=(1, 2, 4, 8, 16), default=[8])
    parser.add_argument('--sizes', type=int, nargs='+', choices=(4, 8, 16), default=[4, 8, 16])
    parser.add_argument('--cache-sets', type=int, default=16)
    parser.add_argument('--line-bytes', type=int, default=128)
    parser.add_argument('--fpga', action='store_true')
    parser.add_argument('--synthesis', action='store_true')
    parser.add_argument('--register-descriptor', type=int, choices=(0, 1))
    parser.add_argument('--admission', choices=('finish', 'idle'),
                        help='持续请求的接收阶段；直接模式默认为 finish，寄存模式默认为 idle')
    parser.add_argument('--window', type=int, choices=(0, 1))
    parser.add_argument('--skip-control', action='store_true')
    parser.add_argument('--fixed-ready', action='store_true')
    parser.add_argument('--continuous', action='store_true',
                        help='持续提供描述符并检查输出顺序、完成次数和在途容量')
    args = parser.parse_args()
    if args.admission is None:
        args.admission = 'finish' if args.register_descriptor == 0 else 'idle'
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [Path(p) for p in runpy.run_path(str(HERE / 'run_rtl.py'))['FILES']
               if not str(p).startswith('tests/')]
    sources = [root / p.relative_to(ROOT) if p.is_relative_to(ROOT) and
               p.relative_to(ROOT).parts[0] == 'rtl' else p for p in sources]
    if args.synthesis:
        monitor_root=out / 'synthesis_monitors'
        monitor_root.mkdir(exist_ok=True)
        for index, path in enumerate(sources):
            if path.is_relative_to(ROOT / 'test/monitors'):
                monitor=monitor_root / path.name
                monitor.write_text('`undef SYNTHESIS\n' + path.read_text() + '\n`define SYNTHESIS 1\n')
                sources[index]=monitor
    benches = {}
    for name in ('tb_conv_im2col_frontend', 'tb_conv_control'):
        p = out / (name + '.sv')
        bench = widen_memory((TEST_ROOT / 'tests' / (name + '.sv')).read_text())
        if args.continuous and name == 'tb_conv_im2col_frontend':
            from continuous_frontend import continuous_bench
            bench = continuous_bench(bench, admission=args.admission)
        if args.fixed_ready and name=='tb_conv_im2col_frontend':
            bench=bench.replace('wr_ready<=USE_TILE_PATH || lfsr[5] || lfsr[9];', "wr_ready<=1'b1;")
            bench=bench.replace('arready<=!mem_active && (lfsr[0] || lfsr[3]);', 'arready<=!mem_active;')
            bench=bench.replace('mem_active && !rvalid && lfsr[2]', 'mem_active && !rvalid')
        if args.register_descriptor is not None:
            bench=bench.replace('conv_im2col_frontend #(', 'conv_im2col_frontend #(.REGISTER_DESCRIPTOR(1\'b' + str(args.register_descriptor) + '),', 1)
        p.write_text(bench)
        benches[name] = p
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sources, *benches.values()]}
    options = ['--binary', '--timing', '--assert', '-DNPU_SIM_ASSERT', '-DCONV_ASSERT', '-Wno-fatal',
               '--output-groups', '0', '--output-split', '12000', '-CFLAGS', '-std=c++20 -O1',
               '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E']
    if args.fpga:
        options.append('-DXILINX_FPGA=1')
    if args.synthesis:
        options.append('-DSYNTHESIS=1')
    results = []
    cases = [(size, bus, lanes, window) for lanes in args.lanes
             for size, bus, window in ((4, 32, 0), (8, 64, 0), (16, 64, 0), (16, 64, 1))
             if size in args.sizes and (args.window is None or window==args.window)]
    for size, bus, lanes, window in cases:
        case = out / f's{size}_b{bus}_l{lanes}_window{window}'
        case.mkdir(exist_ok=True)
        top = 'tb_conv_im2col_frontend'
        vectors = case / 'vectors.txt'
        run([sys.executable, TEST_ROOT / 'tests/gen_rtl_vectors.py', '--size', size,
             '--out', vectors], case / 'vectors.log')
        run([args.verilator, *options, '--top-module', top, f'-GSIZE={size}', f'-GBUS_WIDTH={bus}',
             f'-GLANES={lanes}', f'-GCACHE_SETS={args.cache_sets}', f'-GLINE_BYTES={args.line_bytes}',
             '-GNARROW_MODE=2', f"-GWINDOWED=1'b{window}", f"-GPREFETCH=1'b{window}",
             '--Mdir', case / 'obj', '-j', '1', *sources, benches[top]], case / 'build.log')
        warnings = reviewed_warnings(case / 'build.log')
        run([case / 'obj' / ('V' + top), f'+VECTORS={vectors}'], case / 'run.log')
        text = (case / 'run.log').read_text()
        assert 'RTL_FRONTEND_PASS' in text, case
        if args.continuous:
            assert 'FRONTEND_CONTINUOUS_PASS' in text, case
        results.append({'size': size, 'bus_width': bus, 'lanes': lanes, 'windowed': bool(window),
                        'passed': True, 'warnings': warnings,
                        'summary': [x for x in text.splitlines()
                                    if x.startswith(('RTL_FRONTEND_PASS', 'FRONTEND_CONTINUOUS_PASS'))],
                        'jobs': [x for x in text.splitlines() if x.startswith('RTL_FRONTEND_JOB_PASS')]})
        print(results[-1]['summary'], flush=True)
        for temporary in (case / 'obj').iterdir():
            if temporary.suffix in ('.o', '.a', '.gch'):
                temporary.unlink()
    if not args.skip_control:
        case = out / 'control'
        case.mkdir(exist_ok=True)
        top = 'tb_conv_control'
        run([args.verilator, *options, '--top-module', top, '--Mdir', case / 'obj', '-j', '1',
             *sources, benches[top]], case / 'build.log')
        warnings = reviewed_warnings(case / 'build.log')
        run([case / 'obj' / ('V' + top)], case / 'run.log')
        text = (case / 'run.log').read_text()
        assert 'RTL_CONTROL_PASS' in text
        results.append({'control': True, 'passed': True, 'warnings': warnings,
                        'summary': [x for x in text.splitlines() if x.startswith('RTL_CONTROL_PASS')]})
        for temporary in (case / 'obj').iterdir():
            if temporary.suffix in ('.o', '.a', '.gch'):
                temporary.unlink()
    for path, digest in hashes.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    summary = {'passed': True, 'mode': 'independent numerical and handshake validation',
               'cache_sets': args.cache_sets, 'line_bytes': args.line_bytes, 'xilinx_fpga': args.fpga,
               'continuous_descriptors': args.continuous, 'synthesis': args.synthesis,
               'register_descriptor': args.register_descriptor, 'admission': args.admission,
               'fixed_ready': args.fixed_ready,
               'source_sha256': hashes, 'configurations': results}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('FRONTEND_NUMERIC_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
