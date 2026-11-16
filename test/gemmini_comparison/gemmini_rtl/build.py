#!/usr/bin/env python3
"""Build the complete official Gemmini accelerator with a controlled AXI memory interface."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_output(command, **kwargs):
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, **kwargs).strip()


def verify_dependencies(chipyard, gemmini):
    required = json.loads((ROOT / 'dependencies.json').read_text())
    observed = {}
    for name, entry in required['repositories'].items():
        prefix, *suffix = entry['location'].split('/')
        path = (chipyard if prefix == 'chipyard' else gemmini).joinpath(*suffix)
        commit = checked_output(['git', '-C', str(path), 'rev-parse', 'HEAD'])
        if commit != entry['commit']:
            raise SystemExit(f'{name}: expected {entry["commit"]}, found {commit}')
        changes = checked_output(['git', '-C', str(path), 'diff', '--name-only', 'HEAD'])
        if changes:
            raise SystemExit(f'{name}: tracked sources differ from the pinned revision')
        observed[name] = dict(path=str(path), commit=commit, url=entry['url'])
    return required, observed


def run_logged(command, log, *, cwd, env):
    with log.open('w') as stream:
        completed = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if completed.returncode:
        lines = log.read_text(errors='replace').splitlines()
        raise SystemExit('\n'.join(lines[-40:]) + f'\nBuild failed; see {log}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chipyard', type=Path, required=True)
    parser.add_argument('--gemmini', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--sbt', nargs='+', default=['sbt'])
    parser.add_argument('--java', type=Path)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--sp-kib', type=int, default=64)
    parser.add_argument('--acc-kib', type=int, default=16)
    parser.add_argument('--dma-max-bytes', type=int, choices=[64,128,256,512,1024], default=64)
    parser.add_argument('--im2col', action='store_true',
                        help='Instantiate the official independent Im2Col datapath.')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--reuse-generated', action='store_true',
                        help='Compile existing generated RTL and verify its parameter header.')
    args = parser.parse_args()
    if args.sp_kib <= 0 or args.acc_kib <= 0 or args.jobs <= 0:
        parser.error('Memory capacities and parallel jobs must be positive')

    chipyard, gemmini, work = args.chipyard.resolve(), args.gemmini.resolve(), args.work_dir.resolve()
    required, observed = verify_dependencies(chipyard, gemmini)
    java = str(args.java.resolve()) if args.java else shutil.which('java')
    if not java:
        raise SystemExit('Java 17 is required')
    java_version = checked_output([java, '-version'])
    if not re.search(r'version "17[.\"]', java_version):
        raise SystemExit('Select Java 17 with --java /absolute/path/to/java')
    verilator = shutil.which(args.verilator)
    if not verilator:
        raise SystemExit(f'Cannot find Verilator: {args.verilator}')
    verilator_version = checked_output([verilator, '--version'])

    work.mkdir(parents=True, exist_ok=True)
    for relative in ['build.sbt', 'project/build.properties', 'src/main/scala/GemminiCompare.scala',
                     'sim/run_compare.cpp']:
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() != (ROOT / relative).resolve():
            shutil.copyfile(ROOT / relative, destination)
    env = os.environ.copy()
    env['CHIPYARD_SOURCE'] = str(chipyard)
    env['GEMMINI_SOURCE'] = str(gemmini)
    env['GEMMINI_JAVA'] = java
    env['JAVA_HOME'] = str(Path(java).parent.parent)
    env['PATH'] = str(Path(java).parent) + os.pathsep + env.get('PATH', '')

    suffix = f'sp{args.sp_kib}_acc{args.acc_kib}'
    if args.dma_max_bytes != 64:
        suffix += f'_dma{args.dma_max_bytes}'
    generated = work / ('generated_' + suffix)
    objects = work / ('obj_' + suffix)
    generate_command = args.sbt + [
        f'runMain comparison.Generate {generated.name} {args.sp_kib} {args.acc_kib} 32 4 {str(args.im2col).lower()} {args.dma_max_bytes}']
    if not args.reuse_generated:
        print(f'Generating official Gemmini RTL: SP {args.sp_kib} KiB, accumulator {args.acc_kib} KiB', flush=True)
        run_logged(generate_command, work / ('generate_' + suffix + '.log'), cwd=work, env=env)
    header = generated / 'gemmini_params.h'
    rtl = generated / 'GemminiCompare.sv'
    feature_file = generated / 'generated_configuration.json'
    if not header.is_file() or not rtl.is_file():
        raise SystemExit(f'Generated RTL or parameters are missing in {generated}')
    expected_features = dict(dma_max_bytes=args.dma_max_bytes, has_im2col=args.im2col, has_loop_conv=True,
                             has_dw_convs=True, has_first_layer_optimizations=True)
    if not feature_file.is_file():
        raise SystemExit('Generated hardware configuration is missing')
    observed_features = json.loads(feature_file.read_text())
    observed_features.setdefault('dma_max_bytes', 64)
    if observed_features != expected_features:
        raise SystemExit('Regenerate the RTL with the requested hardware parameters')
    parameters = {name: int(value) for name, value in re.findall(
        r'^#define\s+(DIM|BANK_NUM|BANK_ROWS|ACC_ROWS)\s+(\d+)\s*$', header.read_text(), re.MULTILINE)}
    if (parameters.get('DIM') != 16 or parameters.get('BANK_NUM') != 4 or
            parameters.get('BANK_ROWS', 0) * 4 * 16 != args.sp_kib * 1024 or
            parameters.get('ACC_ROWS', 0) * 16 * 4 != args.acc_kib * 1024):
        raise SystemExit('Generated parameter header does not match the requested hardware configuration')

    compile_command = [verilator, '--cc', '--exe', '--build', '--assert', '--top-module',
                       'GemminiCompare', '-Wno-fatal', '-j', str(args.jobs), '--output-split', '20000',
                       '--output-split-cfuncs', '1000', '-CFLAGS', '-O2 -std=c++17',
                       '--Mdir', str(objects), str(rtl), '-f',
                       str(generated / 'firrtl_black_box_resource_files.f'),
                       str(work / 'sim/run_compare.cpp')]
    print('Compiling the complete accelerator simulator with RTL assertions', flush=True)
    run_logged(compile_command, work / ('verilate_' + suffix + '.log'), cwd=work, env=env)
    simulator = objects / 'VGemminiCompare'
    manifest = {
        'format_version': 1,
        'repositories': observed,
        'tool_versions': dict(required['tool_versions'], java_actual=java_version,
                              verilator_actual=verilator_version),
        'configuration': {'array_rows': 16, 'array_columns': 16, 'input_bits': 8, 'weight_bits': 8,
                          'accumulator_bits': 32, 'scratchpad_bytes': args.sp_kib * 1024,
                          'spatial_array_output_bits': 20,
                          'accumulator_bytes': args.acc_kib * 1024, 'dma_bus_bits': 32,
                          'dma_max_bytes': args.dma_max_bytes, 'dma_outstanding_per_direction': 4,
                          'has_im2col': args.im2col, 'has_loop_conv': True,
                          'has_dw_convs': True, 'has_first_layer_optimizations': True,
                          'clock_gate': False, 'host_cpu_instantiated': False,
                          'memory_interface': 'official TLToAXI4 and AXI4UserYanker'},
        'memory_service': {'read_request_queue_depth': 16, 'first_read_latency_cycles': 3,
                           'read_beat_interval_cycles': 2, 'inter_burst_read_gap_cycles': 3,
                           'write_outstanding': 1, 'aw_to_first_w_min_cycles': 1,
                           'last_w_to_b_min_cycles': 1},
        'generate_command': generate_command,
        'compile_command': compile_command,
        'simulator': str(simulator), 'simulator_sha256': digest(simulator),
        'generated_rtl': str(rtl), 'generated_rtl_sha256': digest(rtl),
        'generated_configuration': str(feature_file),
        'generated_configuration_sha256': digest(feature_file),
        'params_header': str(header), 'params_header_sha256': digest(header),
        'harness_sha256': {relative: digest(ROOT / relative) for relative in
                           ['build.sbt', 'project/build.properties', 'src/main/scala/GemminiCompare.scala',
                            'sim/run_compare.cpp', 'run_cases.py', 'build.py', 'dependencies.json']}}
    manifest_path = generated / 'build_manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Simulator: {simulator}\nBuild manifest: {manifest_path}', flush=True)


if __name__ == '__main__':
    main()
