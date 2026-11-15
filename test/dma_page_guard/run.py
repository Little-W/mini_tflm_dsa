#!/usr/bin/env python3
"""Test page splitting, ordered responses, and GEMM bus-error recovery."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def command(args,log):
    with log.open('w') as stream:
        subprocess.run([str(x) for x in args],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)

def page_guard(out,verilator):
    out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/conv/conv_axi_read_guard.sv',ROOT/'rtl/npu/dma/axi_write_page_guard.sv',
             HERE/'dma_page_guard_top.sv',HERE/'main.cpp']
    command([verilator,'--cc','--exe','--assert','-Wall','-Wno-fatal','--top-module','dma_page_guard_top',
             '--Mdir',out/'obj','-CFLAGS','-std=c++20 -O1',*sources],out/'compile.log')
    command(['make','-C',out/'obj','-f','Vdma_page_guard_top.mk','-j1','OPT_FAST=-O1','OPT_SLOW=-O0'],out/'make.log')
    command([out/'obj/Vdma_page_guard_top'],out/'run.log')
    text=(out/'run.log').read_text()
    if 'DMA_PAGE_GUARD_PASS' not in text:raise RuntimeError(text)
    return {'summary':text.strip(),'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}

def npu_errors(out,verilator):
    out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('conv_npu_tests',ROOT/'test/conv_npu/run.py')
    tests=importlib.util.module_from_spec(spec)
    sys.path.insert(0,str(ROOT/'test/conv_npu'))
    spec.loader.exec_module(tests)
    tasks=[]
    for name,kind in [('cross_page',0),('read_error',1),('read_recovery',0),('write_error',2),('write_recovery',0)]:
        d=out/name;d.mkdir(exist_ok=True)
        command([sys.executable,ROOT/'veri/top_regression/gen_mem.py','--out_dir',d,'--size',4,
                 '--ia_cache_blocks',4,'--ps_frame_count',16,'--mem_words',tests.WORDS,
                 '--K',1,'--N',7,'--M',4,'--lhs_dtype',2,'--dataflow_mode',0,
                 '--per_channel','--random','--random_quant','--tight_strides','--seed',789],d/'generate.log')
        cfg=[int(v,16) for v in (d/'config.mem').read_text().split()]+[0]*32
        initial=tests.load_sparse(d/'init.mem');golden=tests.load_sparse(d/'golden.mem')
        original=bytes(initial);expected=bytes(golden)
        old_output=cfg[17];golden[old_output:old_output+4]=initial[old_output:old_output+4]
        for field,address,count in [(14,0x10ffd,14),(15,0x20ffd,28),(17,0x30fff,4)]:
            old=cfg[field];initial[address:address+count]=original[old:old+count]
            golden[address:address+count]=expected[old:old+count];cfg[field]=address
        if kind==1:golden=bytearray(initial)
        cfg[52]=3 if kind else 0;cfg[53]=kind
        (d/'config.mem').write_text(''.join(f'{v:08x}\n' for v in cfg))
        tests.sparse_mem(d/'init.mem',initial);tests.sparse_mem(d/'golden.mem',golden)
        (d/'required.mem').write_text('@00000000\n0\n');tasks.append(d)
    binary=tests.build(out,4,verilator,1)
    result=tests.run_suite(binary,out,'gemm_bus_errors',tasks)
    if not result['passed']:raise RuntimeError((out/'gemm_bus_errors.log').read_text()[-6000:])
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--guard-only',action='store_true')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    result={'page_guard':page_guard(args.out/'page_guard',args.verilator)}
    if not args.guard_only:result['gemm_errors']=npu_errors(args.out/'npu_errors',args.verilator)
    result['passed']=True
    (args.out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
