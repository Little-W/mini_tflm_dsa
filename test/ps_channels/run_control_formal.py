#!/usr/bin/env python3
"""证明存储布局选择保持帧控制、数据和有效信号的周期。"""
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
SOURCE='rtl/npu/ps_compact/ps_frame_store.sv'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref',default='975ce61')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original=read_rtl_source(args.reference_ref+':'+SOURCE, cwd=ROOT)
    reference=out/'reference.sv';reference.write_bytes(original)
    current=ROOT/SOURCE;regfile=ROOT/'rtl/common/regfile.v'
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (current,regfile)}
    summary={'passed':False,'reference_ref':args.reference_ref,'source_sha256':hashes,
             'reference_sha256':hashlib.sha256(original).hexdigest(),'inputs_constrained':False,
             'method':'complete-state SAT and temporal induction after removing only external RAM address outputs for fixed-layout comparison',
             'runs':[]}
    for bank_bytes,banks,max_rows in ((2048,7,128),(8192,7,512),(8192,9,1024)):
        for fixed in (False,True):
            label=f'b{bank_bytes}_n{banks}_fixed{int(fixed)}';folder=out/label;folder.mkdir(exist_ok=True)
            commands=[]
            options=(f'-GEXTERNAL_RAM=1 -GPOOL_BYTES={(banks-1)*bank_bytes} -GBANK_BYTES={bank_bytes} '
                     f'-GMAX_FRAME_ROWS={max_rows} -GRAM_ADDR_BITS={(banks*(bank_bytes//16)-1).bit_length()}')
            for variant,source in (('reference',reference),('current',current)):
                option=options+(f' -Gp_fixed_ps_channels={int(fixed)}' if variant=='current' else '')
                commands.extend([f'read_slang --top ps_frame_store {option} {shlex.quote(str(source))} {shlex.quote(str(regfile))}',
                                 'prep -top ps_frame_store -flatten'])
                if fixed:commands.extend(['delete w:ram_read_addr w:ram_write_addr','opt_clean'])
                commands.extend(['memory_map','async2sync','opt_clean',f'rename ps_frame_store {variant}',f'design -stash {variant}'])
            commands.extend(['design -copy-from reference -as reference reference','design -copy-from current -as current current',
                             'equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1',
                             'opt_clean','equiv_induct -seq 2','equiv_status -assert'])
            script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n')
            log=folder/'formal.log'
            with log.open('w') as stream:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                      stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
            text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
            report={'bank_bytes':bank_bytes,'banks':banks,'max_frame_rows':max_rows,'fixed_channels':fixed,
                    'passed':result.returncode==0 and 'Equivalence successfully proven' in text,
                    'equivalent_bits':int(match[1]) if match else None,
                    'excluded_outputs':['ram_read_addr','ram_write_addr'] if fixed else [],
                    'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
            summary['runs'].append(report)
            print(json.dumps(report),flush=True)
            if not report['passed']:raise RuntimeError(text[-8000:])
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (current,regfile)}:
        raise RuntimeError('Source changed during control verification')
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':
    main()
