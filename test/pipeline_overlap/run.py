#!/usr/bin/env python3
"""Verify overlapping kernel loads, PS replay, and WS/IS execution with real outputs."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--build', type=Path, help='Reuse an existing run_mini.py simulator build directory')
    parser.add_argument('--verilator', default=os.environ.get('VERILATOR', 'verilator'))
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--bus-width', type=int, choices=(32, 64), default=64)
    parser.add_argument('--first-read-latency', type=int, default=8)
    args = parser.parse_args()
    if args.first_read_latency < 1:
        parser.error('First read latency must be positive')
    repo, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(repo / 'test/gemmini_comparison'))
    import run_mini as common
    import prepare as inputs
    runner = common.load_runner(repo)
    profile = SimpleNamespace(verilator=args.verilator, jobs=args.jobs,
        ia_cache_blocks=8, ps_frames=16, ps_storage_rows=720, s16_output_banks=4,
        cache_sets=128, cache_policy=3, bus_width=args.bus_width,
        dma_max_bytes=256*(args.bus_width//8), read_beat_cycles=1,
        first_read_latency=args.first_read_latency, memory_timing='pipelined')
    build = args.build.resolve() if args.build else out / 'sim'
    if args.build:
        manifest = json.loads((build / 'build.json').read_text())
        if manifest.get('returncode') != 0 or not manifest.get('sources_unchanged_during_build'):
            raise ValueError('Reused simulator build did not complete with stable sources')
        for key in ('bus_width', 'dma_max_bytes', 'read_beat_cycles',
                    'first_read_latency', 'memory_timing', 'ia_cache_blocks',
                    'ps_frames', 'ps_storage_rows', 'cache_sets', 'cache_policy'):
            if manifest.get(key) != getattr(profile, key):
                raise ValueError(f'Reused simulator has different {key}')
        if manifest.get('s16_output_banks_max') != profile.s16_output_banks:
            raise ValueError('Reused simulator has different INT16 output storage')
        for name, digest in manifest['source_sha256'].items():
            if common.sha256(repo / name) != digest:
                raise ValueError(f'Reused simulator source differs: {name}')
        binary = build / 'obj/Vtb_conv_npu'
    else:
        binary = common.build_comparison(runner, repo, build, profile)

    tasks = []
    shapes = [(1, 1, 65), (1, 3, 33), (3, 1, 33), (17, 17, 33),
              (1, 17, 64), (17, 1, 64), (3, 7, 15), (17, 5, 17)]
    for index, (rows, columns, depth) in enumerate(shapes):
        name = f'm{rows}_n{columns}_k{depth}'
        inputs.case(out / 'workloads', name, rows, columns, depth,
                    {'operator': 'directed_gemm'}, 9133 + index)
        for flow in ('ws', 'is'):
            for layout in ('row-major', 'both-packed'):
                directory = out / 'cases' / f'{name}_{flow}_{layout}'
                common.prepare_case(runner, out / 'workloads' / name, directory,
                    8, 16, 720, schedule_mode='auto', dataflow=flow, layout=layout,
                    requested_r=1, requested_w=1, s16_output_banks=4,
                    dma_max_bytes=profile.dma_max_bytes, bus_width=args.bus_width,
                    read_beat_cycles=1)
                tasks.append(directory)

    reference = runner.make_reference(out)
    parameters = []
    for flow in (0, 1):
        parameters.append(runner.task(out, 16, reference,
            name=f'conv_channel_tail_{flow}', co=17, dataflow=flow,
            input_base=0x10FFD, rhs_base=0x20FFF, seed=701+flow))
        parameters.append(runner.gemm_task(out, 16,
            name=f'gemm_channel_tail_{flow}', dataflow=flow))
    runs = []
    for label, selected in (('directed', tasks), ('parameter', parameters)):
        for fixed in (True, False):
            name = label + ('_fixed' if fixed else '_random')
            with (out / (name + '_runner.log')).open('w') as stream:
                with contextlib.redirect_stdout(stream):
                    runs.append(runner.run_suite(binary, out, name, selected, fixed))
            print(json.dumps({'name': name, 'passed': runs[-1]['passed'],
                              'tasks': len(selected)}), flush=True)
            if not runs[-1]['passed']:
                break
        if not runs[-1]['passed']:
            break

    buffer_dir = out / 'kernel_buffer'
    buffer_rtl = repo / 'rtl/npu/loaders/kernel_loader_buffer.sv'
    regfile_rtl = repo / 'rtl/common/regfile.v'
    buffer_tb = Path(__file__).resolve().with_name('tb_kernel_prefetch.sv')
    buffer_command = [args.verilator, '--binary', '--timing', '--assert', '-sv',
        '--top-module', 'tb_kernel_prefetch', '-Wno-fatal', '--Mdir', buffer_dir/'obj',
        '-j', args.jobs, buffer_rtl, regfile_rtl, buffer_tb]
    buffer_returncode = runner.command(buffer_command, buffer_dir/'compile.log')
    buffer_binary = buffer_dir/'obj/Vtb_kernel_prefetch'
    if buffer_returncode == 0:
        buffer_returncode = runner.command([buffer_binary], buffer_dir/'run.log')
    buffer_passed = (buffer_returncode == 0 and
        'KERNEL_PREFETCH_PASS' in (buffer_dir/'run.log').read_text())
    result = {'passed': all(run['passed'] for run in runs) and buffer_passed,
        'build_manifest': str(build/'build.json'),
        'build_manifest_sha256': common.sha256(build/'build.json'),
        'binary_sha256': common.sha256(binary),
        'runs': runs, 'kernel_buffer': {'passed': buffer_passed,
            'returncode': buffer_returncode,
            'source_sha256': {str(buffer_rtl): common.sha256(buffer_rtl),
                              str(regfile_rtl): common.sha256(regfile_rtl),
                              str(buffer_tb): common.sha256(buffer_tb)}}}
    (out/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': result['passed'], 'summary': str(out/'summary.json')}, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
