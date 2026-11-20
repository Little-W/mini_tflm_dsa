#!/usr/bin/env python3
"""比较 IA 输入列排列的全部状态与公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/loaders/ia_loader_cache_mgr.sv'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref',default='05be5b8')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original=read_rtl_source(args.reference_ref+':'+SOURCE, cwd=ROOT, text=True)
    reference=out/'reference.sv';reference.write_text(original)
    current=ROOT/SOURCE
    memories=[ROOT/'rtl/common/regfile.v',ROOT/'rtl/common/pseudo_dual_port_ram.v']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [current,*memories]}
    summary={'passed':False,'reference_ref':args.reference_ref,'source_sha256':hashes,
             'inputs_constrained':False,
             'original_reference_sha256':hashlib.sha256(original.encode()).hexdigest(),'runs':[]}
    for size,bus,data_width,blocks,external in ((4,32,8,2,0),(8,64,16,4,0),(16,32,16,32,1),(16,64,16,32,1),(16,128,16,32,1)):
        folder=out/f's{size}_b{bus}_d{data_width}_c{blocks}_e{external}';folder.mkdir(exist_ok=True)
        options=f'-GSIZE={size} -GBUS_WIDTH={bus} -GDATA_WIDTH={data_width} -GCACHE_BLOCKS={blocks} -GEXTERNAL_RAM={external} -GRAM_WORD_ADDR_WIDTH=12'
        commands=[]
        for name,source in (('reference',reference),('current',current)):
            commands.extend([f'read_slang --top ia_loader_cache_mgr {options} {shlex.quote(str(source))} '+ ' '.join(shlex.quote(str(p)) for p in memories),
                             'prep -top ia_loader_cache_mgr -flatten','memory_map','async2sync','opt_clean',
                             f'rename ia_loader_cache_mgr {name}',f'design -stash {name}'])
        commands.extend(['design -copy-from reference -as reference reference','design -copy-from current -as current current',
                         'equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1',
                         'opt_clean','equiv_induct -seq 2','equiv_status -assert'])
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        with log.open('w') as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                  stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
        text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
        report={'SIZE':size,'BUS_WIDTH':bus,'DATA_WIDTH':data_width,'CACHE_BLOCKS':blocks,'EXTERNAL_RAM':external,
                'passed':result.returncode==0 and 'Equivalence successfully proven' in text,
                'equivalent_bits':int(match[1]) if match else None,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        summary['runs'].append(report);print(json.dumps(report),flush=True)
        if not report['passed']:raise RuntimeError(text[-9000:])
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [current,*memories]}:
        raise RuntimeError('Source changed during verification')
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
