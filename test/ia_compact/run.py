#!/usr/bin/env python3
"""验证共享 IA 存储端口的数据格式及分组加载控制。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts/rtl"))
from source_files import input_files, with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/ia_compact/unit')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--only', choices=['cache', 'loader'])
    parser.add_argument('--reuse-build', action='store_true')
    parser.add_argument('--loader-cache-blocks',type=int,choices=(4,16,32,64),default=4)
    args = parser.parse_args()
    out = args.out.resolve()
    common = [ROOT / 'rtl/common/regfile.v', ROOT / 'rtl/common/pseudo_dual_port_ram.v',
              ROOT / 'rtl/npu/loaders/ia_loader_cache_mgr.sv',
              ROOT / 'test/common/ia_shared_ram_model.sv']
    targets = {
        'cache': ('ia_compact_cache_tb', common + [HERE / 'cache_tb.sv'], HERE / 'cache_test.cpp'),
        'loader': ('ia_compact_loader_tb', common + [
            ROOT / 'rtl/common/add_equal.sv',
            ROOT / 'rtl/npu/loaders/ia_loader.sv', ROOT / 'rtl/npu/loaders/ia_loader_ctrl.sv',
            HERE / 'loader_tb.sv'], HERE / 'loader_test.cpp'),
    }
    results = {}
    for name, (top, rtl, cpp) in targets.items():
        if args.only and args.only != name:
            continue
        target = out / name
        target.mkdir(parents=True, exist_ok=True)
        rtl = with_dependencies(rtl, ROOT)
        sources = input_files([Path(__file__).resolve(), ROOT / "scripts/rtl/source_files.py", *rtl, cpp], ROOT)
        hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
        rules = target / 'compile_rules.mk'
        rules.write_text('%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                         '$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                         '$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n'
                         '$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n')
        command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-j', '1',
                   '--top-module', top, '--Mdir', str(target / 'obj'), '-Wno-fatal',
                   '--output-groups', '0', '--output-split', '10000',
                   '-CFLAGS', f'-std=c++17 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_CACHE_BLOCKS={args.loader_cache_blocks}',
                   '-LDFLAGS', '-fsanitize=undefined', '-MAKEFLAGS',
                   f'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}',
                   *map(str, rtl), str(cpp)]
        if name=='loader':command.insert(1,f'-GCACHE_BLOCKS={args.loader_cache_blocks}')
        binary = target / 'obj' / ('V' + top)
        if args.reuse_build:
            old = json.loads((target / 'summary.json').read_text())
            if old['source_sha256'] != hashes or old['binary_sha256'] != digest(binary):
                raise RuntimeError(f'{name}: executable does not match current sources')
            if name=='loader' and old.get('cache_blocks')!=args.loader_cache_blocks:
                raise RuntimeError('loader: executable capacity differs')
            command = old['compile_command']
        else:
            with (target / 'compile.log').open('w') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f'{name}: compilation failed; see {target / "compile.log"}')
        result = subprocess.run([str(binary)], text=True, capture_output=True, cwd=ROOT)
        (target / 'run.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{name}: {result.stdout}{result.stderr}')
        report = json.loads(result.stdout.strip().splitlines()[-1])
        if not report['passed'] or any(digest(ROOT / p) != h for p, h in hashes.items()):
            raise RuntimeError(f'{name}: failed checks or changed source')
        units = [s for s in (target / 'compile.log').read_text().splitlines()
                 if ' -c ' in s and ' -o ' in s]
        if not units or any('-fsanitize=undefined' not in s for s in units):
            raise RuntimeError(f'{name}: missing undefined behavior sanitizer')
        report.update(source_sha256=hashes, binary_sha256=digest(binary),
                      cache_blocks=args.loader_cache_blocks if name=='loader' else 4,
                      compile_command=command, run_command=[str(binary)],
                      undefined_behavior_sanitizer=True, sanitized_translation_units=len(units))
        (target / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        results[name] = report
        print(json.dumps({'target': name, **{k: v for k, v in report.items()
                                           if k not in ('source_sha256', 'compile_command')}}), flush=True)
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'tests': results}, indent=2) + '\n')


if __name__ == '__main__':
    main()
