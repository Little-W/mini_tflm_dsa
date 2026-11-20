#!/usr/bin/env python3
"""分别验证生产和默认地址就绪参数的完整地址、准备周期、中止及结果等待。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from run_formal import ROOT, digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=1)
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    script=Path(__file__).resolve()
    hashes={str(script.relative_to(ROOT)):digest(script)}
    profiles=[]
    for mask in (0,1):
        folder=out/f'ready_mask_{mask}'
        command=[sys.executable,str(ROOT/'test/frame_address/run.py'),'--out',str(folder),
            '--verilator',args.verilator,'--jobs',str(args.jobs),'--ready-mask-abort',str(mask)]
        with (out/f'ready_mask_{mask}.log').open('w') as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=900)
        profile=json.loads((folder/'summary.json').read_text())
        if not profile['passed'] or profile['ready_mask_abort'] != mask:
            raise RuntimeError(f'Address readiness validation did not pass: {mask}')
        for path,expected in profile['source_sha256'].items():
            if path in hashes and hashes[path] != expected:
                raise RuntimeError(f'Source differs between readiness parameters: {path}')
            hashes[path]=expected
        profiles.append(profile)
        print('ready_mask_abort',mask,'PASS',flush=True)
    for path,expected in hashes.items():
        if digest(ROOT/path) != expected:
            raise RuntimeError(f'Source changed during numeric validation: {path}')
    totals={key:sum(row[key] for row in profiles) for key in
        ('completed','cancelled','reset_cases','wait_checks','cycles','abort_ready_checks','idle_abort_checks')}
    report={'passed':True,'size':16,'address_width':32,'result_latency_cycles':10,
        'source_sha256':hashes,'profiles':profiles,'totals':totals,
        'counting':'Each parameter profile runs the generic and DSP implementations with identical inputs.'}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(totals,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
