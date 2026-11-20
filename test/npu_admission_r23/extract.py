#!/usr/bin/env python3
"""从实际 RTL 提取完整错误、授予、预取空闲及任务接收连接。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '7ef39f0101ebf39184d11dbdc80a4042faee75c2'
TOP = Path('rtl/npu/top/npu_top.sv')
ARB = Path('rtl/npu/dma/axi_block_dma_arbiter.sv')
KERNEL = Path('rtl/npu/loaders/kernel_loader.sv')
AXIL = Path('rtl/axi_top/npu_axil_top.sv')
LINEAR = Path('rtl/npu/dma/axi_linear_block_dma.sv')
GUARD = Path('rtl/npu/conv/conv_axi_read_guard.sv')
MUX = Path('rtl/npu/conv/conv_axi_read_mux.sv')
DUAL = Path('rtl/npu/dma/axi_dual_block_dma.sv')
BUFFER = Path('rtl/soc/soc_axi_pingpong_buffer.sv')
WRITE_GUARD = Path('rtl/npu/dma/axi_write_page_guard.sv')
SOURCES = (TOP, ARB, KERNEL, AXIL, LINEAR, GUARD, MUX, DUAL, BUFFER, WRITE_GUARD)


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT/relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


legacy = load('admission_legacy_extract', 'test/npu_admission/run_formal.py')
fault = load('fault_current_extract', 'test/npu_fault_fanin/extract_fault.py')
r22 = load('admission_r22_extract', 'test/npu_admission_r22/extract.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_at(path, reference=None):
    return read_rtl_source(f'{reference}:{path}', cwd=ROOT, text=True) \
        if reference else (ROOT/path).read_text()


def module(source, name):
    return re.search(r'^module '+name+r'\b.*?^endmodule',source,re.M|re.S)[0]+'\n'


def assignment(source, name):
    return re.search(r'\bassign '+name+r'\s*=.*?;',source,re.S)[0]


def admission(top, name='admission_logic'):
    text = legacy.admission(top, name)
    return text.replace('    output logic sa_ready, cfg_start_event);',
        '''    input logic kernel_loader_o_quiescent, block_dma_arbiter_o_kernel_eligible,
    input logic block_dma_arbiter_i_abort, load_weight_req,
    output logic sa_ready, cfg_start_event);''', 1)


def grant(arb, name='grant_logic'):
    begin = arb.index('    if (p_fpga_control) begin : g_fpga_read_grant')
    end = arb.index('    assign dw_busy', begin)
    extension = assignment(arb, 'o_kernel_eligible') if 'assign o_kernel_eligible' in arb else \
        'assign o_kernel_eligible = rd_command_space && rd_command_client == C_KERNEL;'
    return f'''module {name} #(parameter bit p_fpga_control=1'b1,
    parameter integer ENABLE_QUANT_CLIENT=1)(
    input logic abort,rd_dma_start_q,input logic [2:0] rd_grant_client,
    output logic ia_granted,kernel_granted,bias_granted,quant_granted,dw_granted,
    output logic o_kernel_eligible);
    localparam logic [2:0] C_IA=3'd0,C_KERNEL=3'd1,C_BIAS=3'd2,C_QUANT=3'd3,C_DW=3'd4;
    logic rd_command_space;
    logic [2:0] rd_command_client;
''' + assignment(arb,'rd_command_space')+'\n'+assignment(arb,'rd_command_client')+'\n'+extension+'\n'+arb[begin:end]+'\nendmodule\n'


def verify_extensions(old, current):
    """两个模块只增加原有组合条件的输出，完整原有实现必须逐字保持一致。"""
    arb = current[ARB].replace('    output logic                   bus_error,\n'
        '    // 未计入同周期中止的权重命令资格，供顶层并行计算接收条件。\n'
        '    output logic                   o_kernel_eligible\n',
        '    output logic                   bus_error\n',1).replace(
        '    assign o_kernel_eligible = rd_command_space && rd_command_client == C_KERNEL;\n','',1)
    kernel = current[KERNEL].replace('    output logic                        weight_data_valid,\n'
        '    // 后台状态独立于当前授予，供顶层在末级合并同周期中止。\n'
        '    output logic                        o_prefetch_quiescent\n',
        '    output logic                        weight_data_valid\n',1).replace(
        '  assign o_prefetch_quiescent = load_idle_i_quiescent;\n','',1)
    assert arb == old[ARB], 'The original complete arbiter implementation changed'
    assert kernel == old[KERNEL], 'The original complete kernel implementation changed'
    expected = {
        'o_kernel_eligible': 'block_dma_arbiter_o_kernel_eligible',
        'o_prefetch_quiescent': 'kernel_loader_o_quiescent',
        'load_weight_req': 'load_weight_req',
        'load_weight_granted': 'load_weight_granted',
    }
    for port, signal in expected.items():
        assert re.search(r'\.'+port+r'\s*\(\s*'+signal+r'\s*\)',current[TOP]), (port,signal)
    assert assignment(current[KERNEL],'o_prefetch_quiescent') == \
        'assign o_prefetch_quiescent = load_idle_i_quiescent;'
    return {'original_arbiter_and_kernel_text_identical_after_output_extension': True,
            'top_connections_verified':expected}


def connected(data, name='admission_connected'):
    top, arb, kernel, axil = (data[p] for p in (TOP,ARB,KERNEL,AXIL))
    flags = tuple(x for x in legacy.FLAGS if x not in ('kernel_prefetch_idle','calc_start'))
    ports = 'input logic '+','.join(flags)+''',
    input logic [1:0] abort_state,
    input logic load_weight_req,kernel_quiescent,
    input logic [2:0] rd_grant_client,
    input logic rd_dma_start_q,
    input logic [11:0] error_flags,
    input logic ps_capacity_fault,shared_ram_capacity_fault,frame_mode_q,
    input logic inner_done_valid,run_conv,conv_error,abort_pending,
    input logic [1:0] inner_err_code,
    input logic npu_start_pending_q,npu_start_warmup_q,calc_start_pulse,cfg_conv_enable,
    output logic [10:0] observed
'''
    conns = ','.join('.'+x+'('+x+')' for x in legacy.FLAGS+('abort_state','sa_ready','cfg_start_event'))
    start = re.search(r'\.start\((calc_start.*)\),',top)[1]
    p_control = arb[arb.index('`ifdef ASIC_SYNTHESIS'):arb.index('    typedef enum logic [2:0]')]
    body = f'''module {name} #(parameter integer ENABLE_QUANT_CLIENT=1,ENABLE_CLOCK_GATING=1)(
{ports});
{p_control}
    logic bus_error,task_fault,abort,unused_fault_selected;
    logic ia_granted,kernel_granted,bias_granted,quant_granted,dw_granted,kernel_eligible;
    logic kernel_start,kernel_prefetch_idle,sa_ready,cfg_start_event;
    logic npu_sa_ready,npu_core_calc_start,calc_start,vector_start;
    logic [10:0] fault_flags;
    assign fault_flags={{abort_pending,conv_error,run_vector,run_conv,inner_err_code,
        inner_done_valid,frame_mode_q,bus_error,shared_ram_capacity_fault,ps_capacity_fault}};
    bus_error_logic #(.p_fpga_control(p_fpga_control)) u_error(
        .m_axi_rready(error_flags[0]),.m_axi_rvalid(error_flags[1]),
        .m_axi_bready(error_flags[2]),.m_axi_bvalid(error_flags[3]),
        .m_axi_rresp(error_flags[5:4]),.m_axi_bresp(error_flags[7:6]),
        .rd_dma_done(error_flags[8]),.dma_rd_error(error_flags[9]),
        .wr_dma_done(error_flags[10]),.dma_wr_error(error_flags[11]),.bus_error(bus_error));
    fault_logic u_fault(.i_flags(fault_flags),.task_fault(task_fault),
        .arbiter_abort(abort),.selected_lut(unused_fault_selected));
    grant_logic #(.p_fpga_control(p_fpga_control),.ENABLE_QUANT_CLIENT(ENABLE_QUANT_CLIENT)) u_grant(
        .abort(abort),.rd_dma_start_q(rd_dma_start_q),.rd_grant_client(rd_grant_client),
        .ia_granted(ia_granted),.kernel_granted(kernel_granted),.bias_granted(bias_granted),
        .quant_granted(quant_granted),.dw_granted(dw_granted),.o_kernel_eligible(kernel_eligible));
    kernel_request_idle u_idle(.i_request(load_weight_req),.i_granted(kernel_granted),
        .i_quiescent(kernel_quiescent),.o_start(kernel_start),.o_idle(kernel_prefetch_idle));
    admission_logic u_admission({conns},.kernel_loader_o_quiescent(kernel_quiescent),
        .block_dma_arbiter_o_kernel_eligible(kernel_eligible),.block_dma_arbiter_i_abort(abort),
        .load_weight_req(load_weight_req));
    assign npu_sa_ready=sa_ready;
    assign calc_start=npu_core_calc_start;
    {assignment(axil,'npu_core_calc_start')}
    assign vector_start={start};
    assign observed={{bus_error,task_fault,abort,ia_granted,kernel_granted,bias_granted,
        quant_granted,dw_granted,kernel_start,kernel_prefetch_idle,sa_ready}};
    output logic observed_cfg_start,observed_vector_start;
    assign observed_cfg_start=cfg_start_event;
    assign observed_vector_start=vector_start;
endmodule
'''
    # 公开观察端口按 ANSI 风格加入端口列表。
    body=body.replace('output logic [10:0] observed\n','output logic [10:0] observed,\n'
        '    output logic observed_cfg_start,observed_vector_start\n').replace(
        '    output logic observed_cfg_start,observed_vector_start;\n','')
    return body+grant(arb)+module(kernel,'kernel_request_idle')+admission(top)+\
        r22.bus_error_module(arb)+fault.module_source(top,'fault_logic')
