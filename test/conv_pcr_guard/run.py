#!/usr/bin/env python3
"""Targeted host-only check: PCR planning must not start hardware Conv."""
from pathlib import Path
import argparse, hashlib, json, shlex, subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NN = ROOT / 'drivers/tflm/NMSIS/NN'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/conv_pcr_guard')
    args = parser.parse_args()
    output_root = args.out.resolve()
    build_root = output_root/'objects'
    build_root.mkdir(parents=True, exist_ok=True)
    sources = [NN/'Source/ExtraAccFunctions/riscv_conv_acc.c']
    sources += [NN/'Source/ConvolutionFunctions'/f'{name}.c' for name in [
        'riscv_convolve_s8','riscv_convolve_wrapper_s8','riscv_convolve_1x1_s8',
        'riscv_convolve_1x1_s8_fast','riscv_convolve_1_x_n_s8','riscv_convolve_get_buffer_sizes_s8',
        'riscv_nn_mat_mult_kernel_s8_s16','riscv_nn_mat_mult_kernel_row_offset_s8_s16']]
    sources += [NN/'Source/NNSupportFunctions'/f'{name}.c' for name in
                ['riscv_nn_mat_mult_nt_t_s8','riscv_q7_to_q15_with_offset']]
    sources += [ROOT/'test/conv_cosim/reference.c']
    results=[]
    for name,nmsis,pcr in [('standalone_pcr',False,1),('nmsis_pcr',True,1),('nmsis_standard_no_caps',True,0)]:
        out=output_root/name;out.mkdir(parents=True,exist_ok=True)
        build=build_root/name;build.mkdir(exist_ok=True)
        includes=NN/'Include' if nmsis else ROOT/'drivers'
        driver=NN/'Source/ExtraAccFunctions/dsa_accel.c' if nmsis else ROOT/'drivers/dsa_accel.c'
        files=[HERE/'test_guard.c',driver]+(sources if nmsis else [])
        flags=['-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
               '-DDSA_MMIO_CUSTOM','-DDSA_TILE_SIZE=16','-DDSA_IA_CACHE_BLOCKS=4',
               '-DDSA_PS_FRAME_COUNT=8',f'-DDSA_PCR_ENGINE={pcr}',
               '-DDSA_PANEL_MAX_R=8','-DDSA_PANEL_MAX_W=16',
               f'-DDSA_PS_POOL_BYTES={81920 if pcr else 0}','-DDSA_PS_FORCE_RAW=0',
               '-I',str(includes),'-I',str(ROOT/'drivers')]
        if nmsis:flags+=['-DTEST_NMSIS','-include',str(ROOT/'test/conv_driver/host_compat.h')]
        objects=[];deps=set(files);commands=[];log=[]
        for index,source in enumerate(files):
            obj=build/f'{index}.o';dep=build/f'{index}.d';objects.append(obj)
            command=['gcc',*flags,'-MMD','-MF',str(dep),'-c',str(source),'-o',str(obj)]
            commands.append(command);process=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
            log += ['$ '+shlex.join(command),process.stdout,process.stderr]
            if process.returncode:
                (out/'build.log').write_text('\n'.join(log));raise RuntimeError(source)
            dependencies=dep.read_text().replace('\\\n',' ').split(':',1)[1]
            deps.update(Path(token).resolve() for token in shlex.split(dependencies))
        binary=build/'probe';command=['gcc',*[str(obj) for obj in objects],'-o',str(binary)]
        commands.append(command);process=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
        log += ['$ '+shlex.join(command),process.stdout,process.stderr]
        (out/'build.log').write_text('\n'.join(log));assert process.returncode==0
        source_sha={str(path.relative_to(ROOT)):digest(path) for path in sorted(deps)}
        process=subprocess.run([str(binary)],cwd=ROOT,text=True,capture_output=True)
        (out/'run.log').write_text(process.stdout+process.stderr)
        passed=process.returncode==0 and 'PCR_CONV_GUARD_PASS' in process.stdout
        record=dict(name=name,passed=passed,returncode=process.returncode,compiled_pcr=pcr,
            verification_level='host C driver/NMSIS with MMIO observation; no RTL, SoC or timing test',
            commands=commands,source_sha256=source_sha,binary_sha256=digest(binary),
            log_sha256=digest(out/'run.log'),observations=process.stdout.splitlines())
        (out/'status.json').write_text(json.dumps(record,indent=2)+'\n');results.append(record)
        print(name,process.stdout,end='');assert passed
    status=dict(passed=True,upstream_base='148964d180f52cb852c5a7e3d5c89773fa0a8ea5',
                scope='Two PCR driver variants; one ordinary-compile missing-capability control. No hardware START or MMIO writes in any case.',
                checked_software_outputs=16,runner_sha256=digest(Path(__file__)),
                unused_function_warning='The host build suppresses -Wunused-function because PCR selection leaves legacy static helpers unused; no production source is changed.',
                profiles=results)
    (output_root/'status.json').write_text(json.dumps(status,indent=2)+'\n')

if __name__=='__main__':
    main()
