#!/usr/bin/env python3
"""比较计算核心输出寄存前后的数据、分组完成和部分和接口。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CORE = Path('rtl/npu/compute/compute_core.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log, *, cwd=ROOT):
    with log.open('w') as stream:
        subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a')
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--sizes', type=int, nargs='+', default=[2, 3, 4, 16])
    parser.add_argument('--cycles', type=int, default=4096)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'compute_core_reference.sv'
    reference_bytes = read_rtl_source(f'{args.reference}:{CORE}', cwd=ROOT)
    reference.write_text(re.sub(r'\bmodule compute_core\b', 'module compute_core_reference',
                               reference_bytes.decode(), count=1))
    sources = [ROOT / CORE, ROOT / 'rtl/npu/compute/bias_mux.sv',
               ROOT / 'rtl/npu/compute/ws_systolic_array.sv',
               ROOT / 'rtl/npu/compute/ws_systolic_cell.sv',
               ROOT / 'rtl/npu/buffers/ps_buffer.sv', ROOT / 'rtl/common/regfile.v',
               HERE / 'tb.sv', Path(__file__).resolve()]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    reports = []
    for size in args.sizes:
        directory = out / f'size{size}'
        directory.mkdir(exist_ok=True)
        obj = directory / 'obj'
        command = [args.verilator, '--binary', '--timing', '--assert', '--build-jobs', '1',
                   '-Wno-fatal', '--top-module', 'compute_output_pipeline_tb',
                   '--Mdir', str(obj), '--output-groups', '0', '--output-split', '10000',
                   '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
                   f'-GSIZE={size}', f'-GCYCLES={args.cycles}',
                   *map(str, sources[:-1]), str(reference)]
        start = time.monotonic()
        execute(command, directory / 'compile.log')
        binary = obj / 'Vcompute_output_pipeline_tb'
        execute([str(binary)], directory / 'run.log')
        text = (directory / 'run.log').read_text()
        report = json.loads(next(line for line in text.splitlines() if line.startswith('{')))
        report.update(compile_command=command, binary_sha256=digest(binary),
                      elapsed_seconds=round(time.monotonic()-start, 3))
        saved_binary = directory / 'run_test'
        shutil.copy2(binary, saved_binary)
        report['run_command'] = [str(saved_binary)]
        (directory / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        shutil.rmtree(obj)
        reports.append(report)
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('compile_command', 'run_command')}), flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('Source changed during comparison')
    summary = dict(passed=all(report['passed'] for report in reports),
                   reference=args.reference, reference_sha256=hashlib.sha256(reference_bytes).hexdigest(),
                   source_sha256=hashes, sources_unchanged=True,
                   output_latency_cycles=1, final_completion_latency_cycles=1,
                   intermediate_completion_latency_cycles=0,
                   checked_values=sum(report['checked_values'] for report in reports),
                   runs=reports)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
