#!/usr/bin/env python3
"""在保持进位组约束的条件下，将兼容逻辑放入 S 输入 LUT 的空闲 O5。"""
from __future__ import annotations

import argparse
import collections
import functools
import gc
import hashlib
import json
from pathlib import Path
import re

from pair_packed_luts import candidates, enabled, functional_digest
from placed_resources import placed_resources


def integer(value):
    if not isinstance(value, str):
        return int(value)
    value = value.strip()
    number = int(value, 2)
    return number - (1 << len(value)) if len(value) == 32 and value[0] == '1' else number


class Connections:
    def __init__(self, module):
        self.cells = module['cells']
        self.users = collections.defaultdict(list)
        self.drivers = {}
        self.constants = {'0', '1', 'x', 'z'}
        for name, cell in self.cells.items():
            for port, bits in cell['connections'].items():
                for bit in bits:
                    if cell['port_directions'][port] == 'output':
                        if bit in self.drivers:
                            raise ValueError(f'Multiple drivers: {bit}')
                        self.drivers[bit] = (name, port)
                        if cell['type'] in ('GND', 'VCC', 'PSEUDO_GND', 'PSEUDO_VCC'):
                            self.constants.add(bit)
                    else:
                        self.users[bit].append((name, port))
        self.occupants = collections.defaultdict(list)
        for name, cell in self.cells.items():
            if any(key.startswith('CONSTR_') for key in cell.get('attributes', {})):
                self.occupants[self.coordinate(name)].append(name)

    @functools.cache
    def coordinate(self, name):
        attributes = self.cells[name].get('attributes', {})
        parent = attributes.get('CONSTR_PARENT')
        if not parent:
            return name, 0, 0, integer(attributes.get('CONSTR_Z', 0))
        root, x, y, z = self.coordinate(parent)
        nx = x + integer(attributes.get('CONSTR_X', 0))
        ny = y + integer(attributes.get('CONSTR_Y', 0))
        nz = integer(attributes.get('CONSTR_Z', 0))
        # xc7 的绝对 Z 只指定同一 slice 内的位置；高位继承父单元。
        nz = (nz | (z & ~0x3f)) if enabled(attributes.get('CONSTR_ABS_Z', 0)) else z + nz
        return root, nx, ny, nz

    def available_carry_slots(self):
        slots, reasons = {}, collections.Counter()
        for name, cell in self.cells.items():
            if cell['type'] != 'CARRY4':
                continue
            root, x, y, z = self.coordinate(name)
            for index in range(4):
                reasons['carry_bit_positions'] += 1
                if not enabled(cell.get('attributes', {}).get(f'X_CARRY_DI{index}_VIA_X', 0)):
                    reasons['di_not_via_x'] += 1
                    continue
                select_bits = cell['connections'].get(f'S{index}', [])
                if not select_bits or select_bits[0] not in self.drivers:
                    reasons['select_missing'] += 1
                    continue
                upper, output_port = self.drivers[select_bits[0]]
                lut = self.cells[upper]
                attributes = lut.get('attributes', {})
                inputs = [(port, bit) for port, bits in lut['connections'].items()
                          if lut['port_directions'][port] == 'input' for bit in bits]
                outputs = [(port, bit) for port, bits in lut['connections'].items()
                           if lut['port_directions'][port] == 'output' for bit in bits]
                if (lut['type'] != 'SLICE_LUTX' or output_port != 'O6'
                        or not enabled(attributes.get('X_LUT_LOGICAL_OUTPUT', 0))
                        or 'X_LUT_AS_DRAM' in attributes or 'X_LUT_AS_SRL' in attributes
                        or not 1 <= len(inputs) <= 5 or len(outputs) != 1
                        or any(re.fullmatch('A[1-5]', port) is None for port, _ in inputs)):
                    reasons['select_not_small_logic'] += 1
                    continue
                position = (root, x, y, (z & ~0x3f) | (index << 4))
                if self.coordinate(upper) != position:
                    reasons['select_relative_mismatch'] += 1
                    continue
                if any(key in attributes for key in ('BEL', 'NEXTPNR_BEL', 'DONT_TOUCH', 'REGION')):
                    reasons['select_protected'] += 1
                    continue
                if self.occupants.get((*position[:3], position[3] + 1)):
                    reasons['lower_lut_occupied'] += 1
                    continue
                if self.occupants.get((*position[:3], position[3] + 3)):
                    reasons['lower_ff_occupied'] += 1
                    continue
                local_ff = self.occupants.get((*position[:3], position[3] + 2), [])
                external = False
                for output in (f'O{index}', f'CO{index}'):
                    for bit in cell['connections'].get(output, []):
                        chain_users = 0
                        for user, port in self.users[bit]:
                            if user in local_ff and port == 'D' and self.cells[user]['type'] == 'SLICE_FFX':
                                continue
                            if (output == 'CO3' and port == 'CIN' and self.cells[user]['type'] == 'CARRY4'
                                    and self.coordinate(user)[0] == root):
                                chain_users += 1
                                continue
                            external = True
                        if chain_users > 1:
                            external = True
                if external:
                    reasons['carry_external_output'] += 1
                    continue
                input_set = {bit for _, bit in inputs}
                slots[upper] = {'carry': name, 'bit': index, 'inputs': input_set,
                                'variable_inputs': input_set - self.constants,
                                'output': select_bits[0]}
        reasons['available_slots'] = len(slots)
        return slots, dict(reasons)


def read_placement_guide(path):
    design = json.loads(path.read_text())
    if len(design['modules']) != 1:
        raise ValueError('A single placed module is required')
    module = next(iter(design['modules'].values()))
    resources = placed_resources(module)
    if not resources['placement_complete']:
        raise ValueError('The placement guide must have complete legal placement')
    positions = {name: cell['attributes']['NEXTPNR_BEL'] for name, cell in module['cells'].items()}
    occupied = set(positions.values())
    lut_occupancy = collections.Counter()
    for name, cell in module['cells'].items():
        if cell['type'] == 'SLICE_LUTX':
            match = re.fullmatch(r'(.+/[A-D])[56]LUT', positions[name])
            if match:
                lut_occupancy[match.group(1)] += 1
    return {'positions': positions, 'occupied': occupied, 'lut_occupancy': lut_occupancy,
            'physical_lut_positions': resources['physical_lut_positions']}


def site_distance(first, second):
    a = re.search(r'_X([0-9]+)Y([0-9]+)', first)
    b = re.search(r'_X([0-9]+)Y([0-9]+)', second)
    if a is None or b is None:
        raise ValueError('The placement guide has no site coordinates')
    return abs(int(a.group(1)) - int(b.group(1))) + abs(int(a.group(2)) - int(b.group(2)))


def select_pairs(slots, independent, guide=None, maximum_distance=8, maximum_pairs=None):
    active = set(independent)
    by_input = collections.defaultdict(set)
    for name, entry in independent.items():
        for bit in entry['variable_inputs']:
            by_input[bit].add(name)
    pairs = []
    for upper in sorted(slots, key=lambda name: (-len(slots[name]['inputs']), name)):
        if maximum_pairs is not None and len(pairs) >= maximum_pairs:
            break
        select = slots[upper]
        if guide is None:
            possible = set().union(*(by_input[bit] for bit in select['variable_inputs'])) if select['variable_inputs'] else set()
        else:
            upper_bel = guide['positions'].get(upper, '')
            if not upper_bel.endswith('6LUT'):
                continue
            lower_bel = upper_bel[:-4] + '5LUT'
            lower_ff = upper_bel[:-4] + '5FF'
            if lower_bel in guide['occupied'] or lower_ff in guide['occupied']:
                continue
            possible = active
        choices = []
        for lower in possible:
            if lower not in active:
                continue
            logic = independent[lower]
            if (len(select['inputs'] | logic['inputs']) > 5
                    or select['output'] in logic['inputs'] or logic['output'] in select['inputs']):
                continue
            shared = len(select['variable_inputs'] & logic['variable_inputs'])
            distance = 0
            if guide is not None:
                lower_bel = guide['positions'].get(lower, '')
                match = re.fullmatch(r'(.+/[A-D])[56]LUT', lower_bel)
                if match is None or guide['lut_occupancy'][match.group(1)] != 1:
                    continue
                distance = site_distance(upper_bel, lower_bel)
                if distance > maximum_distance:
                    continue
            choices.append((distance, -shared, -len(logic['inputs']), lower))
        if choices:
            distance, negative_shared, _, lower = min(choices)
            active.remove(lower)
            pairs.append({'upper': upper, 'lower': lower, 'carry': select['carry'], 'bit': select['bit'],
                          'unique_inputs': len(select['inputs'] | independent[lower]['inputs']),
                          'shared_variable_inputs': -negative_shared,
                          'guide_site_distance': distance if guide else None})
    return pairs


def constrain_pairs(module, slots, independent, pairs):
    original = {name: {key: value for key, value in cell.get('attributes', {}).items() if key.startswith('CONSTR_')}
                for name, cell in module['cells'].items()}
    used_upper, used_lower = set(), set()
    for pair in pairs:
        upper, lower = pair['upper'], pair['lower']
        if upper in used_upper or lower in used_lower or upper == lower:
            raise ValueError('Each new pair must use a distinct select LUT and independent LUT')
        select, logic = slots[upper], independent[lower]
        if (len(select['inputs'] | logic['inputs']) > 5 or select['output'] in logic['inputs']
                or logic['output'] in select['inputs']):
            raise ValueError('Incompatible carry LUT pair')
        attributes = module['cells'][upper].setdefault('attributes', {})
        child = module['cells'][lower].setdefault('attributes', {})
        if any(key.startswith('CONSTR_') for key in child):
            raise ValueError('The additional LUT must have no relative constraints')
        existing = attributes.get('CONSTR_CHILDREN', '')
        # S 输入单元保持原有位置；新增子单元使用同位置的 5LUT。
        attributes['CONSTR_CHILDREN'] = existing + (';' if existing else '') + lower
        child.update(CONSTR_PARENT=upper, CONSTR_X=f'{0:032b}', CONSTR_Y=f'{0:032b}',
                     CONSTR_Z=f'{1:032b}', CONSTR_ABS_Z=f'{0:032b}')
        used_upper.add(upper)
        used_lower.add(lower)
    for name, constraints in original.items():
        attributes = module['cells'][name].get('attributes', {})
        for key, value in constraints.items():
            if key == 'CONSTR_CHILDREN' and name in used_upper:
                if value and not attributes[key].startswith(value + ';'):
                    raise RuntimeError('The existing children changed')
            elif attributes[key] != value:
                raise RuntimeError('An existing relative constraint changed')


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--placement-guide', type=Path)
    parser.add_argument('--maximum-site-distance', type=int, default=8, help='参考布局中允许的最大 SLICE 坐标曼哈顿距离')
    parser.add_argument('--maximum-pairs', type=int)
    args = parser.parse_args()
    if args.packed.resolve() == args.out.resolve():
        parser.error('Use a separate output file for the constrained design')
    if args.maximum_site_distance < 0 or args.maximum_pairs is not None and args.maximum_pairs < 0:
        parser.error('The limits must be nonnegative')
    guide = read_placement_guide(args.placement_guide) if args.placement_guide else None
    gc.collect()
    design = json.loads(args.packed.read_text())
    if len(design['modules']) != 1:
        parser.error('A single packed module is required')
    module = next(iter(design['modules'].values()))
    if module.get('attributes', {}).get('step') != 'pack':
        parser.error('The input must be a packed design')
    network = Connections(module)
    slots, reasons = network.available_carry_slots()
    independent, excluded = candidates(module)
    pairs = select_pairs(slots, independent, guide, args.maximum_site_distance, args.maximum_pairs)
    before = functional_digest(module)
    constrain_pairs(module, slots, independent, pairs)
    if functional_digest(module) != before:
        raise RuntimeError('Logical cell contents changed')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(design, separators=(',', ':')) + '\n')
    result = {'pair_count': len(pairs), 'available_carry_slots': len(slots), 'independent_luts': len(independent),
              'carry_slot_checks': reasons, 'independent_lut_exclusions': excluded, 'pairs': pairs,
              'functional_cells_sha256': before, 'cell_contents_preserved': True,
              'existing_constraints_preserved': True, 'source_packed_sha256': digest(args.packed),
              'output_packed_sha256': digest(args.out), 'placement_complete': False,
              'physical_lut_positions': None,
              'method': 'S 输入来自至多五个输入的普通 LUT，DI 使用 X，O5 及输出选择器空闲。新增逻辑保持原函数并成为 S LUT 的相对位置子单元；原进位组及寄存器约束保留。'}
    if guide:
        result.update(placement_guide_sha256=digest(args.placement_guide), maximum_guide_site_distance=args.maximum_site_distance,
                      guide_physical_lut_positions=guide['physical_lut_positions'])
    else:
        result['requires_shared_variable_input'] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('pair_count', 'available_carry_slots', 'independent_luts')}))


if __name__ == '__main__':
    main()
