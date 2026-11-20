#!/usr/bin/env python3
"""生成修改前后完整向量引擎的独立综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-rev',default='b8b34d5')
    parser.add_argument('--bus-width',type=int,choices=(32,64),default=64)
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    reference=read_rtl_source(args.reference_rev+':rtl/npu/conv/vector_engine.sv', cwd=ROOT, text=True)
    path=out/'vector_reference.sv'
    path.write_text(reference.replace('module vector_engine #(','module vector_engine_reference #(',1))
    packages=[ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    support=packages+[p for p in sorted((ROOT/'rtl/npu/conv').glob('*.sv')) if p not in packages and p.name!='vector_engine.sv']
    cases={name:{'top':top,'options':['-GBUS_WIDTH='+str(args.bus_width)],
                  'sources':[str(p) for p in support+[source]],
                  'configuration':f'TILE16 PE8 BUS{args.bus_width} MAX_TAPS49 POOL_MAX_TAPS256'}
           for name,top,source in [('vector_reference','vector_engine_reference',path),
                                   ('vector_shared','vector_engine',ROOT/'rtl/npu/conv/vector_engine.sv')]}
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    manifest={'reference_rev':args.reference_rev,'reference_body_sha256':hashlib.sha256(reference.encode()).hexdigest(),
              'sources_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in support+[path,ROOT/'rtl/npu/conv/vector_engine.sv']}}
    (out/'sources.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(out/'cases.json')


if __name__=='__main__':main()
