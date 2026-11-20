#!/usr/bin/env python3
"""比较偏置驻留检查的全部状态与输出，包含计数器最高位进位。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/loaders/bias_loader_buffer.sv'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref',default='975ce61')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original=subprocess.check_output(['git','show',args.reference_ref+':'+SOURCE],cwd=ROOT,text=True)
    marker='  logic [CNT_W-1:0]             bank_blocks_count [2];'
    assert marker in original
    observer=marker+'''\n  (* keep *) wire [CNT_W:0] bank_end_q [2];
  for (genvar bank=0;bank<2;bank++) begin : g_formal_range
    assign bank_end_q[bank]={1'b0,bank_block_idx[bank]}+{1'b0,bank_blocks_count[bank]};
  end
'''
    reference=out/'reference.sv';reference.write_text(original.replace(marker,observer))
    current=ROOT/SOURCE;memory=ROOT/'rtl/common/REGFILE.v'
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (current,memory)}
    summary={'passed':False,'reference_ref':args.reference_ref,'source_sha256':hashes,
             'inputs_constrained':False,'reference_observer':'combinational sum of the original stored base and count',
             'original_reference_sha256':hashlib.sha256(original.encode()).hexdigest(),'runs':[]}
    for size,bus,count_width,groups in ((4,32,1,1),(16,32,12,4),(16,64,28,32),(16,64,32,1)):
        folder=out/f's{size}_b{bus}_c{count_width}_g{groups}';folder.mkdir(exist_ok=True)
        options=f'-GSIZE={size} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count_width} -GGROUP_BLOCKS_MAX={groups}'
        commands=[]
        for name,source in (('reference',reference),('current',current)):
            commands.extend([f'read_slang --top bias_loader_buffer {options} {shlex.quote(str(source))} {shlex.quote(str(memory))}',
                             'prep -top bias_loader_buffer -flatten','memory_map','async2sync','opt_clean',
                             f'rename bias_loader_buffer {name}',f'design -stash {name}'])
        commands.extend(['design -copy-from reference -as reference reference','design -copy-from current -as current current',
                         'equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1',
                         'opt_clean','equiv_induct -seq 2','equiv_status -assert'])
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        with log.open('w') as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                  stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
        text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
        report={'SIZE':size,'BUS_WIDTH':bus,'COUNT_WIDTH':count_width,'GROUP_BLOCKS_MAX':groups,
                'passed':result.returncode==0 and 'Equivalence successfully proven' in text,
                'equivalent_bits':int(match[1]) if match else None,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        summary['runs'].append(report);print(json.dumps(report),flush=True)
        if not report['passed']:raise RuntimeError(text[-9000:])
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (current,memory)}:
        raise RuntimeError('Source changed during verification')
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
