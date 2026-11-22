#!/usr/bin/env python3
"""建立完整控制器及实际写保护、返回缓冲和配置接收的局部连接测量。"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

from extract import ROOT, TOP, CTRL, ARB, ADD, REFERENCE, digest, source_at, bias_module, controller_wrapper


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def module(source,name):
    return re.search(r'^module '+name+r'\b.*?^endmodule',source,re.M|re.S)[0]+'\n'


def registered_wrapper(unit,ports,parameters=''):
    declarations=['input logic clk','input logic rst_n']
    internal=[]
    updates=[]
    connections=['.clk(clk)','.rst_n(rst_n)']
    for name,port in ports.items():
        if name in ('clk','rst_n') or name.startswith('formal_'):
            continue
        width=len(port['bits'])
        size=f'[{width-1}:0] ' if width>1 else ''
        direction=port['direction']
        external=('i_' if direction=='input' else 'o_')+name
        declarations.append(f'{direction} logic {size}{external}')
        internal.append(f'    logic {size}{name};')
        updates.append(f'        {name} <= {external};' if direction=='input' else f'        {external} <= {name};')
        connections.append(f'.{name}({name})')
    return 'module measurement_top(\n    '+',\n    '.join(declarations)+'\n);\n'+'\n'.join(internal)+'''
    always_ff @(posedge clk) begin
'''+ '\n'.join(updates)+f'''
    end
    {unit} {parameters} u_impl(
        '''+',\n        '.join(connections)+');\nendmodule\n'


def return_control(top,arbiter,axil,admission,fault):
    grant_begin=arbiter.index('    if (p_fpga_control) begin : g_fpga_read_grant')
    grant_end=arbiter.index('    assign dw_busy',grant_begin)
    error_begin=arbiter.index('    if (p_fpga_control) begin : g_fpga_bus_error')
    error_end=arbiter.index('    logic rd_dma_linear_read_mode_q;',error_begin)
    start=re.search(r'assign npu_core_calc_start\s*=.*?;',axil,re.S)[0]
    header='''module return_control #(
    parameter integer BUS_WIDTH=64, REG_WIDTH=32, WRITE_OUTSTANDING=4,
    ENABLE_QUANT_CLIENT=1, ENABLE_CLOCK_GATING=1
) (
    input logic clk,rst_n,
    input logic linear_awvalid,linear_wvalid,linear_wlast,linear_bready,
    input logic [REG_WIDTH-1:0] linear_awaddr,
    input logic [7:0] linear_awlen,
    input logic [2:0] linear_awsize,
    input logic [1:0] linear_awburst,
    input logic [BUS_WIDTH-1:0] linear_wdata,
    input logic [BUS_WIDTH/8-1:0] linear_wstrb,
    input logic m_axi_awready,m_axi_wready,
    output logic linear_awready,linear_wready,linear_bvalid,
    output logic [1:0] linear_bresp,
    output logic m_axi_awvalid,m_axi_wvalid,m_axi_wlast,
    output logic [REG_WIDTH-1:0] m_axi_awaddr,
    output logic [7:0] m_axi_awlen,
    output logic [2:0] m_axi_awsize,
    output logic [1:0] m_axi_awburst,
    output logic [BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    input logic s_axi_bvalid, input logic [1:0] s_axi_bresp,
    output logic s_axi_bready,
    input logic s_axi_rvalid,s_axi_rlast,m_axi_rready,
    input logic [1:0] s_axi_rresp,
    input logic [BUS_WIDTH-1:0] s_axi_rdata,
    output logic s_axi_rready,
    input logic rd_dma_done,dma_rd_error,wr_dma_done,dma_wr_error,
    input logic [2:0] rd_command_client,
    input logic rd_dma_start_q,
    input logic ps_capacity_fault,shared_ram_capacity_fault,
    input logic frame_mode_q,inner_done_valid,run_conv,run_vector,conv_error,abort_pending,
    input logic [1:0] inner_err_code,abort_state,
    input logic kernel_request,kernel_quiescent,
    input logic ia_prefetch_idle,vector_rejected,vector_engine_ready,ctrl_sa_ready,
    input logic frame_scheduler_ready,cfg_stage0_valid,cfg_stage1_valid,cfg_stage2_valid,operand_cache_idle,
    input logic cfg_vector_enable,npu_start_pending_q,npu_start_warmup_q,calc_start_pulse,
    output logic bus_error,abort,task_fault,write_guard_idle,
    output logic ia_granted,kernel_granted,bias_granted,quant_granted,dw_granted,
    output logic kernel_start,kernel_prefetch_idle,sa_ready,cfg_start_event
);
    localparam bit p_fpga_control=1'b1;
    localparam logic [2:0] C_IA=3'd0,C_KERNEL=3'd1,C_BIAS=3'd2,C_QUANT=3'd3,C_DW=3'd4;
    logic m_axi_bready,m_axi_bvalid;
    logic [1:0] m_axi_bresp,m_axi_rresp;
    logic m_axi_rvalid,m_axi_rlast;
    logic [BUS_WIDTH-1:0] m_axi_rdata;
    logic rd_command_space,npu_core_calc_start,npu_sa_ready,calc_start;
    logic [10:0] fault_flags;
    logic unused_fault_selected;
    assign rd_command_space=!rd_dma_start_q;
    assign npu_sa_ready=sa_ready;
    assign calc_start=npu_core_calc_start;
    assign fault_flags={abort_pending,conv_error,run_vector,run_conv,inner_err_code,
        inner_done_valid,frame_mode_q,bus_error,shared_ram_capacity_fault,ps_capacity_fault};
    soc_axi_pingpong_chan #(.WIDTH(2)) u_b_buf(
        .clk(clk),.rst_n(rst_n),.s_valid(s_axi_bvalid),.s_ready(s_axi_bready),.s_data(s_axi_bresp),
        .m_valid(m_axi_bvalid),.m_ready(m_axi_bready),.m_data(m_axi_bresp));
    soc_axi_pingpong_chan #(.WIDTH(BUS_WIDTH+3)) u_r_buf(
        .clk(clk),.rst_n(rst_n),.s_valid(s_axi_rvalid),.s_ready(s_axi_rready),
        .s_data({s_axi_rdata,s_axi_rresp,s_axi_rlast}),
        .m_valid(m_axi_rvalid),.m_ready(m_axi_rready),.m_data({m_axi_rdata,m_axi_rresp,m_axi_rlast}));
    axi_write_page_guard #(.ADDR_W(REG_WIDTH),.DATA_W(BUS_WIDTH),
        .WRITE_OUTSTANDING(WRITE_OUTSTANDING)) u_write_guard(
        .clk(clk),.rst_n(rst_n),
        .s_awvalid(linear_awvalid),.s_awready(linear_awready),.s_awaddr(linear_awaddr),
        .s_awlen(linear_awlen),.s_awsize(linear_awsize),.s_awburst(linear_awburst),
        .s_wvalid(linear_wvalid),.s_wready(linear_wready),.s_wdata(linear_wdata),
        .s_wstrb(linear_wstrb),.s_wlast(linear_wlast),
        .s_bvalid(linear_bvalid),.s_bready(linear_bready),.s_bresp(linear_bresp),
        .m_awvalid(m_axi_awvalid),.m_awready(m_axi_awready),.m_awaddr(m_axi_awaddr),
        .m_awlen(m_axi_awlen),.m_awsize(m_axi_awsize),.m_awburst(m_axi_awburst),
        .m_wvalid(m_axi_wvalid),.m_wready(m_axi_wready),.m_wdata(m_axi_wdata),
        .m_wstrb(m_axi_wstrb),.m_wlast(m_axi_wlast),
        .m_bvalid(m_axi_bvalid),.m_bready(m_axi_bready),.m_bresp(m_axi_bresp),.idle(write_guard_idle));
    fault_logic u_fault(.i_flags(fault_flags),.task_fault(task_fault),
        .arbiter_abort(abort),.selected_lut(unused_fault_selected));
    kernel_request_idle u_idle(.i_request(kernel_request),.i_granted(kernel_granted),
        .i_quiescent(kernel_quiescent),.o_start(kernel_start),.o_idle(kernel_prefetch_idle));
'''
    conns=','.join('.'+x+'('+x+')' for x in admission.FLAGS+('abort_state','sa_ready','cfg_start_event'))
    header+='    admission_logic u_admission('+conns+');\n'+start+'\n'
    return header+arbiter[grant_begin:grant_end]+arbiter[error_begin:error_end]+'\nendmodule\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--formal',type=Path,required=True)
    parser.add_argument('--reference',default=REFERENCE)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    formal=args.formal.resolve()
    admission=load_module('admission_extract',ROOT/'test/npu_admission/run_formal.py')
    fault=load_module('fault_extract',ROOT/'test/npu_fault_fanin/extract_fault.py')
    buffer_path=Path('rtl/soc/soc_axi_pingpong_buffer.sv')
    kernel_path=Path('rtl/npu/loaders/kernel_loader.sv')
    axil_path=Path('rtl/axi_top/npu_axil_top.sv')
    guard_path=Path('rtl/npu/dma/axi_write_page_guard.sv')
    sources=(TOP,CTRL,ARB,ADD,buffer_path,kernel_path,axil_path,guard_path)
    cases={};manifest={'reference_commit':args.reference,'source_sha256':{},'extracted_sha256':{}}
    for label in ('reference','current'):
        folder=out/label;folder.mkdir(exist_ok=True)
        data={p:source_at(p,args.reference if label=='reference' else None) for p in sources}
        manifest['source_sha256'][label]={str(p):__import__('hashlib').sha256(value.encode()).hexdigest()
                                        for p,value in data.items()}
        controller=folder/'controller.sv'
        controller.write_text(bias_module(data[TOP])+controller_wrapper(data[CTRL]))
        ports=json.loads(read_rtl_text(formal/f'controller_w32_s16_b64_lut1_{label}.json'))['modules']['controller_compare']['ports']
        registered=folder/'controller_measure.sv'
        registered.write_text(registered_wrapper('controller_compare',ports,
            '#(.REG_WIDTH(32),.SIZE(16),.BUS_WIDTH(64),.p_admission_use_lut(1\'b1))'))
        cases['bias_'+label]={'top':'measurement_top','sources':[str(controller),str(registered),str(ROOT/CTRL),str(ROOT/ADD)],
            'options':['-DSYNTHESIS=1','-DXILINX_FPGA=1'],
            'configuration':'完整控制器、实际偏置地址和零判断；32位地址、16单元、BUS64、输入输出测量寄存器'}
        return_path=folder/'return_control.sv'
        return_path.write_text(return_control(data[TOP],data[ARB],data[axil_path],admission,fault)+
            module(data[buffer_path],'soc_axi_pingpong_chan')+
            module(data[kernel_path],'kernel_request_idle')+
            admission.admission(data[TOP],'admission_logic')+fault.module_source(data[TOP],'fault_logic'))
        raw=folder/'return_control.json';script=folder/'return_control.ys';log=folder/'return_control.log'
        script.write_text(f'read_slang --top return_control -DSYNTHESIS=1 -DXILINX_FPGA=1 '
            f'{return_path} {ROOT/guard_path} {formal/"lut_models.v"}\n'
            f'prep -top return_control\nwrite_json {raw}\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=90)
        ports=json.loads(read_rtl_text(raw))['modules']['return_control']['ports']
        registered_return=folder/'return_measure.sv'
        registered_return.write_text(registered_wrapper('return_control',ports))
        cases['return_'+label]={'top':'measurement_top','sources':[str(return_path),str(registered_return),str(ROOT/guard_path)],
            'options':['-DSYNTHESIS=1','-DXILINX_FPGA=1'],
            'configuration':'实际写保护、SoC R/B缓冲、总线错误、故障、五客户端授予、kernel空闲及AXIL开始和NPU配置接收'}
        manifest['extracted_sha256'][label]={p.name:digest(p) for p in folder.glob('*.sv')}
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(out/'cases.json')


if __name__=='__main__':main()
