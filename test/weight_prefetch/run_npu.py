#!/usr/bin/env python3
"""检查生产 NPU 的权重提交条件、有效权重及完整数值结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=1)
    parser.add_argument('--build-timeout',type=int,default=7200)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    executable=shutil.which(args.verilator)
    if executable is None:raise RuntimeError('Cannot find Verilator: '+args.verilator)
    observer=ROOT/'test/weight_prefetch/npu_observer.sv'
    sources=[ROOT/'rtl/npu/compute'/name for name in ('ws_systolic_cell.sv','ws_systolic_array.sv','compute_core.sv')]+[observer]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    wrapper=out/'verilator_weight_prefetch'
    wrapper.write_text('#!'+sys.executable+'\nimport os,sys\ncommand='+repr([executable,str(observer)])+'+sys.argv[1:]\nos.execv(command[0],command)\n')
    wrapper.chmod(0o755)
    command=[sys.executable,str(ROOT/'test/frame_address/run_npu.py'),'--out',str(out/'suite'),
             '--verilator',str(wrapper),'--jobs',str(args.jobs),'--build-timeout',str(args.build_timeout)]
    with (out/'run.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    suite=json.loads((out/'suite/summary.json').read_text())
    coverage=[]
    for path in sorted((out/'suite').rglob('*.log')):
        for line in path.read_text(errors='replace').splitlines():
            if line.startswith(('WEIGHT_PREFETCH_NPU_PASS ','WEIGHT_PREFETCH_ARRAY_PASS ')):
                coverage.append({'log':str(path.relative_to(out)),'kind':line.split()[0],
                    **{key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}})
    if not any(row.get('resident_starts',0)>0 for row in coverage):
        raise RuntimeError('Resident reuse coverage missing')
    if not any(row.get('row_commit_overlaps',0)>0 for row in coverage):
        raise RuntimeError('Overlapping weight commit coverage missing')
    if hashes!={str(p.relative_to(ROOT)):digest(p) for p in sources}:
        raise RuntimeError('Sources changed during verification')
    report={'passed':suite['passed'],'source_sha256':hashes,'coverage':coverage,
            'simulator_manifest':suite['simulator_manifest'],'runs':suite['runs']}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'coverage':coverage},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
