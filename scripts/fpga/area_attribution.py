#!/usr/bin/env python3
"""根据保留的原始网线和唯一组合扇出，统计布局前 LUT 的功能归属。"""
from pathlib import Path
from collections import Counter, defaultdict, deque
import argparse
import hashlib
import json
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--metrics', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    mp = args.mapped.resolve()
    mt = args.metrics.resolve()
    output = args.out.resolve()
    base = output.parent
    m = json.loads(mp.read_text())['modules']['soc_top']
    metrics = json.loads(mt.read_text())
    cells = m['cells']
    nets = m['netnames']
    labels = {
        'im2col_frontend': 'im2col 前端与地址生成',
        'im2col_cache': 'im2col 窗口缓存控制',
        'im2col_read_guard': 'im2col AXI 读请求检查',
        'ia_loader': 'IA 加载与缓存管理',
        'shared_sram': '共享 SRAM 接口与读复用',
        'matrix_compute': '矩阵计算阵列与累加',
        'requant': '量化、标量乘法与量化行缓存',
        'vector_engine': '向量计算与控制',
        'ps_storage': 'PS 存储与地址控制',
        'ps_schedule': 'PS 帧调度',
        'kernel_loader': '权重加载与缓存',
        'bias_loader': '偏置加载',
        'writeback': '输出排列与 AXI 写回',
        'matrix_configuration': '矩阵任务配置',
        'matrix_control': '矩阵任务控制',
        'npu_dma': 'NPU DMA 与仲裁',
        'cpu': 'PicoRV32、乘除法及接口',
        'soc_axi': 'SoC AXI 互连与时序缓冲',
        'soc_ram_control': 'SoC 主存访问控制',
        'axil_registers': 'NPU AXI-Lite 寄存器',
        'soc_other': 'SoC 其他外围逻辑',
    }

    def classify(name='', src=''):
        n = name.replace(' ', '.')
        f = src.split('|')[0].split(':')[0].rsplit('/', 1)[-1]
        if 'g_im2col' in n or f.startswith(('conv_im2col', 'conv_coordinate', 'conv_windowed', 'conv_axi_read_guard', 'conv_cache_')):
            if 'u_read_guard' in n or f == 'conv_axi_read_guard.sv':
                return 'im2col_read_guard'
            if 'u_cache' in n or f.startswith(('conv_windowed', 'conv_cache_')):
                return 'im2col_cache'
            return 'im2col_frontend'
        if 'u_ia_loader' in n or f.startswith('ia_loader'):
            return 'ia_loader'
        if 'g_shared_ia_ps' in n or f in ('ia_ps_channel_ram.sv', 'ia_ps_shared_ram.sv', 'shared_ram_read_mux.sv', 'vector_shared_store.sv', 'shared_ram_mapper.sv'):
            return 'shared_sram'
        if 'u_vec_requant' in n or 'u_requant_group_buffer' in n or f.startswith(('requant_', 'vec_requant', 'registered_multiplier_s32')):
            return 'requant'
        if 'u_ps_buffer' in n or f.startswith(('ps_frame_store', 'ps_raw_', 'ps_capacity', 'ps_buffer')):
            return 'ps_storage'
        if 'g_frame_schedule' in n or f.startswith('ps_window'):
            return 'ps_schedule'
        if 'g_vector_engine' in n or f.startswith(('vector_', 'vec_dw', 'vec_add')):
            return 'vector_engine'
        if 'u_compute_core' in n or f in ('compute_core.sv', 'ws_systolic_array.sv', 'ws_systolic_cell.sv', 'ws_accumulator_array.sv', 'ws_data_setup.sv', 'ws_de_diagonalizer.sv'):
            return 'matrix_compute'
        if 'u_kernel_loader' in n or f.startswith('kernel_loader'):
            return 'kernel_loader'
        if 'u_bias_loader' in n or f.startswith('bias_loader'):
            return 'bias_loader'
        if 'u_output_pipeline' in n or f in ('oa_writer.sv', 'oa_writeback.sv', 'vec_s8_to_fifo_full.sv', 'vec_s8_to_fifo.sv', 'vec_s16_to_fifo_full.sv', 'npu_output_pipeline.sv'):
            return 'writeback'
        if 'u_task_configuration' in n or f == 'npu_task_configuration.sv':
            return 'matrix_configuration'
        if 'u_matrix_engine' in n or f in ('npu_matrix_engine.sv', 'npu_controller.sv', 'frame_address.sv'):
            return 'matrix_control'
        if 'u_block_dma_arbiter' in n or '/npu/dma/' in src or f in ('block_dma_arbiter.sv', 'npu_operand_cache_bridge.sv'):
            return 'npu_dma'
        if 'u_picorv32' in n or 'u_pico_axi_bridge' in n or f.startswith(('picorv32', 'pico_axi')):
            return 'cpu'
        if 'u_axi_sim_ram' in n or f == 'soc_axi_ram.sv':
            return 'soc_ram_control'
        if f == 'npu_axil_reg_if.sv' or 'u_npu_axil_reg_if' in n:
            return 'axil_registers'
        if any(s in n for s in ('pingpong', 'u_axi_interconnect', 'u_axil_interconnect')) or f.startswith(('soc_axi', 'soc_axil', 'axi_interconnect', 'axil_interconnect')):
            return 'soc_axi'
        if any(s in n for s in ('u_soc_uart', 'u_timer', 'u_gpio')) or f in ('simpleuart.v', 'soc_uart.sv', 'soc_timer.sv', 'soc_gpio.sv'):
            return 'soc_other'
        return None

    anchors = defaultdict(set)
    examples = defaultdict(set)
    source_examples = defaultdict(set)
    for name, net in nets.items():
        attributes = net.get('attributes', {})
        hdlname = attributes.get('hdlname')
        if not hdlname:
            continue
        group = classify(hdlname, attributes.get('src', ''))
        if group:
            for bit in net['bits']:
                if isinstance(bit, int):
                    anchors[bit].add(group)
            if len(examples[group]) < 3:
                examples[group].add(hdlname.replace(' ', '.'))
            source_examples[group].add(attributes.get('src', '').split('|')[0].split(':')[0])

    def outputs(cell):
        return [bit for port, bits in cell['connections'].items()
                if cell['port_directions'].get(port) == 'output'
                for bit in bits if isinstance(bit, int)]

    def inputs(cell):
        return [bit for port, bits in cell['connections'].items()
                if cell['port_directions'].get(port) == 'input'
                for bit in bits if isinstance(bit, int)]

    def islut(cell):
        return bool(re.fullmatch(r'LUT[1-6](?:_2)?', cell['type']))

    comb = {name for name, cell in cells.items()
            if islut(cell) or cell['type'] in ('INV', 'CARRY4', 'MUXF7', 'MUXF8')}
    lut = {name for name, cell in cells.items() if islut(cell)}
    assert len(lut) == metrics['resources']['logic_lut_cells']
    bit_users = defaultdict(set)
    for name, cell in cells.items():
        for bit in inputs(cell):
            bit_users[bit].add(name)
    seed = {}
    direct = {}
    unknown = '__unknown__'
    owner_by_endpoint = {}
    for name, cell in cells.items():
        found = set().union(*(anchors.get(bit, set()) for bit in outputs(cell)))
        if name in lut:
            direct[name] = found
            if found:
                seed[name] = found
        else:
            group = classify(name, cell.get('attributes', {}).get('src', ''))
            groups = {group} if group else found
            if groups:
                owner_by_endpoint[name] = groups
                if name in comb:
                    seed[name] = groups
            elif name not in comb:
                owner_by_endpoint[name] = {unknown}

    resolved = dict(seed)
    pending = {}
    parents = defaultdict(set)
    collected = {}
    for name in comb:
        if name in seed:
            continue
        result = set()
        dependencies = set()
        for bit in outputs(cells[name]):
            users = bit_users.get(bit, set())
            if not users:
                result.add(unknown)
            for user in users:
                if user in seed:
                    result.update(seed[user])
                elif user in comb:
                    dependencies.add(user)
                else:
                    result.update(owner_by_endpoint.get(user, {unknown}))
        pending[name] = len(dependencies)
        collected[name] = result
        for child in dependencies:
            parents[child].add(name)
    queue = deque(name for name, number in pending.items() if number == 0)
    while queue:
        name = queue.popleft()
        resolved[name] = collected[name] or {unknown}
        for parent in parents[name]:
            collected[parent].update(resolved[name])
            pending[parent] -= 1
            if pending[parent] == 0:
                queue.append(parent)
    for name in comb:
        if name not in resolved:
            resolved[name] = {unknown}
    counts = Counter()
    direct_count = Counter()
    cone_count = Counter()
    unknown_counts = Counter()
    for name in lut:
        found = resolved[name]
        if len(found) == 1 and unknown not in found:
            group = next(iter(found))
            counts[group] += 1
            count = direct_count if len(direct.get(name, set())) == 1 else cone_count
            count[group] += 1
        elif unknown in found:
            unknown_counts['no_unique_original_anchor'] += 1
        else:
            unknown_counts['multiple_function_groups'] += 1
    assert sum(counts.values()) + sum(unknown_counts.values()) == len(lut)
    rows = []
    for group, count in counts.most_common():
        rows.append({
            'group': group,
            'description': labels[group],
            'logic_lut_cells_inferred': count,
            'output_original_net_attribution': direct_count[group],
            'unique_combinational_fanout_attribution': cone_count[group],
            'examples_of_original_nets': sorted(examples[group]),
            'source_files_observed': sorted(s for s in source_examples[group] if s)[:8],
        })
    resources = metrics['resources']
    nominal = resources['lut_sites_nominal_before_packing']
    target = 50000
    paths = []
    for path in metrics['paths']['distinct_register_path_groups']:
        paths.append({
            'combinational_cells': path['combinational_cells'],
            'start': path['startpoint'].get('register_origin') or path['startpoint']['net'],
            'end': path['endpoint'].get('register_origin') or path['endpoint']['net'],
        })
    longest = metrics['paths']['longest_register_path_cells']
    report = {
        'scope': 'Yosys XC7 布局前映射的 soc_top；每个已映射逻辑 LUT 单元计数一次。',
        'input_sha256': {
            str(path.relative_to(base) if path.is_relative_to(base) else path):
                hashlib.sha256(path.read_bytes()).hexdigest() for path in (mp, mt)
        },
        'logic_lut_cells': len(lut),
        'distributed_ram_lut_sites_nominal': resources['distributed_ram_lut_sites_nominal'],
        'shift_register_lut_sites_nominal': resources['shift_register_lut_sites_nominal'],
        'lut_sites_nominal_before_packing': nominal,
        'physical_lut_sites_after_placement': None,
        'target_lut_sites': target,
        'logic_lut_difference': len(lut) - target,
        'nominal_total_lut_difference': nominal - target,
        'required_nominal_total_reduction_percent': round(100 * (nominal - target) / nominal, 3),
        'attribution_method': {
            'classification': '功能归属推断，保留原始网名或组合扇出所到达的唯一功能组；不代表原 RTL 模块在独立综合中的面积。',
            'direct_original_module_attributes_on_lut_cells': 0,
            'original_net_names_with_hdlname': sum('hdlname' in net.get('attributes', {}) for net in nets.values()),
            'rules': [
                '逻辑 LUT 输出若关联唯一功能组的原始 hdlname 网线，按该功能组计数。',
                '其余 LUT 只在组合扇出到达的原始网线或有源文件属性的逻辑终点全部属于同一功能组时归类。',
                '跨功能组和无法定位的单元保留未归类；单元只计数一次。',
            ],
            'limitations': 'Flatten 与 ABC 已将全部 LUT 的 src 改为 Xilinx 映射文件；功能推断使用保留下来的网线和终点。实际 LUT 位置数及频率由布局布线报告提供。',
        },
        'logic_lut_cells_with_unique_inferred_function': sum(counts.values()),
        'unclassified_logic_lut_cells': sum(unknown_counts.values()),
        'unclassified_reasons': dict(unknown_counts),
        'groups': rows,
        'reported_distinct_register_path_groups': paths,
        'longest_reported_register_path_combinational_cells': longest,
        'timing_status': f'结构路径最长为{longest}个组合单元，目标为10；150 MHz 需要器件延迟与布线分析。',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('AREA_ATTRIBUTION', json.dumps({
        'logic_lut_cells': len(lut),
        'lut_sites_nominal_before_packing': nominal,
        'nominal_total_lut_difference': nominal - target,
        'unclassified_logic_lut_cells': sum(unknown_counts.values()),
    }))


if __name__ == '__main__':
    main()
