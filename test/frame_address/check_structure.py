#!/usr/bin/env python3
"""检查共享地址乘加器的输出寄存器与实际组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, parameter, resources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['frame_address_prepare']
    dsps = {name:cell for name,cell in module['cells'].items() if cell['type']=='DSP48E1'}
    assert len(dsps)==1
    name, dsp = next(iter(dsps.items()))
    registers = {key:parameter(dsp,key) for key in ('AREG','BREG','MREG','PREG','CREG','OPMODEREG')}
    assert registers=={'AREG':0,'BREG':0,'MREG':0,'PREG':1,'CREG':0,'OPMODEREG':0}
    assert dsp['connections']['OPMODE'][:4]==['1','0','1','0']
    assert dsp['connections']['PCIN']==['0']*48
    paths = connected_paths(module,limit=5,group_limit=0)
    assert paths['graph_complete'] and paths['longest_register_path_cells']<=15
    report = {'passed':True,'mapped_sha256':hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'resources':resources(module['cells']),'dsp_name':name,'dsp_registers':registers,'paths':paths}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'dsp':1,'longest_register_path_cells':paths['longest_register_path_cells']}))


if __name__=='__main__':
    main()
