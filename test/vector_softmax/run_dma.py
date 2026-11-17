#!/usr/bin/env python3
"""Test Softmax through production VCE, DMA and AXI with random backpressure."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def command(argv,log):
    result=subprocess.run([str(x) for x in argv],cwd=ROOT,capture_output=True,text=True)
    log.write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError(str(log)+'\n'+(result.stdout+result.stderr)[-12000:])
    return result.stdout

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--replay',type=Path)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    conv=ROOT/'rtl/npu/conv';harness=ROOT/'test/vector_engine'
    sv=[conv/'conv_im2col_pkg.sv',conv/'vector_engine_pkg.sv']
    sv += [p for p in sorted(conv.rglob('*.sv')) if p not in sv]
    sv += sorted((ROOT/'rtl/npu/dma').rglob('*.sv'))
    sv += [ROOT/'rtl/common/pseudo_dual_port_ram.v',harness/'vector_engine_dma_top.sv']
    objects=[]
    for name in ('reference','reference_add'):
        obj=out/(name+'.o');objects.append(obj)
        command(['gcc','-std=c11','-O2','-c',harness/(name+'.c'),'-o',obj],out/(name+'.log'))
    command([args.verilator,'--cc','--exe','--assert','--top-module','vector_engine_dma_top',
             '-Wno-fatal','-Wno-PINMISSING','-GTILE=16','-GPE_COUNT=8','--Mdir',out/'obj',
             '--output-groups','0','--output-split','12000','--output-split-cfuncs','200',
             '-CFLAGS','-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096',
             '-LDFLAGS',' '.join(map(str,objects)),*sv,HERE/'dma_main.cpp'],out/'verilate.log')
    command(['make','-C',out/'obj','-f','Vvector_engine_dma_top.mk','-j',args.jobs,
             'OPT_FAST=-O1','OPT_SLOW=-O0','OPT_GLOBAL=-O1','VK_PCH_I_FAST=',
             'VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E'],out/'build.log')
    executable=out/'obj/Vvector_engine_dma_top'
    stdout=command([executable,*([args.replay.resolve()] if args.replay else [])],out/'run.log')
    match=re.search(r'SOFTMAX_DMA_PASS cases=(\d+) outputs=(\d+)',stdout)
    if not match:raise RuntimeError('Missing DMA test completion')
    records=[]
    for line in stdout.splitlines():
        if line.startswith('CASE '):
            fields=line.split();records.append({'name':fields[1],**{k:int(v) for k,v in (field.split('=') for field in fields[2:])}})
    result={'passed':True,'tile':16,'pe_count':8,'bus_bits':32,'random_backpressure':True,
            'cases':int(match[1]),'outputs':int(match[2]),'records':records,
            'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}
    if args.replay:result['replay_sha256']=hashlib.sha256(args.replay.read_bytes()).hexdigest()
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(match[0])

if __name__=='__main__':main()
