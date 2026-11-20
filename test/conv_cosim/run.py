#!/usr/bin/env python3
"""Actual production NMSIS C -> AXI-Lite -> NPU RTL -> production SoC AXI RAM."""
from pathlib import Path
import argparse, hashlib, json, os, re, shlex, subprocess, sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def run(cmd, log, timeout=900):
    with log.open('w') as f:
        f.write('$ '+' '.join(str(v) for v in cmd)+'\n'); f.flush()
        try:
            p=subprocess.run([str(v) for v in cmd],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
            return p.returncode
        except subprocess.TimeoutExpired:
            f.write('\nTIMEOUT\n');return 124

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--size',type=int,default=4)
    ap.add_argument('--out',type=Path)
    mode=ap.add_mutually_exclusive_group()
    mode.add_argument('--axil-protocol-only',action='store_true')
    mode.add_argument('--disabled-per-channel',action='store_true')
    mode.add_argument('--disabled-is',action='store_true')
    mode.add_argument('--narrow-kernel',action='store_true')
    ap.add_argument('--build',type=Path,default=ROOT/'build/conv_cosim/objects')
    ap.add_argument('--verilator',default='verilator')
    ap.add_argument('--jobs',type=int,default=2)
    ap.add_argument('--skip-build',action='store_true')
    a=ap.parse_args()
    profile=('disabled_per_channel' if a.disabled_per_channel else 'disabled_is' if a.disabled_is else
             'narrow_kernel' if a.narrow_kernel else 'axil' if a.axil_protocol_only else '')
    suffix='_'+profile if profile else ''
    out=(a.out or ROOT/'build/conv_cosim'/f's{a.size}{suffix}'/'results').resolve();out.mkdir(parents=True,exist_ok=True)
    build=(a.build/f's{a.size}{suffix}').resolve();build.mkdir(parents=True,exist_ok=True)
    nn=ROOT/'drivers/tflm/NMSIS/NN'
    csrc=[nn/'Source/ExtraAccFunctions/dsa_accel.c',nn/'Source/ExtraAccFunctions/riscv_conv_acc.c']
    csrc += [nn/'Source/ConvolutionFunctions'/f'{n}.c' for n in [
        'riscv_convolve_s8','riscv_convolve_wrapper_s8','riscv_convolve_1x1_s8','riscv_convolve_1x1_s8_fast',
        'riscv_convolve_1_x_n_s8','riscv_convolve_get_buffer_sizes_s8',
        'riscv_nn_mat_mult_kernel_s8_s16','riscv_nn_mat_mult_kernel_row_offset_s8_s16']]
    csrc += [nn/'Source/NNSupportFunctions'/f'{n}.c' for n in ['riscv_nn_mat_mult_nt_t_s8','riscv_q7_to_q15_with_offset']]
    csrc += [HERE/'reference.c']
    npu=ROOT/'rtl/npu';packages=[npu/'conv/conv_im2col_pkg.sv',npu/'conv/vector_engine_pkg.sv']
    svsrc=packages+[p for p in sorted(npu.rglob('*.sv')) if p not in packages]+sorted(npu.rglob('*.v'))
    svsrc += sorted((ROOT/'rtl/common').glob('REGFILE.v')) + sorted((ROOT/'rtl/common').glob('onehot_check.sv')) + sorted((ROOT/'rtl/common').glob('add_equal.sv'))
    svsrc += [ROOT/'rtl/common/pseudo_dual_port_ram.v',ROOT/'rtl/axi_top/npu_axil_reg_if.sv',
        ROOT/'rtl/axi_top/npu_axil_top.sv',ROOT/'test/models/soc_axi_ram.sv',HERE/'conv_cosim_top.sv']
    cflags=['-std=c11','-O2','-Wall','-Wextra','-Werror','-DDSA_MMIO_CUSTOM',f'-DDSA_TILE_SIZE={a.size}',
            '-DDSA_PS_FRAME_COUNT=16','-include',ROOT/'test/conv_driver/host_compat.h',
            '-I',nn/'Include','-I',ROOT/'drivers']
    simulator_config=ROOT/'test/conv_npu/simulator.vlt'
    inputs=set(csrc+svsrc+[HERE/'main.cpp',Path(__file__),simulator_config])
    inputs.update(npu.rglob('*.svh'))
    # Capture actual C headers before deciding whether --skip-build is safe.
    # The common planner and NMSIS headers are not standalone compile sources.
    for src in csrc:
        dependencies=subprocess.check_output(
            [str(v) for v in ['gcc',*cflags,'-MM','-MT','deps',src]],cwd=ROOT,text=True)
        names=shlex.split(dependencies.replace('\\\n',' ').split(':',1)[1])
        inputs.update((ROOT/name).resolve() for name in names)
    status={'verification_level':'production NMSIS C and MMIO driver + real npu_axil_top RTL + production soc_axi_ram',
        'size':a.size,'enable_per_channel':int(not a.disabled_per_channel),
        'enable_is_mode':int(not a.disabled_is),'weight_width':8 if a.narrow_kernel else 16,
        'verilator':subprocess.check_output([a.verilator,'--version'],text=True).strip(),
        'gcc':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)},'tests':[]}
    manifest=build/'build_manifest.json'
    if a.skip_build:
        if not manifest.exists():
            raise RuntimeError('No recorded build manifest; run without --skip-build')
        previous=json.loads(manifest.read_text())
        if (previous['source_sha256'] != status['source_sha256'] or previous['size'] != a.size or
                any(previous.get(key,default)!=status[key] for key,default in
                    [('enable_per_channel',1),('enable_is_mode',1),('weight_width',16)])):
            raise RuntimeError('Source files changed since this binary was built; omit --skip-build')
        status['build']=previous['build']
    if not a.skip_build:
        objects=[]
        for i,src in enumerate(csrc):
            obj=build/f'c{i}.o';objects.append(obj)
            cmd=['gcc',*cflags,'-c',src,'-o',obj]
            if run(cmd,out/f'c{i}_build.log'):
                print((out/f'c{i}_build.log').read_text());return 1
        lib=build/'libdriver.a'
        if run(['ar','rcs',lib,*objects],out/'archive.log'):return 1
        cppflags=f'-std=c++17 -O1 -D__GNUC_PYTHON__ -DDSA_MMIO_CUSTOM -DDSA_TILE_SIZE={a.size} -DDSA_PS_FRAME_COUNT=16 -I{nn/"Include"} -I{ROOT/"drivers"}'
        cmd=[a.verilator,'--cc','--exe','--build','--assert','--top-module','conv_cosim_top','-Wno-fatal',
            f'-I{npu/"ps_compact"}',f'-GSIZE={a.size}',f'-GENABLE_PER_CHANNEL={int(not a.disabled_per_channel)}',
            f'-GENABLE_IS_MODE={int(not a.disabled_is)}',f'-GWEIGHT_WIDTH={8 if a.narrow_kernel else 16}',
            '--Mdir',build/'obj','-j',a.jobs,
            '-CFLAGS',cppflags,'-LDFLAGS',str(lib),'-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0',simulator_config,*svsrc,HERE/'main.cpp']
        rc=run(cmd,out/'rtl_build.log',timeout=1200)
        log=(out/'rtl_build.log').read_text()
        source_after={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                      for name in status['source_sha256']}
        unchanged=source_after==status['source_sha256']
        if not unchanged:rc=125
        status['build']={'returncode':rc,'command':[str(v) for v in cmd],
            'sources_unchanged_during_build':unchanged,
            'warnings':{name:log.count('%Warning-'+name+':') for name in sorted(set(re.findall(r'%Warning-([^:]+):',log)))}}
        (out/'status.json').write_text(json.dumps(status,indent=2)+'\n')
        if rc:print(log[-10000:]);return 1
        manifest.write_text(json.dumps(status,indent=2)+'\n')
    binary=build/'obj/Vconv_cosim_top'
    if a.disabled_per_channel:
        suites=[('disabled_per_channel',['+CONV_DISABLED_PER_CHANNEL','+DDR_RAND_LAT=1'])]
        marker='CONV_DISABLED_PER_CHANNEL_PASS'
    elif a.disabled_is:
        suites=[(profile,['+CONV_DISABLED_IS','+DDR_RAND_LAT=1'])]
        marker='CONV_DISABLED_IS_PASS'
    elif a.axil_protocol_only:
        suites=[('axil_protocol',['+AXIL_PROTOCOL_ONLY','+DDR_RAND_LAT=1','+DDR_CMD_MAX_LAT=3','+DDR_W_MAX_LAT=3','+DDR_RSP_MAX_LAT=3'])]
        marker='AXIL_PROTOCOL_PASS'
    else:
        suites=[('fixed',['+DDR_RAND_LAT=0']),('random',['+DDR_RAND_LAT=1','+DDR_CMD_MAX_LAT=3','+DDR_W_MAX_LAT=3','+DDR_RSP_MAX_LAT=3'])]
        marker='CONV_C_RTL_COSIM_PASS'
    for name,flags in suites:
        rc=run([binary,*flags],out/f'{name}.log',timeout=300)
        log=(out/f'{name}.log').read_text();print(log,flush=True)
        passed=rc==0 and marker in log
        status['tests'].append({'name':name,'passed':passed,'returncode':rc,'log':str(out/f'{name}.log'),
            'case_lines':[line for line in log.splitlines() if line.startswith(('COSIM_','AXIL_PROTOCOL','CONV_DISABLED_'))]})
        (out/'status.json').write_text(json.dumps(status,indent=2)+'\n')
        if not passed:return 1
    return 0
if __name__=='__main__':sys.exit(main())
