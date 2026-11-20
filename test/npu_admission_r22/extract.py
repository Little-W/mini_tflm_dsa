#!/usr/bin/env python3
"""从实际顶层、控制器和仲裁器提取配置接收与偏置零判断。"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')
CTRL = Path('rtl/npu/control/npu_controller.sv')
ARB = Path('rtl/npu/dma/axi_block_dma_arbiter.sv')
ADD = Path('rtl/common/add_equal.sv')
REFERENCE = 'b20921b3b1fc3351b1f6447dd688af12ac60ef19'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_at(relative, reference=None):
    if reference is None:
        return (ROOT / relative).read_text()
    return subprocess.check_output(['git', 'show', f'{reference}:{relative}'], cwd=ROOT, text=True)


def bias_region(source):
    begin = source.index('        wire [31:0] exec_bias_base =')
    end = source.index('        wire [31:0] exec_dst_base =', begin)
    return source[begin:end]


def controller_bias_connection(source):
    block = source.split(') u_npu_controller (', 1)[1].split('\n    );', 1)[0]
    matches = re.findall(r'\.bias_base\s*\(([^)]+)\)', block)
    if len(matches) != 1:
        raise RuntimeError('Expected one actual controller bias input connection')
    return matches[0]


def bias_module(source, name='bias_logic'):
    return f'''module {name} #(
    parameter integer REG_WIDTH=32,
    parameter bit p_admission_use_lut=1'b1
) (
    input logic [REG_WIDTH-1:0] bias_base,
    input logic [31:0] exec_channel,
    input logic frame_mode_q, is_mode, ws_final_bias,
    input logic frame_command_final, frame_command_init,
    output logic [31:0] address,
    output logic [REG_WIDTH-1:0] controller_bias
);
''' + bias_region(source) + f'''
    assign address=exec_bias_base;
    assign controller_bias={controller_bias_connection(source)};
endmodule
'''


def controller_wrapper(controller, name='controller_compare'):
    match = re.search(r'module npu_controller\s*#\((.*?)\)\s*\((.*?)\n\);', controller, re.S)
    if not match:
        raise RuntimeError('Expected the actual complete controller header')
    parameters, ports = match.groups()
    clean = re.sub(r'//[^\n]*', '', ports)
    names = re.findall(r'\b(?:input|output)\s+(?:(?:wire|logic|reg|signed)\s+)*(?:\[[^]]+\]\s*)?(\w+)', clean)
    if len(names) != len(set(names)):
        raise RuntimeError('Controller ports are ambiguous')
    parameter_names = re.findall(r'parameter\s+int\s+unsigned\s+(\w+)\s*=', parameters)
    connections = ',\n        '.join('.'+port+'('+('bias_o_controller' if port == 'bias_base' else port)+')' for port in names)
    parameter_connections = ', '.join('.'+port+'('+port+')' for port in parameter_names)
    return f'''module {name} #({parameters},
    parameter bit p_admission_use_lut=1'b1
) ({ports}
    ,
    input logic [31:0] exec_channel,
    input logic frame_mode_q, is_mode, ws_final_bias,
    input logic frame_command_final, frame_command_init,
    output logic [31:0] observed_bias_address
);
    logic [31:0] bias_o_address;
    logic [REG_WIDTH-1:0] bias_o_controller;
    bias_logic #(.REG_WIDTH(REG_WIDTH), .p_admission_use_lut(p_admission_use_lut)) u_bias (
        .bias_base(bias_base), .exec_channel(exec_channel),
        .frame_mode_q(frame_mode_q), .is_mode(is_mode), .ws_final_bias(ws_final_bias),
        .frame_command_final(frame_command_final), .frame_command_init(frame_command_init),
        .address(bias_o_address), .controller_bias(bias_o_controller)
    );
    assign observed_bias_address=bias_o_address;
    npu_controller #({parameter_connections}) u_controller (
        {connections}
    );
endmodule
'''


def observed_controller(source):
    """导出所有时序赋值的寄存器，包含尚未用于公开输出的配置错误状态。"""
    names=('cfg_16bits_ia_reg','compute_tail_count','config_error','current_state',
           'done_valid','err_code','error_type','init_cfg_bias','init_cfg_ia','init_cfg_oa',
           'init_cfg_requant','init_cfg_weight','resident_used','send_weight_trigger',
           'shadow_inflight','shadow_ready','use_16bits','weight_commit')
    actual=sorted(set(re.findall(r'\b(\w+)\s*<=',re.sub(r'//[^\n]*','',source))))
    if actual != list(names):
        raise RuntimeError('Complete controller register declaration coverage changed')
    source=source.replace('\n);','\n    , output logic [23:0] formal_full_state\n);',1)
    return source.replace('endmodule','    assign formal_full_state={'+','.join(names)+'};\nendmodule',1)


def bus_error_module(source, name='bus_error_logic'):
    begin = source.index('    if (p_fpga_control) begin : g_fpga_bus_error')
    end = source.index('    logic rd_dma_linear_read_mode_q;', begin)
    return f'''module {name} #(parameter bit p_fpga_control=1'b1)(
    input logic m_axi_rready, m_axi_rvalid, m_axi_bready, m_axi_bvalid,
    input logic [1:0] m_axi_rresp, m_axi_bresp,
    input logic rd_dma_done, dma_rd_error, wr_dma_done, dma_wr_error,
    output logic bus_error
);
''' + source[begin:end] + '\nendmodule\n'


def retain_public_and_state(path, top):
    """显式比较所有状态输出，避免把重构后的组合中间线当作相同状态。"""
    data = json.loads(Path(path).read_text())
    module = data['modules'][top]
    state_bits = set()
    for cell in module['cells'].values():
        if 'ff' in cell['type'].lower() and 'Q' in cell['connections']:
            state_bits.update(bit for bit in cell['connections']['Q'] if isinstance(bit, int))
    covered = set()
    states = []
    for name, net in sorted(module['netnames'].items()):
        if name.startswith('$') or net.get('hide_name', 0):
            continue
        selected = [(i, bit) for i, bit in enumerate(net['bits']) if bit in state_bits]
        if not selected:
            continue
        port = 'formal_state_' + hashlib.sha256(name.encode()).hexdigest()[:16]
        bits = [bit for _, bit in selected]
        module['ports'][port] = {'direction': 'output', 'bits': bits}
        states.append({'name': name, 'positions': [i for i, _ in selected], 'bits': len(bits)})
        covered.update(bits)
    if state_bits != covered:
        raise RuntimeError(f'Unobserved controller/arbiter state bits: {len(state_bits-covered)}')
    module['netnames'] = {name: {'hide_name': 0, 'bits': port['bits'], 'attributes': {}}
                          for name, port in module['ports'].items()}
    Path(path).write_text(json.dumps(data) + '\n')
    return {'unique_state_bits': len(state_bits), 'observed_state': states}
