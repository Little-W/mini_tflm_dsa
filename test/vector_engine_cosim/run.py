#!/usr/bin/env python3
"""Run production NMSIS and VCE drivers against AXI-Lite and NPU RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def run(command, log, timeout=1200):
    with log.open('w') as stream:
        stream.write('COMMAND: ' + repr([str(x) for x in command]) + '\n')
        stream.flush()
        process = subprocess.run([str(x) for x in command], cwd=ROOT,
                                 stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    if process.returncode:
        print(log.read_text()[-14000:], flush=True)
    return process.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=16)
    parser.add_argument('--pe-count', type=int, default=8)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--disabled', action='store_true')
    mode.add_argument('--pcr', action='store_true',
                      help='Enable unified compressed PS storage with 14 KiB shared IA/PS RAM')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    if args.pcr and args.size != 16:
        parser.error('PCR requires --size 16')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    build = out / 'build'
    build.mkdir(exist_ok=True)
    nn = ROOT / 'drivers/tflm/NMSIS/NN'
    csrc = [nn / 'Source/ExtraAccFunctions' / f'{name}.c'
            for name in ['dsa_accel', 'riscv_dwconv_acc', 'riscv_add_acc']]
    csrc += [nn / 'Source/ConvolutionFunctions' / f'{name}.c' for name in [
        'riscv_depthwise_conv_s8', 'riscv_depthwise_conv_wrapper_s8',
        'riscv_depthwise_conv_s8_opt', 'riscv_depthwise_conv_3x3_s8',
        'riscv_depthwise_conv_get_buffer_sizes_s8']]
    csrc += [nn / 'Source/PoolingFunctions' / f'{name}.c' for name in [
        'riscv_avgpool_s8', 'riscv_max_pool_s8', 'riscv_avgpool_get_buffer_sizes_s8']]
    csrc += [nn / 'Source/BasicMathFunctions/riscv_elementwise_add_s8.c']
    csrc += [ROOT / 'test/conv_cosim/reference.c']
    references = [
        (nn / 'Source/ConvolutionFunctions/riscv_depthwise_conv_s8.c',
         'riscv_depthwise_conv_s8', 'reference_depthwise_s8'),
        (nn / 'Source/PoolingFunctions/riscv_avgpool_s8.c',
         'riscv_avgpool_s8', 'reference_avgpool_s8'),
        (nn / 'Source/PoolingFunctions/riscv_max_pool_s8.c',
         'riscv_max_pool_s8', 'reference_max_pool_s8'),
    ]
    npu = ROOT / 'rtl/npu'
    package = npu / 'conv/conv_im2col_pkg.sv'
    dw_package = npu / 'conv/vector_engine_pkg.sv'
    svsrc = [package, dw_package]
    svsrc += [p for p in sorted(npu.rglob('*.sv')) if p not in svsrc]
    svsrc += sorted(npu.rglob('*.v'))
    svsrc += [ROOT / 'rtl/common/pseudo_dual_port_ram.v',
              ROOT / 'rtl/axi_top/npu_axil_reg_if.sv',
              ROOT / 'rtl/axi_top/npu_axil_top.sv',
              ROOT / 'test/models/soc_axi_ram.sv', HERE / 'vector_engine_cosim_top.sv']
    cflags = ['-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
              '-DDSA_MMIO_CUSTOM', f'-DDSA_TILE_SIZE={args.size}', '-DDSA_PS_FRAME_COUNT=16',
              '-include', ROOT / 'test/conv_driver/host_compat.h',
              '-I', nn / 'Include', '-I', ROOT / 'drivers']
    if args.pcr:
        cflags += ['-DDSA_PS_COMPRESS=1']
    simulator_config = ROOT / 'test/conv_npu/simulator.vlt'
    inputs = set(csrc + svsrc + [HERE / 'main.cpp', Path(__file__), simulator_config])
    inputs.update(npu.rglob('*.svh'))
    for src in csrc:
        output = subprocess.check_output([str(x) for x in ['gcc', *cflags, '-MM', '-MT', 'deps', src]],
                                         cwd=ROOT, text=True)
        dependencies = shlex.split(output.replace('\\\n', ' ').split(':', 1)[1])
        inputs.update((ROOT / name).resolve() for name in dependencies)
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    status = {
        'scope': 'Production NMSIS C and MMIO driver, actual AXI-Lite NPU top, production AXI RAM.',
        'reference': 'Repository NMSIS scalar kernels compiled with accelerator dispatch disabled.',
        'size': args.size, 'pe_count': args.pe_count, 'enabled': not args.disabled, 'pcr': args.pcr,
        'shared_data_bytes': 14336 if args.pcr else 0,
        'verilator': subprocess.check_output([args.verilator, '--version'], text=True).strip(),
        'source_sha256': hashes, 'runs': [],
    }
    manifest = build / 'manifest.json'
    binary = build / 'obj/Vvector_engine_cosim_top'
    if args.skip_build:
        previous = json.loads(manifest.read_text())
        for key in ['source_sha256', 'size', 'pe_count', 'enabled', 'pcr']:
            if previous[key] != status[key]:
                raise RuntimeError(f'Build inputs changed: {key}')
        status['build'] = previous['build']
        if (not binary.is_file() or
                hashlib.sha256(binary.read_bytes()).hexdigest() != previous['build'].get('binary_sha256')):
            raise RuntimeError('Executable differs from the recorded build')
    else:
        objects = []
        for index, src in enumerate(csrc):
            obj = build / f'c{index}.o'
            if run(['gcc', *cflags, '-c', src, '-o', obj], out / f'c{index}.log'):
                return 1
            objects.append(obj)
        for index, (src, original, replacement) in enumerate(references):
            obj = build / f'reference{index}.o'
            cmd = ['gcc', *cflags, '-DDSA_NN_VECTOR_ENABLE=0',
                   f'-D{original}={replacement}', '-c', src, '-o', obj]
            if run(cmd, out / f'reference{index}.log'):
                return 1
            objects.append(obj)
        library = build / 'libdriver.a'
        if run(['ar', 'rcs', library, *objects], out / 'archive.log'):
            return 1
        cppflags = (f'-std=c++17 -O1 -D__GNUC_PYTHON__ -DDSA_MMIO_CUSTOM '
                    f'-DDSA_TILE_SIZE={args.size} -DDSA_PS_FRAME_COUNT=16 -DDW_TEST_PE_COUNT={args.pe_count} '
                    f'-I{nn / "Include"} -I{ROOT / "drivers"}')
        if args.pcr:
            cppflags += ' -DDSA_PS_COMPRESS=1'
        command = [args.verilator, '--cc', '--exe', '--assert',
                   '--output-groups', '0', '--output-split', '12000',
                   '--top-module', 'vector_engine_cosim_top', '-Wno-fatal', f'-I{npu / "ps_compact"}',
                   f'-GSIZE={args.size}', f'-GVECTOR_PE_COUNT={args.pe_count}',
                   f'-GENABLE_VECTOR_ENGINE={int(not args.disabled)}',
                   '--Mdir', build / 'obj', '-j', args.jobs, '-CFLAGS', cppflags,
                   '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0',
                   simulator_config, *svsrc, HERE / 'main.cpp', library]
        if args.pcr:
            command += ['-DGEMPACT_PS_COMPRESS=1', '-DGEMMORA_PS_POOL_BYTES=12288']
        rc = run(command, out / 'compile.log')
        compile_command = ['make', '-C', build / 'obj', '-f', 'Vvector_engine_cosim_top.mk',
                           '-j', args.jobs, 'OPT_FAST=-O1', 'OPT_SLOW=-O0',
                           'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E']
        if rc == 0:
            rc = run(compile_command, out / 'make.log')
        text = (out / 'compile.log').read_text()
        if (out / 'make.log').exists():
            text += (out / 'make.log').read_text()
        after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashes}
        unchanged = after == hashes
        status['build'] = {
            'returncode': rc, 'sources_unchanged_during_build': unchanged,
            'command': [str(x) for x in command],
            'compile_command': [str(x) for x in compile_command],
            'warnings': {name: text.count('%Warning-' + name + ':')
                         for name in sorted(set(re.findall(r'%Warning-([^:]+):', text)))},
        }
        if rc == 0:
            status['build']['binary_sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
        (out / 'summary.json').write_text(json.dumps(status, indent=2) + '\n')
        if rc or not unchanged:
            if not unchanged:
                print('Source files changed during build; rebuild using the completed source.', flush=True)
            return 1
        manifest.write_text(json.dumps(status, indent=2) + '\n')
    for name, flags in [
        ('fixed', ['+DDR_RAND_LAT=0']),
        ('random', ['+DDR_RAND_LAT=1', '+DDR_CMD_MAX_LAT=3', '+DDR_W_MAX_LAT=3', '+DDR_RSP_MAX_LAT=3']),
    ]:
        if args.disabled:
            flags += ['+DW_DISABLED']
        if args.pcr:
            flags += ['+PS_COMPRESS']
        rc = run([binary, *flags], out / f'{name}.log', timeout=300)
        log = (out / f'{name}.log').read_text()
        passed = rc == 0 and 'VECTOR_ENGINE_C_RTL_COSIM_PASS' in log
        mapping = [dict(re.findall(r'(\w+)=([^\s]+)', line))
                   for line in log.splitlines() if line.startswith('VECTOR_ENGINE_CONV_MAPPING_PASS ')]
        lines = [line for line in log.splitlines() if line.startswith('VECTOR_ENGINE_')]
        for line in lines:
            print(line, flush=True)
        status['runs'].append({'name': name, 'returncode': rc, 'passed': bool(passed),
                               'single_input_dw_mapping': mapping, 'case_lines': lines})
        status['passed'] = len(status['runs']) == 2 and all(run['passed'] for run in status['runs'])
        (out / 'summary.json').write_text(json.dumps(status, indent=2) + '\n')
        if not passed:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
