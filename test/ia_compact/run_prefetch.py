#!/usr/bin/env python3
"""Verify whole-group IA prefetch with concurrent cache reuse and exact DMA tags."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/ia_prefetch/concurrent')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--reuse-build', action='store_true')
    parser.add_argument('--ordered-job', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rtl = [ROOT / 'rtl/common/REGFILE.v', ROOT / 'rtl/common/pseudo_dual_port_ram.v',
           ROOT / 'rtl/common/add_equal.sv',
           ROOT / 'rtl/npu/loaders/ia_loader_cache_mgr.sv',
           ROOT / 'rtl/npu/loaders/ia_loader_ctrl.sv',
           ROOT / 'rtl/npu/loaders/ia_loader.sv', HERE / 'prefetch_tb.sv']
    cpp = HERE / 'prefetch_test.cpp'
    sources = [Path(__file__).resolve(), *rtl, cpp]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    rules = out / 'compile_rules.mk'
    rules.write_text('%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                     '$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                     '$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n'
                     '$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n')
    command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-j', '1',
               '--top-module', 'ia_prefetch_tb', '--Mdir', str(out / 'obj'), '-Wno-fatal',
               '--output-groups', '0', '--output-split', '10000',
               '-CFLAGS', '-std=c++17 -O1 -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all',
               '-LDFLAGS', '-fsanitize=undefined', '-MAKEFLAGS',
               f'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}',
               *map(str, rtl), str(cpp)]
    if args.ordered_job:
        command.insert(1, '-GORDERED_JOB=1')
        command[command.index('-CFLAGS') + 1] += ' -DORDERED_JOB_TEST'
    binary = out / 'obj/Via_prefetch_tb'
    started = time.monotonic()
    if args.reuse_build:
        old = json.loads((out / 'summary.json').read_text())
        if old['source_sha256'] != hashes or old['binary_sha256'] != digest(binary):
            raise RuntimeError('executable does not match current sources')
        command = old['compile_command']
    else:
        with (out / 'compile.log').open('w') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'compilation failed; see {out / "compile.log"}')
    run_command = [str(binary)]
    result = subprocess.run(run_command, text=True, capture_output=True, cwd=ROOT)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    report = json.loads(result.stdout.strip().splitlines()[-1])
    if not report['passed'] or any(digest(ROOT / path) != sha for path, sha in hashes.items()):
        raise RuntimeError('failed checks or changed sources')
    units = [line for line in (out / 'compile.log').read_text().splitlines()
             if ' -c ' in line and ' -o ' in line]
    if not units or any('-fsanitize=undefined' not in line for line in units):
        raise RuntimeError('missing undefined behavior sanitizer')
    report.update(source_sha256=hashes, binary_sha256=digest(binary),
                  compile_command=command, run_command=run_command,
                  undefined_behavior_sanitizer=True, sanitized_translation_units=len(units),
                  elapsed_seconds=time.monotonic() - started)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ('compile_command', 'source_sha256')}))


if __name__ == '__main__':
    main()
