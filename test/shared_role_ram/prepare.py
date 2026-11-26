#!/usr/bin/env python3
"""保存共享通道两种返回行为的完整模块综合输入及文件摘要。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'rtl/npu/buffers/ia_ps_channel_ram.sv'
    role=ROOT/'rtl/npu/buffers/ia_ps_role_ram.sv'
    snapshot=out/source.name;snapshot.write_bytes(source.read_bytes())
    role_snapshot=out/role.name;role_snapshot.write_bytes(role.read_bytes())
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources=resolve([snapshot,role_snapshot],ROOT)
    parameters=dict(p_bank_bytes=8192,p_total_bytes=57344,p_shared_write_stage=1,
                    p_ia_nonempty_writes=1,p_paired_ia_ports=1)
    cases={}
    for label,value in [('held',0),('independent',1)]:
        selected=dict(parameters,p_allow_inactive_return_updates=value)
        cases[label]=dict(top='ia_ps_channel_ram',sources=list(map(str,sources)),parameters=selected,
            options=['-DSYNTHESIS=1','-DXILINX_FPGA=1']+[f'-G{k}={v}'for k,v in selected.items()],
            configuration='完整通道 RAM，保持全部容量、地址端口和逐周期读写能力')
    hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest()for path in sources}
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps(dict(source_sha256=hashes),indent=2)+'\n')


if __name__=='__main__':main()
