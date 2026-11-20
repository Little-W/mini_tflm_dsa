#!/usr/bin/env python3
"""从生产双通路 DMA 保存模式寄存器与读取保护、复用模块的联合综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SOURCES=('rtl/npu/dma/axi_dual_block_dma.sv',
         'rtl/npu/conv/conv_axi_read_guard.sv', 'rtl/npu/conv/conv_axi_read_mux.sv')


def mode(source):
    names=re.search(r'logic job_conv, (job_\w+);',source).group(1)
    assignments={}
    for name in ('job_conv',names):
        values=re.findall(r'\b'+name+r'\s*<=\s*([^;]+);',source)
        assert len(values)==2 and values[0].strip()=="1'b0"
        assignments[name]=values[1].strip()
    text='    logic job_conv, '+names+';\n'
    text+='    always_ff @(posedge clk or negedge rst_n) begin\n'
    text+="        if(!rst_n) begin job_conv<=1'b0; "+names+"<=1'b0; end\n"
    text+='        else if(cfg_fire) begin\n'
    text+=''.join(f'            {name}<={value};\n' for name,value in assignments.items())
    return text+'        end\n    end\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='dcef8d89')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    manifest={'reference':args.reference,'source_sha256':{},'excerpt_sha256':{}}
    cases={}
    template=(ROOT/'test/dma_read_ready/read_pair.sv.inc').read_text()
    for label in ('reference','current'):
        folder=out/label;folder.mkdir(exist_ok=True)
        sources={}
        manifest['source_sha256'][label]={}
        for name in SOURCES:
            data=subprocess.check_output(['git','show',f'{args.reference}:{name}'],cwd=ROOT) \
                if label=='reference' else (ROOT/name).read_bytes()
            sources[name]=data.decode()
            (folder/Path(name).name).write_bytes(data)
            manifest['source_sha256'][label][name]=hashlib.sha256(data).hexdigest()
        dual=sources[SOURCES[0]]
        begin=dual.index('        conv_axi_read_guard #(')
        declaration=dual.find('        logic read_mux_i_arvalid, read_mux_o_arvalid;')
        if declaration>=0:begin=declaration
        end=dual.index('    end else begin : g_linear_only',begin)
        instances=dual[begin:end]
        registers=mode(dual)
        wrapper=folder/'read_pair.sv'
        wrapper.write_text(template.replace('@@MODE@@',registers).replace('@@INSTANCES@@',instances))
        manifest['excerpt_sha256'][label]={'mode':hashlib.sha256(registers.encode()).hexdigest(),
            'instances':hashlib.sha256(instances.encode()).hexdigest(),
            'wrapper':hashlib.sha256(wrapper.read_bytes()).hexdigest()}
        cases[label]={'top':'read_ready_top','options':['-D','SYNTHESIS=1','-DXILINX_FPGA=1',
            '-GREG_WIDTH=32','-GBUS_WIDTH=64','-GREAD_OUTSTANDING=4'],
            'sources':[str(wrapper),str(folder/'conv_axi_read_guard.sv'),str(folder/'conv_axi_read_mux.sv')],
            'configuration':'生产模式寄存器、读取保护与读请求复用，保留全部AXI端口'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
