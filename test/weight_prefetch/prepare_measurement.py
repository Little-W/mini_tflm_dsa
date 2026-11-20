#!/usr/bin/env python3
"""固定完整十六行十六列阵列的交换与覆盖写入综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[]
    for name in ('ws_systolic_cell.sv','ws_systolic_array.sv'):
        source=ROOT/'rtl/npu/compute'/name
        target=out/name;target.write_bytes(source.read_bytes());sources.append(target)
    cases={}
    for label,exchange in [('reference',1),('candidate',0)]:
        cases[label]={'top':'ws_systolic_array','options':['-D','SYNTHESIS=1','-GSIZE=16',
            '-GDATA_IN_WIDTH=16','-GWEIGHT_WIDTH=16','-GACC_WIDTH=32',f'-Gp_exchange_weights={exchange}'],
            'parameters':{'SIZE':16,'DATA_IN_WIDTH':16,'WEIGHT_WIDTH':16,'ACC_WIDTH':32,'p_exchange_weights':exchange},
            'sources':[str(p) for p in sources],
            'configuration':'完整16×16阵列，输入和权重均为16位，累加结果32位'}
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    (out/'input_manifest.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},indent=2)+'\n')

if __name__=='__main__':main()
