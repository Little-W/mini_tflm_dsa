#!/usr/bin/env python3
"""保存生产 SoC RAM 的固定容量、AXI 参数及参考和当前综合输入。"""
import argparse
import json
from pathlib import Path
from common import snapshot

PARAMETERS={'DP':32768,'DW':64,'AW':32,'MEM_WORD_WIDTH':64,'INIT_EN':0,
            'READ_OUTSTANDING':4,'WRITE_OUTSTANDING':4,'READ_FIRST_LATENCY':2}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='1ff5aaee')
    args=parser.parse_args();out=args.out.resolve()
    _,inputs=snapshot(out,args.reference)
    cases={label:{'top':'soc_axi_ram','sources':[str(out/'production'/label/'soc_axi_ram.sv')],
                  'options':['-D','SYNTHESIS=1','-D','XILINX_FPGA=1']+
                            [f'-G{key}={value}' for key,value in PARAMETERS.items()],
                  'configuration':'生产 SoC RAM，保留全部容量及 AXI 读写处理'}
           for label in ['reference','current']}
    (out/'cases.json').write_text(json.dumps(cases,indent=2,ensure_ascii=False)+'\n')
    (out/'inputs.json').write_text(json.dumps({**inputs,'parameters':PARAMETERS},indent=2)+'\n')
    print(out/'cases.json')


if __name__=='__main__':main()
