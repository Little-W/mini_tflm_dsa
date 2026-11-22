#!/usr/bin/env python3
"""保留完整 WS 参数存储状态，比较量化状态、公开输出和其他存储端口。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from requant_test_utils import controller_module

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/writeback/vec_requant.sv')
PROFILES = ['4:32:1:1:1', '8:64:2:4:1', '16:64:2:32:1',
            '16:64:4:4:1', '16:64:16:2:1', '16:64:2:2:0',
            '8:64:1:4:1', '16:128:2:4:1']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(folder, name, commands):
    script, log = folder / (name + '.ys'), folder / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=600)
    return log


def memory_interfaces(module):
    """相同存储模型共享任意读值，所有地址、数据及使能均参与比较。"""
    models = {}
    for name, cell in sorted(module['cells'].items()):
        # WS 存储保留实际内容与全部读取端口，其他存储比较完整驱动接口。
        if cell['type'] != '$mem_v2' or not name.endswith('.mem') or 'g_ws_bank_write.' in name:
            continue
        # 端口名称采用原存储名称的散列，使组合逻辑单元数量不影响编号。
        suffix = hashlib.sha256(name.encode()).hexdigest()[:20]
        read_name, drive_name = 'formal_memory_read_' + suffix, 'formal_memory_drive_' + suffix
        connections = cell['connections']
        read_bits = connections['RD_DATA']
        driven_bits = [bit for port in sorted(connections) if port != 'RD_DATA'
                       for bit in connections[port]]
        for port, direction, bits in [(read_name, 'input', read_bits),
                                      (drive_name, 'output', driven_bits)]:
            module['ports'][port] = {'direction': direction, 'bits': bits}
            module['netnames'][port] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
        models[name] = {'parameters': cell['parameters'],
                        'port_widths': {port: len(bits) for port, bits in connections.items()}}
        del module['cells'][name]
    return models


def control_wrapper(source):
    """保留实际配置、DMA 状态与参数存储，把算术消费端作为任意输入。"""
    full=controller_module(source)
    first=full.index('\n);')+3
    end=full.index('  // 数据通路（')
    body=full[first:end]
    header='''module quant_parameter_control #(
    parameter int BUS_WIDTH=64, VLEN=16, REG_WIDTH=32, MAX_IA_REUSE=32,
    parameter int ENABLE_PER_CHANNEL=1, ENABLE_IS_MODE=1,
    parameter bit ENABLE_S16=1,
    parameter int p_compute_lanes=2, p_input_rows=VLEN*MAX_IA_REUSE,
    parameter bit p_parameter_output=1
)(
    input logic clk,rst_n,init_cfg,cfg_per_channel,cfg_dataflow_mode,cfg_s16,
    input logic signed [31:0] activation_min_in,activation_max_in,dst_offset_in,multiplier_in,shift_in,
    input logic [31:0] k,m,ia_reuse_num_in,
    input logic load_quant_granted,dma_raw_valid,
    input logic [BUS_WIDTH-1:0] dma_raw_data,
    input logic i_row_consume,i_tile_done,
    input logic [((VLEN*MAX_IA_REUSE<=1)?1:$clog2(VLEN*MAX_IA_REUSE))-1:0] i_read_index,i_group_index,
    input logic [((VLEN<=1)?1:$clog2(VLEN))-1:0] i_element_index[p_compute_lanes],
    output logic load_quant_req,quant_params_valid,
    output logic dma_start,dma_is_write,dma_linear_read_mode,dma_slot_id,dma_use_16bits,
    output logic [REG_WIDTH-1:0] dma_base_addr,dma_row_stride,dma_rows_to_read,
    output logic signed [REG_WIDTH-1:0] dma_lhs_zp,
    output logic [7:0] dma_burst_len_m1,
    output logic [103*VLEN-1:0] o_ws,
    output logic [103*(BUS_WIDTH/32)-1:0] o_is,
    output logic [39*p_compute_lanes-1:0] o_serial
);
'''
    outputs='''
    assign row_consume_valid=i_row_consume;
    assign row_consume_tile_done=i_tile_done;
    assign parameter_read_idx=i_read_index;
    assign input_group_idx_cur=i_group_index;
    assign serial_element_index=i_element_index;
    for(genvar lane=0;lane<VLEN;lane++)begin:g_monitor_ws
        assign o_ws[103*lane+:103]={ch_multiplier_lane_r[lane],ch_shift_lane_r[lane],
            ch_product_multiplier_lane_r[lane],ch_product_amount_lane_r[lane]};
    end
    for(genvar bank=0;bank<BUS_WIDTH/32;bank++)begin:g_monitor_is
        assign o_is[103*bank+:103]={ch_multiplier_is_read[bank],ch_shift_is_read[bank],
            ch_product_multiplier_is_read[bank],ch_product_amount_is_read[bank]};
    end
    for(genvar lane=0;lane<p_compute_lanes;lane++)begin:g_monitor_serial
        if(p_compute_lanes<VLEN)
            assign o_serial[39*lane+:39]={serial_product_multiplier[lane],serial_product_amount[lane]};
        else assign o_serial[39*lane+:39]='0;
    end
endmodule
'''
    return header+body+outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=PROFILES,
                        help='VLEN:BUS_WIDTH:compute_lanes:reuse:per_channel')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes, snapshots = {}, {}
    for label, root in [('reference', args.reference_root.resolve()),
                        ('current', args.source_root.resolve())]:
        snapshots[label] = []
        paths = ([Path('rtl/npu/writeback/requant_pkg.sv')] if (root/'rtl/npu/writeback/requant_pkg.sv').exists() else []) + [RTL] + [p.relative_to(root) for p in sorted((root / 'rtl/common').glob('*'))
                           if p.suffix in ('.sv', '.v')]
        for relative in paths:
            source, target = root / relative, out / 'inputs' / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(control_wrapper(source.read_text())) if relative == RTL else target.write_bytes(source.read_bytes())
            hashes[str(source)] = digest(source)
            snapshots[label].append(target)
    report = {'passed': False, 'inputs_constrained': False,
              'memory_read_data_constrained': False, 'source_sha256': hashes,
              'comparison': '参数控制状态、DMA 接口、全部 WS 存储内容与 IS 存储完整驱动端口', 'profiles': []}
    for profile in args.profiles:
        vlen, bus, lanes, reuse, per_channel = map(int, profile.split(':'))
        folder = out / profile.replace(':', '_')
        folder.mkdir(exist_ok=True)
        flags = (f'-D SYNTHESIS=1 -D XILINX_FPGA=1 -GVLEN={vlen} -GBUS_WIDTH={bus} '
                 f'-Gp_compute_lanes={lanes} -GMAX_IA_REUSE={reuse} '
                 f'-Gp_input_rows={vlen*reuse} -GENABLE_S16=1 -GENABLE_PER_CHANNEL={per_channel}')
        models = {}
        for label in snapshots:
            raw = folder / (label + '_raw.json')
            execute(folder, label + '_elaborate', [
                f'read_slang --top quant_parameter_control {flags} ' + shlex.join(map(str, snapshots[label])),
                'prep -top quant_parameter_control -flatten', 'opt_clean', 'write_json ' + shlex.quote(str(raw))])
            design = json.loads(raw.read_text())
            module = design['modules']['quant_parameter_control']
            models[label] = memory_interfaces(module)
            (folder / (label + '.json')).write_text(json.dumps({'modules': {label: module}}) + '\n')
        if models['reference'] != models['current']:
            raise RuntimeError('两份存储模型的参数或端口宽度不一致')
        log = execute(folder, 'equivalence', [
            'read_json ' + shlex.quote(str(folder / 'reference.json')),
            'memory_map', 'opt_clean', 'design -stash reference',
            'read_json ' + shlex.quote(str(folder / 'current.json')),
            'memory_map', 'opt_clean', 'design -stash current',
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'async2sync', 'opt_clean', 'opt_merge', 'equiv_simple -short -seq 1',
            'opt_clean', 'equiv_induct -seq 4', 'equiv_status -assert'])
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if match is None or int(match[2]):
            raise RuntimeError('参数控制与存储等价证明未完成')
        row = {'vlen': vlen, 'bus_width': bus, 'compute_lanes': lanes, 'reuse': reuse,
               'per_channel': per_channel, 'passed': True, 'equivalent_bits': int(match[1]),
               'memories': len(models['current']),
               'memory_parameters_sha256': hashlib.sha256(json.dumps(models['current'], sort_keys=True).encode()).hexdigest(),
               'log_sha256': digest(log)}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    if any(digest(Path(path)) != value for path, value in hashes.items()):
        raise RuntimeError('验证期间源文件发生变化')
    report['passed'] = True
    report['equivalent_bits'] = sum(row['equivalent_bits'] for row in report['profiles'])
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
