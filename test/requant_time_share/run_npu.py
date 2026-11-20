#!/usr/bin/env python3
"""在完整生产NPU中检查分时量化的组预留、数值结果和恢复。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--verilator',default='verilator');p.add_argument('--jobs',type=int,default=1);p.add_argument('--build-timeout',type=int,default=7200)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    executable=shutil.which(a.verilator)
    if executable is None:raise RuntimeError('Verilator unavailable')
    observers=[ROOT/'test/requant_time_share'/name for name in
               ('npu_observer.sv','npu_configuration_observer.sv')]
    sources=[ROOT/s for s in ['rtl/npu/top/npu_top.sv','rtl/npu/writeback/vec_requant.sv','rtl/npu/writeback/requant_group_buffer.sv','rtl/npu/writeback/requant_compute_lane.sv']]+observers
    hashes={str(s.relative_to(ROOT)):sha(s) for s in sources}
    wrapper=out/'verilator_requant_time_share'
    wrapper.write_text('#!'+sys.executable+'\nimport os,sys\ncommand='+repr([executable,*map(str,observers)])+'+sys.argv[1:]\nos.execv(command[0],command)\n');wrapper.chmod(0o755)
    cmd=[sys.executable,str(ROOT/'test/weight_prefetch/run_npu.py'),'--out',str(out/'suite'),'--verilator',str(wrapper),'--jobs',str(a.jobs),'--build-timeout',str(a.build_timeout)]
    with (out/'run.log').open('w') as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    suite=json.loads((out/'suite/summary.json').read_text());coverage=[];configuration_coverage=[]
    for p in sorted((out/'suite').rglob('*.log')):
        for line in p.read_text(errors='replace').splitlines():
            if line.startswith('REQUANT_GROUP_NPU_PASS '):coverage.append({'log':str(p.relative_to(out)),**{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}})
            if line.startswith('REQUANT_CONFIGURATION_NPU_PASS '):configuration_coverage.append({'log':str(p.relative_to(out)),**{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}})
    if not coverage or max(x['maximum_rows'] for x in coverage)<256:raise RuntimeError('Large group coverage incomplete')
    if not configuration_coverage or sum(x['pending_cycles'] for x in configuration_coverage)==0:raise RuntimeError('Configuration lifetime coverage incomplete')
    if hashes!={str(s.relative_to(ROOT)):sha(s) for s in sources}:raise RuntimeError('Sources changed during verification')
    result={'passed':suite['passed'],'source_sha256':hashes,'coverage':coverage,'configuration_coverage':configuration_coverage,'simulator_manifest':suite['simulator_manifest'],'runs':suite['runs']}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'coverage':coverage}))
if __name__=='__main__':main()
