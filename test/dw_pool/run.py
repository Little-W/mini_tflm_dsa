#!/usr/bin/env python3
"""Build and run the production DW/pool engine, arbiter and DMA against NMSIS."""
from pathlib import Path
import argparse,hashlib,json,re,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def command(args,log):
    with log.open('w') as f:
        f.write('$ '+' '.join(map(str,args))+'\n');f.flush()
        result=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text()[-16000:]);raise RuntimeError(f'Command failed: {log}')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verilator',default='verilator');p.add_argument('--out',type=Path,default=ROOT/'build/dw_pool')
    p.add_argument('--pes',type=int,nargs='+',help='parallel PE counts; default min(8, tile)');p.add_argument('--tile',type=int,default=16)
    p.add_argument('--jobs',type=int,default=1);p.add_argument('--perf',action='store_true');p.add_argument('--skip-build',action='store_true')
    a=p.parse_args();a.pes=a.pes or [min(8,a.tile)];out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    nn=ROOT/'drivers/tflm/NMSIS/NN'
    csrc=[HERE/'reference.c',nn/'Source/ConvolutionFunctions/riscv_depthwise_conv_s8.c',
          nn/'Source/PoolingFunctions/riscv_avgpool_s8.c',nn/'Source/PoolingFunctions/riscv_max_pool_s8.c',
          nn/'Source/PoolingFunctions/riscv_avgpool_get_buffer_sizes_s8.c']
    conv=ROOT/'rtl/npu/conv'
    svsrc=[conv/'00_conv_im2col_pkg.sv',conv/'01_dw_pool_pkg.sv']
    svsrc += [x for x in sorted(conv.glob('*.sv')) if x not in svsrc]
    svsrc += list(sorted((ROOT/'rtl/npu/dma').glob('*.sv')))
    svsrc += [ROOT/'rtl/common/pseudo_dual_port_ram.v',HERE/'dw_pool_dma_top.sv']
    cflags=['-std=c11','-O2','-fwrapv','-Wall','-Wextra','-Werror','-DDSA_NN_DW_POOL_ENABLE=0',
            '-include',ROOT/'test/conv_driver/host_compat.h','-I',nn/'Include','-I',ROOT/'drivers']
    result={'verification':'RTL engine + production DMA; NMSIS scalar numerical reference','tile':a.tile,
            'verilator':subprocess.check_output([a.verilator,'--version'],text=True).strip(),'runs':[]}
    for pe in a.pes:
        folder=out/f'pe{pe}';folder.mkdir(exist_ok=True);objects=[]
        sources=set(csrc+svsrc+[HERE/'main.cpp',Path(__file__)])
        for src in csrc:
            deps=subprocess.check_output(list(map(str,['gcc',*cflags,'-MM','-MT','deps',src])),cwd=ROOT,text=True)
            sources.update((ROOT/x).resolve() for x in shlex.split(deps.replace('\\\n',' ').split(':',1)[1]))
        source_sha={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources}
        manifest=folder/'build.json'
        if not a.skip_build:
            for i,src in enumerate(csrc):
                obj=folder/f'c{i}.o';objects.append(obj)
                command(['gcc',*cflags,'-c',src,'-o',obj],folder/f'c{i}.log')
            lib=folder/'libreference.a';command(['ar','rcs',lib,*objects],folder/'ar.log')
            command([a.verilator,'--cc','--exe','--build','--assert','--top-module','dw_pool_dma_top','-Wno-fatal',
                     '-Wno-PINMISSING',f'-GTILE={a.tile}',f'-GPE_COUNT={pe}','--Mdir',folder/'obj','-j',a.jobs,
                     '-CFLAGS','-std=c++17 -O1','-LDFLAGS',lib,'-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0',*svsrc,HERE/'main.cpp'],folder/'build.log')
            if any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in source_sha.items()):
                raise RuntimeError('Sources changed during compilation; rebuild required')
            manifest.write_text(json.dumps({'sha256':source_sha,'pe':pe,'tile':a.tile},indent=2)+'\n')
        else:
            old=json.loads(manifest.read_text())
            if old!={'sha256':source_sha,'pe':pe,'tile':a.tile}:raise RuntimeError('Sources or parameters changed; rebuild required')
        logfile=folder/('perf.log' if a.perf else 'functional.log')
        command([folder/'obj/Vdw_pool_dma_top']+(['--perf'] if a.perf else []),logfile)
        text=logfile.read_text();print(text,flush=True);assert 'DW_POOL_DMA_PASS' in text
        rows=[]
        for line in text.splitlines():
            if line.startswith('CASE '):
                parts=line.split();rows.append({'name':parts[1],**{k:int(v) for k,v in (pair.split('=') for pair in parts[2:])}})
        result['runs'].append({'pe':pe,'passed':True,'cases':rows,'log':str(logfile),
                              'executable_sha256':hashlib.sha256((folder/'obj/Vdw_pool_dma_top').read_bytes()).hexdigest()})
        (out/('performance.json' if a.perf else 'summary.json')).write_text(json.dumps(result,indent=2)+'\n')
    return 0
if __name__=='__main__':sys.exit(main())
