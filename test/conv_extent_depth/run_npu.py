#!/usr/bin/env python3
"""Run the complete NPU regression with tensor extent consumption checks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator-modern')
    parser.add_argument('--jobs',type=int,default=1)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    executable=shutil.which(args.verilator)
    if not executable:raise RuntimeError('Verilator is unavailable')
    inputs=[ROOT/'rtl/npu/top/npu_top.sv',HERE/'observer.sv',Path(__file__).resolve()]
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    hashes={str(p.relative_to(ROOT)):digest(p) for p in inputs}
    wrapper=out/'verilator_extents'
    wrapper.write_text('#!'+sys.executable+'\nimport os,sys\ncommand='+
                       repr([executable,str(HERE/'observer.sv')])+
                       '+sys.argv[1:]\nos.execv(command[0],command)\n')
    wrapper.chmod(0o755)
    command=[sys.executable,str(ROOT/'test/npu_registered_fault/run.py'),
             '--out',str(out/'suite'),'--verilator',str(wrapper),'--jobs',str(args.jobs)]
    with (out/'run.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    suite=json.loads((out/'suite/summary.json').read_text())
    coverage=[]
    for path in sorted((out/'suite').rglob('*.log')):
        for line in path.read_text(errors='replace').splitlines():
            if line.startswith('CONV_EXTENT_PASS '):
                coverage.append(dict(log=str(path.relative_to(out)),
                    **{key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}))
    if not coverage or not all(sum(row[key] for row in coverage)>0
                              for key in ('checked_cycles','dma_initializations')):
        raise RuntimeError('Extent consumption coverage incomplete')
    if hashes!={str(p.relative_to(ROOT)):digest(p) for p in inputs}:
        raise RuntimeError('Verification sources changed during execution')
    result=dict(passed=suite['passed'],source_sha256=hashes,coverage=coverage,command=command,
                suite_report=str(out/'suite/summary.json'))
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=result['passed'],runs=len(coverage),
                         checked_cycles=sum(row['checked_cycles'] for row in coverage))))


if __name__=='__main__':main()
