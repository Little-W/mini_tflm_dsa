#!/usr/bin/env python3
"""测量上下文计数、实际读写保护、SoC 返回缓冲到任务接收的连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import extract
from extract import (ROOT,REFERENCE,SOURCES,TOP,ARB,KERNEL,AXIL,LINEAR,GUARD,MUX,DUAL,BUFFER,
                     WRITE_GUARD,digest,source_at,load,module,assignment,admission,legacy,fault,r22)

# 复用已采用的输入输出测量寄存器和写响应连接生成器。
_saved=sys.modules.get('extract')
sys.modules['extract']=r22
try:
    previous=load('admission_return_measurement','test/npu_admission_r22/prepare_measurement.py')
finally:
    sys.modules['extract']=_saved
mode=load('read_mode_measurement','test/dma_read_permission/prepare_measurement.py')


def once(text, old, new):
    assert text.count(old)==1,old
    return text.replace(old,new,1)


def build(data):
    text=previous.return_control(data[TOP],data[ARB],data[AXIL],legacy,fault)
    text=once(text,'input logic s_axi_rvalid,s_axi_rlast,m_axi_rready,',
              'input logic s_axi_rvalid,s_axi_rlast,\n    output logic m_axi_rready,')
    text=once(text,'output logic kernel_start,kernel_prefetch_idle,sa_ready,cfg_start_event\n',
'''output logic kernel_start,kernel_prefetch_idle,sa_ready,cfg_start_event,
    input logic [2:0] rd_context_count,
    input logic cfg_fire,conv_enable,dma_range_enable,
    input logic [127:0] cfg_base_flat,
    input logic [131:0] cfg_end_flat,
    input logic linear_arvalid,
    input logic [REG_WIDTH-1:0] linear_araddr,
    input logic [7:0] linear_arlen,
    input logic [2:0] linear_arsize,
    input logic [1:0] linear_arburst,
    output logic linear_arready,linear_rvalid,linear_rlast,
    output logic [BUS_WIDTH-1:0] linear_rdata,
    output logic [1:0] linear_rresp,
    input logic fe_arvalid,fe_rready,
    input logic [REG_WIDTH-1:0] fe_araddr,
    input logic [7:0] fe_arlen,
    input logic [2:0] fe_arsize,
    input logic [1:0] fe_arburst,
    output logic fe_arready,fe_rvalid,fe_rlast,
    output logic [BUS_WIDTH-1:0] fe_rdata,
    output logic [1:0] fe_rresp,
    output logic m_axi_arvalid,
    output logic [REG_WIDTH-1:0] m_axi_araddr,
    output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,
    output logic [1:0] m_axi_arburst,
    input logic m_axi_arready,
    output logic guard_idle,mux_idle,mode_conv,
    input logic cfg_conv_enable,
    output logic vector_start
''')
    extra='''    logic o_kernel_eligible;
    logic linear_rready,unused_read_error;
'''+re.search(r'wire rd_active\s*=\s*[^;]+;',data[LINEAR])[0]+'\n'+\
        assignment(data[LINEAR],'m_axi_rready').replace('m_axi_rready','linear_rready')+'\n'
    extra+=assignment(data[ARB],'o_kernel_eligible')+'\n' if 'assign o_kernel_eligible' in data[ARB] else \
        'assign o_kernel_eligible=rd_command_space && rd_command_client==C_KERNEL;\n'
    extra+='    assign vector_start='+re.search(r'\.start\((calc_start.*)\),',data[TOP])[1]+';\n'
    read_ports=('clk','rst_n','cfg_fire','conv_enable','dma_range_enable','cfg_base_flat','cfg_end_flat',
        'linear_arvalid','linear_rready','linear_araddr','linear_arlen','linear_arsize','linear_arburst',
        'linear_arready','linear_rvalid','linear_rlast','linear_rdata','linear_rresp',
        'fe_arvalid','fe_rready','fe_araddr','fe_arlen','fe_arsize','fe_arburst','fe_arready','fe_rvalid',
        'fe_rlast','fe_rdata','fe_rresp','m_axi_arvalid','m_axi_rready','m_axi_araddr','m_axi_arlen',
        'm_axi_arsize','m_axi_arburst','m_axi_arready','m_axi_rvalid','m_axi_rlast','m_axi_rdata','m_axi_rresp',
        'guard_idle','mux_idle','mode_conv')
    extra+='    read_ready_top #(.REG_WIDTH(REG_WIDTH),.BUS_WIDTH(BUS_WIDTH),.READ_OUTSTANDING(4)) u_read_pair(\n'
    extra+=','.join('.'+x+'('+x+')' for x in read_ports)+',.read_error(unused_read_error));\n'
    text=once(text,'    assign rd_command_space=!rd_dma_start_q;',extra+'    assign rd_command_space=!rd_dma_start_q;')
    conns=','.join('.'+x+'('+x+')' for x in legacy.FLAGS+('abort_state','sa_ready','cfg_start_event'))
    text=once(text,'    admission_logic u_admission('+conns+');',
        '    admission_logic u_admission('+conns+''',
        .kernel_loader_o_quiescent(kernel_quiescent),.block_dma_arbiter_o_kernel_eligible(o_kernel_eligible),
        .block_dma_arbiter_i_abort(abort),.load_weight_req(kernel_request));''')
    # 返回数据的位次直接核对实际 SoC 缓冲模块。
    buffer=module(data[BUFFER],'soc_axi_pingpong_buffer')
    packet=re.search(r'assign\s+s_r_payload\s*=\s*([^;]+);',buffer)[1]
    assert packet=='{m_axi_rdata, m_axi_rresp, m_axi_rlast}'
    pair=(ROOT/'test/dma_read_ready/read_pair.sv.inc').read_text()
    begin=data[DUAL].index('        logic read_mux_i_arvalid, read_mux_o_arvalid;')
    end=data[DUAL].index('    end else begin : g_linear_only',begin)
    pair=pair.replace('@@MODE@@',mode.mode(data[DUAL])).replace('@@INSTANCES@@',data[DUAL][begin:end])
    pair=once(pair,'input logic [31:0] conv_range_base[4],','input logic [127:0] cfg_base_flat,')
    pair=once(pair,'input logic [32:0] conv_range_end[4],','input logic [131:0] cfg_end_flat,')
    pair=once(pair,"    localparam bit CONV_SUPPORTED=1'b1;",'''    localparam bit CONV_SUPPORTED=1'b1;
    logic [31:0] conv_range_base[4];
    logic [32:0] conv_range_end[4];
    for(genvar i=0;i<4;i++) begin : g_ranges
        assign conv_range_base[i]=cfg_base_flat[i*32+:32];
        assign conv_range_end[i]=cfg_end_flat[i*33+:33];
    end''')
    return text+pair+module(data[BUFFER],'soc_axi_pingpong_chan')+\
        module(data[KERNEL],'kernel_request_idle')+admission(data[TOP])+fault.module_source(data[TOP],'fault_logic')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--formal',type=Path,required=True)
    parser.add_argument('--reference',default=REFERENCE)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    cases={};report={'reference_commit':args.reference,'source_sha256':{},'extracted_sha256':{},
        'scope':'生产 BUS64；rd_context_count、描述符与外部模块状态为测量寄存器输入；实际读写保护、读通道复用、模式寄存器、SoC R/B 缓冲、错误、授予、kernel 空闲和 AXIL/NPU 接收表达式。'}
    for label in ('reference','current'):
        folder=out/label;folder.mkdir(exist_ok=True)
        data={p:source_at(p,args.reference if label=='reference' else None) for p in SOURCES}
        report['source_sha256'][label]={str(p):hashlib.sha256(s.encode()).hexdigest() for p,s in data.items()}
        source=folder/'return_control.sv';source.write_text(build(data))
        sources=[source]
        for path in (GUARD,MUX,WRITE_GUARD):
            target=folder/path.name;target.write_text(data[path]);sources.append(target)
        raw=folder/'ports.json';script=folder/'elaborate.ys';log=folder/'elaborate.log'
        script.write_text('read_slang --top return_control -DSYNTHESIS=1 -DXILINX_FPGA=1 '+
            ' '.join(str(p) for p in (*sources,args.formal.resolve()/'lut_models.v'))+'\n'+
            f'prep -top return_control\ncheck -assert\nwrite_json {raw}\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        ports=json.loads(raw.read_text())['modules']['return_control']['ports']
        wrapper=folder/'measure.sv';wrapper.write_text(previous.registered_wrapper('return_control',ports))
        sources.append(wrapper)
        report['extracted_sha256'][label]={p.name:digest(p) for p in sources}
        cases[label]={'top':'measurement_top','sources':[str(p) for p in sources],
            'options':['-DSYNTHESIS=1','-DXILINX_FPGA=1'],
            'configuration':'实际读写保护和返回缓冲，读上下文计数至错误、授予、空闲、AXIL 开始和 NPU 接收'}
    (out/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    print(out/'cases.json')


if __name__=='__main__':main()
