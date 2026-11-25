#!/usr/bin/env python3
"""由寄存器和存储器的原始层次反向计算完整 SoC 的功能资源分布。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import FF_PATTERN, LUT_PATTERN, RAM_LUT_SITES, SRL_TYPES, register_origins
from lut_dependencies import lut_output_dependencies


def unobserved_cells(module):
    """跨全部输入和存储边界保守计算公开输出的依赖。"""
    drivers = defaultdict(set)
    inputs = {}
    reached = set()
    roots = {bit for port in module.get('ports', {}).values()
             if port['direction'] in ('output', 'inout')
             for bit in port['bits'] if isinstance(bit, int)}
    for name, cell in module['cells'].items():
        directions = cell['port_directions']
        if set(cell['connections']) - set(directions):
            raise ValueError('缺少单元端口方向：' + name)
        inputs[name] = {bit for port, bits in cell['connections'].items()
                        if directions[port] in ('input', 'inout')
                        for bit in bits if isinstance(bit, int)}
        outputs = [port for port in cell['connections'] if directions[port] in ('output', 'inout')]
        for port in outputs:
            for bit in cell['connections'][port]:
                if isinstance(bit, int):
                    drivers[bit].add(name)
        if not outputs:
            reached.add(name)
            roots.update(inputs[name])
    queue, visited = deque(roots), set(roots)
    while queue:
        bit = queue.popleft()
        for name in drivers[bit]:
            if name in reached:
                continue
            reached.add(name)
            for source in inputs[name]:
                if source not in visited:
                    visited.add(source)
                    queue.append(source)
    return set(module['cells']) - reached


def function_owner(name):
    """将保留的实例或寄存器名称转换为功能模块名。"""
    name = name.replace('\\', '').replace(' ', '.')
    if 'u_picorv32.' in name:
        return 'cpu'
    if 'u_axi_sim_ram.' in name:
        return 'axi_system_memory'
    if '.u_frontend.' in name:
        child = name.split('.u_frontend.', 1)[1].split('.')[0]
        return 'im2col.' + child if child.startswith('u_') else 'im2col.control'
    if '.g_vector_engine.u_engine.' in name:
        child = name.split('.g_vector_engine.u_engine.', 1)[1].split('.')[0]
        return 'vector.' + child if child.startswith('u_') else 'vector.local_control'
    if '.u_matrix_engine.' in name:
        child = name.split('.u_matrix_engine.', 1)[1]
        for prefix, label in (
            ('u_compute_core.u_systolic_array.', 'compute_array'),
            ('u_compute_core.u_ps_buffer.', 'partial_sum_buffer'),
            ('u_compute_core.', 'compute_control'),
            ('u_output_pipeline.u_vec_requant.', 'requantization'),
            ('u_output_pipeline.u_bias_add.', 'bias_add'),
            ('u_output_pipeline.u_oa_writer.', 'output_writer'),
            ('u_output_pipeline.u_vec_s8_to_fifo.', 'output_packer'),
            ('u_output_pipeline.', 'output_control'),
            ('g_frame_schedule.', 'frame_schedule'),
        ):
            if child.startswith(prefix):
                return 'matrix.' + label
        first = child.split('.')[0]
        return 'matrix.' + first if first.startswith('u_') else 'matrix.control'
    if '.u_block_dma_arbiter.u_dma.' in name:
        first = name.split('.u_block_dma_arbiter.u_dma.', 1)[1].split('.')[0]
        return 'dma.' + first if first.startswith('u_') else 'dma.control'
    if '.u_block_dma_arbiter.' in name:
        return 'dma.arbiter'
    if '.u_npu_top.' in name:
        first = name.split('.u_npu_top.', 1)[1].split('.')[0]
        return 'npu.' + first if first.startswith('u_') else 'npu.control'
    if 'u_npu_axil_top.' in name:
        return 'npu.axi_control'
    match = re.search(r'\b(u_[A-Za-z0-9_]+)\.', name)
    return 'soc.' + match.group(1) if match else None


def analyze(module, origins, unobserved):
    """保留共享单元集合，分别报告唯一归属和分数分配结果。"""
    cells = module['cells']
    boundary = {}
    aliases = defaultdict(set)
    drivers = defaultdict(set)
    fanin = defaultdict(set)
    masks = defaultdict(int)
    pending = deque()
    labels = {'unclassified': 0, 'public_outputs': 1}

    def label_bit(label):
        if label not in labels:
            labels[label] = len(labels)
        return 1 << labels[label]

    def output_bits(cell):
        return {bit for port, bits in cell['connections'].items()
                if cell['port_directions'][port] in ('output', 'inout')
                for bit in bits if isinstance(bit, int)}

    def input_bits(cell):
        clock_ports = {'CLK', 'WCLK', 'CLKA', 'CLKB', 'CLKARDCLK', 'CLKBWRCLK'}
        if FF_PATTERN.fullmatch(cell['type']):
            clock_ports.add('C')
        return {bit for port, bits in cell['connections'].items()
                if cell['port_directions'][port] in ('input', 'inout')
                and port not in clock_ports
                for bit in bits if isinstance(bit, int)}

    for name, net in module.get('netnames', {}).items():
        if not name.startswith('$'):
            for bit in net['bits']:
                if isinstance(bit, int):
                    aliases[bit].add(name)
    for name, cell in cells.items():
        for bit in output_bits(cell):
            drivers[bit].add(name)
    conflicts = {bit: names for bit, names in drivers.items() if len(names) != 1}
    if conflicts:
        raise ValueError('同一连接位存在多个驱动：' + repr(list(conflicts.items())[:5]))

    def infer_names(name, cell):
        original = origins.get(name)
        owner = function_owner(original) if original else None
        if owner:
            return {owner}, 'register_origin'
        for value in (name, cell.get('attributes', {}).get('hdlname', '')):
            owner = function_owner(value)
            if owner:
                return {owner}, 'cell_hierarchy'
        owners = {function_owner(alias) for bit in output_bits(cell) for alias in aliases[bit]}
        owners.discard(None)
        return owners, 'output_signal' if owners else None

    def seed(bit, mask):
        if isinstance(bit, int) and mask & ~masks[bit]:
            masks[bit] |= mask
            pending.append(bit)

    def spread():
        while pending:
            output = pending.popleft()
            for source in fanin[output]:
                seed(source, masks[output])

    def arc(output, inputs):
        if isinstance(output, int):
            fanin[output].update(bit for bit in inputs if isinstance(bit, int))

    for name, cell in cells.items():
        kind, ports = cell['type'], cell['connections']
        is_boundary = FF_PATTERN.fullmatch(kind) or kind.startswith('RAMB') or kind in RAM_LUT_SITES or kind in SRL_TYPES or kind == 'DSP48E1'
        if is_boundary:
            owners, method = infer_names(name, cell)
            mask = sum(label_bit(owner) for owner in owners)
            boundary[name] = {'mask': mask, 'method': method, 'cell_type': kind}
            if mask:
                for bit in input_bits(cell):
                    seed(bit, mask)
        elif kind == 'CARRY4':
            for port in ('O', 'CO'):
                for index, bit in enumerate(ports.get(port, [])):
                    selected = list(ports.get('CI', [])) + list(ports.get('CYINIT', []))
                    selected += ports.get('S', [])[:index + 1]
                    selected += ports.get('DI', [])[:index + (port == 'CO')]
                    arc(bit, selected)
        elif LUT_PATTERN.fullmatch(kind):
            for port, bits in ports.items():
                if cell['port_directions'][port] == 'output':
                    dependencies = [bit for _, _, bit in lut_output_dependencies(cell, port)]
                    for bit in bits:
                        arc(bit, dependencies)
        elif kind in ('INV', 'MUXF7', 'MUXF8', 'MUXF9', 'IBUF', 'OBUF'):
            for bit in output_bits(cell):
                arc(bit, input_bits(cell))
        elif kind in ('BUFG', 'BUFGCE'):
            for bit in ports.get('CE', []):
                seed(bit, label_bit('npu.clock_control'))
        else:
            raise ValueError('资源归属尚未定义该单元类型：' + kind)

    for port in module.get('ports', {}).values():
        if port['direction'] in ('output', 'inout'):
            for bit in port['bits']:
                seed(bit, label_bit('public_outputs'))
    spread()

    # 乘法器等硬件单元可能没有原始输出别名，以实际连接的下一级存储归属补充。
    waiting = {name for name, row in boundary.items() if not row['mask']}
    while waiting:
        resolved = set()
        for name in waiting:
            mask = 0
            for bit in output_bits(cells[name]):
                mask |= masks[bit]
            if mask:
                boundary[name].update(mask=mask, method='downstream_storage')
                for bit in input_bits(cells[name]):
                    seed(bit, mask)
                resolved.add(name)
        if not resolved:
            break
        waiting -= resolved
        spread()
    for name in waiting:
        boundary[name].update(mask=label_bit('unclassified'), method='unclassified')
        for bit in input_bits(cells[name]):
            seed(bit, label_bit('unclassified'))
    spread()

    owner_names = {value: name for name, value in labels.items()}

    def names_for(mask):
        return tuple(owner_names[index] for index in range(mask.bit_length()) if mask & (1 << index))

    rows = defaultdict(Counter)
    allocated = defaultdict(Fraction)
    shared = Counter()
    categories = Counter()
    assignments = {}
    resource_groups = defaultdict(Counter)
    for name, cell in cells.items():
        kind = cell['type']
        mask = boundary[name]['mask'] if name in boundary else 0
        if not mask:
            for bit in output_bits(cell):
                mask |= masks[bit]
        owners = names_for(mask)
        if LUT_PATTERN.fullmatch(kind):
            if name in unobserved:
                category, owners = 'unobserved', ('unobserved',)
            elif not owners or owners == ('unclassified',):
                category, owners = 'unclassified', ('unclassified',)
            elif len(owners) == 1:
                category = 'unique'
            else:
                category = 'shared'
                shared[owners] += 1
            categories[category] += 1
            assignments[name] = {'category': category, 'owners': owners}
            for owner in owners:
                rows[owner][category + '_logic_lut_cells'] += 1
                allocated[owner] += Fraction(1, len(owners))
        elif kind in ('INV', 'CARRY4', 'DSP48E1', 'RAMB36E1', 'RAMB18E1') or FF_PATTERN.fullmatch(kind) or kind in RAM_LUT_SITES or kind in SRL_TYPES:
            resource_groups['; '.join(owners) if owners else 'unclassified'][kind] += 1
    total = sum(1 for cell in cells.values() if LUT_PATTERN.fullmatch(cell['type']))
    if sum(categories.values()) != total or sum(allocated.values()) != total:
        raise ValueError('功能归属结果与完整网表的 LUT 总数不一致')
    table = []
    for owner in sorted(rows, key=lambda key: -allocated[key]):
        table.append({'function': owner, **dict(rows[owner]),
                      'allocated_logic_lut_cells': float(allocated[owner]),
                      'allocated_logic_lut_fraction': str(allocated[owner])})
    return {'logic_lut_cells': total, 'categories': dict(categories),
            'allocated_logic_lut_fraction': str(sum(allocated.values())),
            'functions': table,
            'shared_groups': [{'functions': names, 'logic_lut_cells': count}
                              for names, count in shared.most_common()],
            'other_resource_groups': {key: dict(value) for key, value in resource_groups.items()},
            'boundary_assignment_methods': dict(Counter(row['method'] for row in boundary.values())),
            'unclassified_boundary_cells': sorted(waiting),
            'boundary_cells': {name: {**row, 'owners': names_for(row['mask'])}
                               for name, row in boundary.items()},
            'lut_assignments': assignments,
            'method': 'Register origins and retained memory-instance or output names identify storage and arithmetic owners. Combinational dependencies propagate owner sets backward, stopping at those boundaries. LUT inputs use their INIT function; CARRY4 inputs follow bitwise carry direction. A shared LUT is listed once globally and divided equally only in the optional fractional allocation. Cells unable to affect any public output remain included as unobserved resources.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--netlist', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--reachability', type=Path,
                        help='复用同一网表已有的公开输出可达性结果')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--top', default='soc_top')
    parser.add_argument('--include-cell-details', action='store_true',
                        help='同时保存逐个 LUT 和存储单元的归属')
    args = parser.parse_args()
    raw = args.netlist.read_bytes()
    if args.netlist.suffix == '.gz':
        raw = gzip.decompress(raw)
    module = json.loads(raw)['modules'][args.top]
    mapped_digest = hashlib.sha256(raw).hexdigest()
    if args.reachability:
        reach = json.loads(args.reachability.read_text())
        if reach['mapped_sha256'] != mapped_digest:
            raise ValueError('公开输出可达性结果来自其他网表')
        unobserved = {row['cell'] for row in reach['unobserved_cells']}
    else:
        unobserved = unobserved_cells(module)
    origins = register_origins(args.pre_lut, args.top)
    result = analyze(module, origins, unobserved)
    result['mapped_sha256'] = mapped_digest
    result['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not args.include_cell_details:
        result.pop('boundary_cells')
        result.pop('lut_assignments')
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'logic_lut_cells': result['logic_lut_cells'], 'categories': result['categories'],
                      'boundary_assignment_methods': result['boundary_assignment_methods']}, indent=2))
    for row in result['functions'][:30]:
        print(json.dumps(row))


if __name__ == '__main__':
    main()
