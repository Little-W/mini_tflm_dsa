#!/usr/bin/env python3
"""验证寄存请求下的预取、缓存复用、取消和持续授予。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--ordered-job', action='store_true')
    parser.add_argument('--fpga', action='store_true')
    args = parser.parse_args()
    source = args.source_root.resolve()
    verilator_root = Path(subprocess.check_output(
        [args.verilator, "--getenv", "VERILATOR_ROOT"], text=True).strip())
    runtime_include = "-isystem " + shlex.quote(str(verilator_root / "include"))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rtl = sorted(path for path in (source / 'rtl/common').iterdir()
                 if path.suffix in ('.sv', '.v'))
    rtl += [source / 'rtl/npu/compute/select_add.sv']
    rtl += [source / ('rtl/npu/loaders/' + name + '.sv')
            for name in ('ia_ordered_coordinate_equal', 'ia_ordered_coordinate_same', 'ia_loader_cache_mgr', 'ia_loader_ctrl', 'ia_loader')]
    rtl += [HERE / 'ia_tb.sv', ROOT / 'test/common/ia_shared_ram_model.sv',
            ROOT / 'test/ia_request_stage/request_observer.sv']
    cpp = HERE / 'ia_test.cpp'
    inputs = [Path(__file__), *rtl, cpp]
    hashes = {str(path): digest(path) for path in inputs}
    rules = out / 'compile_rules.mk'
    rules.write_text('%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
                     '$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(filter-out -Wall -Wextra -Werror,$(CXXFLAGS) $(CPPFLAGS)) $(OPT_FAST) -c -o $@ $<\n'
                     '$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(filter-out -Wall -Wextra -Werror,$(CXXFLAGS) $(CPPFLAGS)) $(OPT_SLOW) -c -o $@ $<\n'
                     '$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(filter-out -Wall -Wextra -Werror,$(CXXFLAGS) $(CPPFLAGS)) $(OPT_GLOBAL) -c -o $@ $<\n')
    flags = []
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        library_text = library.read_text()
        names = ('LUT1', 'LUT2', 'LUT3', 'LUT4', 'LUT5', 'LUT6', 'LUT6_2',
                 'MUXF7', 'MUXF8', 'DSP48E1', 'FDRE', 'CARRY4')
        models = [re.search(r'^module ' + name + r'\b.*?^endmodule', library_text,
                            re.MULTILINE | re.DOTALL).group(0) for name in names]
        model = out / 'xilinx_primitives.sv'
        model.write_text('\n\n'.join(models) + '\n')
        flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', str(model)]
    command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-j', '1',
               '--top-module', 'ia_prefetch_tb', '--Mdir', str(out / 'obj'), '-Wno-fatal',
               '--output-groups', '0', '--output-split', '10000',
               '-CFLAGS', '-std=c++17 -O1 -Wall -Wextra -Werror -fsanitize=undefined -fno-sanitize-recover=all ' + runtime_include,
               '-LDFLAGS', '-fsanitize=undefined', '-MAKEFLAGS',
               f'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}',
               *flags, *map(str, rtl), str(cpp)]
    if args.ordered_job:
        command.insert(1, '-GORDERED_JOB=1')
        command[command.index('-CFLAGS') + 1] += ' -DORDERED_JOB_TEST'
    started = time.monotonic()
    with (out / 'compile.log').open('w') as log:
        result = subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Compilation failed: ' + str(out / 'compile.log'))
    binary = out / 'obj/Via_prefetch_tb'
    report = dict(passed=False, source_sha256=hashes, binary_sha256=digest(binary),
                  compile_command=command, ordered_job=args.ordered_job, fpga=args.fpga, runs=[])
    for mode, arguments in (('blocked', []), ('sustained', ['--sustained-grant'])):
        result = subprocess.run([str(binary), *arguments], text=True, capture_output=True, cwd=source)
        log = out / (mode + '.log')
        log.write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(str(log) + '\n' + result.stdout + result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        if len(rows) != 1 or not rows[0]['passed'] or not rows[0]['cancelled_requests']:
            raise RuntimeError('Missing protocol coverage: ' + str(log))
        row = rows[0]
        row.update(mode=mode, log_sha256=digest(log))
        report['runs'].append(row)
    if hashes != {str(path): digest(path) for path in inputs}:
        raise RuntimeError('Source changed during request-stage validation')
    report.update(passed=True, elapsed_seconds=time.monotonic() - started)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'ordered_job', 'fpga', 'runs')}))


if __name__ == '__main__':
    main()
