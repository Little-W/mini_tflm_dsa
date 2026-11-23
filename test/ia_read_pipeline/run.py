#!/usr/bin/env python3
"""验证固定 RAM 容量下两种编译配置的读流水线和行控制。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import input_files, with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    rtl = with_dependencies([HERE / 'tb_ia_read_pipeline.sv',
        ROOT / 'rtl/npu/loaders/ia_loader_cache_mgr.sv'], ROOT)
    inputs = input_files([Path(__file__), ROOT / 'scripts/rtl/source_files.py', *rtl], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in inputs}
    results = []
    for compact in (0, 1):
        for write_stage in (0, 1):
            case = out / f'compact_{compact}_write_{write_stage}'
            case.mkdir(parents=True, exist_ok=True)
            rules = case / 'compile_rules.mk'
            rules.write_text('%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                '$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                '$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n'
                '$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n')
            command = ['verilator' , '--binary', '--timing', '--assert', '-j', '1',
                '--top-module', 'tb_ia_read_pipeline', '--Mdir', str(case / 'obj'),
                f'-GCOMPACT_ENABLE={compact}', f'-GSHARED_WRITE_STAGE={write_stage}',
                '-Wno-fatal', '--output-groups', '0', '--output-split', '10000',
                '-CFLAGS', '-std=c++20 -O0 -fsanitize=undefined -fno-sanitize-recover=all',
                '-LDFLAGS', '-fsanitize=undefined', '-MAKEFLAGS',
                f'OPT_FAST=-O0 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}', *map(str, rtl)]
            with (case / 'compile.log').open('w') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError('Compilation failed: ' + str(case / 'compile.log'))
            binary = case / 'obj/Vtb_ia_read_pipeline'
            result = subprocess.run([str(binary)], text=True, capture_output=True, cwd=ROOT)
            (case / 'run.log').write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(str(case / 'run.log') + '\n' + result.stdout + result.stderr)
            report = next(json.loads(line) for line in result.stdout.splitlines() if line.startswith('{'))
            if not report['passed']:
                raise RuntimeError('Failed assertions: ' + str(case))
            report.update(compile_command=command, binary_sha256=digest(binary),
                run_log_sha256=digest(case / 'run.log'))
            results.append(report)
            print(json.dumps({key: value for key, value in report.items() if key != 'compile_command'}), flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in inputs}:
        raise RuntimeError('Sources changed during validation')
    (out / 'summary.json').write_text(json.dumps(dict(passed=True, source_sha256=hashes, cases=results), indent=2) + '\n')


if __name__ == '__main__':
    main()
