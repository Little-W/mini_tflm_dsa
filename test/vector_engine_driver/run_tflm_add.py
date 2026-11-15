#!/usr/bin/env python3
"""Check TFLM Add hardware selection, broadcast fallback and in-place evaluation."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
TF=ROOT/'drivers/tflm/tflm/tflite-micro';NN=ROOT/'drivers/tflm/NMSIS/NN'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);records=[]
 for enabled in (0,1):
  name=f'tflm_add_{enabled}';exe=a.out/name
  command=['g++','-std=c++17','-O2','-fsanitize=undefined','-fno-sanitize-recover=all','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-DNMSIS_NN',f'-DDSA_NN_VECTOR_ENABLE={enabled}','-DTF_LITE_STRIP_ERROR_STRINGS','-DTF_LITE_DISABLE_X86_NEON','-I'+str(TF),'-I'+str(TF/'tensorflow/lite/micro/tools/make/downloads/gemmlowp'),'-I'+str(NN/'Include'),'-I'+str(TF/'tensorflow/lite/micro/tools/make/downloads/flatbuffers/include'),str(HERE/'test_tflm_add.cc'),str(TF/'tensorflow/lite/micro/kernels/add.cc'),str(TF/'tensorflow/lite/kernels/internal/common.cc'),str(TF/'tensorflow/lite/kernels/internal/runtime_shape.cc'),'-o',str(exe)]
  build=subprocess.run(command,text=True,capture_output=True);(a.out/(name+'_build.log')).write_text(build.stdout+build.stderr)
  if build.returncode:raise RuntimeError(build.stderr)
  run=subprocess.run([str(exe.resolve())],text=True,capture_output=True);(a.out/(name+'.log')).write_text(run.stdout+run.stderr)
  if run.returncode:raise RuntimeError(run.stderr)
  records.append({'hardware_compiled':bool(enabled),'passed':True,'cases':['software_fallback','hardware_dispatch','device_failure','broadcast','in_place'] if enabled else ['software','broadcast','in_place']})
 (a.out/'summary.json').write_text(json.dumps({'passed':True,'ubsan':True,'tests':records},indent=2)+'\n');print('TFLM_ADD_SELECTION_PASS variants=2')
if __name__=='__main__':main()
