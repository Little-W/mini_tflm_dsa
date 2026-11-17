#!/usr/bin/env python3
"""Validate persistent TFLM Add configuration and the production driver."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
TF=ROOT/'drivers/tflm/tflm/tflite-micro'
NN=ROOT/'drivers/tflm/NMSIS/NN'

def run(command,log):
    result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True,
                          env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
    log.write_text('$ '+' '.join(map(str,command))+'\n'+result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout+result.stderr)
    return result.stdout

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    shared=['-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all',
            '-ffunction-sections','-fdata-sections','-DDSA_MMIO_CUSTOM=1',
            '-DDSA_MATMUL_TIMEOUT=16','-DDSA_NN_RUNTIME_CONTROL=1']
    driver=ROOT/'drivers/dsa_accel.c';driver_object=out/'dsa_accel.o'
    run(['gcc','-std=c11',*shared,'-I'+str(ROOT/'drivers'),'-c',str(driver),
         '-o',str(driver_object)],out/'driver_build.log')
    includes=[ROOT/'drivers',NN/'Include',TF,
              TF/'tensorflow/lite/micro/tools/make/downloads/gemmlowp',
              TF/'tensorflow/lite/micro/tools/make/downloads/flatbuffers/include']
    sources=[HERE/'test_tflm_add_prepared.cc',
             TF/'tensorflow/lite/micro/kernels/add.cc',
             TF/'tensorflow/lite/micro/kernels/add_common.cc',
             TF/'tensorflow/lite/micro/kernels/kernel_util.cc',
             TF/'tensorflow/lite/micro/micro_context.cc',
             TF/'tensorflow/lite/micro/micro_utils.cc',
             TF/'tensorflow/lite/kernels/kernel_util.cc',
             TF/'tensorflow/lite/core/c/common.cc',
             TF/'tensorflow/lite/kernels/internal/common.cc',
             TF/'tensorflow/lite/kernels/internal/runtime_shape.cc',
             TF/'tensorflow/lite/kernels/internal/quantization_util.cc']
    executable=out/'tflm_add_prepared'
    run(['g++','-std=c++17',*shared,'-Wl,--gc-sections','-DNMSIS_NN',
         '-DDSA_NN_PREPARED_ENABLE=1','-DDSA_NN_VECTOR_ENABLE=1',
         '-DTF_LITE_STRIP_ERROR_STRINGS','-DTF_LITE_DISABLE_X86_NEON',
         *['-I'+str(p) for p in includes],*map(str,sources),str(driver_object),
         '-o',str(executable)],out/'tflm_build.log')
    result=run([str(executable)],out/'run.log');print(result,end='')
    headers=[ROOT/'drivers/dsa_prepared.h',ROOT/'drivers/dsa_prepared_impl.h',
             ROOT/'drivers/dsa_vector.h',ROOT/'drivers/dsa_vector_impl.h',
             NN/'Include/riscv_nn_prepared.h',
             TF/'tensorflow/lite/micro/kernels/nmsis_nn/prepared.h']
    summary={'passed':True,'asan':True,'ubsan':True,'result':result.strip(),
             'coverage':['arena_configuration_pointer','prepare_reuses_configuration',
                         'prepare_allocation_failure','invoke_without_shape_or_tensor_lookup',
                         'invoke_without_allocation_or_capability_query','dynamic_addresses',
                         'immutable_configuration','runtime_mask','capability_fallback',
                         'broadcast_fallback','in_place_fallback','partial_overlap_error',
                         'device_error','busy','timeout'],
             'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in [*sources,driver,*headers,Path(__file__).resolve()]}}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':main()
