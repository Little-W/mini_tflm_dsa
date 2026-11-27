#!/usr/bin/env python3
"""综合完整缓存，比较预读结果进入响应队列后的资源与全部寄存器路径。"""
import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def run(command):
    subprocess.run(list(map(str,command)),cwd=ROOT,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='51f725d020a390aeda7d1f79af3a1f19e9e161b6')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--dma',action='store_true',help='包含窗口队列、完整前端与 DMA 输出保存寄存器')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    relative='rtl/npu/dma/cache/conv_cache_request_path.sv'
    previous=out/'reference_request_path.sv'
    previous.write_bytes(subprocess.check_output(['git','show',args.reference+':'+relative],cwd=ROOT))
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    if args.dma:
        top='axi_dual_block_dma'
        sources=resolve([ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',
                         ROOT/'rtl/npu/dma/axi_dual_block_dma.sv'],ROOT)
        parameters=dict(DATA_WIDTH=16,SIZE=64,BUS_WIDTH=64,DATA_LANES=8,REG_WIDTH=32,
            CACHE_BLOCKS=32,DMA_MAX_BYTES=2048,READ_OUTSTANDING=4,WRITE_OUTSTANDING=4,
            RD_CONTEXT_DEPTH=4,RD_TAG_WIDTH=3,IM2COL_SIZE=16,WINDOW_OUTSTANDING=4,
            WINDOW_LANES=8,CONV_CACHE_SETS=16,CONV_CACHE_WAYS=2,CONV_LINE_BYTES=128,
            CONV_CACHE_POLICY=3)
    else:
        top='conv_windowed_cache'
        sources=resolve([ROOT/'rtl/npu/dma/cache/conv_windowed_cache.sv'],ROOT)
        parameters=dict(SETS=16,WAYS=2,LINE_BYTES=128,BUS_WIDTH=64,READ_WIDTH=64,
                        CACHE_POLICY=3,DEMAND_DEPTH=2,p_preview_request=1)
    options=['-D','SYNTHESIS=1','-D','XILINX_FPGA=1']+[f'-G{k}={v}' for k,v in parameters.items()]
    options+=['-I'+str(ROOT/'include')]
    cases={label:dict(top=top,parameters=parameters,options=options,
        configuration='实际 SoC 参数，保存全部端口与内部寄存器',
        sources=[str(previous if label=='reference' and path==ROOT/relative else path)
                 for path in sources]) for label in ('reference','current')}
    if 'conv_cache_preview_response u_response' in previous.read_text():
        helper=out/'reference_preview_response.sv'
        helper.write_bytes(subprocess.check_output(['git','show',args.reference+
            ':rtl/npu/dma/cache/conv_cache_preview_response.sv'],cwd=ROOT))
        cases['reference']['sources'].append(str(helper))
    config=out/'cases.json';config.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    resume=['--resume'] if args.resume else []
    for label in ('reference','current'):
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',config,
             '--cases',label,'--out',out,'--through','pre_lut',*resume])
        run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/label,
             '--out',out/(label+'_mapped'),'--mode','physical-cost','--delay-target-ps','6667',
             '--wire-delay-ps','300','--max-lut-inputs','8','--discard-abc9-temporaries',*resume])
    run([sys.executable,ROOT/'test/cache_response_ready/inspect_paths.py','--mapping',out,
         '--out',out/'paths',*(['--dma'] if args.dma else [])])


if __name__=='__main__':main()
