#!/usr/bin/env python3
"""从生产源码提取实际返回路径，联合测量读取就绪、错误和客户端授予。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source, read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCES = (
    'rtl/npu/dma/axi_dual_block_dma.sv',
    'rtl/npu/conv/conv_axi_read_guard.sv',
    'rtl/npu/conv/conv_axi_read_mux.sv',
    'rtl/npu/dma/axi_block_dma_arbiter.sv',
    'rtl/npu/dma/axi_linear_block_dma.sv',
    'rtl/soc/soc_axi_pingpong_buffer.sv',
    'rtl/npu/loaders/kernel_loader.sv',
    'rtl/npu/top/npu_top.sv',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Expected one source boundary: ' + old)
    return text.replace(old, new)


def module(text, name):
    return re.search(r'^module ' + name + r'\b.*?^endmodule', text, re.M | re.S)[0] + '\n'


def statement(text, target):
    matches = re.findall(r'\bassign\s+' + target + r'\s*=.*?;', text, re.S)
    if len(matches) != 1:
        raise RuntimeError('Expected one assignment: ' + target)
    return '    ' + matches[0] + '\n'


def build_wrapper(source, read_pair):
    arbiter = source[SOURCES[3]]
    top = source[SOURCES[7]]
    for index, name in enumerate(('IA', 'KERNEL', 'BIAS', 'QUANT', 'DW')):
        if not re.search(r'\bC_' + name + r"\s*=\s*3'd" + str(index) + r'\b', arbiter):
            raise RuntimeError('Unexpected client encoding: ' + name)
    buffer = module(source[SOURCES[5]], 'soc_axi_pingpong_buffer')
    packet = re.search(r'assign\s+s_r_payload\s*=\s*([^;]+);', buffer)[1]
    packet_input = packet.replace('m_axi_', 's_axi_')
    declarations = '''
    logic linear_rready, rd_active;
    logic m_axi_rvalid, m_axi_rlast, m_axi_bvalid;
    logic [BUS_WIDTH-1:0] m_axi_rdata;
    logic [1:0] m_axi_rresp, m_axi_bresp;
    logic rd_command_space;
    logic dma_bus_error, task_fault;
    localparam bit p_fpga_control = 1'b1;
    localparam logic [2:0] C_IA=3'd0, C_KERNEL=3'd1, C_BIAS=3'd2,
        C_QUANT=3'd3, C_DW=3'd4;
    soc_axi_pingpong_chan #(.WIDTH(BUS_WIDTH+3)) u_return_buffer (
        .clk(clk), .rst_n(rst_n),
        .s_valid(s_axi_rvalid), .s_ready(s_axi_rready),
        .s_data(@@R_INPUT@@),
        .m_valid(m_axi_rvalid), .m_ready(m_axi_rready),
        .m_data(@@R_OUTPUT@@)
    );
    soc_axi_pingpong_chan #(.WIDTH(2)) u_write_response_buffer (
        .clk(clk), .rst_n(rst_n),
        .s_valid(s_axi_bvalid), .s_ready(s_axi_bready), .s_data(s_axi_bresp),
        .m_valid(m_axi_bvalid), .m_ready(m_axi_bready), .m_data(m_axi_bresp)
    );
    assign dma_bus_error = bus_error;
    assign abort = abort_pending || task_fault;
    kernel_request_idle u_request_idle (
        .i_request(kernel_request), .i_granted(kernel_granted),
        .i_quiescent(kernel_quiescent), .o_start(kernel_start), .o_idle(kernel_idle)
    );
'''
    declarations = declarations.replace('@@R_INPUT@@', packet_input).replace('@@R_OUTPUT@@', packet)
    declarations += statement(arbiter, 'rd_command_space')
    declarations += statement(top, 'task_fault')
    active = re.search(r'wire rd_active\s*=\s*[^;]+;', source[SOURCES[4]])[0]
    declarations += '    ' + active.replace('wire rd_active', 'assign rd_active') + '\n'
    ready = statement(source[SOURCES[4]], 'm_axi_rready')
    declarations += ready.replace('m_axi_rready', 'linear_rready')
    if 'begin : g_fpga_read_grant' in arbiter:
        begin = arbiter.index('    if (p_fpga_control) begin : g_fpga_read_grant')
        end = arbiter.index('    assign dw_busy', begin)
        declarations += arbiter[begin:end]
    else:
        declarations += ''.join(statement(arbiter, name + '_granted')
                                for name in ('dw', 'ia', 'kernel', 'bias', 'quant'))
    if 'begin : g_fpga_bus_error' in arbiter:
        begin = arbiter.index('    if (p_fpga_control) begin : g_fpga_bus_error')
        end = arbiter.index('    logic rd_dma_linear_read_mode_q;', begin)
        declarations += arbiter[begin:end]
    else:
        declarations += statement(arbiter, 'bus_error')
    wrapper = replace_once(read_pair, 'module read_ready_top #(', 'module dma_return_admission_top #(')
    wrapper = replace_once(wrapper, 'READ_OUTSTANDING=4\n', 'READ_OUTSTANDING=4, ENABLE_QUANT_CLIENT=1\n')
    wrapper = replace_once(wrapper, 'input logic linear_arvalid, linear_rready,',
                           'input logic linear_arvalid,\n    input logic [2:0] rd_context_count,')
    wrapper = replace_once(wrapper, 'input logic m_axi_arready, m_axi_rvalid, m_axi_rlast,',
                           'input logic m_axi_arready, s_axi_rvalid, s_axi_rlast,')
    wrapper = replace_once(wrapper, 'input logic [BUS_WIDTH-1:0] m_axi_rdata,',
                           'input logic [BUS_WIDTH-1:0] s_axi_rdata,')
    wrapper = replace_once(wrapper, 'input logic [1:0] m_axi_rresp,', '''input logic [1:0] s_axi_rresp,
    input logic s_axi_bvalid, m_axi_bready,
    input logic [1:0] s_axi_bresp,
    output logic s_axi_rready, s_axi_bready,
    input logic [2:0] rd_command_client,
    input logic rd_dma_start_q, rd_dma_done, dma_rd_error, wr_dma_done, dma_wr_error,
    input logic abort_pending, ps_capacity_fault, shared_ram_capacity_fault,
    input logic frame_mode_q, inner_done_valid, run_conv, run_vector, conv_error,
    input logic [1:0] inner_err_code,
    input logic kernel_request, kernel_quiescent,
    output logic bus_error, abort,
    output logic ia_granted, kernel_granted, bias_granted, quant_granted, dw_granted,
    output logic kernel_start, kernel_idle,''')
    wrapper = replace_once(wrapper, '    localparam bit CONV_SUPPORTED',
                           declarations + '\n    localparam bit CONV_SUPPORTED')
    return wrapper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='47e51eff')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('read_pair_prepare',
        ROOT / 'test/dma_read_permission/prepare_measurement.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    template = read_rtl_text(ROOT / 'test/dma_read_ready/read_pair.sv.inc')
    manifest = {'reference_revision': args.reference, 'source_sha256': {}, 'excerpt_sha256': {},
        'scope': 'Actual guard, mux, R/B buffers, extracted arbiter grant/error and top fault expressions, '
                 'and actual kernel_request_idle; unmodified context/grant state and completion flags are analysis inputs.'}
    cases = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        source = {}
        manifest['source_sha256'][label] = {}
        for name in SOURCES:
            data = read_rtl_source(f'{args.reference}:{name}', cwd=ROOT) \
                if label == 'reference' else (ROOT / name).read_bytes()
            source[name] = data.decode()
            manifest['source_sha256'][label][name] = digest(data)
            (folder / Path(name).name).write_bytes(data)
        dual = source[SOURCES[0]]
        begin = dual.index('        logic read_mux_i_arvalid, read_mux_o_arvalid;')
        end = dual.index('    end else begin : g_linear_only', begin)
        pair = template.replace('@@MODE@@', prepare.mode(dual)).replace('@@INSTANCES@@', dual[begin:end])
        excerpts = {
            'return_admission.sv': build_wrapper(source, pair),
            'return_buffer.sv': module(source[SOURCES[5]], 'soc_axi_pingpong_chan'),
            'kernel_idle.sv': module(source[SOURCES[6]], 'kernel_request_idle'),
        }
        manifest['excerpt_sha256'][label] = {}
        for name, data in excerpts.items():
            (folder / name).write_text(data)
            manifest['excerpt_sha256'][label][name] = digest(data.encode())
        cases[label] = {'top': 'dma_return_admission_top',
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GREG_WIDTH=32',
                        '-GBUS_WIDTH=64', '-GREAD_OUTSTANDING=4'],
            'sources': [str(folder / name) for name in (*excerpts, 'conv_axi_read_guard.sv',
                                                        'conv_axi_read_mux.sv')],
            'configuration': '实际读取保护、请求复用、SoC 返回缓冲及错误和授予组合表达式'}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
