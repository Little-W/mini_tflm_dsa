#!/usr/bin/env python3
"""比较两种存储布局的帧控制周期、连续重放和并行读写。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=[f'{size}:{banks}' for size in (2048,4096,8192) for banks in (6,7,8,9)])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/'rtl/npu/buffers/ia_ps_shared_ram.sv', ROOT/'rtl/common/regfile.v',
               ROOT/'rtl/npu/ps_compact/ps_frame_store.sv', ROOT/'test/ps_channels/tb_store.sv']
    hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    summary = {'passed':False, 'source_sha256':hashes, 'profiles':[]}
    for profile in args.profiles:
        size,banks = map(int, profile.split(':'))
        folder=out/f'b{size}_n{banks}'
        folder.mkdir(exist_ok=True)
        command=['verilator-modern','--binary','--timing','-Wno-fatal','-j','1','--top-module','tb_ps_channel_store',
                 '--Mdir',str(folder/'obj'),f'-Gp_bank_bytes={size}',f'-Gp_banks={banks}',*map(str,sources)]
        with (folder/'compile.log').open('w') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run([str(folder/'obj/Vtb_ps_channel_store')],cwd=ROOT,text=True,capture_output=True)
        (folder/'run.log').write_text(result.stdout+result.stderr)
        match=re.search(r'PS_CHANNEL_STORE_PASS (.*)',result.stdout)
        if result.returncode or not match:
            raise RuntimeError(result.stdout+result.stderr)
        report={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',match[1])}
        report.update(passed=True,total_bytes=size*banks)
        summary['profiles'].append(report)
        print(json.dumps(report),flush=True)
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}:
        raise RuntimeError('Source changed during frame verification')
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':
    main()
