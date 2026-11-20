#!/usr/bin/env python3
"""Check that packed CARRY4 inputs retain their original signals through identity LUTs."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def aliases(module):
    result = collections.defaultdict(set)
    for name, net in module['netnames'].items():
        for index, bit in enumerate(net['bits']):
            result[bit].add(name if len(net['bits']) == 1 else f'{name}[{index}]')
    return result


def check_connections(reference, packed):
    original_names = aliases(reference)
    packed_names = aliases(packed)
    drivers = {}
    for name, cell in packed['cells'].items():
        for port, values in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for bit in values:
                    drivers[bit] = (name, cell)

    def matches(expected, actual, seen=None):
        if not isinstance(actual, int):
            return expected == actual
        if original_names[expected] & packed_names[actual]:
            return True
        if actual not in drivers:
            return False
        seen = set() if seen is None else seen
        if actual in seen:
            return False
        seen.add(actual)
        _, driver = drivers[actual]
        if driver['type'] == 'PSEUDO_GND':
            return expected == '0'
        if driver['type'] == 'PSEUDO_VCC':
            return expected == '1'
        if driver['type'] == 'SLICE_LUTX' and driver.get('attributes', {}).get('X_ORIG_TYPE') == 'LUT1':
            init = driver['parameters'].get('INIT', '0')
            value = init if isinstance(init, int) else int(init, 2)
            inputs = [values[0] for port, values in driver['connections'].items()
                      if driver['port_directions'][port] == 'input' and values]
            if value == 2 and len(inputs) == 1:
                return matches(expected, inputs[0], seen)
        return False

    checked = 0
    direct_inputs = 0
    errors = []
    for name, cell in reference['cells'].items():
        if cell['type'] != 'CARRY4':
            continue
        current = packed['cells'].get(name)
        if current is None or current['type'] != 'CARRY4':
            errors.append(f'CARRY4 instance missing after packing: {name}')
            continue
        for port in ('CI', 'CYINIT', 'DI', 'S'):
            for index, expected in enumerate(cell['connections'].get(port, [])):
                packed_port = {'CI': 'CIN', 'CYINIT': 'CYINIT'}.get(port, port + str(index))
                actual = current['connections'].get(packed_port, [])
                valid = matches(expected, actual[0]) if actual else expected == '0' and port in ('CI', 'CYINIT')
                if not valid:
                    errors.append(f'{name}.{port}[{index}] changed during packing')
                checked += 1
                if port == 'DI' and current['attributes'].get(f'X_CARRY_DI{index}_VIA_X'):
                    direct_inputs += 1
    return {'passed': not errors, 'checked_carry_inputs': checked,
            'direct_di_inputs': direct_inputs, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--packed', type=Path, required=True)
    parser.add_argument('--top', default='soc_top')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())['modules'][args.top]
    modules = json.loads(args.packed.read_text())['modules']
    packed = modules.get(args.top, next(iter(modules.values())))
    result = check_connections(reference, packed)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
