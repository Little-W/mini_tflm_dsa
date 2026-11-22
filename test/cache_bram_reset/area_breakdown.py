#!/usr/bin/env python3
"""按组合逻辑的后继用途整理缓存 LUT、存储和寄存器分布。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import FF_PATTERN, RAM_LUT_SITES, SRL_TYPES, parameter, register_origins
from lut_dependencies import LUT_PATTERN, lut_output_dependencies

CATEGORIES = ('prefetch_queue', 'prefetch_offer', 'request_lookup', 'response',
              'replacement_fill', 'metadata', 'axi_reader', 'configuration', 'other')


def category(name: str) -> str:
    if 'u_span.' in name:
        return 'axi_reader'
    if 'g_metadata_way' in name:
        return 'metadata'
    if re.search(r'u_prefetch|\bpf_|\bprefetch_', name):
        return 'prefetch_queue'
    if name.startswith(('offer_', 'reference_')):
        return 'prefetch_offer'
    if name.startswith(('select_', 'fill_', 'demand_', 'hint_')):
        return 'replacement_fill'
    if name.startswith(('response_', 'rsp_', 'ram_rdata', 'outstanding_count')):
        return 'response'
    if name.startswith(('request_', 'work_', 'lookup_', 'incoming_', 'next_', 'fg_state', 'g_data_way', 'req_')):
        return 'request_lookup'
    if name.startswith(('base_q', 'end_q', 'bypass_q', 'windowed_q', 'configured', 'clearing', 'clear_set', 'cfg_')):
        return 'configuration'
    if name.startswith(('ar', 'rready')):
        return 'axi_reader'
    return 'other'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    design = json.loads((args.native / 'mapped.json').read_text())
    module = design['modules']['conv_windowed_cache']
    cells = module['cells']
    origins = register_origins(args.native / 'pre_lut.il')
    inputs = defaultdict(set)
    masks = defaultdict(int)
    pending = deque()
    memory = Counter()
    registers = Counter()

    def seed(bit, label):
        if isinstance(bit, int):
            flag = 1 << CATEGORIES.index(label)
            if not masks[bit] & flag:
                masks[bit] |= flag
                pending.append(bit)

    def connect(outputs, dependencies):
        selected = [bit for bit in dependencies if isinstance(bit, int)]
        for bit in outputs:
            if isinstance(bit, int):
                inputs[bit].update(selected)

    for name, cell in cells.items():
        kind, ports = cell['type'], cell['connections']
        label = category(origins.get(name, name))
        incoming = {port: bits for port, bits in ports.items()
                    if cell['port_directions'][port] == 'input'}
        outgoing = {port: bits for port, bits in ports.items()
                    if cell['port_directions'][port] == 'output'}
        if FF_PATTERN.fullmatch(kind):
            registers[label] += len(ports['Q'])
            for port in ('D', 'CE', 'R', 'S', 'CLR', 'PRE'):
                for bit in ports.get(port, []):
                    seed(bit, label)
        elif kind.startswith('RAMB'):
            memory[name] += 0
            for port, bits in incoming.items():
                if not port.startswith(('CLK', 'CASCADE')):
                    for bit in bits:
                        seed(bit, label)
        elif kind in RAM_LUT_SITES or kind in SRL_TYPES:
            memory[name] += RAM_LUT_SITES.get(kind, 1)
            for port, bits in outgoing.items():
                selected = [value for key, values in incoming.items()
                            if re.fullmatch(r'ADDR[A-D]|A|A[0-9]+|ADR[0-9]+|DPRA|DPRA[0-9]+|RADR[0-9]+', key)
                            for value in values]
                if kind in ('RAM32M', 'RAM64M') and port.startswith('DO'):
                    selected = incoming.get('ADDR' + port[-1], [])
                connect(bits, selected)
            for port, bits in incoming.items():
                read_only = port.startswith(('DPRA', 'RADR'))
                read_only |= kind in SRL_TYPES and port.startswith('A')
                read_only |= kind in ('RAM32M', 'RAM64M') and port in ('ADDRA', 'ADDRB', 'ADDRC')
                if not port.startswith(('CLK', 'WCLK')) and not read_only:
                    for bit in bits:
                        seed(bit, label)
        elif LUT_PATTERN.fullmatch(kind):
            for port, bits in outgoing.items():
                connect(bits, [bit for _, _, bit in lut_output_dependencies(cell, port)])
        elif kind == 'CARRY4':
            for output in ('O', 'CO'):
                for index, bit in enumerate(ports.get(output, [])):
                    dependencies = ports.get('CI', []) + ports.get('CYINIT', [])
                    dependencies += ports.get('S', [])[:index + 1]
                    dependencies += ports.get('DI', [])[:index + (output == 'CO')]
                    connect([bit], dependencies)
        elif kind == 'DSP48E1':
            if any(parameter(cell, name) for name in ('AREG', 'BREG', 'CREG', 'DREG', 'ADREG', 'MREG', 'PREG')):
                raise RuntimeError('缓存用途统计需要分别处理带寄存级的 DSP')
            dependencies = [bit for port, bits in incoming.items()
                            if not port.startswith(('CLK', 'RST', 'CE')) for bit in bits]
            connect([bit for bits in outgoing.values() for bit in bits], dependencies)
        elif kind in ('INV', 'MUXF7', 'MUXF8', 'MUXF9', 'OBUF'):
            connect([bit for bits in outgoing.values() for bit in bits],
                    [bit for bits in incoming.values() for bit in bits])
        elif kind not in ('IBUF', 'BUFG', 'BUFH', 'VCC', 'GND'):
            raise RuntimeError('未分类的映射单元: ' + kind)
    for name, port in module['ports'].items():
        if port['direction'] == 'output':
            for bit in port['bits']:
                seed(bit, category(name))
    while pending:
        bit = pending.popleft()
        for previous in inputs.get(bit, ()):
            merged = masks[previous] | masks[bit]
            if merged != masks[previous]:
                masks[previous] = merged
                pending.append(previous)
    aliases = defaultdict(list)
    for name, net in module.get('netnames', {}).items():
        if not name.startswith('$'):
            for bit in net['bits']:
                if isinstance(bit, int):
                    aliases[bit].append(name)
    exclusive, shared, unassigned = Counter(), Counter(), []
    for name, cell in cells.items():
        if not LUT_PATTERN.fullmatch(cell['type']):
            continue
        selected = 0
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for bit in bits:
                    selected |= masks.get(bit, 0)
        labels = [name for index, name in enumerate(CATEGORIES) if selected & (1 << index)]
        if len(labels) == 1:
            exclusive[labels[0]] += 1
        else:
            shared[','.join(labels) if labels else 'unassigned_consumer'] += 1
            if not labels:
                unassigned.append({'cell': name, 'aliases': sorted({alias
                    for port, bits in cell['connections'].items()
                    if cell['port_directions'][port] == 'output'
                    for bit in bits for alias in aliases.get(bit, [])})})
    groups = Counter()
    for name, count in memory.items():
        if count:
            groups[re.sub(r'\.\d+\.\d+$', '', name)] += count
    total = sum(exclusive.values()) + sum(shared.values())
    result = {
        'logic_lut_total': total,
        'exclusive_successor_categories': dict(exclusive.most_common()),
        'shared_successor_categories': dict(shared.most_common()),
        'distributed_storage_lut_groups': dict(groups.most_common()),
        'flip_flops_by_successor_use': dict(registers.most_common()),
        'unassigned_consumer_luts': unassigned,
        'method': 'Each logic LUT is counted once by the categories of its downstream register or output consumers. Shared categories are listed separately. DSP combinational input dependencies are conservative; this grouping locates candidate structures and is not an additive prediction of optimization savings.',
    }
    metrics = json.loads((args.native / 'metrics.json').read_text())
    if total != metrics['resources']['logic_lut_cells']:
        raise RuntimeError('LUT 用途统计与映射总数不一致')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
