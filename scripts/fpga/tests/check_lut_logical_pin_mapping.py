#!/usr/bin/env python3
"""逐单元核对普通逻辑 LUT 在布局前后的 INIT、逻辑引脚和网络连接。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import gc
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from placed_resources import placed_resources
from check_json_init import logical_pins


def open_content(path, text=False):
    actual = path if path.exists() else path.with_suffix(path.suffix + '.gz')
    return gzip.open(actual, 'rt' if text else 'rb') if actual.suffix == '.gz' else actual.open('r' if text else 'rb')


def digest(path):
    value = hashlib.sha256()
    with open_content(path) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_module(path):
    with open_content(path, text=True) as stream:
        modules = json.load(stream)['modules']
    selected = [(name, m) for name, m in modules.items() if m.get('cells')]
    if len(selected) != 1:
        raise RuntimeError('A single flattened implementation module is required')
    return selected[0]


def ordinary_luts(m):
    return {name: cell for name, cell in m['cells'].items()
            if cell['type'] == 'SLICE_LUTX' and
            re.fullmatch(r'LUT[1-6]', cell['attributes'].get('X_ORIG_TYPE', '')) and
            'X_LUT_AS_DRAM' not in cell['attributes'] and 'X_LUT_AS_SRL' not in cell['attributes']}


def output_nets(cell):
    return {bit for port, bits in cell['connections'].items()
            if cell['port_directions'][port] == 'output' for bit in bits}


def aliases(m, needed):
    result = defaultdict(set)
    for name, net in m['netnames'].items():
        for index, bit in enumerate(net['bits']):
            if bit in needed:
                result[bit].add(name if len(net['bits']) == 1 else f'{name}[{index}]')
    result['0'].add('$PACKER_GND_NET')
    result['1'].add('$PACKER_VCC_NET')
    for cell in m['cells'].values():
        if cell['type'] not in ('PSEUDO_GND', 'PSEUDO_VCC'):
            continue
        name = '$PACKER_GND_NET' if cell['type'] == 'PSEUDO_GND' else '$PACKER_VCC_NET'
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for bit in bits:
                    if bit in needed:
                        result[bit].add(name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, required=True)
    parser.add_argument('--physical', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_top, source = read_module(args.packed)
    reference = {name: {'init': cell['parameters']['INIT'],
                       'type': cell['attributes']['X_ORIG_TYPE'], 'pins': logical_pins(cell),
                       'outputs': output_nets(cell)}
                 for name, cell in ordinary_luts(source).items()}
    if not reference:
        raise RuntimeError('The input contains no ordinary logic LUTs')
    old_aliases = aliases(source, {bit for cell in reference.values()
                                 for bit in set(cell['pins'].values()) | cell['outputs']})
    del source
    gc.collect()
    physical_top, physical = read_module(args.physical)
    current = ordinary_luts(physical)
    current_pins = {name: logical_pins(cell) for name, cell in current.items()}
    new_aliases = aliases(physical, {bit for name, cell in current.items()
                                   for bit in set(current_pins[name].values()) | output_nets(cell)})
    errors, error_count = [], 0

    def require(condition, kind, **detail):
        nonlocal error_count
        if not condition:
            error_count += 1
            if len(errors) < 50:
                errors.append({'kind': kind, **detail})

    require(set(reference) == set(current), 'logic_cell_set',
            missing=sorted(set(reference) - set(current))[:20],
            additional=sorted(set(current) - set(reference))[:20])
    pin_checks = 0
    output_checks = 0
    checked = 0
    for name, old in reference.items():
        if name not in current:
            continue
        cell, pins = current[name], current_pins[name]
        require(cell['attributes']['X_ORIG_TYPE'] == old['type'], 'original_type', cell=name)
        require(cell['parameters']['INIT'] == old['init'], 'init', cell=name)
        require(set(pins) == set(old['pins']), 'logical_pin_set', cell=name,
                expected=sorted(old['pins']), actual=sorted(pins))
        for pin in set(pins) & set(old['pins']):
            a, b = old_aliases[old['pins'][pin]], new_aliases[pins[pin]]
            require(bool(a & b), 'logical_pin_net', cell=name, pin=pin,
                    expected_aliases=sorted(a), actual_aliases=sorted(b))
            pin_checks += 1
        remaining_outputs = output_nets(cell)
        require(len(old['outputs']) == len(remaining_outputs), 'output_count', cell=name)
        for bit in old['outputs']:
            expected = old_aliases[bit]
            matches = {current_bit for current_bit in remaining_outputs
                       if expected & new_aliases[current_bit]}
            require(len(matches) == 1, 'output_net', cell=name,
                    expected_aliases=sorted(expected),
                    actual_aliases=[sorted(new_aliases[current_bit]) for current_bit in remaining_outputs])
            if len(matches) == 1:
                remaining_outputs -= matches
                output_checks += 1
        checked += 1

    positions = defaultdict(dict)
    for name, cell in current.items():
        bel = cell['attributes'].get('NEXTPNR_BEL', '')
        match = re.fullmatch(r'(.+/[A-D])([56])LUT', bel)
        require(match is not None, 'logic_lut_bel', cell=name, bel=bel)
        if match is None:
            continue
        position, half = match.groups()
        require(half not in positions[position], 'duplicate_lut_half', position=position, half=half)
        positions[position][half] = (name, cell)
    shared_positions = 0
    common_pin_checks = 0
    for position, halves in positions.items():
        if len(halves) != 2:
            continue
        shared_positions += 1
        lower, upper = halves['5'][1], halves['6'][1]
        for index in range(1, 7):
            port = f'A{index}'
            a, b = lower['connections'].get(port, []), upper['connections'].get(port, [])
            if a and b:
                require(a == b, 'shared_physical_input', position=position, port=port,
                        lower_cell=halves['5'][0], upper_cell=halves['6'][0])
                common_pin_checks += 1
    resources = placed_resources(physical)
    require(resources['placement_complete'], 'complete_unique_bels',
            unplaced_cells=resources['unplaced_cells'][:20], resource_errors=resources['resource_errors'][:20])
    report = {'passed': error_count == 0, 'source_top': source_top, 'physical_top': physical_top,
              'reference_logic_luts': len(reference), 'physical_logic_luts': len(current),
              'logic_luts_checked': checked, 'logical_input_connections_checked': pin_checks,
              'logical_output_connections_checked': output_checks,
              'shared_logic_lut_positions': shared_positions,
              'shared_physical_input_connections_checked': common_pin_checks,
              'all_cells_have_unique_bels': resources['placement_complete'],
              'resources': resources, 'error_count': error_count, 'errors': errors,
              'source_sha256': digest(args.packed), 'physical_sha256': digest(args.physical),
              'checker_sha256': digest(Path(__file__)),
              'method': 'Compare each ordinary LUT INIT and original logical input set, match all logical input and output nets by network aliases, allow physical input permutations and O6/O5 output renaming, check common inputs of shared logic LUT positions and unique BEL assignment for every implementation cell.'}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'logic_luts_checked',
          'logical_input_connections_checked', 'shared_logic_lut_positions', 'error_count')}, ensure_ascii=False))
    if error_count:
        raise SystemExit('Logical LUT mapping validation failed; see ' + str(args.out))


if __name__ == '__main__':
    main()
