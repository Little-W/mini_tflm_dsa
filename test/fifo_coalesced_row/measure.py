#!/usr/bin/env python3
"""综合相同的完整写回和 FIFO 连接，比较合并行结束选择的资源及路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
REFERENCE='8fe8b96991259ef9c7f0e18ad9fc326a1353fa8e'


def execute(command):
    subprocess.run(list(map(str,command)),cwd=ROOT,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default=REFERENCE)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--cases',nargs='+',choices=('reference','current'),default=['reference','current'])
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    reference=out/'reference_fifo.sv'
    reference.write_bytes(subprocess.check_output(['git','show',args.reference+':rtl/npu/writeback/vec_s8_to_fifo_full.sv'],cwd=ROOT))
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    wrapper=ROOT/'test/fifo_coalesced_row/fifo_oa_row_timing_top.sv'
    options=['-DSYNTHESIS=1','-DXILINX_FPGA=1','-GVLEN=16','-GBUS_WIDTH=64','-GCOUNT_WIDTH=28']
    cases={name:dict(top='fifo_oa_row_timing_top',configuration='完整写回与32个存储体的循环INT8 FIFO，64位总线和28位写回计数',
                    options=options,sources=list(map(str,resolve(inputs,ROOT))))
           for name,inputs in [('reference',[reference,wrapper]),('current',[wrapper])]}
    configuration=out/'cases.json';configuration.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    resume=['--resume'] if args.resume else []
    execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',configuration,
             '--cases',*args.cases,'--out',out,'--through','pre_lut',*resume])
    for label in args.cases:
        execute([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/label,
                 '--out',out/(label+'_mapped'),'--mode','physical-cost','--delay-target-ps','6667',
                 '--wire-delay-ps','300','--max-lut-inputs','8','--discard-abc9-temporaries',*resume])


if __name__=='__main__':
    main()
