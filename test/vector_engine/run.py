#!/usr/bin/env python3
"""Test the Vector Compute Engine and DMA using independent integer references."""
from pathlib import Path
import argparse,hashlib,json,re,shlex,subprocess,sys
from prepare_add_replay import prepare_replay
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
    p.add_argument('--verilator',default='verilator');p.add_argument('--out',type=Path,default=ROOT/'build/vector_engine')
    p.add_argument('--pes',type=int,nargs='+',help='parallel PE counts; default min(8, tile)');p.add_argument('--tile',type=int,default=16)
    p.add_argument('--jobs',type=int,default=1);p.add_argument('--perf',action='store_true');p.add_argument('--skip-build',action='store_true')
    p.add_argument('--window-study',action='store_true',help='aligned DW shapes with the common two-cycle read service')
    p.add_argument('--cache-sets',type=int,default=128);p.add_argument('--cache-policy',type=int,choices=range(4),default=3)
    p.add_argument('--prepared',type=Path,help='prepared model directory containing nearest-even Add tensors')
    p.add_argument('--softmax-replay',type=Path,help='Softmax tables and original model tensors')
    a=p.parse_args();a.pes=a.pes or [min(8,a.tile)];out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    csrc=[HERE/'reference.c',HERE/'reference_add.c']
    conv=ROOT/'rtl/npu/conv'
    svsrc=[conv/'conv_im2col_pkg.sv',conv/'vector_engine_pkg.sv']
    svsrc += [x for x in sorted(conv.rglob('*.sv')) if x not in svsrc]
    svsrc += list(sorted((ROOT/'rtl/npu/dma').rglob('*.sv')))
    svsrc += [ROOT/'rtl/common/pseudo_dual_port_ram.v',HERE/'vector_engine_dma_top.sv']
    import runpy
    svsrc = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](svsrc)
    cflags=['-std=c11','-O2','-Wall','-Wextra','-Werror']
    result={'verification':'RTL engine + production DMA; independent signed-integer nearest-even reference','tile':a.tile,'cache_sets':a.cache_sets,'cache_policy':a.cache_policy,
            'verilator':subprocess.check_output([a.verilator,'--version'],text=True).strip(),'runs':[]}
    if a.window_study:
        result['workload_suite']='aligned depthwise windows'
        result['memory_service']={'bus_bits':32,'first_read_response_after_ar_cycles':3,
                                  'read_beat_interval_cycles':2,'between_read_bursts_cycles':3,
                                  'random_wait':False}
    replay=out/'add_replay.bin'
    if a.prepared: result['replay']=prepare_replay(a.prepared,replay)
    for pe in a.pes:
        folder=out/f'pe{pe}';folder.mkdir(exist_ok=True);objects=[]
        sources=set(csrc+svsrc+[HERE/'main.cpp',HERE/'prepare_add_replay.py',Path(__file__)]+list(HERE.glob('*.h')))
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
            command([a.verilator,'--cc','--exe','--assert','--top-module','vector_engine_dma_top','-Wno-fatal',
                     '-Wno-PINMISSING',f'-GTILE={a.tile}',f'-GPE_COUNT={pe}',f'-GCACHE_SETS={a.cache_sets}',f'-GCACHE_POLICY={a.cache_policy}','--Mdir',folder/'obj',
                     '--output-groups','0','--output-split','12000','--output-split-cfuncs','200',
                     '-CFLAGS',f'-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096 -DTEST_TILE_SIZE={a.tile}',
                     '-LDFLAGS',lib,ROOT/'test/conv_npu/simulator.vlt',*svsrc,HERE/'main.cpp'],folder/'verilate.log')
            command(['make','-C',folder/'obj','-f','Vvector_engine_dma_top.mk','-j',a.jobs,
                     'OPT_FAST=-O1','OPT_SLOW=-O0','OPT_GLOBAL=-O1','VK_PCH_I_FAST=',
                     'VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E'],folder/'build.log')
            if any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in source_sha.items()):
                raise RuntimeError('Sources changed during compilation; rebuild required')
            manifest.write_text(json.dumps({'sha256':source_sha,'pe':pe,'tile':a.tile,'cache_sets':a.cache_sets,'cache_policy':a.cache_policy},indent=2)+'\n')
        else:
            old=json.loads(manifest.read_text())
            if old!={'sha256':source_sha,'pe':pe,'tile':a.tile,'cache_sets':a.cache_sets,'cache_policy':a.cache_policy}:raise RuntimeError('Sources or parameters changed; rebuild required')
        logfile=folder/('perf.log' if a.perf else 'functional.log')
        command([folder/'obj/Vvector_engine_dma_top']+(['--perf'] if a.perf else [])+(['--window-study'] if a.window_study else [])+
                (['--replay',replay] if a.prepared else [])+
                (['--softmax-replay',a.softmax_replay.resolve()] if a.softmax_replay else []),logfile)
        text=logfile.read_text();print(text,flush=True);assert 'VECTOR_ENGINE_DMA_PASS' in text
        rows=[]
        for line in text.splitlines():
            if line.startswith('CASE '):
                parts=line.split();rows.append({'name':parts[1],**{k:int(v) for k,v in (pair.split('=') for pair in parts[2:])}})
        totals=re.search(r'VECTOR_ENGINE_DMA_PASS cases=(\d+) outputs=(\d+) add_cases=(\d+) add_outputs=(\d+) softmax_cases=(\d+) softmax_outputs=(\d+)',text)
        if not totals: raise RuntimeError('Incomplete verification result')
        result['runs'].append({'pe':pe,'passed':True,'cases':rows,'log':str(logfile),
                              'totals':dict(zip(('cases','outputs','add_cases','add_outputs','softmax_cases','softmax_outputs'),map(int,totals.groups()))),
                              'executable_sha256':hashlib.sha256((folder/'obj/Vvector_engine_dma_top').read_bytes()).hexdigest()})
        (out/('performance.json' if a.perf else 'summary.json')).write_text(json.dumps(result,indent=2)+'\n')
    return 0
if __name__=='__main__':sys.exit(main())
