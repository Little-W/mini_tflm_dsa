#!/usr/bin/env python3
from pathlib import Path
import subprocess, os, sys, json
root=Path(os.environ.get('REPO_ROOT', Path(__file__).resolve().parents[2]))
source=Path(__file__).resolve().parent
build=Path(os.environ.get('BUILD_DIR', root/'build/conv_driver'))
build.mkdir(parents=True,exist_ok=True)
nn=root/'drivers/tflm/NMSIS/NN'
common=['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-DDSA_MMIO_CUSTOM','-DDSA_MATMUL_TIMEOUT=8','-ffunction-sections','-fdata-sections','-fsanitize=undefined','-fno-sanitize-recover=all']
programs={
 'standalone': [root/'drivers/dsa_accel.c'],
 'nmsis': [nn/'Source/ExtraAccFunctions/dsa_accel.c', nn/'Source/ExtraAccFunctions/riscv_conv_acc.c']+
 [nn/'Source/ConvolutionFunctions'/f'{n}.c' for n in ['riscv_convolve_s8','riscv_convolve_wrapper_s8','riscv_convolve_1x1_s8','riscv_convolve_1x1_s8_fast','riscv_convolve_1_x_n_s8','riscv_convolve_get_buffer_sizes_s8','riscv_nn_mat_mult_kernel_s8_s16','riscv_nn_mat_mult_kernel_row_offset_s8_s16']]+
 [nn/'Source/NNSupportFunctions'/f'{n}.c' for n in ['riscv_nn_mat_mult_nt_t_s8','riscv_q7_to_q15_with_offset']]
}
reports={}
for name,files in programs.items():
 cmd=common[:]
 if name=='nmsis': cmd+=['-DTEST_NMSIS','-include',str(source/'host_compat.h'),'-I',str(nn/'Include')]
 cmd+=['-I',str(root/'drivers')]+[str(f) for f in files]+[str(source/'test_driver.c'),'-Wl,--gc-sections','-o',str(build/name)]
 compile_run=subprocess.run(cmd,text=True,capture_output=True)
 (build/f'{name}_build.log').write_text('$ '+' '.join(cmd)+'\n'+compile_run.stdout+compile_run.stderr)
 if compile_run.returncode:
  print(compile_run.stderr);sys.exit(compile_run.returncode)
 run=subprocess.run([str(build/name)],text=True,capture_output=True)
 (build/f'{name}_run.log').write_text(run.stdout+run.stderr)
 print(run.stdout+run.stderr,end='')
 if run.returncode: sys.exit(run.returncode)
 reports[name]={'compile':'PASS','run':'PASS','verification_level':'host driver/MMIO and real NMSIS call path; not RTL or SoC execution'}
(build/'status.json').write_text(json.dumps(reports,indent=2)+'\n')
