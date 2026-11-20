#!/usr/bin/env python3
"""为输入兼容的独立普通 LUT 添加相对位置约束。"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re


def enabled(value):
    if isinstance(value, str):
        value = value.strip()
        return bool(int(value, 2)) if re.fullmatch('[01]+', value) else value.lower() == 'true'
    return bool(value)


def signals(cell, direction):
    return {bit for port, bits in cell['connections'].items()
            if cell['port_directions'][port] == direction for bit in bits}


def candidates(module):
    protected = set()
    constant = {'0', '1', 'x', 'z'}
    for cell in module['cells'].values():
        kind, attributes = cell['type'], cell.get('attributes', {})
        storage = kind == 'SLICE_LUTX' and (enabled(attributes.get('X_LUT_AS_DRAM', 0))
                                           or enabled(attributes.get('X_LUT_AS_SRL', 0)))
        if kind in ('CARRY4', 'SLICE_FFX', 'SELMUX2_1', 'F7MUX', 'F8MUX', 'F9MUX') or storage:
            protected.update(signals(cell, 'input'))
        if kind in ('GND', 'VCC', 'PSEUDO_GND', 'PSEUDO_VCC'):
            constant.update(signals(cell, 'output'))
    selected, rejected = {}, collections.Counter()
    for name, cell in module['cells'].items():
        if cell['type'] != 'SLICE_LUTX':
            continue
        attributes, ports = cell.get('attributes', {}), cell['connections']
        reason = None
        if enabled(attributes.get('X_LUT_AS_DRAM', 0)) or enabled(attributes.get('X_LUT_AS_SRL', 0)):
            reason = 'storage'
        elif not enabled(attributes.get('X_LUT_LOGICAL_OUTPUT', 0)):
            reason = 'dedicated_lut'
        elif any(key.startswith('CONSTR_') for key in attributes):
            reason = 'relative_constraint'
        elif any(key in attributes for key in ('BEL', 'NEXTPNR_BEL', 'REGION', 'DONT_TOUCH')):
            reason = 'fixed_or_protected'
        inputs = [(port, bit) for port, bits in ports.items()
                  if cell['port_directions'][port] == 'input' for bit in bits]
        outputs = [(port, bit) for port, bits in ports.items()
                   if cell['port_directions'][port] == 'output' for bit in bits]
        if reason is None and (not 1 <= len(inputs) <= 5
                               or any(re.fullmatch(r'A[1-5]', port) is None for port, _ in inputs)):
            reason = 'input_ports'
        if reason is None and (len(outputs) != 1 or outputs[0][0] not in ('O5', 'O6')):
            reason = 'output_ports'
        if reason is None and outputs[0][1] in protected:
            reason = 'dedicated_or_register_sink'
        if reason is not None:
            rejected[reason] += 1
            continue
        input_set = {bit for _, bit in inputs}
        selected[name] = {'inputs': input_set, 'variable_inputs': input_set - constant,
                          'output': outputs[0][1]}
    return selected, dict(rejected)


def select_pairs(selected, maximum_pairs=None):
    names = sorted(selected, key=lambda name: (-len(selected[name]['inputs']), name))
    by_input = collections.defaultdict(set)
    active = set(names)
    for name in names:
        for bit in selected[name]['variable_inputs']:
            by_input[bit].add(name)
    pairs = []
    for first in names:
        if first not in active or maximum_pairs is not None and len(pairs) >= maximum_pairs:
            continue
        left = selected[first]
        neighbors = set().union(*(by_input[bit] for bit in left['variable_inputs'])) if left['variable_inputs'] else set()
        neighbors.intersection_update(active)
        neighbors.discard(first)
        possible = []
        for second in neighbors:
            right = selected[second]
            if len(left['inputs'] | right['inputs']) > 5:
                continue
            if left['output'] in right['inputs'] or right['output'] in left['inputs']:
                continue
            shared = len(left['variable_inputs'] & right['variable_inputs'])
            possible.append((-shared, -len(right['inputs']), second))
        if possible:
            second = min(possible)[2]
            active.difference_update((first, second))
            pairs.append((first, second))
    return pairs


def functional_digest(module):
    digest = hashlib.sha256()
    for name, cell in sorted(module['cells'].items()):
        view = {**cell, 'attributes': {key: value for key, value in cell.get('attributes', {}).items()
                                      if not key.startswith('CONSTR_')}}
        digest.update(json.dumps([name, view], sort_keys=True, separators=(',', ':')).encode())
    return digest.hexdigest()


def constrain_pairs(module, selected, pairs):
    used = set()
    for first, second in pairs:
        if first == second or first in used or second in used:
            raise ValueError('A LUT can belong to only one new pair')
        left, right = selected[first], selected[second]
        if (len(left['inputs'] | right['inputs']) > 5
                or not left['variable_inputs'] & right['variable_inputs']
                or left['output'] in right['inputs'] or right['output'] in left['inputs']):
            raise ValueError('Incompatible LUT pair')
        upper = module['cells'][first].setdefault('attributes', {})
        lower = module['cells'][second].setdefault('attributes', {})
        if any(key.startswith('CONSTR_') for attributes in (upper, lower) for key in attributes):
            raise ValueError('Existing relative constraint must be retained')
        # 根单元可使用任意一组 6LUT/5LUT；子单元只增加一个相对 Z 位置。
        upper['CONSTR_CHILDREN'] = second
        lower.update(CONSTR_PARENT=first, CONSTR_X=f'{0:032b}', CONSTR_Y=f'{0:032b}',
                     CONSTR_Z=f'{1:032b}', CONSTR_ABS_Z=f'{0:032b}')
        used.update((first, second))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, required=True)
    parser.add_argument('--top', help='指定打包 JSON 的模块名；单模块文件可省略')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--maximum-pairs', type=int)
    args = parser.parse_args()
    if args.packed.resolve() == args.out.resolve():
        parser.error('Use a separate output file for the constrained design')
    if args.maximum_pairs is not None and args.maximum_pairs < 0:
        parser.error('--maximum-pairs must be nonnegative')
    source = args.packed.read_bytes()
    design = json.loads(source)
    del source
    modules = design['modules']
    if args.top is None:
        if len(modules) != 1:
            parser.error('Specify --top for a JSON containing multiple modules')
        module = next(iter(modules.values()))
    elif args.top in modules:
        module = modules[args.top]
    else:
        parser.error('The requested top module is absent')
    if module.get('attributes', {}).get('step') != 'pack':
        parser.error('The input must be a packed design')
    selected, rejected = candidates(module)
    pairs = select_pairs(selected, args.maximum_pairs)
    before = functional_digest(module)
    constrain_pairs(module, selected, pairs)
    if functional_digest(module) != before:
        raise RuntimeError('Logical cell contents changed while adding constraints')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(design, separators=(',', ':')) + '\n')
    result = {'candidate_luts': len(selected), 'pair_count': len(pairs), 'excluded': rejected,
              'functional_cells_sha256': before, 'cell_contents_preserved': True,
              'pairs': [{'upper': left, 'lower': right,
                         'unique_inputs': len(selected[left]['inputs'] | selected[right]['inputs']),
                         'shared_variable_inputs': len(selected[left]['variable_inputs'] & selected[right]['variable_inputs'])}
                        for left, right in pairs],
              'physical_lut_positions': None, 'placement_complete': False,
              'method': '仅约束无专用或寄存器使用者的独立普通逻辑；每对至少共享一个非常量输入，输入并集至多五个。逻辑、连接、INIT 与原有约束保持，实际占用由后续合法布局统计。'}
    for label, path in (('source_packed_sha256', args.packed), ('output_packed_sha256', args.out)):
        with path.open('rb') as source:
            result[label] = hashlib.file_digest(source, 'sha256').hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('candidate_luts', 'pair_count', 'cell_contents_preserved')}))


if __name__ == '__main__':
    main()
