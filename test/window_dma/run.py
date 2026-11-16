#!/usr/bin/env python3
"""Verify ordered outstanding window requests through the production DMA."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def command(args,log):
    with log.open('w') as stream:
        stream.write('$ '+' '.join(map(str,args))+'\n');stream.flush()
        result=subprocess.run(list(map(str,args)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-12000:])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    conv=ROOT/'rtl/npu/conv'
    sources=[conv/'00_conv_im2col_pkg.sv',conv/'01_vector_engine_pkg.sv']
    sources += [p for p in sorted(conv.glob('*.sv')) if p not in sources]
    sources += sorted((ROOT/'rtl/npu/dma').glob('*.sv'))
    sources += [ROOT/'rtl/common/pseudo_dual_port_ram.v',HERE/'window_dma_top.sv',HERE/'main.cpp']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    command([args.verilator,'--cc','--exe','--assert','--top-module','window_dma_top',
             '-Wno-fatal','-Wno-PINMISSING','--Mdir',out/'obj','--output-groups','0',
             '--output-split','12000','-CFLAGS','-std=c++17',*sources],out/'elaborate.log')
    command(['make','-C',out/'obj','-f','Vwindow_dma_top.mk','-j',args.jobs,
             'OPT_FAST=-O1','OPT_SLOW=-O0','OPT_GLOBAL=-O1','VK_PCH_I_FAST=',
             'VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E'],out/'compile.log')
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==v for p,v in hashes.items())
    command([out/'obj/Vwindow_dma_top'],out/'run.log')
    text=(out/'run.log').read_text();assert 'WINDOW_DMA_PASS' in text
    result={'passed':True,'source_sha256':hashes,'executable_sha256':hashlib.sha256((out/'obj/Vwindow_dma_top').read_bytes()).hexdigest(),
            'log':str(out/'run.log'),'tests':[line for line in text.splitlines() if line.startswith(('CASE ','WINDOW_DMA_PASS'))]}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(text,end='')

if __name__=='__main__':main()
