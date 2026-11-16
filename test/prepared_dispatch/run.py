#!/usr/bin/env python3
"""Validate prepared DMA submissions through both production driver frontends."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
NN = ROOT / 'drivers/tflm/NMSIS/NN'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, default=ROOT/'build/prepared_dispatch')
parser.add_argument('--legacy-is', type=int, choices=(0,1), default=1)
args = parser.parse_args()
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
reports = {}
for name, driver in [('standalone', ROOT / 'drivers/dsa_accel.c'),
                     ('nmsis', NN / 'Source/ExtraAccFunctions/dsa_accel.c')]:
    command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=undefined', '-fno-sanitize-recover=all',
               '-ffunction-sections', '-fdata-sections', '-DDSA_MMIO_CUSTOM',
               '-DDSA_MATMUL_TIMEOUT=8', f'-DDSA_ENABLE_IS_MODE={args.legacy_is}']
    if name == 'nmsis':
        command += ['-DTEST_NMSIS', '-include', str(ROOT/'test/conv_driver/host_compat.h'),
                    '-I', str(NN/'Include')]
    command += ['-I', str(ROOT/'drivers'), str(driver),
                str(Path(__file__).with_name('test_prepared.c')),
                '-Wl,--gc-sections', '-o', str(OUT/name)]
    build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (OUT/f'{name}_build.log').write_text('$ '+' '.join(command)+'\n'+build.stdout+build.stderr)
    if build.returncode:
        print(build.stdout+build.stderr)
        raise SystemExit(build.returncode)
    run = subprocess.run([str(OUT/name)], cwd=ROOT, text=True, capture_output=True, timeout=60)
    (OUT/f'{name}_run.log').write_text(run.stdout+run.stderr)
    print(run.stdout+run.stderr, end='')
    if run.returncode:
        raise SystemExit(run.returncode)
    reports[name] = {'passed': 'PREPARED_DISPATCH_PASS' in run.stdout,
                     'result': run.stdout.strip(), 'build_command': command}
tf = ROOT/'drivers/tflm/tflm/tflite-micro'
downloads = tf/'tensorflow/lite/micro/tools/make/downloads'
command = ['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Wno-unused-parameter',
           '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
           '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
           '-DDSA_NN_RUNTIME_CONTROL=1', '-DTF_LITE_STRIP_ERROR_STRINGS',
           '-DTF_LITE_DISABLE_X86_NEON',
           *['-I'+str(p) for p in (ROOT/'drivers', NN/'Include', tf,
                                   downloads/'gemmlowp', downloads/'flatbuffers/include')],
           str(Path(__file__).with_name('test_bindings.cc')),
           str(tf/'tensorflow/lite/micro/kernels/kernel_util.cc'),
           '-o', str(OUT/'bindings')]
build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
(OUT/'bindings_build.log').write_text('$ '+' '.join(command)+'\n'+build.stdout+build.stderr)
if build.returncode:
    print(build.stdout+build.stderr)
    raise SystemExit(build.returncode)
run = subprocess.run([str(OUT/'bindings')], cwd=ROOT, text=True, capture_output=True,
                     timeout=60, env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
(OUT/'bindings_run.log').write_text(run.stdout+run.stderr)
print(run.stdout+run.stderr, end='')
if run.returncode:
    raise SystemExit(run.returncode)
reports['bindings'] = {'passed': 'PREPARED_BINDINGS_PASS' in run.stdout,
                       'result': run.stdout.strip(), 'build_command': command}
(OUT/'summary.json').write_text(json.dumps(reports, indent=2)+'\n')
