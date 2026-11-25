#!/usr/bin/env python3
"""固定写回步长与完整控制器源码，并生成显式指定参数的综合配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('rtl/npu/writeback/oa_writer.sv')
sys.path.insert(0,str(ROOT/'test'))
from rtl_reference import read_rtl_source
from run_step import extract


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl',type=Path,default=ROOT/SOURCE)
    parser.add_argument('--reference',default='ed5c58ab')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    texts=dict(reference=read_rtl_source(f'{args.reference}:{SOURCE}',cwd=ROOT,text=True),
               current=args.rtl.read_text())
    cases={}
    for label,text in texts.items():
        step=out/f'step_{label}.sv';step.write_text(extract(text,'writer_step'))
        full=out/f'writer_{label}.sv';full.write_text(text)
        for top,path,count in [('writer_step',step,29),('oa_writer',full,29),('oa_writer',full,16)]:
            parameters=dict(REG_WIDTH=32,COUNT_WIDTH=count)
            if top=='oa_writer':parameters.update(VLEN=16,BUS_WIDTH=64)
            options=['-D','SYNTHESIS=1','-D','XILINX_FPGA=1']
            options += [f'-G{key}={value}' for key,value in parameters.items()]
            name=f'{"step" if top=="writer_step" else "writer"}_{label}_{count}'
            cases[name]=dict(top=top,sources=[str(path)],options=options,parameters=parameters,
                configuration='组步长捕获寄存器' if top=='writer_step' else '完整写回控制器')
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    report=dict(reference=args.reference,
        source_sha256={key:hashlib.sha256(text.encode()).hexdigest() for key,text in texts.items()},
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'sources.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    main()
