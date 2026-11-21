#!/usr/bin/env python3
"""Run the SystemVerilog compute-core test against production RTL."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/compute_core')
    parser.add_argument('--sizes', type=int, nargs='+', default=[4, 8, 16])
    parser.add_argument('--k', type=int)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    if args.jobs < 1 or any(size not in (4, 8, 16) for size in args.sizes):
        parser.error('--jobs must be positive and --sizes must use 4, 8, or 16')
    if args.k is not None and args.k < 1:
        parser.error('--k must be positive')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [HERE / 'tb_compute_core_if.sv', HERE / 'compute_core_test.sv',
               HERE / 'tb_compute_core.sv', ROOT / 'rtl/npu/compute/compute_core.sv',
               ROOT / 'rtl/npu/compute/bias_mux.sv', ROOT / 'rtl/npu/buffers/ps_buffer.sv',
               ROOT / 'rtl/common/pseudo_dual_port_ram.v',
               ROOT / 'rtl/common/regfile.v',
               ROOT / 'rtl/common/parallel_prefix_add.sv',
               ROOT / 'rtl/npu/compute/ws_systolic_array.sv',
               ROOT / 'rtl/npu/compute/ws_systolic_cell.sv',
               ROOT / 'rtl/npu/ps_compact/ps_adaptive_codec.sv',
               ROOT / 'rtl/npu/ps_compact/ps_frame_store.sv']
    recorded = [Path(__file__).resolve(), HERE / 'gen_mats.py', ROOT / 'Makefile', *sources]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in recorded}
    results, builds = [], []
    for size in args.sizes:
        k = args.k if args.k is not None else 3 * size + 3
        for compressed in ([False, True] if size == 16 else [False]):
            directory = out / f'size{size}_k{k}_{"codec" if compressed else "fifo"}'
            directory.mkdir(parents=True, exist_ok=True)
            data = directory / 'data'
            data.mkdir(exist_ok=True)
            generate = [os.sys.executable, str(HERE / 'gen_mats.py'), '--size', str(size),
                        '--k', str(k), '--seed', str(args.seed)]
            subprocess.run(generate, cwd=data, check=True, capture_output=True, text=True)
            command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
                       '--top-module', 'tb_compute_core', '--Mdir', str(directory / 'obj'),
                       '--output-split', '10000', '-j', str(args.jobs),
                       '-CFLAGS', '-O0', '-I' + str(ROOT / 'rtl/npu/ps_compact')]
            if compressed:
                command.append('-DGEMPACT_PS_COMPRESS')
            command += [str(data / 'test_params_pkg.sv'), *map(str, sources)]
            with (directory / 'compile.log').open('w') as log:
                build = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            if build.returncode:
                raise RuntimeError(f'Compilation failed: {directory / "compile.log"}')
            binary = directory / 'obj/Vtb_compute_core'
            builds.append(dict(size=size, k=k, compressed_store=compressed, command=command,
                               binary=str(binary), binary_sha256=digest(binary),
                               generated_package_sha256=digest(data / 'test_params_pkg.sv')))
            for raw in ((0, 1) if compressed else (1,)):
                run_command = [str(binary), '+DATA_DIR=' + str(data), f'+PS_FORCE_RAW={raw}']
                run = subprocess.run(run_command, cwd=directory, capture_output=True, text=True, timeout=120)
                log = directory / f'run_raw{raw}.log'
                log.write_text(run.stdout + run.stderr)
                if run.returncode or 'PASS: compute_core matched' not in run.stdout:
                    raise RuntimeError(f'Compute-core test failed: {log}')
                match = re.search(r'COMPUTE_CORE_RESULT (\{[^\n]+\})', run.stdout)
                if not match:
                    raise RuntimeError(f'Missing comparison counts: {log}')
                result = json.loads(match.group(1))
                result.update(passed=True, command=run_command, log=str(log), log_sha256=digest(log))
                results.append(result)
                print(json.dumps({key: result[key] for key in ('passed', 'size', 'k', 'compressed_store',
                                                               'force_raw', 'partial_values', 'replay_values', 'output_values')}), flush=True)
    for name, value in hashes.items():
        if digest(ROOT / name) != value:
            raise RuntimeError(f'Source changed during verification: {name}')
    report = dict(passed=True, sources_unchanged=True, source_sha256=hashes,
                  builds=builds, results=results, cases=len(results),
                  partial_values=sum(row['partial_values'] for row in results),
                  replay_values=sum(row['replay_values'] for row in results),
                  output_values=sum(row['output_values'] for row in results))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'cases', 'partial_values', 'replay_values', 'output_values')}))


if __name__ == '__main__':
    main()
