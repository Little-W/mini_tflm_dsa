#!/usr/bin/env python3
"""从实际源码提取核加载请求、后台空闲、仲裁和任务接收组合。"""
import hashlib
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = 'c4edde85f284bdd71d4c254e2456ffae955d4016'
KERNEL = Path('rtl/npu/loaders/kernel_loader.sv')
TOP = Path('rtl/npu/top/npu_top.sv')
ARB = Path('rtl/npu/dma/axi_block_dma_arbiter.sv')
AXIL = Path('rtl/axi_top/npu_axil_top.sv')
SOURCES = (KERNEL, TOP, ARB, AXIL)


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


previous = load('r25_previous_admission', 'test/npu_admission_r23/extract.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(path, reference=None):
    return read_rtl_source(f'{reference}:{path}', cwd=ROOT, text=True) \
        if reference else (ROOT / path).read_text()


def assignment(text, signal):
    return re.search(r'\bassign\s+' + signal + r'\s*=.*?;', text, re.S)[0]


def extensions(old, current):
    """核对新增组合观察输出之外的完整核加载实现和顶层连接。"""
    data = current[KERNEL]
    data = data.replace('    output logic                        o_prefetch_quiescent,\n'
                        '    // 供任务接收在后台空闲条件下判断当前需求请求。\n'
                        '    output logic                        o_admission_request\n',
                        '    output logic                        o_prefetch_quiescent\n', 1)
    begin = data.index('  logic [5:0] admission_i_flags;')
    end = data.index('`endif', begin) + len('`endif\n')
    data = data[:begin] + data[end:]
    begin = data.index('  // 后台空闲已排除待发预取和在途传输；')
    end = data.index('  assign o_admission_request = admission_o_request;', begin)
    end += len('  assign o_admission_request = admission_o_request;\n')
    data = data[:begin] + data[end:]
    assert data == old[KERNEL], '完整核加载状态与原有输出表达式发生变化'
    top = current[TOP].replace('    logic kernel_loader_o_admission_request;\n', '', 1)
    top = top.replace('        .o_admission_request(kernel_loader_o_admission_request),\n', '', 1)
    top = top.replace('assign admission_kernel_occupied = kernel_loader_o_admission_request &&',
                      'assign admission_kernel_occupied = load_weight_req &&', 1)
    assert top == old[TOP], '顶层修改超出新增组合输出的接入范围'
    for path in (ARB, AXIL):
        assert old[path] == current[path], str(path)
    return {'original_kernel_implementation_unchanged': True,
            'top_only_admission_request_connection_changed': True,
            'new_register_bits': 0, 'added_cycles': 0}


KERNEL_FLAGS = ('command_mode_q', 'command_waiting', 'transfer_active', 'transfer_prefetch',
                'ext_dma_busy', 'buf_load_ready', 'ctrl_load_req', 'cache_flush', 'init_cfg',
                'prefetch_window_open', 'buf_send_start', 'prefetch_valid',
                'comparison_ready', 'comparison_match_q')
TOP_FLAGS = tuple(x for x in previous.legacy.FLAGS if x not in ('kernel_prefetch_idle', 'calc_start'))
OUTPUTS = ('load_weight_req', 'kernel_quiescent', 'request_masked', 'kernel_start',
           'kernel_prefetch_idle', 'ia_granted', 'kernel_granted', 'bias_granted',
           'quant_granted', 'dw_granted', 'sa_ready', 'cfg_start_event', 'vector_start')


def kernel_control(text):
    enum = re.search(r'typedef enum logic \[1:0\] \{PF_EMPTY, PF_PENDING, PF_LOADING, PF_CACHED\} prefetch_state_t;', text)[0]
    body = '\n'.join(assignment(text, name) for name in (
        'managed_mode', 'demand_issue', 'prefetch_issue', 'load_weight_req',
        'prefetch_candidate_valid', 'prefetch_check_pending', 'load_idle_i_quiescent'))
    if 'output logic                        o_admission_request' in text:
        parameter = re.search(r'  localparam bit p_admission_use_lut =.*?`endif', text, re.S)[0]
        begin = text.index('  assign admission_i_flags =')
        end = text.index('  assign o_admission_request = admission_o_request;', begin)
        end += len('  assign o_admission_request = admission_o_request;')
        extra = parameter + '\nlogic [5:0] admission_i_flags;\nlogic admission_o_request;\n' + text[begin:end]
    else:
        extra = 'assign o_admission_request = load_weight_req;'
    return '''module kernel_control #(parameter integer REG_WIDTH=32,SIZE=16)(
    input logic [1:0] prefetch_state,response_slots_active,
    input logic ''' + ','.join(KERNEL_FLAGS) + ''',
    input logic [REG_WIDTH-1:0] prefetch_rows,prefetch_valid_cols,
    output logic load_weight_req,load_idle_i_quiescent,o_admission_request);
''' + enum + '''
    logic managed_mode,demand_issue,prefetch_issue,prefetch_candidate_valid,prefetch_check_pending;
''' + body + '\n' + extra + '\nendmodule\n'


def connected(data):
    top, kernel, arb, axil = (data[x] for x in (TOP, KERNEL, ARB, AXIL))
    admission = previous.admission(top)
    admission = admission.replace('    output logic sa_ready, cfg_start_event);',
        '    input logic kernel_loader_o_admission_request,\n    output logic sa_ready, cfg_start_event);', 1)
    control = arb[arb.index('`ifdef ASIC_SYNTHESIS'):arb.index('    typedef enum logic [2:0]')]
    connections = ','.join('.'+name+'('+name+')' for name in previous.legacy.FLAGS + ('abort_state','sa_ready','cfg_start_event'))
    inputs = ','.join(TOP_FLAGS + KERNEL_FLAGS)
    kernel_connections = ','.join('.'+name+'('+name+')' for name in KERNEL_FLAGS + ('prefetch_state','response_slots_active','prefetch_rows','prefetch_valid_cols','load_weight_req'))
    start = re.search(r'\.start\((calc_start[^\n]*)\),', top)[1]
    body = f'''module admission_connected #(
    parameter integer REG_WIDTH=32,SIZE=16,ENABLE_QUANT_CLIENT=1,ENABLE_CLOCK_GATING=1)(
    input logic clk,rst_n,
    input logic {inputs},
    input logic [1:0] prefetch_state,response_slots_active,abort_state,
    input logic [REG_WIDTH-1:0] prefetch_rows,prefetch_valid_cols,
    input logic abort,rd_dma_start_q,
    input logic [2:0] rd_grant_client,
    input logic npu_start_pending_q,npu_start_warmup_q,calc_start_pulse,cfg_conv_enable,
    output logic {','.join(OUTPUTS)});
{control}
    logic kernel_loader_o_quiescent,kernel_loader_o_admission_request,kernel_eligible;
    logic calc_start,npu_sa_ready,npu_core_calc_start;
    kernel_control #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE)) u_request(
        {kernel_connections},.load_idle_i_quiescent(kernel_loader_o_quiescent),
        .o_admission_request(kernel_loader_o_admission_request));
    assign kernel_quiescent=kernel_loader_o_quiescent;
    assign request_masked=kernel_loader_o_quiescent && kernel_loader_o_admission_request;
    grant_logic #(.p_fpga_control(p_fpga_control),.ENABLE_QUANT_CLIENT(ENABLE_QUANT_CLIENT)) u_grant(
        .abort(abort),.rd_dma_start_q(rd_dma_start_q),.rd_grant_client(rd_grant_client),
        .ia_granted(ia_granted),.kernel_granted(kernel_granted),.bias_granted(bias_granted),
        .quant_granted(quant_granted),.dw_granted(dw_granted),.o_kernel_eligible(kernel_eligible));
    kernel_request_idle u_idle(.i_request(load_weight_req),.i_granted(kernel_granted),
        .i_quiescent(kernel_loader_o_quiescent),.o_start(kernel_start),.o_idle(kernel_prefetch_idle));
    admission_logic u_admission({connections},
        .kernel_loader_o_quiescent(kernel_loader_o_quiescent),
        .kernel_loader_o_admission_request(kernel_loader_o_admission_request),
        .block_dma_arbiter_o_kernel_eligible(kernel_eligible),.block_dma_arbiter_i_abort(abort),
        .load_weight_req(load_weight_req));
    assign npu_sa_ready=sa_ready;
    assign calc_start=npu_core_calc_start;
    {assignment(axil,'npu_core_calc_start')}
    assign vector_start={start};
endmodule
'''
    return body + kernel_control(kernel) + previous.grant(arb) + \
        previous.module(kernel, 'kernel_request_idle') + admission


def wrapper(ports):
    declarations = ['input logic clk', 'input logic rst_n']
    internal, updates, connections = [], [], ['.clk(clk)', '.rst_n(rst_n)']
    for name, port in ports.items():
        if name in ('clk', 'rst_n'):
            continue
        width = len(port['bits'])
        span = f'[{width-1}:0] ' if width > 1 else ''
        external = ('i_' if port['direction'] == 'input' else 'o_') + name
        declarations.append(f'{port["direction"]} logic {span}{external}')
        internal.append(f'    logic {span}{name};')
        updates.append(f'        {name} <= {external};' if port['direction'] == 'input' else f'        {external} <= {name};')
        connections.append(f'.{name}({name})')
    return 'module measurement_top(\n    '+',\n    '.join(declarations)+');\n' + '\n'.join(internal) + \
        '\n    always_ff @(posedge clk) begin\n'+'\n'.join(updates)+'\n    end\n' + \
        '    admission_connected u_impl('+','.join(connections)+');\nendmodule\n'
