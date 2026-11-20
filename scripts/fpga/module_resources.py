#!/usr/bin/env python3
"""Attribute flattened LUT cells to RTL modules through preserved sources and consumers."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re

from netlist_metrics import FF_PATTERN, LUT_PATTERN, RAM_LUT_SITES, SRL_TYPES, register_origins


def rtl_source(cell):
    for part in cell.get('attributes', {}).get('src', '').split('|'):
        match = re.search(r'((?:rtl|picorv32)/[^:]+\.(?:sv|v)):', part)
        if match:
            return match.group(1)
    return None


def register_sources(path, origins):
    """从原始 Q 信号的声明取得 RTL 来源，保留技术映射前的模块归属。"""
    signals = {origin.split(' ')[0] for origin in origins.values()}
    sources = {}
    current = None
    with path.open() as stream:
        for line in stream:
            if line.startswith('  attribute \\src '):
                current = rtl_source({'attributes': {'src': json.loads(line.split('\\src ', 1)[1])}})
            elif line.startswith('  wire '):
                name = line.split('# ', 1)[1].strip() if '# ' in line else line.split()[-1]
                name = name.lstrip('\\')
                if current and name in signals:
                    sources[name] = current
                current = None
            elif line.startswith(('  cell ', '  memory ', 'module ', 'end')):
                current = None
    return {name: sources[origin.split(' ')[0]] for name, origin in origins.items()
            if origin.split(' ')[0] in sources}


def attribute_resources(module, origins, source_origins=None):
    cells = module['cells']
    source_origins = source_origins or {}
    instance_sources = collections.defaultdict(set)
    for name, origin in origins.items():
        if name not in cells:
            continue
        source = source_origins.get(name) or rtl_source(cells[name])
        if source:
            instance = origin.split(' ')[0].rsplit('.', 1)[0]
            instance_sources[instance].add(source)

    def owner(name, cell):
        source = rtl_source(cell) or source_origins.get(name)
        if source and not source.startswith('rtl/common/'):
            return source
        instance = origins.get(name, name).split(' ')[0]
        while '.' in instance:
            instance = instance.rsplit('.', 1)[0]
            # 公共 REGFILE 等单元的资源归入最近的功能模块。
            possible = {item for item in instance_sources.get(instance, set())
                        if not item.startswith('rtl/common/')}
            if len(possible) == 1:
                return next(iter(possible))
        return source

    owners = {name: owner(name, cell) for name, cell in cells.items()}
    labels = sorted(set(item for item in owners.values() if item is not None) | {'top_level_outputs', 'unclassified'})
    label_bits = {label: 1 << index for index, label in enumerate(labels)}
    output_drivers = {}
    consumers = collections.defaultdict(set)
    boundary = set()
    for name, cell in cells.items():
        kind = cell['type']
        if FF_PATTERN.fullmatch(kind) or kind.startswith(('RAM', 'SRL', 'DSP')) or kind == 'CARRY4' or owners[name]:
            boundary.add(name)
        for port, values in cell['connections'].items():
            for bit in values:
                if not isinstance(bit, int):
                    continue
                if cell['port_directions'][port] == 'output':
                    output_drivers[bit] = name
                else:
                    consumers[bit].add(name)

    upstream = collections.defaultdict(set)
    downstream = collections.defaultdict(set)
    ownership = collections.defaultdict(int)
    for bit, driver in output_drivers.items():
        if driver in boundary:
            continue
        for consumer in consumers[bit]:
            if consumer in boundary:
                ownership[driver] |= label_bits[owners[consumer] or 'unclassified']
            elif consumer != driver:
                upstream[consumer].add(driver)
                downstream[driver].add(consumer)
    for port in module.get('ports', {}).values():
        if port['direction'] == 'output':
            for bit in port['bits']:
                if bit in output_drivers:
                    ownership[output_drivers[bit]] |= label_bits['top_level_outputs']
    nodes = set(cells) - boundary
    degree = {name: len(downstream[name]) for name in nodes}
    ready = collections.deque(name for name, count in degree.items() if count == 0)
    while ready:
        name = ready.popleft()
        for parent in upstream[name]:
            ownership[parent] |= ownership[name]
            degree[parent] -= 1
            if degree[parent] == 0:
                ready.append(parent)

    counts = collections.defaultdict(collections.Counter)
    mixed = collections.Counter()
    total_luts = 0
    for name, cell in cells.items():
        kind = cell['type']
        label = owners[name]
        if LUT_PATTERN.fullmatch(kind):
            total_luts += 1
            mask = ownership[name]
            if label is None:
                if mask and mask & (mask - 1) == 0:
                    label = labels[mask.bit_length() - 1]
                elif mask:
                    label = 'shared_between_modules'
                    mixed[mask] += 1
                else:
                    label = 'unclassified'
            counts[label]['logic_lut_cells'] += 1
        elif FF_PATTERN.fullmatch(kind):
            counts[label or 'unclassified']['flip_flops'] += 1
        elif kind in RAM_LUT_SITES:
            counts[label or 'unclassified']['distributed_ram_lut_sites_nominal'] += RAM_LUT_SITES[kind]
        elif kind in SRL_TYPES:
            counts[label or 'unclassified']['shift_register_lut_sites_nominal'] += 1
        elif kind in ('DSP48E1', 'RAMB36E1', 'RAMB18E1', 'CARRY4'):
            counts[label or 'unclassified'][kind.lower()] += 1
    rows = [{'rtl_source_or_group': label, **dict(count)} for label, count in counts.items()]
    rows.sort(key=lambda row: (-row.get('logic_lut_cells', 0), row['rtl_source_or_group']))
    assert sum(row.get('logic_lut_cells', 0) for row in rows) == total_luts
    return {
        'logic_lut_cells': total_luts, 'module_resources': rows,
        'mixed_lut_groups': [{'logic_lut_cells': count,
                              'consumers': [label for index, label in enumerate(labels) if mask & (1 << index)]}
                             for mask, count in mixed.most_common(20)],
        'remaining_graph_cycle_cells': sum(count > 0 for count in degree.values()),
        'registers_with_original_signal_source': sum(name in cells for name in source_origins),
        'attribution_method': 'Original register signal declarations, RTL source attributes and register instance names identify storage and arithmetic owners. Flattened LUTs without source attributes are assigned when all reachable consumer owners agree; shared and unclassified logic are reported separately.',
        'physical_lut_positions_by_module': None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--netlist', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--top', default='soc_top')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.netlist.read_text())['modules'][args.top]
    origins = register_origins(args.pre_lut)
    result = attribute_resources(module, origins, register_sources(args.pre_lut, origins))
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    for row in result['module_resources'][:15]:
        print(json.dumps(row))


if __name__ == '__main__':
    main()
