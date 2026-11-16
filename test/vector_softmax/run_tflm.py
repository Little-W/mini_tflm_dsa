#!/usr/bin/env python3
"""Test Softmax Prepare, dispatch, fallback, allocation and MMIO validation."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
TF=ROOT/'drivers/tflm/tflm/tflite-micro'
NN=ROOT/'drivers/tflm/NMSIS/NN'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    records=[]
    for enabled in (0,1):
        executable=out/f'tflm_softmax_{enabled}'
        includes=[ROOT/'drivers',NN/'Include',TF,
                  TF/'tensorflow/lite/micro/tools/make/downloads/gemmlowp',
                  TF/'tensorflow/lite/micro/tools/make/downloads/flatbuffers/include']
        sources=[HERE/'test_tflm.cc',
                 TF/'tensorflow/lite/micro/kernels/softmax.cc',
                 TF/'tensorflow/lite/micro/kernels/softmax_common.cc',
                 TF/'tensorflow/lite/micro/kernels/kernel_util.cc',
                 TF/'tensorflow/lite/micro/micro_context.cc',
                 TF/'tensorflow/lite/micro/micro_utils.cc',
                 TF/'tensorflow/lite/kernels/internal/common.cc',
                 TF/'tensorflow/lite/kernels/internal/runtime_shape.cc',
                 TF/'tensorflow/lite/kernels/internal/quantization_util.cc']
        command=['g++','-std=c++17','-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                 '-ffunction-sections','-fdata-sections','-Wl,--gc-sections',
                 '-DDSA_MMIO_CUSTOM=1','-DDSA_SOFTMAX_TIMEOUT=16','-DDSA_NN_RUNTIME_CONTROL=1',
                 f'-DDSA_NN_VECTOR_ENABLE={enabled}','-DTF_LITE_STRIP_ERROR_STRINGS',
                 '-DTF_LITE_DISABLE_X86_NEON',*['-I'+str(p) for p in includes],
                 *map(str,sources),'-o',str(executable)]
        build=subprocess.run(command,text=True,capture_output=True)
        (out/f'build_{enabled}.log').write_text(build.stdout+build.stderr)
        if build.returncode:raise RuntimeError(build.stderr)
        run=subprocess.run([str(executable)],text=True,capture_output=True,
                           env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        (out/f'run_{enabled}.log').write_text(run.stdout+run.stderr)
        if run.returncode:raise RuntimeError(run.stdout+run.stderr)
        print(run.stdout,end='',flush=True)
        records.append({'hardware_compiled':bool(enabled),'passed':True})
    summary={'passed':True,'ubsan':True,'asan':True,'configurations':records,
             'coverage':['prepare_allocation','batched_hardware_dispatch','runtime_mask',
                         'software_compile','capacity_fallback','capability_fallback','in_place_fallback',
                         'hardware_error','driver_capabilities','driver_spans','driver_aliases',
                         'driver_busy','driver_timeout','driver_registers']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':main()
