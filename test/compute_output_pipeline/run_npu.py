#!/usr/bin/env python3
"""在完整生产 NPU 中检查计算输出周期、参数初始化和全部事务数值。"""
from __future__ import annotations
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator-modern')
    parser.add_argument('--jobs',type=int,default=1)
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    executable=shutil.which(args.verilator)
    if executable is None:
        raise RuntimeError('Verilator unavailable')
    sources=[ROOT/'rtl/npu/compute/compute_core.sv',ROOT/'rtl/npu/top/npu_top.sv',
             HERE/'npu_observer.sv',Path(__file__).resolve()]
    hashes={str(path.relative_to(ROOT)):digest(path) for path in sources}
    wrapper=out/'verilator_output_pipeline'
    wrapper.write_text('#!'+sys.executable+'\nimport os,sys\ncommand='+
                       repr([executable,str(HERE/'npu_observer.sv')])+
                       '+sys.argv[1:]\nos.execv(command[0],command)\n')
    wrapper.chmod(0o755)
    command=[sys.executable,str(ROOT/'test/requant_time_share/run_npu.py'),
             '--out',str(out/'suite'),'--verilator',str(wrapper),'--jobs',str(args.jobs)]
    with (out/'run.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    suite=json.loads((out/'suite/summary.json').read_text())
    rows=[]
    contexts=[]
    for path in sorted((out/'suite').rglob('*.log')):
        for line in path.read_text(errors='replace').splitlines():
            if line.startswith(('COMPUTE_OUTPUT_PIPELINE_PASS ','COMPUTE_OUTPUT_CONTEXT_PASS ')):
                record={'log':str(path.relative_to(out)),
                        **{key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}}
                (rows if line.startswith('COMPUTE_OUTPUT_PIPELINE_PASS ') else contexts).append(record)
    if not rows or not contexts or not any(record['intermediate_completions'] for record in rows):
        raise RuntimeError('Compute output integration coverage incomplete')
    if hashes != {str(path.relative_to(ROOT)):digest(path) for path in sources}:
        raise RuntimeError('Source changed during integration comparison')
    report=dict(passed=suite['passed'],source_sha256=hashes,sources_unchanged=True,
                output_latency_cycles=1,final_completion_latency_cycles=1,
                intermediate_completion_latency_cycles=0,output_coverage=rows,
                initialization_coverage=contexts,simulator_manifest=suite['simulator_manifest'],
                command=command,suite_report=str(out/'suite/summary.json'))
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],checked_values=sum(row['values'] for row in rows),
                         initializations=sum(row['initializations'] for row in contexts))),flush=True)


if __name__=='__main__':
    main()
