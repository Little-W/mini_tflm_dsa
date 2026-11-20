#!/usr/bin/env python3
"""对实际 SoC RAM 命令判定执行完整二态输入 SAT 等价检查。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from common import ROOT,snapshot,miter


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='1ff5aaee')
    args=parser.parse_args();out=args.out.resolve()
    functions,inputs=snapshot(out/'inputs',args.reference)
    model=out/'miter.sv';model.write_text(miter(*functions))
    rows=[]
    for aw in [8,16,32,40]:
        for shift in range(6):
            script=out/f'aw{aw}_s{shift}.ys';log=script.with_suffix('.log')
            script.write_text(f'read_verilog -formal -sv {model}\n'
                f'chparam -set AW {aw} -set ADDR_LSB {shift} command_miter\n'
                'prep -top command_miter -flatten\n'
                'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                    '--worker',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
            assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
            rows.append({'address_width':aw,'address_lsb':shift,'passed':True,
                         'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    (out/'summary.json').write_text(json.dumps({'passed':True,'inputs':inputs,
        'domain':'all two-state inputs','input_assumptions':[],
        'miter_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'profiles':rows},indent=2)+'\n')
    print(json.dumps({'passed':True,'profiles':len(rows)}))


if __name__=='__main__':main()
