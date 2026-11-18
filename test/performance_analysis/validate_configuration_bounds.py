#!/usr/bin/env python3
"""Validate AXI DMA limits and unified NPU shared-RAM configurations."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import time


BUS_WIDTHS = (32, 64)
BANK_BYTES = (2048, 4096, 8192)
BANK_COUNTS = (6, 7, 8, 9)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def segment_checks(scope, bus_width, dma_bytes):
    beat_bytes = bus_width // 8
    beats = dma_bytes // beat_bytes
    lines = [f"assert({scope}.BUS_WIDTH=={bus_width});",
             f"assert({scope}.DMA_MAX_BYTES=={dma_bytes});"]
    for function in ("read_segment_beats", "write_segment_beats"):
        for address, remaining, expected in (
            (0x1000, 256, beats),
            (0x1000, 1, 1),
            (0x2000-beat_bytes, 256, 1),
            (0x2000-2*beat_bytes, 256, min(2, beats)),
        ):
            lines.append(f"assert({scope}.{function}(32'h{address:08x},9'd{remaining})=={expected});")
    return lines


def unified_testbench(bus_width):
    cases = [dict(bank_bytes=size, bank_count=count, shared=True)
             for size in BANK_BYTES for count in BANK_COUNTS]
    cases += [dict(bank_bytes=size, bank_count=7, frames=1, shared=True)
              for size in BANK_BYTES]
    cases += [dict(bank_bytes=size, bank_count=count, shared=False)
              for size, count in ((512, 7), (1536, 7), (1024, 7), (2048, 5), (2048, 10))]
    cases += [dict(bank_bytes=2048, bank_count=7, total_bytes=14337, shared=False)]
    instances, checks = [], []
    for index, case in enumerate(cases):
        size, count, enabled = case['bank_bytes'], case['bank_count'], case['shared']
        frames = case.get('frames', 16)
        max_ia_banks = 4 if count >= 8 else 2
        output_banks = max(min(frames*2, 32), max_ia_banks*size//512 if enabled else 1)
        total = case.get('total_bytes', size * count)
        scope = f'n{index}'
        core = scope + '.u_npu_top'
        arbiter = core + '.u_block_dma_arbiter'
        dma = arbiter + '.u_dma'
        frontend = dma + '.g_im2col.u_frontend'
        register = scope + '.u_npu_axil_reg_if'
        pool = core + '.u_compute_core.u_ps_buffer.g_compressed.u_store'
        total_override = f',.SHARED_TOTAL_BYTES({total})' if 'total_bytes' in case else ''
        instances.append(
            f"npu_axil_top #(.BUS_WIDTH({bus_width}),.DMA_MAX_BYTES(16),"
            f".PS_FRAME_COUNT({frames}),.SHARED_BANK_BYTES({size}),.SHARED_BANK_COUNT({count}){total_override}) "
            f"{scope}(.clk(1'b0),.rst_n(1'b0));")
        checks += [f"assert({scope}.SHARED_CAPABLE==1'b{int(enabled)});",
                   f"assert({register}.SHARED_CAPABLE==1'b{int(enabled)});",
                   f"assert({core}.SHARED_RAM_ENABLED==1'b{int(enabled)});",
                   f"assert({core}.BUS_WIDTH=={bus_width});",
                   f"assert({core}.SHARED_BANK_BYTES=={size});",
                   f"assert({core}.SHARED_TOTAL_BYTES=={total});",
                   f"assert({register}.AXI_DATA_BITS=={bus_width});",
                   f"assert({core}.OA_FIFO_BANKS=={output_banks});",
                   f"assert({scope}.MATRIX_S8_BANKS=={output_banks});",
                   f"assert({register}.MATRIX_S8_BANKS=={output_banks});",
                   f"assert({register}.DMA_MAX_BYTES==16);"]
        for component in (arbiter, dma, frontend, frontend+'.u_cache',
                          frontend+'.u_cache.g_window.u_window',
                          frontend+'.u_cache.g_window.u_window.u_span'):
            checks += [f"assert({component}.DMA_MAX_BYTES==16);",
                       f"assert({component}.BUS_WIDTH=={bus_width});"]
        checks += segment_checks(dma+'.u_linear', bus_width, 16)
        if enabled:
            ram = core + '.g_shared_ia_ps.u_ram'
            checks += [f"assert({register}.SHARED_TOTAL_BYTES=={total});",
                       f"assert({register}.SHARED_BANK_BYTES=={size});",
                       f"assert({register}.SHARED_IA_BANK_MASK==32'h{0x16 if count >= 8 else 0x6:x});",
                       f"assert({register}.PS_DIRECTORY_ROWS==1024);",
                       f"assert({ram}.BANK_BYTES=={size});",
                       f"assert({ram}.TOTAL_BYTES=={total});",
                       f"assert({ram}.BANKS=={count});",
                       f"assert({ram}.ROWS=={size//16});",
                       f"assert({core}.IA_MAX_CACHE_BLOCKS=={max_ia_banks*size//512});",
                       f"assert({pool}.EXTERNAL_RAM==1);",
                       f"assert({pool}.POOL_BYTES=={total-size});",
                       f"assert({pool}.BANK_BYTES=={size});",
                       f"assert({pool}.BANKS=={count-1});",
                       f"assert({pool}.BANK_DEPTH=={size//16});",
                       f"assert({pool}.DIRECTORY_ROWS==1024);"]
        else:
            checks += [f"assert({register}.SHARED_TOTAL_BYTES==0);",
                       f"assert({register}.SHARED_BANK_BYTES==0);",
                       f"assert({register}.SHARED_IA_BANK_MASK==0);",
                       f"assert({register}.PS_DIRECTORY_ROWS==0);"]
    source = ('module parameter_test(output logic passed);\n' + '\n'.join(instances) +
              '\ninitial begin\n' + '\n'.join(checks) + '\npassed=1;\nend\nendmodule\n')
    return source, cases, len(checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2],
                        help='Source repository to validate (default: this repository)')
    parser.add_argument('--out', type=Path, required=True,
                        help='Directory for generated tests, binaries, logs, and summary.json')
    parser.add_argument('--verilator', default=os.environ.get('VERILATOR', 'verilator'),
                        help='Verilator executable (default: VERILATOR environment variable or PATH)')
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    started = time.monotonic()
    spec = importlib.util.spec_from_file_location('configuration_build_sim', repo/'test/model_benchmark/build_sim.py')
    build_sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_sim)
    from scripts.capacity.config import DEFAULTS, validate_config

    source_list, source_args = build_sim.filelist_sources(
        repo/'veri/flist/dut_axil.f', repo/'veri/sim', repo/'picorv32')
    all_sources = set(source_list)
    all_sources.update(repo/name for name in (
        'test/model_benchmark/build_sim.py', 'scripts/capacity/config.py',
        'scripts/capacity/model.py', 'test/performance_analysis/validate_configuration_bounds.py'))
    all_sources.update((repo/'rtl/npu/ps_compact').glob('*.svh'))
    before = {str(path.relative_to(repo)): digest(path) for path in sorted(all_sources)}
    rejected_python, accepted_python = [], []
    for bus_width in BUS_WIDTHS:
        for value in (0, 12, 512, 512*(bus_width//8)):
            options = dict(bus_width=bus_width, dma_max_bytes=value,
                           shared_bank_bytes=2048, shared_bank_count=7)
            try:
                build_sim.build_sim(out/f'python_dma_w{bus_width}_{value}', **options)
            except ValueError as error:
                if 'Invalid simulator configuration' not in str(error):
                    raise
                rejected_python.append(dict(kind='dma', **options))
            else:
                raise RuntimeError(f'Benchmark accepted DMA_MAX_BYTES={value} for AXI{bus_width}')
        for size in BANK_BYTES:
            for count in BANK_COUNTS:
                values = dict(DEFAULTS, NPU_AXI_DATA_WIDTH=bus_width,
                              SHARED_BANK_BYTES=size, SHARED_BANK_COUNT=count)
                validate_config(values, check_budget=False)
                accepted_python.append(dict(bus_width=bus_width, bank_bytes=size, bank_count=count))
        for size, count in ((0, 7), (512, 7), (1536, 7), (1024, 7), (2048, 0), (2048, 5), (2048, 10)):
            options = dict(bus_width=bus_width, shared_bank_bytes=size, shared_bank_count=count)
            try:
                build_sim.build_sim(out/f'python_shared_w{bus_width}_b{size}_n{count}', **options)
            except ValueError as error:
                if 'Shared RAM' not in str(error):
                    raise
                rejected_python.append(dict(kind='shared', **options))
            else:
                raise RuntimeError(f'Benchmark accepted shared bank geometry {size} x {count}')
    main_cpp = out/'main.cpp'
    main_cpp.write_text('#include "Vparameter_test.h"\n#include "verilated.h"\n#include <cstdio>\n'
                        'int main(int argc,char**argv){Verilated::commandArgs(argc,argv);'
                        'Vparameter_test top;top.eval();if(!top.passed)return 2;'
                        'std::puts("CONFIGURATION_BOUNDS_PASS");return 0;}\n')
    records = []

    def execute(name, sv, sources, *, expected_accept=True, rejection_marker=None,
                defines=(), details=None):
        directory = out/name
        directory.mkdir(parents=True, exist_ok=True)
        tb = directory/'parameter_test.sv'
        tb.write_text(sv)
        command = [args.verilator, '--cc', '--exe', '--assert', '-Wno-fatal', '-Wno-PINMISSING',
                   '--top-module', 'parameter_test', '--Mdir', str(directory/'obj'),
                   '--output-groups', '0', '--output-split', '12000',
                   '-CFLAGS', '-std=c++17', *defines, *sources, str(tb), str(main_cpp)]
        compile_command = ['make', '-C', str(directory/'obj'), '-f', 'Vparameter_test.mk', '-j', '1',
                           'OPT_FAST=-O0', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O0',
                           'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E']
        for cmd, filename in ((command, 'generate.log'), (compile_command, 'compile.log')):
            with (directory/filename).open('w') as stream:
                result = subprocess.run(cmd, cwd=repo, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
            if result.returncode:
                raise RuntimeError(f'{name}: see {directory/filename}: '+(directory/filename).read_text()[-3000:])
        binary = directory/'obj/Vparameter_test'
        result = subprocess.run([str(binary)], cwd=repo, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=30)
        (directory/'run.log').write_text(result.stdout)
        accepted = result.returncode == 0 and 'CONFIGURATION_BOUNDS_PASS' in result.stdout
        passed = accepted if expected_accept else result.returncode != 0 and rejection_marker in result.stdout
        if not passed:
            raise RuntimeError(f'{name}: unexpected configuration result: {result.stdout}')
        record = dict(name=name, passed=True, expected_accept=expected_accept, accepted=accepted,
                      returncode=result.returncode, generate_command=command, compile_command=compile_command,
                      run_command=[str(binary)], testbench_sha256=digest(tb), binary_sha256=digest(binary))
        if details:
            record.update(details)
        records.append(record)
        print(json.dumps({key: record[key] for key in ('name', 'passed', 'accepted')}), flush=True)
        for path in (directory/'obj').iterdir():
            if path.suffix in ('.o', '.d', '.gch'):
                path.unlink()

    dma_sources = [str(repo/name) for name in ('rtl/npu/dma/axi_linear_block_dma.sv',
                                              'rtl/npu/conv/conv_axi_span_reader.sv')]
    supported_by_bus = {bus: [bus//8 * 2**power for power in range(9)] for bus in BUS_WIDTHS}
    for bus_width, supported in supported_by_bus.items():
        for name, values, accepted in (
            ('supported_values', supported, True), ('reject_zero', (0,), False),
            ('reject_short_beat', (bus_width//16,), False),
            ('reject_non_power_of_two', (12,), False), ('reject_over_limit', (supported[-1]*2,), False),
        ):
            instances, checks = [], []
            for index, value in enumerate(values):
                instances += [f"axi_linear_block_dma #(.BUS_WIDTH({bus_width}),.DMA_MAX_BYTES({value})) "
                              f"linear{index}(.clk(1'b0),.rst_n(1'b0));",
                              f"conv_axi_span_reader #(.BUS_WIDTH({bus_width}),.DMA_MAX_BYTES({value})) "
                              f"span{index}(.clk(1'b0),.rst_n(1'b0));"]
                if accepted:
                    checks += segment_checks(f'linear{index}', bus_width, value)
                    checks += [f'assert(span{index}.DMA_MAX_BYTES=={value});',
                               f'assert(span{index}.BUS_WIDTH=={bus_width});']
            sv = ('module parameter_test(output logic passed);\n' + '\n'.join(instances) +
                  '\ninitial begin\n' + '\n'.join(checks) + '\npassed=1;\nend\nendmodule\n')
            execute(f'axi{bus_width}_'+name, sv, dma_sources, expected_accept=accepted,
                    rejection_marker='DMA_MAX_BYTES',
                    details=dict(bus_width=bus_width, dma_bytes=list(values), assertions=len(checks)))
    for bus_width in BUS_WIDTHS:
        sv, cases, assertions = unified_testbench(bus_width)
        execute(f'axi{bus_width}_unified_shared', sv, source_args,
                defines=('-DGEMPACT_PS_COMPRESS',),
                details=dict(bus_width=bus_width, configurations=cases, assertions=assertions))
    after = {str(path.relative_to(repo)): digest(path) for path in sorted(all_sources)}
    if before != after:
        raise RuntimeError('Configuration validation sources changed during execution')
    report = dict(passed=True, repository=str(repo), script_sha256=digest(__file__),
                  elapsed_seconds=time.monotonic()-started,
                  verilator_version=subprocess.check_output([args.verilator, '--version'], text=True).strip(),
                  supported_dma_bytes_by_bus_width=supported_by_bus,
                  shared_bank_bytes=list(BANK_BYTES), shared_bank_counts=list(BANK_COUNTS),
                  benchmark_rejected_configurations=rejected_python,
                  accepted_public_shared_configurations=accepted_python,
                  checks=['DMA parameter admission and 4 KiB segmentation',
                          'Unified DMA and im2col parameter propagation',
                          'Shared RAM geometry and AXI-Lite capability parameters',
                          'External partial-sum pool dimensions and directory capacity'],
                  source_sha256=before, runs=records)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, rtl_runs=len(records),
                         assertions=sum(record['assertions'] for record in records),
                         summary=str(out/'summary.json'))), flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
