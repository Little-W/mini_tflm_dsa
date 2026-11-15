#!/usr/bin/env python3
"""Check runtime software/hardware dispatch through production NMSIS kernels."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
NN = ROOT / 'drivers/tflm/NMSIS/NN'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/nmsis_runtime')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    groups = {
        'ExtraAccFunctions': ['dsa_accel', 'riscv_nn_dsa', 'riscv_conv_acc',
                              'riscv_dwconv_acc', 'riscv_fully_connected_acc', 'riscv_add_acc'],
        'BasicMathFunctions': ['riscv_elementwise_add_s8'],
        'ConvolutionFunctions': ['riscv_convolve_s8', 'riscv_convolve_wrapper_s8',
            'riscv_convolve_1x1_s8', 'riscv_convolve_1x1_s8_fast', 'riscv_convolve_1_x_n_s8',
            'riscv_convolve_get_buffer_sizes_s8', 'riscv_nn_mat_mult_kernel_s8_s16',
            'riscv_nn_mat_mult_kernel_row_offset_s8_s16', 'riscv_depthwise_conv_s8',
            'riscv_depthwise_conv_wrapper_s8', 'riscv_depthwise_conv_s8_opt',
            'riscv_depthwise_conv_3x3_s8', 'riscv_depthwise_conv_get_buffer_sizes_s8'],
        'PoolingFunctions': ['riscv_avgpool_s8', 'riscv_max_pool_s8', 'riscv_avgpool_get_buffer_sizes_s8'],
        'FullyConnectedFunctions': ['riscv_fully_connected_s8', 'riscv_fully_connected_per_channel_s8'],
        'NNSupportFunctions': ['riscv_nn_mat_mult_nt_t_s8', 'riscv_q7_to_q15_with_offset',
            'riscv_nn_vec_mat_mult_t_s8', 'riscv_nn_vec_mat_mult_t_per_ch_s8'],
    }
    sources = [NN / 'Source' / group / (name+'.c') for group, names in groups.items() for name in names]
    sources.append(Path(__file__).with_name('test_runtime.c'))
    command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=undefined', '-fno-sanitize-recover=all', '-ffunction-sections',
        '-fdata-sections', '-DDSA_NN_RUNTIME_CONTROL=1', '-DDSA_MMIO_CUSTOM',
        '-DDSA_MATMUL_TIMEOUT=8', '-include', str(ROOT/'test/conv_driver/host_compat.h'),
        '-I', str(NN/'Include'), '-I', str(ROOT/'drivers'),
        *map(str, sources), '-Wl,--gc-sections', '-o', str(out/'test_runtime')]
    build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (out/'build.log').write_text('$ '+' '.join(command)+'\n'+build.stdout+build.stderr)
    if build.returncode:
        print(build.stdout+build.stderr)
        return build.returncode
    run = subprocess.run([str(out/'test_runtime')], cwd=ROOT, text=True, capture_output=True, timeout=60)
    (out/'run.log').write_text(run.stdout+run.stderr)
    print(run.stdout+run.stderr, end='')
    report = {'passed': run.returncode == 0 and 'NMSIS_RUNTIME_PASS' in run.stdout,
              'verification': 'Host UBSan; all 32 runtime masks including Add; numerical software outputs; MMIO dispatch; status errors, timeouts and completion errors after START',
              'result': run.stdout.strip(), 'build_command': command,
              'source_sha256': {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    if not report['passed']:
        (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        return 1
    tflm = ROOT/'drivers/tflm/tflm/tflite-micro'
    downloads = tflm/'tensorflow/lite/micro/tools/make/downloads'
    adapter_sources = [Path(__file__).with_name('test_pooling_adapter.cc'),
        tflm/'tensorflow/lite/micro/kernels/kernel_util.cc',
        tflm/'tensorflow/lite/micro/kernels/pooling_common.cc',
        tflm/'tensorflow/lite/kernels/internal/runtime_shape.cc',
        tflm/'tensorflow/lite/micro/micro_log.cc']
    adapter_command = ['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-Wno-missing-field-initializers',
        '-ffunction-sections', '-fdata-sections', '-fsanitize=undefined',
        '-fno-sanitize-recover=all', '-DTF_LITE_STATIC_MEMORY',
        '-DTF_LITE_DISABLE_X86_NEON', '-DNMSIS_NN',
        '-include', str(ROOT/'test/conv_driver/host_compat.h'),
        '-I', str(tflm), '-I', str(NN/'Include'),
        '-I', str(downloads/'flatbuffers/include'), '-I', str(downloads/'gemmlowp'),
        *map(str, adapter_sources), '-Wl,--gc-sections', '-o', str(out/'test_pooling_adapter')]
    build = subprocess.run(adapter_command, cwd=ROOT, text=True, capture_output=True)
    (out/'pooling_build.log').write_text('$ '+' '.join(adapter_command)+'\n'+build.stdout+build.stderr)
    if build.returncode:
        print(build.stdout+build.stderr)
        return build.returncode
    run = subprocess.run([str(out/'test_pooling_adapter')], cwd=ROOT,
                         text=True, capture_output=True, timeout=60)
    (out/'pooling_run.log').write_text(run.stdout+run.stderr)
    print(run.stdout+run.stderr, end='')
    report['pooling_adapter'] = {
        'passed':run.returncode == 0 and 'TFLM_POOLING_ADAPTER_PASS' in run.stdout,
        'result':run.stdout.strip(), 'build_command':adapter_command,
        'verification':'Production TFLM adapter with NMSIS status stubs; batch dimensions and returned errors'}
    report['passed'] = report['passed'] and report['pooling_adapter']['passed']
    adapter_sources.append(tflm/'tensorflow/lite/micro/kernels/nmsis_nn/pooling.cc')
    report['source_sha256'].update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in adapter_sources})
    fc_sources = [Path(__file__).with_name('test_fc_adapter.cc'),
        tflm/'tensorflow/lite/core/c/common.cc',
        tflm/'tensorflow/lite/kernels/internal/tensor_ctypes.cc',
        tflm/'tensorflow/lite/micro/kernels/kernel_util.cc',
        tflm/'tensorflow/lite/kernels/internal/runtime_shape.cc',
        tflm/'tensorflow/lite/micro/micro_context.cc',
        tflm/'tensorflow/lite/micro/micro_log.cc']
    adapter_flags = adapter_command[:adapter_command.index(str(adapter_sources[0]))]
    for mode in ('scratch', 'persistent'):
        fc_command = [*adapter_flags, '-Wno-unused-but-set-variable',
            '-Wno-sign-compare', '-I', str(downloads/'ruy')]
        if mode == 'persistent':
            fc_command.append('-DKERNELS_OPTIMIZED_FOR_SPEED')
        fc_command += [*map(str,fc_sources), '-Wl,--gc-sections',
                       '-o', str(out/('test_fc_adapter_'+mode))]
        build = subprocess.run(fc_command,cwd=ROOT,text=True,capture_output=True)
        (out/('fc_'+mode+'_build.log')).write_text('$ '+' '.join(fc_command)+'\n'+build.stdout+build.stderr)
        if build.returncode:
            print(build.stdout+build.stderr)
            return build.returncode
        run = subprocess.run([str(out/('test_fc_adapter_'+mode))],cwd=ROOT,
                             text=True,capture_output=True,timeout=60)
        (out/('fc_'+mode+'_run.log')).write_text(run.stdout+run.stderr)
        print(run.stdout+run.stderr,end='')
        report['fc_adapter_'+mode] = {
            'passed':run.returncode==0 and 'TFLM_FC_ADAPTER_PASS' in run.stdout,
            'result':run.stdout.strip(), 'build_command':fc_command,
            'verification':'Production TFLM FC Prepare/Eval; quantization metadata and NMSIS status stubs; ranks 2/3/4, per-tensor/per-channel, optional bias, buffers and one-call error propagation'}
        report['passed'] = report['passed'] and report['fc_adapter_'+mode]['passed']
    fc_sources.append(tflm/'tensorflow/lite/micro/kernels/nmsis_nn/fully_connected.cc')
    report['source_sha256'].update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in fc_sources})
    dw_sources = [Path(__file__).with_name('test_dw_adapter.cc'), *fc_sources[1:-1]]
    dw_command = [*adapter_flags, '-Wno-unused-but-set-variable', '-Wno-sign-compare',
        '-I', str(downloads/'ruy'), *map(str,dw_sources), '-Wl,--gc-sections',
        '-o', str(out/'test_dw_adapter')]
    build = subprocess.run(dw_command,cwd=ROOT,text=True,capture_output=True)
    (out/'dw_build.log').write_text('$ '+' '.join(dw_command)+'\n'+build.stdout+build.stderr)
    if build.returncode:
        print(build.stdout+build.stderr)
        return build.returncode
    run = subprocess.run([str(out/'test_dw_adapter')],cwd=ROOT,
                         text=True,capture_output=True,timeout=60)
    (out/'dw_run.log').write_text(run.stdout+run.stderr)
    print(run.stdout+run.stderr,end='')
    report['dw_adapter'] = {
        'passed':run.returncode==0 and 'TFLM_DW_ADAPTER_PASS' in run.stdout,
        'result':run.stdout.strip(), 'build_command':dw_command,
        'verification':'Production TFLM DW Prepare/Eval; quantization metadata and NMSIS status stubs; channels 2/3/8/16, batches 1/2, per-tensor/per-channel, optional bias, scratch pointer and size, one-call error propagation'}
    report['passed'] = report['passed'] and report['dw_adapter']['passed']
    dw_sources.append(tflm/'tensorflow/lite/micro/kernels/nmsis_nn/depthwise_conv.cc')
    report['source_sha256'].update({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dw_sources})
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
