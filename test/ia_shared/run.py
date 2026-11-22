#!/usr/bin/env python3
"""Verify shared IA RAM against local synchronous RAM and an integer model."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/ia_shared')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--reuse-build', action='store_true')
    parser.add_argument('--bank-bytes',type=int,choices=(2048,4096,8192),default=2048)
    parser.add_argument('--bank-count',type=int,choices=range(6,10),default=7)
    parser.add_argument('--compact-offset-width', type=int, choices=(9, 16), default=16)
    parser.add_argument('--bus-width', type=int, choices=(32, 64), default=32)
    parser.add_argument('--dma-lanes', type=int, choices=(4, 8, 16), default=4)
    parser.add_argument('--shared-write-stage', type=int, choices=(0, 1), default=0)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    out = args.out.resolve()
    source_root = args.source_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rtl = sorted(path for path in (source_root / 'rtl/common').iterdir()
                 if path.suffix in ('.sv', '.v'))
    rtl += [source_root / 'rtl/npu/compute/select_add.sv',
            source_root / 'rtl/npu/loaders/ia_loader_cache_mgr.sv',
            source_root / 'rtl/npu/buffers/ia_ps_shared_ram.sv', HERE / 'cache_tb.sv']
    cpp = HERE / 'cache_test.cpp'
    sources = [Path(__file__).resolve(), *rtl, cpp]
    source_paths = {str(path.relative_to(source_root) if path.is_relative_to(source_root)
                        else path.relative_to(ROOT)): path for path in sources}
    hashes = {name: digest(path) for name, path in source_paths.items()}
    related_paths = {str(path): source_root / path for path in [
        Path('rtl/npu/loaders/ia_loader.sv'), Path('rtl/npu/loaders/ia_loader_ctrl.sv')]}
    related = {name: digest(path) for name, path in related_paths.items()}
    rules = out / 'compile_rules.mk'
    rules.write_text(
        '%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
        '$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
        '$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n'
        '$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n')
    top = 'ia_shared_cache_tb'
    command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-j', str(args.jobs),
               '--top-module', top, f'-GBANK_BYTES={args.bank_bytes}', f'-GBANK_COUNT={args.bank_count}',
               f'-GBUS_WIDTH={args.bus_width}', f'-GDMA_LANES={args.dma_lanes}',
               f'-GSHARED_WRITE_STAGE={args.shared_write_stage}',
               f'-GCOMPACT_OFFSET_WIDTH={args.compact_offset_width}', '--Mdir', str(out / 'obj'), '-Wno-fatal',
               '--output-groups', '0', '--output-split', '10000',
               '-CFLAGS', f'-std=c++17 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_BANK_BYTES={args.bank_bytes} -DTEST_BANK_COUNT={args.bank_count} -DTEST_DMA_LANES={args.dma_lanes}',
               '-LDFLAGS', '-fsanitize=undefined', '-MAKEFLAGS',
               f'-B OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}',
               *map(str, rtl), str(cpp)]
    binary = out / 'obj' / ('V' + top)
    start = time.monotonic()
    if args.reuse_build:
        previous = json.loads((out / 'summary.json').read_text())
        if previous['source_sha256'] != hashes or previous['binary_sha256'] != digest(binary) or previous['allocation_bank_bytes']!=args.bank_bytes or previous['physical_banks']!=args.bank_count:
            raise RuntimeError('Executable does not match the current sources')
        if previous.get('compact_offset_width', 16) != args.compact_offset_width:
            raise RuntimeError('Executable compact offset width differs')
        if previous.get('bus_width', 32) != args.bus_width or previous.get('dma_lanes', 4) != args.dma_lanes:
            raise RuntimeError('Executable input width differs')
        if previous.get('shared_write_stage', 0) != args.shared_write_stage:
            raise RuntimeError('Executable write stage differs')
        command = previous['compile_command']
    else:
        with (out / 'compile.log').open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'Compilation failed: {out / "compile.log"}')
    compile_seconds = time.monotonic() - start
    log_text = (out / 'compile.log').read_text()
    if re.search(r'%Warning-(?:WIDTH|LATCH|UNOPTFLAT)', log_text):
        raise RuntimeError('Width, latch, or combinational cycle warning in compiled RTL')
    units = [line for line in log_text.splitlines() if ' -c ' in line and ' -o ' in line]
    if not units or any('-fsanitize=undefined' not in line for line in units):
        raise RuntimeError('Undefined behavior sanitizer is missing from a translation unit')
    run_start = time.monotonic()
    result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'IA/shared RAM verification failed: {result.stdout}{result.stderr}')
    report = json.loads(result.stdout.strip().splitlines()[-1])
    if not report['passed'] or any(digest(source_paths[name]) != value for name, value in hashes.items()):
        raise RuntimeError('Failed verification or source changed during execution')
    if any(digest(related_paths[name]) != value for name, value in related.items()):
        raise RuntimeError('Related loader source changed during execution')
    report.update(source_sha256=hashes, related_source_sha256=related,
                  compiled_rtl=[str(path.relative_to(source_root) if path.is_relative_to(source_root)
                                    else path.relative_to(ROOT)) for path in rtl],
                  binary_sha256=digest(binary), compile_command=command,
                  run_command=[str(binary)], undefined_behavior_sanitizer=True,
                  compact_offset_width=args.compact_offset_width,
                  bus_width=args.bus_width, dma_lanes=args.dma_lanes,
                  shared_write_stage=args.shared_write_stage,
                  sanitized_translation_units=len(units), compile_seconds=compile_seconds,
                  run_seconds=time.monotonic() - run_start, source_hashes_unchanged=True)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ('source_sha256', 'related_source_sha256', 'compile_command')}))


if __name__ == '__main__':
    main()
