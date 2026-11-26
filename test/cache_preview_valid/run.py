#!/usr/bin/env python3
"""证明有效位候选选择的二值等价性，并检查四态传播。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    rtl=[ROOT/'rtl/npu/dma/cache/conv_cache_lookup_valid_select.sv']
    forward=ROOT/'rtl/npu/dma/cache/conv_cache_valid_forward.sv'
    rtl.append(forward if forward.exists() else ROOT/'rtl/npu/dma/cache/conv_cache_metadata_way.sv')
    sources=[HERE/'compare.sv',*rtl]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources+[HERE/'tb_four_state.sv',Path(__file__)]}
    cases=[]
    for sets in (2,16,64):
        script=out/f'formal_sets{sets}.ys'
        log=out/f'formal_sets{sets}.log'
        script.write_text('\n'.join([
            'read_slang --top cache_preview_valid_compare -G p_sets='+str(sets)+' '+shlex.join(map(str,sources)),
            'prep -top cache_preview_valid_compare -flatten',
            'opt_clean',
            'sat -verify -prove match 1 -show-inputs -show-outputs',
        ])+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        assert 'SUCCESS!' in log.read_text(),log
        cases.append({'sets':sets,'passed':True,'inputs_constrained':False})
        print('FORMAL_PASS sets='+str(sets),flush=True)
    binary=out/'four_state.vvp'
    with (out/'four_state_compile.log').open('w') as stream:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),*map(str,sources),str(HERE/'tb_four_state.sv')],
                       cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    result=subprocess.run(['vvp',str(binary)],capture_output=True,text=True,check=True,timeout=120)
    (out/'four_state.log').write_text(result.stdout+result.stderr)
    checks=int(re.search(r'CACHE_PREVIEW_VALID_PASS checks=(\d+)',result.stdout)[1])
    assert checks==282144
    assert hashes=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes}
    report={'passed':True,'formal':cases,'four_state_checks':checks,'source_sha256':hashes}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':
    main()
