#!/usr/bin/env python3
"""将控制兼容的两个 LUT 与寄存器组放到同一个物理 LUT 位置。"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re

from pair_packed_luts import enabled, functional_digest, select_pairs, signals


def number(value):
    return int(value, 2) if isinstance(value, str) else int(value)


def children(attributes):
    return [name for name in attributes.get('CONSTR_CHILDREN', '').split(';') if name]


def control_key(cell):
    ports, parameters, attributes = cell['connections'], cell.get('parameters', {}), cell.get('attributes', {})
    # 同一 slice 的两类触发器共用时钟、使能、复位及同步模式。
    controls = tuple(tuple(ports.get(port, [])) for port in ('CK', 'CE', 'SR'))
    polarity = tuple(enabled(parameters.get(name, 0)) for name in
                     ('IS_CLK_INVERTED', 'IS_R_INVERTED', 'IS_S_INVERTED',
                      'IS_CLR_INVERTED', 'IS_PRE_INVERTED'))
    return controls, polarity, attributes.get('X_ORIG_TYPE'), 'X_FFSYNC' in attributes


def candidates(module):
    cells = module['cells']
    users = collections.defaultdict(list)
    constants = {'0', '1', 'x', 'z'}
    for name, cell in cells.items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'input':
                for bit in bits:
                    users[bit].append((name, port))
        if cell['type'] in ('GND', 'VCC', 'PSEUDO_GND', 'PSEUDO_VCC'):
            constants.update(signals(cell, 'output'))
    for port, data in module.get('ports', {}).items():
        if data['direction'] == 'output':
            for bit in data['bits']:
                users[bit].append(('$port', port))
    selected, rejected = {}, collections.Counter()
    fixed = {'BEL', 'NEXTPNR_BEL', 'REGION', 'DONT_TOUCH'}
    for name, cell in cells.items():
        if cell['type'] != 'SLICE_LUTX':
            continue
        attributes, ports = cell.get('attributes', {}), cell['connections']
        reason = None
        if enabled(attributes.get('X_LUT_AS_DRAM', 0)) or enabled(attributes.get('X_LUT_AS_SRL', 0)):
            reason = 'storage'
        elif not enabled(attributes.get('X_LUT_LOGICAL_OUTPUT', 0)):
            reason = 'dedicated_lut'
        elif fixed.intersection(attributes):
            reason = 'fixed_or_protected'
        elif any(key.startswith('CONSTR_') and key != 'CONSTR_CHILDREN' for key in attributes):
            reason = 'other_relative_constraint'
        inputs = [(port, bit) for port, bits in ports.items()
                  if cell['port_directions'][port] == 'input' for bit in bits]
        outputs = [(port, bit) for port, bits in ports.items()
                   if cell['port_directions'][port] == 'output' for bit in bits]
        if reason is None and (not 1 <= len(inputs) <= 5 or
                               any(re.fullmatch('A[1-5]', port) is None for port, _ in inputs)):
            reason = 'input_ports'
        if reason is None and (len(outputs) != 1 or outputs[0][0] != 'O6'):
            reason = 'output_ports'
        child_names = children(attributes)
        if reason is None and len(child_names) != 1:
            reason = 'not_single_register_group'
        register = cells.get(child_names[0]) if len(child_names) == 1 else None
        if reason is None and (register is None or register['type'] != 'SLICE_FFX'):
            reason = 'child_is_not_register'
        if reason is None:
            ff_attributes = register.get('attributes', {})
            if fixed.intersection(ff_attributes) or 'X_FF_AS_LATCH' in ff_attributes:
                reason = 'register_fixed_or_latch'
            elif ff_attributes.get('X_ORIG_TYPE') not in ('FDRE', 'FDSE', 'FDCE', 'FDPE',
                                                        'FDRE_1', 'FDSE_1', 'FDCE_1', 'FDPE_1'):
                reason = 'register_type'
            elif (ff_attributes.get('CONSTR_PARENT') != name or children(ff_attributes) or
                  number(ff_attributes.get('CONSTR_X', -1)) != 0 or
                  number(ff_attributes.get('CONSTR_Y', -1)) != 0 or
                  number(ff_attributes.get('CONSTR_Z', -1)) != 2 or
                  enabled(ff_attributes.get('CONSTR_ABS_Z', 0))):
                reason = 'register_relative_constraint'
            elif any(key.startswith('CONSTR_') and key not in
                     ('CONSTR_PARENT', 'CONSTR_CHILDREN', 'CONSTR_X', 'CONSTR_Y', 'CONSTR_Z', 'CONSTR_ABS_Z')
                     for key in ff_attributes):
                reason = 'other_register_constraint'
            elif users[outputs[0][1]] != [(child_names[0], 'D')]:
                # O5 与 5FF 的 Q 共用输出选择器，O5 只允许连接同位置的 D。
                reason = 'lut_has_other_consumers'
            elif len(register['connections'].get('CK', [])) != 1:
                reason = 'register_clock'
        if reason is not None:
            rejected[reason] += 1
            continue
        input_set = {bit for _, bit in inputs}
        selected[name] = {'inputs': input_set, 'variable_inputs': input_set - constants,
                          'output': outputs[0][1], 'register': child_names[0],
                          'control_key': control_key(register)}
    return selected, dict(rejected)


def compatible_pairs(selected, maximum_pairs=None):
    groups = collections.defaultdict(dict)
    for name, item in selected.items():
        groups[item['control_key']][name] = item
    pairs = []
    for key in sorted(groups, key=repr):
        remaining = None if maximum_pairs is None else maximum_pairs - len(pairs)
        pairs.extend(select_pairs(groups[key], remaining))
    return pairs


def constrain_pairs(module, selected, pairs):
    cells = module['cells']
    current, _ = candidates(module)
    used = set()
    for first, second in pairs:
        if first == second or first in used or second in used:
            raise ValueError('Each LUT and register group must occur only once')
        if first not in current or second not in current or selected[first] != current[first] or selected[second] != current[second]:
            raise ValueError('The current group does not match its inspected constraints')
        left, right = current[first], current[second]
        if (left['control_key'] != right['control_key'] or len(left['inputs'] | right['inputs']) > 5 or
                not left['variable_inputs'] & right['variable_inputs'] or
                left['output'] in right['inputs'] or right['output'] in left['inputs']):
            raise ValueError('LUT inputs or register controls are incompatible')
        upper, lower = cells[first]['attributes'], cells[second]['attributes']
        upper_ff, lower_ff = left['register'], right['register']
        # 四个单元按 6LUT、5LUT、FF、5FF 顺序占用同一位置的四个 BEL。
        upper['CONSTR_CHILDREN'] = ';'.join((upper_ff, second, lower_ff))
        lower.pop('CONSTR_CHILDREN', None)
        lower.update(CONSTR_PARENT=first, CONSTR_X=f'{0:032b}', CONSTR_Y=f'{0:032b}',
                     CONSTR_Z=f'{1:032b}', CONSTR_ABS_Z=f'{0:032b}')
        cells[lower_ff]['attributes'].update(CONSTR_PARENT=first, CONSTR_Z=f'{3:032b}')
        used.update((first, second))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, required=True)
    parser.add_argument('--top')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--maximum-pairs', type=int)
    args = parser.parse_args()
    if args.packed.resolve() == args.out.resolve():
        parser.error('Use a separate output file')
    if args.maximum_pairs is not None and args.maximum_pairs < 0:
        parser.error('--maximum-pairs must be nonnegative')
    design = json.loads(args.packed.read_bytes())
    modules = design['modules']
    if args.top is None and len(modules) != 1:
        parser.error('Specify --top for a design containing multiple modules')
    if args.top is not None and args.top not in modules:
        parser.error('The requested top is absent')
    module = modules[args.top] if args.top is not None else next(iter(modules.values()))
    if module.get('attributes', {}).get('step') != 'pack':
        parser.error('The input must be a packed design')
    selected, rejected = candidates(module)
    pairs = compatible_pairs(selected, args.maximum_pairs)
    before = functional_digest(module)
    constrain_pairs(module, selected, pairs)
    if functional_digest(module) != before:
        raise RuntimeError('Logical contents changed during constraint grouping')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(design, separators=(',', ':')) + '\n')
    result = {'candidate_groups': len(selected), 'pair_count': len(pairs), 'excluded': rejected,
              'functional_cells_sha256': before, 'cell_contents_preserved': True,
              'pairs': [{'upper': first, 'lower': second, 'upper_register': selected[first]['register'],
                         'lower_register': selected[second]['register'],
                         'unique_inputs': len(selected[first]['inputs'] | selected[second]['inputs']),
                         'shared_variable_inputs': len(selected[first]['variable_inputs'] & selected[second]['variable_inputs'])}
                        for first, second in pairs],
              'physical_lut_positions': None, 'placement_complete': False,
              'method': '共用输入至多五个且至少共享一个非常量输入；两组触发器控制一致，LUT 输出仅连接本组触发器 D。保存逻辑与初值，实际物理位置由合法布局统计。'}
    for label, path in [('source_packed_sha256', args.packed), ('output_packed_sha256', args.out)]:
        with path.open('rb') as source:
            result[label] = hashlib.file_digest(source, 'sha256').hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('candidate_groups', 'pair_count', 'cell_contents_preserved')}))


if __name__ == '__main__':
    main()
