#!/usr/bin/env python3
"""证明整组量化预留覆盖阵列、缓存和算术流水中的全部行。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/s for s in ['rtl/npu/writeback/requant_group_buffer.sv','rtl/common/regfile.v','test/requant_time_share/buffer_proof.sv']]
    sources.append(ROOT/'test/monitors/requant_group_buffer_observer.sv')
    hashes={str(s.relative_to(ROOT)):sha(s) for s in sources};results=[]
    for rows in (1,3,16,512,1024):
        script=out/f'rows_{rows}.ys'
        script.write_text(f'read_slang --top requant_buffer_proof -Gp_rows={rows} '+ ' '.join(map(str,sources))+'\n'+
            'proc\nflatten\nopt -full\nmemory_map\nasync2sync\nchformal -lower\nopt -full\n'+
            'sat -seq 2 -tempinduct -maxsteps 8 -set-at 1 rst_n 0 -set-assumes -prove-asserts -verify -timeout 60\n')
        with (out/f'rows_{rows}.log').open('w') as log:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
        results.append({'rows':rows,'passed':True,'script_sha256':sha(script)})
    if hashes!={str(s.relative_to(ROOT)):sha(s) for s in sources}:raise RuntimeError('Sources changed during proof')
    summary={'passed':True,'source_sha256':hashes,'results':results,
        'assumptions':['整组仅在ready时预留，行数在1..深度之间','实际输入行数不超过已预留行数','输出仅消费已经发射的行'],
        'arbitrary_inputs':['整组和行的到达时间','行发射暂停','任意算术等待','复位与清空']}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
