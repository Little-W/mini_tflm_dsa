#!/usr/bin/env python3
"""在目标 DSP 数量和组合级数限制内选择算术单元。"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re

from lut_dependencies import LUT_PATTERN, lut_output_dependencies


SEQUENTIAL = re.compile(r'^\$(?:dff|sdff|adff|aldff|dlatch|adlatch|sr|ff)[a-z]*$|^\$_(?:DFF|SDFF|DFFE|DLATCH)|^FD[CRPS]E$|^LD[CP]E$')


def integer(value):
    return value if isinstance(value, int) else int(value, 2)


def attribute_text(value):
    """读取字符串及常量表达式生成的 ASCII 位向量属性。"""
    value = str(value).strip()
    if re.fullmatch(r'(?:[01]{8})+', value):
        try:
            value = int(value, 2).to_bytes(len(value) // 8, 'big').decode('ascii')
        except UnicodeDecodeError:
            return value.lower()
    return value.strip('\x00').strip().lower()


def bits(cell, direction):
    return {bit for port, values in cell['connections'].items()
            if cell['port_directions'][port] == direction
            for bit in values if isinstance(bit, int)}


def next_autoidx(design):
    """恢复 JSON 中私有名称所需的 RTLIL 自动编号范围。"""
    maximum = 0
    for module_name, module in design['modules'].items():
        names = [module_name]
        for kind in ('cells', 'netnames', 'ports', 'memories'):
            names.extend(module.get(kind, {}))
        for name in names:
            for value in re.findall(r'\$(\d+)', name):
                maximum = max(maximum, int(value))
    if maximum >= 2 ** 31 - 1:
        raise ValueError('Automatic name counter exceeds the RTLIL integer range')
    return maximum + 1


def combinational_inputs(cell, output=None):
    kind = cell['type']
    if SEQUENTIAL.match(kind) or kind.startswith(('RAMB', 'URAM')):
        return set()
    if kind.startswith(('RAM', 'SRL')):
        return {bit for port, values in cell['connections'].items()
                if re.fullmatch(r'A|A[0-9]+|ADDR[A-D]?|DPRA[0-9]+', port)
                for bit in values if isinstance(bit, int)}
    if LUT_PATTERN.fullmatch(kind):
        outputs = [output] if output is not None else [port for port in cell['connections']
                   if cell['port_directions'][port] == 'output']
        return {bit for port in outputs for _, _, bit in lut_output_dependencies(cell, port)}
    return bits(cell, 'input')


def select_attribute_cells(module, budget, reserve=0):
    """按 RTL 算术结果的 use_dsp 属性选择单元，保留未标注的运算。"""
    cells = module['cells']
    existing = sum(cell['type'] == 'DSP48E1' for cell in cells.values())
    marked_bits = collections.defaultdict(list)
    for name, net in module.get('netnames', {}).items():
        if attribute_text(net.get('attributes', {}).get('use_dsp', '')) != 'yes':
            continue
        for bit in net['bits']:
            if isinstance(bit, int):
                marked_bits[bit].append(name)
    selected = []
    for name, cell in sorted(cells.items()):
        if cell['type'] != '$alu':
            continue
        signals = sorted({signal for bit in cell['connections']['Y']
                          for signal in marked_bits.get(bit, [])})
        cell_marked = attribute_text(cell.get('attributes', {}).get('use_dsp', '')) == 'yes'
        if not signals and not cell_marked:
            continue
        width = integer(cell['parameters']['Y_WIDTH'])
        if not 1 <= width <= 48:
            raise ValueError(f'RTL DSP arithmetic width is outside 1..48: {name} ({width})')
        selected.append({'cell': name, 'width': width, 'rtl_signals': signals,
                         'cell_attribute': cell_marked})
    if existing + len(selected) + reserve > budget:
        raise ValueError(f'RTL DSP attributes require {existing + len(selected)} DSP cells '
                         f'plus {reserve} reserved cells; budget is {budget}')
    return {'dsp_budget': budget, 'dsp_reserve': reserve, 'existing_dsp_cells': existing,
            'additional_dsp_cells': len(selected), 'resulting_dsp_cells': existing + len(selected),
            'minimum_width': 1, 'maximum_width': 48, 'candidate_cells': len(selected),
            'selected': selected, 'use_dsp_attributes': True,
            'selection_rule': 'Select arithmetic cells whose result or cell has RTL use_dsp=yes; '
                              'preserve all other arithmetic and report complete mapped paths'}


def select_cells(module, budget, reserve=0, minimum_width=24, maximum_width=48,
                 maximum_chain=1, pack_small_alu=False):
    if maximum_chain not in (1, 2):
        raise ValueError('Selected combinational DSP limit must be one or two')
    if pack_small_alu and maximum_chain != 1:
        raise ValueError('Four-lane arithmetic requires independent selected DSP cells')
    cells = module['cells']
    existing = sum(cell['type'] == 'DSP48E1' for cell in cells.values())
    if existing + reserve > budget:
        raise ValueError(f'Existing DSP count {existing} plus reserve {reserve} exceeds budget {budget}')
    candidates = {}
    for name, cell in cells.items():
        if cell['type'] != '$alu':
            continue
        width = integer(cell['parameters']['Y_WIDTH'])
        if not minimum_width <= width <= maximum_width:
            continue
        variable_inputs = sum(isinstance(bit, int) for port in ('A', 'B')
                              for bit in cell['connections'][port])
        candidates[name] = {'width': width, 'variable_operand_bits': variable_inputs,
                            'score': width + min(variable_inputs, 2 * width)}
    names = sorted(candidates)
    indices = {name: index for index, name in enumerate(names)}
    fixed_bit = 1 << len(names)
    dsp_outputs = set()
    dsp_inputs = set()
    drivers = {}
    nodes = {}
    for name, cell in cells.items():
        outputs = bits(cell, 'output')
        if cell['type'] == 'DSP48E1':
            if integer(cell['parameters'].get('PREG', 1)) == 0:
                dsp_outputs.update(outputs)
                dsp_inputs.update(bits(cell, 'input'))
            else:
                for parameter, source, cascade_in, cascade_out in (
                        ('ACASCREG', 'A', 'ACIN', 'ACOUT'), ('BCASCREG', 'B', 'BCIN', 'BCOUT')):
                    if integer(cell['parameters'].get(parameter, 1)) == 0:
                        dsp_outputs.update(bit for bit in cell['connections'].get(cascade_out, []) if isinstance(bit, int))
                        dsp_inputs.update(bit for port in (source, cascade_in)
                                          for bit in cell['connections'].get(port, []) if isinstance(bit, int))
            continue
        if LUT_PATTERN.fullmatch(cell['type']):
            # 每个输出具有自己的依赖节点，保留双输出原语内部的独立函数。
            views = [(port, combinational_inputs(cell, port),
                      {bit for bit in cell['connections'][port] if isinstance(bit, int)})
                     for port in cell['connections'] if cell['port_directions'][port] == 'output']
        else:
            inputs = combinational_inputs(cell)
            views = [('', inputs, outputs)] if inputs else []
        for port, inputs, selected_outputs in views:
            node = (name, port)
            nodes[node] = inputs
            for bit in selected_outputs:
                if bit in drivers and drivers[bit] != node:
                    raise ValueError(f'Multiple combinational drivers for bit {bit}')
                drivers[bit] = node
    parents = {name: {drivers[bit] for bit in inputs if bit in drivers} for name, inputs in nodes.items()}
    children = collections.defaultdict(set)
    for name, dependencies in parents.items():
        for dependency in dependencies:
            children[dependency].add(name)
    degree = {name: len(dependencies) for name, dependencies in parents.items()}
    ready = collections.deque(name for name, count in degree.items() if count == 0)
    origins = {}
    while ready:
        name = ready.popleft()
        origin = fixed_bit if nodes[name] & dsp_outputs else 0
        for dependency in parents[name]:
            origin |= origins[dependency]
        if name[0] in indices:
            origin |= 1 << indices[name[0]]
        origins[name] = origin
        for child in sorted(children[name]):
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
    remaining = sorted(name for name, count in degree.items() if count)
    if remaining:
        raise ValueError('Combinational cycle before DSP selection: ' +
                         ', '.join(name + ('.' + port if port else '') for name, port in remaining[:8]))

    forbidden = 0
    for bit in dsp_inputs:
        if bit in drivers:
            forbidden |= origins[drivers[bit]]
    ancestors = {}
    descendants = collections.defaultdict(int)
    blocked_by_existing = []
    for name, index in indices.items():
        origin = origins.get((name, ''), 1 << index)
        ancestors[name] = origin & (fixed_bit - 1) & ~(1 << index)
        if origin & fixed_bit or forbidden & (1 << index):
            blocked_by_existing.append(name)
        pending = ancestors[name]
        while pending:
            bit = pending & -pending
            descendants[bit.bit_length() - 1] |= 1 << index
            pending ^= bit

    limit = budget - reserve - existing
    selected = []
    additional = 0
    small_groups = collections.defaultdict(list)
    blocked = sum(1 << indices[name] for name in blocked_by_existing)
    selected_bits = 0
    prefix, suffix = {}, {}
    topological_candidates = sorted(names, key=lambda name: (ancestors[name].bit_count(), name))

    def peak(mask, values):
        result = 0
        pending = mask & selected_bits
        while pending:
            bit = pending & -pending
            result = max(result, values.get(bit.bit_length() - 1, 0))
            pending ^= bit
        return result

    def refresh_depths():
        prefix.clear()
        suffix.clear()
        for item in topological_candidates:
            index = indices[item]
            if selected_bits & (1 << index):
                prefix[index] = 1 + peak(ancestors[item], prefix)
        for item in reversed(topological_candidates):
            index = indices[item]
            if selected_bits & (1 << index):
                suffix[index] = 1 + peak(descendants[index], suffix)
    # 先保持 24 至 48 位算术的选择，再用较窄独立单元补充剩余 DSP。
    for name in sorted(names, key=lambda item: (-(candidates[item]['width'] >= 24),
                                                -candidates[item]['score'], -candidates[item]['width'], item)):
        index = indices[name]
        if additional == limit and not pack_small_alu:
            break
        if blocked & (1 << index):
            continue
        if maximum_chain > 1 and 1 + peak(ancestors[name], prefix) + peak(descendants[index], suffix) > maximum_chain:
            continue
        group = None
        if pack_small_alu and candidates[name]['width'] <= 10:
            polarity = tuple(cells[name]['connections']['BI'])
            groups = small_groups[polarity]
            if groups and len(groups[-1]) < 4:
                group = groups[-1]
        cost = int(group is None)
        if additional + cost > limit:
            continue
        if pack_small_alu and candidates[name]['width'] <= 10:
            if group is None:
                group = []
                small_groups[polarity].append(group)
            group.append(name)
        additional += cost
        selected.append(name)
        selected_bits |= 1 << index
        if maximum_chain == 1:
            blocked |= (1 << index) | ancestors[name] | descendants[index]
        else:
            blocked |= 1 << index
            refresh_depths()
    for name in selected:
        if maximum_chain == 1 and ancestors[name] & selected_bits:
            raise AssertionError('Selected DSP cells have a combinational dependency')
    if maximum_chain > 1 and max(prefix.values(), default=0) > maximum_chain:
        raise AssertionError('Selected DSP chain exceeds its configured limit')
    report = {
        'dsp_budget': budget, 'dsp_reserve': reserve, 'existing_dsp_cells': existing,
        'additional_dsp_cells': additional, 'resulting_dsp_cells': existing + additional,
        'minimum_width': minimum_width, 'maximum_width': maximum_width,
        'candidate_cells': len(candidates), 'blocked_by_existing_combinational_dsp': blocked_by_existing,
        'selected': [{'cell': name, **candidates[name]} for name in selected],
        'selection_rule': 'Select 24 to 48 bit arithmetic first, then narrower independent cells; highest estimated area within each group; no combinational path between selected DSP cells or an existing unregistered DSP',
    }
    if pack_small_alu:
        report['small_alu_packing'] = {
            'maximum_width': 10, 'lanes_per_dsp': 4,
            'groups': [{'cells': group, 'BI': list(polarity)}
                       for polarity, groups in small_groups.items()
                       for group in groups if len(group) > 1],
        }
        report['selection_rule'] += '; up to four independent cells of at most ten bits share a DSP when BI is identical'
    if maximum_chain > 1:
        report.update(maximum_selected_combinational_dsps=maximum_chain,
                      selected_combinational_dsp_upper_bound=max(prefix.values(), default=0),
                      selection_rule='Select wide arithmetic first within the DSP budget; at most two selected DSP cells on any combinational path; preserve separation from existing unregistered DSP cells')
    return report


def retain_as_carry(report, reference, names):
    """从已验证的选择中保留指定算术单元，其余 DSP 选择保持不变。"""
    if 'small_alu_packing' in report or 'small_alu_packing' in reference:
        raise ValueError('Retained carry cells require an unpacked arithmetic selection')
    for key in ('dsp_budget', 'dsp_reserve', 'existing_dsp_cells', 'minimum_width', 'maximum_width', 'selected'):
        if report[key] != reference[key]:
            raise ValueError('The arithmetic selection does not match its reference: ' + key)
    if report.get('maximum_selected_combinational_dsps', 1) != reference.get('maximum_selected_combinational_dsps', 1):
        raise ValueError('The selected DSP chain limit differs from its reference')
    keep = set(names)
    if len(keep) != len(names):
        raise ValueError('Each retained arithmetic cell must be specified once')
    selected_names = {item['cell'] for item in report['selected']}
    if keep - selected_names:
        raise ValueError('Retained cells must belong to the saved DSP selection: ' + ', '.join(sorted(keep - selected_names)))
    retained = [item for item in report['selected'] if item['cell'] in keep]
    selected = [item for item in report['selected'] if item['cell'] not in keep]
    report.update(retained_as_carry=retained, selected=selected,
                  original_additional_dsp_cells=report['additional_dsp_cells'],
                  additional_dsp_cells=len(selected),
                  resulting_dsp_cells=report['existing_dsp_cells'] + len(selected))
    report['selection_rule'] += '; listed arithmetic cells remain in fabric carry logic; all other DSP selections are preserved'
    return report


def apply_mapping(module, report):
    """保留原始输出连接，将独立小位宽运算组合为四通道 DSP 输入。"""
    cells = module['cells']
    groups = report.get('small_alu_packing', {}).get('groups', [])
    grouped = {name for group in groups for name in group['cells']}
    selected = {item['cell'] for item in report['selected']}
    if not grouped <= selected or sum(len(group['cells']) for group in groups) != len(grouped):
        raise ValueError('Packed groups must contain distinct selected cells')
    maximum_bit = max((bit for collection in (module.get('ports', {}).values(),
                                              module.get('netnames', {}).values())
                       for item in collection for bit in item.get('bits', [])
                       if isinstance(bit, int)), default=1)
    maximum_bit = max(maximum_bit, max((bit for cell in cells.values()
                                      for values in cell['connections'].values()
                                      for bit in values if isinstance(bit, int)), default=1))

    def unused(width):
        nonlocal maximum_bit
        result = list(range(maximum_bit + 1, maximum_bit + width + 1))
        maximum_bit += width
        return result

    def operand(cell, port):
        parameters = cell['parameters']
        width = integer(parameters['Y_WIDTH'])
        values = list(cell['connections'][port])
        if len(values) != integer(parameters[port + '_WIDTH']):
            raise ValueError('Arithmetic operand width differs from its connection')
        signed = integer(parameters['A_SIGNED']) and integer(parameters['B_SIGNED'])
        extension = values[-1] if signed and values else '0'
        # 零位操作数按零扩展，其余操作数先扩展或截断，再补零至通道宽度。
        return (values + [extension] * width)[:width] + ['0'] * (10 - width)

    for index, group in enumerate(groups):
        if not 2 <= len(group['cells']) <= 4 or len(group['BI']) != 1:
            raise ValueError('A packed arithmetic group needs two to four cells and one BI bit')
        name = f'$__fpga_dsp_alu4${index}'
        if name in cells:
            raise ValueError('Packed arithmetic cell name already exists: ' + name)
        connections = {port: [] for port in ('A', 'B', 'CI', 'X', 'Y', 'CO')}
        connections['BI'] = group['BI'][:]
        sources = []
        lanes = []
        for member in group['cells']:
            cell = cells[member]
            width = integer(cell['parameters']['Y_WIDTH'])
            if cell['type'] != '$alu' or not 1 <= width <= 10 or cell['connections']['BI'] != group['BI']:
                raise ValueError('Packed arithmetic cell has incompatible type, width, or BI')
            for port in ('A', 'B'):
                connections[port].extend(operand(cell, port))
            if len(cell['connections']['CI']) != 1:
                raise ValueError('Each arithmetic lane requires one CI bit')
            connections['CI'].extend(cell['connections']['CI'])
            for port in ('X', 'Y', 'CO'):
                if len(cell['connections'][port]) != width:
                    raise ValueError('Arithmetic output width differs from its connection')
                connections[port].extend(cell['connections'][port] + unused(10 - width))
            if cell.get('attributes', {}).get('src'):
                sources.append(cell['attributes']['src'])
            lanes.append({'cell': member, 'width': width, 'parameters': cell['parameters'].copy()})
        for _ in range(4 - len(group['cells'])):
            for port in ('A', 'B'):
                connections[port].extend(['0'] * 10)
            connections['CI'].append('0')
            for port in ('X', 'Y', 'CO'):
                connections[port].extend(unused(10))
        cells[name] = {
            'hide_name': 1, 'type': '$__FPGA_DSP_ALU4', 'parameters': {},
            'attributes': {'src': '|'.join(dict.fromkeys(sources))} if sources else {},
            'port_directions': {port: ('input' if port in ('A', 'B', 'CI', 'BI') else 'output')
                                for port in connections},
            'connections': connections,
        }
        group.update(mapped_cell=name, lanes=lanes)
        for member in group['cells']:
            del cells[member]
    for selection in report['selected']:
        if selection['cell'] not in grouped:
            cells[selection['cell']]['type'] = '$__FPGA_DSP_ALU'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--top', required=True)
    parser.add_argument('--budget', type=int, default=740)
    parser.add_argument('--reserve', type=int, default=0)
    parser.add_argument('--minimum-width', type=int, default=24)
    parser.add_argument('--maximum-chain', type=int, choices=(1, 2), default=1)
    parser.add_argument('--use-dsp-attributes', action='store_true',
                        help='仅转换 RTL 中 use_dsp=yes 的算术结果，不按面积分数选择其他运算')
    parser.add_argument('--pack-small-alu', action='store_true',
                        help='将最多四个相同 BI、独立且不超过十位的运算组合到一个 DSP')
    parser.add_argument('--selection-reference', type=Path,
                        help='使用同一输入网表生成的 DSP 选择报告')
    parser.add_argument('--keep-as-carry', action='append', default=[],
                        help='保留指定单元的原始 $alu 类型；可以重复给出不同单元名称')
    args = parser.parse_args()
    if args.budget < 0 or args.reserve < 0 or not 1 <= args.minimum_width <= 48:
        parser.error('DSP budget and reserve must be nonnegative; minimum width must be from 1 through 48')
    if bool(args.selection_reference) != bool(args.keep_as_carry):
        parser.error('--selection-reference and --keep-as-carry must be specified together')
    if args.pack_small_alu and (args.maximum_chain != 1 or args.keep_as_carry):
        parser.error('--pack-small-alu requires --maximum-chain 1 and no retained carry cells')
    if args.use_dsp_attributes and (args.pack_small_alu or args.keep_as_carry or args.maximum_chain != 1):
        parser.error('--use-dsp-attributes cannot be combined with automatic selection options')
    input_sha256 = hashlib.sha256(args.input.read_bytes()).hexdigest()
    design = json.loads(args.input.read_text())
    module = design['modules'][args.top]
    if args.use_dsp_attributes:
        report = select_attribute_cells(module, args.budget, args.reserve)
    else:
        report = select_cells(module, args.budget, args.reserve, args.minimum_width,
                              maximum_chain=args.maximum_chain, pack_small_alu=args.pack_small_alu)
    if args.selection_reference:
        reference = json.loads(args.selection_reference.read_text())
        if reference['input_sha256'] != input_sha256:
            raise ValueError('The arithmetic input differs from the saved selection')
        report = retain_as_carry(report, reference, args.keep_as_carry)
        report['selection_reference_sha256'] = hashlib.sha256(args.selection_reference.read_bytes()).hexdigest()
    apply_mapping(module, report)
    args.output.write_text(json.dumps(design, separators=(',', ':')) + '\n')
    autoidx_path = args.output.with_suffix('.autoidx.il')
    autoidx_value = next_autoidx(design)
    autoidx_path.write_text(f'autoidx {autoidx_value}\n')
    report['automatic_name_counter'] = autoidx_value
    report['automatic_name_counter_sha256'] = hashlib.sha256(autoidx_path.read_bytes()).hexdigest()
    report['input_sha256'] = input_sha256
    report['output_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    report['lut_dependencies_sha256'] = hashlib.sha256(
        Path(__file__).with_name('lut_dependencies.py').read_bytes()).hexdigest()
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('selected', 'blocked_by_existing_combinational_dsp')}))


if __name__ == '__main__':
    main()
