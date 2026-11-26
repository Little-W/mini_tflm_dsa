#!/usr/bin/env python3
"""在完整生产 AXI 系统中检查普通双端口 RAM 的消费者资格和数值结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--prepare-only',action='store_true',help='仅生成可用于生产回归的消费者检查包装器')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    executable=shutil.which(args.verilator)
    if executable is None:raise RuntimeError('无法找到 Verilator')
    observer=Path(__file__).with_name('consumer_observer.sv').resolve()
    channel=ROOT/'rtl/npu/buffers/ia_ps_channel_ram.sv'
    snapshot=out/channel.name
    # 存储器采用 FPGA 返回行为，AXI 顶层继续使用已验证的通用时钟门控模型。
    snapshot.write_text('`define XILINX_FPGA 1\n'+channel.read_text()+'\n`undef XILINX_FPGA\n')
    wrapper=out/'verilator_role'
    command=[executable,str(observer)]
    wrapper.write_text('#!'+sys.executable+'\nimport os,sys\n'+
        'fpga=any("DXILINX_FPGA" in x for x in sys.argv[1:])\n'+
        'arguments=['+repr(str(snapshot))+' if not fpga and x=='+repr(str(channel))+' else x for x in sys.argv[1:]]\n'+
        'role='+repr(str(ROOT/'rtl/npu/buffers/ia_ps_role_ram.sv'))+'\n'+
        'if role not in arguments and any(x.endswith((".sv",".v")) for x in arguments):arguments.append(role)\n'+
        'command='+repr(command)+'+arguments\nos.execv(command[0],command)\n')
    wrapper.chmod(0o755)
    if args.prepare_only:
        print(wrapper,flush=True)
        return
    selected=[ROOT/'rtl/npu/top/npu_top.sv',ROOT/'rtl/npu/buffers/ia_ps_channel_ram.sv',
              ROOT/'rtl/npu/buffers/ia_ps_role_ram.sv',observer,Path(__file__)]
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    hashes={str(path.relative_to(ROOT)):digest(path)for path in selected}
    runner=ROOT/'test/vector_weight_qualification/run_shared_system.py'
    with (out/'run.log').open('w') as stream:
        subprocess.run([sys.executable,str(runner),'--out',str(out/'production'),
            '--verilator',str(wrapper),'--jobs',str(args.jobs)],cwd=ROOT,
            stdout=stream,stderr=subprocess.STDOUT,check=True)
    report=json.loads((out/'production/summary.json').read_text())
    assert report['passed']
    activity=[]
    for name in ['fixed','random']:
        log=(out/'production/system'/(name+'.log')).read_text()
        rows=re.findall(r'SHARED_ROLE_CONSUMER_PASS (.*)',log)
        assert len(rows)==1
        counts={key:int(value)for key,value in re.findall(r'(\w+)=(\d+)',rows[0])}
        assert all(counts[key]>0 for key in ['configurations','ia','ps','weights','quant','held_quant'])
        activity.append(dict(run=name,**counts))
    assert hashes=={str(path.relative_to(ROOT)):digest(path)for path in selected}
    report['shared_role_consumers']=activity
    report['role_sources_sha256']=hashes
    report['channel_snapshot_sha256']=digest(snapshot)
    report['simulation_configuration']='共享通道选择 FPGA 返回行为；AXI 顶层采用通用时钟门控模型'
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('SHARED_ROLE_SYSTEM_PASS',flush=True)


if __name__=='__main__':main()
