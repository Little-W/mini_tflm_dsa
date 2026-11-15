#!/usr/bin/env python3
"""Test DW/pool/vector MMIO drivers and NMSIS software dispatch on the host."""
from pathlib import Path
import argparse
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
NN = ROOT / 'drivers/tflm/NMSIS/NN'
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/dw_pool_driver')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [NN / 'Source/ExtraAccFunctions/dsa_accel.c',
               NN / 'Source/ExtraAccFunctions/riscv_dwconv_acc.c']
    sources += [NN / 'Source/ConvolutionFunctions' / f'{name}.c' for name in (
        'riscv_depthwise_conv_s8', 'riscv_depthwise_conv_wrapper_s8',
        'riscv_depthwise_conv_s8_opt', 'riscv_depthwise_conv_3x3_s8',
        'riscv_depthwise_conv_get_buffer_sizes_s8')]
    sources += [NN / 'Source/PoolingFunctions' / f'{name}.c' for name in (
        'riscv_avgpool_s8', 'riscv_max_pool_s8', 'riscv_avgpool_get_buffer_sizes_s8')]
    common = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
              '-DDSA_MMIO_CUSTOM', '-DDSA_MATMUL_TIMEOUT=8',
              '-fsanitize=undefined', '-fno-sanitize-recover=all',
              '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections']
    report = {'verification_level': 'host MMIO driver and NMSIS dispatch', 'tests': []}
    for name in ('standalone', 'nmsis', 'nmsis_software'):
        command = common[:]
        if name == 'standalone':
            selected = [ROOT / 'drivers/dsa_accel.c']
        else:
            selected = sources
            command += ['-DTEST_NMSIS', '-include', ROOT / 'test/conv_driver/host_compat.h',
                        '-I', NN / 'Include']
            if name == 'nmsis_software':
                command += ['-DDSA_NN_DW_POOL_ENABLE=0']
        command += ['-I', ROOT / 'drivers', *selected, HERE / 'test_driver.c', '-o', out / name]
        command = [str(value) for value in command]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        (out / f'{name}_build.log').write_text('$ ' + ' '.join(command) + '\n' + build.stdout + build.stderr)
        if build.returncode:
            print(build.stdout + build.stderr)
            return build.returncode
        run = subprocess.run([str(out / name)], cwd=ROOT, text=True, capture_output=True, timeout=30)
        (out / f'{name}.log').write_text(run.stdout + run.stderr)
        print(name + ': ' + run.stdout + run.stderr, end='')
        passed = run.returncode == 0 and 'DW_POOL_DRIVER_PASS' in run.stdout
        report['tests'].append({'name': name, 'passed': passed, 'output': run.stdout.strip()})
        (out / 'status.json').write_text(json.dumps(report, indent=2) + '\n')
        if not passed:
            return 1
    library = out / 'libnmsis_dw_pool_software.so'
    command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-fPIC', '-shared', '-Wl,-z,defs', '-DDSA_NN_DW_POOL_ENABLE=0',
               '-include', ROOT / 'test/conv_driver/host_compat.h',
               '-I', NN / 'Include', *sources[1:], '-o', library]
    command = [str(value) for value in command]
    build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
    (out / 'nmsis_independent_build.log').write_text('$ ' + ' '.join(command) + '\n' + build.stdout + build.stderr)
    if build.returncode:
        print(build.stdout + build.stderr)
        return build.returncode
    undefined = subprocess.check_output(['nm', '-u', str(library)], text=True)
    if 'dsa_' in undefined or 'mmio' in undefined:
        raise RuntimeError('Software library contains unresolved hardware driver references')
    report['tests'].append({'name': 'nmsis_independent', 'passed': True,
                            'output': 'NMSIS_DW_POOL_INDEPENDENT_SOFTWARE_LINK_PASS'})
    (out / 'status.json').write_text(json.dumps(report, indent=2) + '\n')
    print('nmsis_independent: NMSIS_DW_POOL_INDEPENDENT_SOFTWARE_LINK_PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
