#!/usr/bin/env python3
"""使用相同生产配置比较向量激活限幅与边界比较优化前后的完整向量引擎。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
out=args.out.resolve()
out.mkdir(parents=True,exist_ok=True)
sources=['rtl/npu/conv/'+name+'.sv'for name in ('vector_engine','vector_pe','vector_activation_clamp','vector_round_shift','vector_engine_control')]
reference=[]
for name in sources:
    path=out/Path(name).name
    path.write_text(subprocess.check_output(['git','show','86034eb4:'+name],cwd=ROOT,text=True))
    reference.append(str(path))
options=['-DSYNTHESIS=1','-DXILINX_FPGA=1','-GTILE=16','-GBUS_WIDTH=64','-GPE_COUNT=8',
         '-GWINDOW_LANES=8','-GSHARED_STORAGE_ENABLE=1','-GSHARED_QUANT_ENABLE=0',
         '-GSHARED_STORAGE_ADDR_WIDTH=12']
cases={name:{'top':'vector_engine','sources':files,'options':options,
             'configuration':'16通道、8个PE、64位总线、共享存储、本地量化'}
       for name,files in [('reference',reference),('candidate',[str(ROOT/p)for p in sources])]}
configuration=out/'cases.json'
configuration.write_text(json.dumps(cases,indent=2)+'\n')
subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',configuration,
                '--cases','reference','candidate','--out',out,'--through','pre_lut'],cwd=ROOT,check=True)
results={}
for name in cases:
    target=out/(name+'_cost')
    subprocess.run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/name,'--out',target,
                    '--mode','physical-cost','--delay-target-ps','6667','--wire-delay-ps','300',
                    '--max-lut-inputs','8'],cwd=ROOT,check=True)
    data=json.loads((target/'metrics.json').read_text())
    results[name]={'resources':data['resources'],'paths':data['paths'],
                   'manifest':json.loads((out/name/'manifest.json').read_text())}
(out/'summary.json').write_text(json.dumps({'production_options':options,'results':results},indent=2)+'\n')
