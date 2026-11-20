#!/usr/bin/env python3
"""检查 Vivado DSP 属性及实际 B 端口连接中的跨计算单元组合级联。"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

PE = re.compile(r'(?:^|/)(gen_row\[(\d+)\](?:\.|/)gen_col\[(\d+)\](?:\.|/)ws_cell)(?:/|$)')


def inspect(cells, connections, size, maximum=0, maximum_b_cells=9):
    records = {}
    by_pe = {}
    for entry in cells:
        name = entry['name']
        if name in records:
            raise ValueError('Duplicate DSP cell: ' + name)
        match = PE.search(name)
        if match is None:
            raise ValueError('DSP is outside a named computation cell: ' + name)
        coordinate = (int(match[2]), int(match[3]))
        if any(index >= size for index in coordinate):
            raise ValueError('Computation cell index exceeds array size')
        record = dict(entry)
        record['b_input'] = record['b_input'].strip().upper()
        for key in ('breg', 'bcascreg', 'areg', 'acascreg', 'mreg', 'preg'):
            record[key] = int(record[key])
        if record['b_input'] not in ('DIRECT', 'CASCADE'):
            raise ValueError('Unsupported DSP B input selection')
        legal = {0: {0}, 1: {1}, 2: {1, 2}}
        if record['breg'] not in legal or record['bcascreg'] not in legal[record['breg']]:
            raise ValueError('Invalid BREG and BCASCREG combination')
        record['pe'] = list(coordinate)
        records[name] = record
        by_pe.setdefault(coordinate, []).append(name)
    expected = {(row, column) for row in range(size) for column in range(size)}
    if set(by_pe) != expected:
        raise ValueError('DSP coverage does not contain every computation cell')

    edges = {}
    incoming = {name: set() for name in records}
    for connection in connections:
        source, target = connection['source'], connection['target']
        if source not in records or target not in records:
            raise ValueError('DSP connection refers to an unrecorded cell')
        port = connection['port']
        expected_port = 'BCIN' if records[target]['b_input'] == 'CASCADE' else 'B'
        if port != expected_port:
            raise ValueError('Connection does not reach the selected DSP B input')
        key = (source, target, port)
        edges.setdefault(key, set()).add(connection['target_pin'])
        incoming[target].add(source)

    cache = {}
    active = set()

    def depth(name):
        if name in cache:
            return cache[name]
        if records[name]['bcascreg'] != 0:
            cache[name] = (0, 0, [name])
            return cache[name]
        if name in active:
            raise ValueError('Combinational DSP B cascade contains a cycle')
        active.add(name)
        result = (1, 0, [name])
        for source in incoming[name]:
            units, crossings, path = depth(source)
            crossings += records[source]['pe'] != records[name]['pe']
            selected = (path + [name] if (crossings, len(path)+1) >
                        (result[1], len(result[2])) else result[2])
            result = (max(units + 1, result[0]), max(crossings, result[1]), selected)
        active.remove(name)
        cache[name] = result
        return result

    paths = [depth(name) for name in records]
    worst = max(paths, key=lambda value: (value[1], value[0]))
    longest_b = max(value[0] for value in paths)
    return {
        'passed': worst[1] <= maximum and longest_b <= maximum_b_cells,
        'measurement_kind': 'Vivado DSP properties and selected B-input net connectivity',
        'size': size, 'pe_count': len(by_pe), 'dsp_count': len(records),
        'maximum_cross_pe_bypass_allowed': maximum,
        'maximum_combinational_b_dsp_cells_allowed': maximum_b_cells,
        'longest_cross_pe_bypass': worst[1],
        'b_dsp_cells_on_selected_path': sum(records[name]['bcascreg'] == 0 for name in worst[2]),
        'selected_path': worst[2],
        'longest_combinational_b_dsp_cells': longest_b,
        'cells': [records[name] for name in sorted(records)],
        'edges': [dict(source=source, target=target, port=port, connected_bits=len(bits),
                       crosses_pe=records[source]['pe'] != records[target]['pe'],
                       target_b_output_registered=records[target]['bcascreg'] != 0)
                  for (source, target, port), bits in sorted(edges.items())],
        'timing_claim': 'Connection analysis; 150 MHz requires implementation timing reports',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cells', type=Path, required=True)
    parser.add_argument('--connections', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--size', type=int, default=16)
    parser.add_argument('--max-cross-pe-bypass', type=int, default=0)
    parser.add_argument('--max-b-dsp-cells', type=int, default=9)
    parser.add_argument('--all-cells', type=Path)
    args = parser.parse_args()
    if args.size < 1 or args.max_cross_pe_bypass < 0 or args.max_b_dsp_cells < 1:
        parser.error('Size must be positive and bypass count must be nonnegative')
    with args.cells.open() as stream:
        cells = list(csv.DictReader(stream, delimiter='\t'))
    with args.connections.open() as stream:
        connections = list(csv.DictReader(stream, delimiter='\t'))
    result = inspect(cells, connections, args.size, args.max_cross_pe_bypass, args.max_b_dsp_cells)
    result['input_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (args.cells, args.connections)}
    if args.all_cells:
        with args.all_cells.open() as stream:
            all_cells = list(csv.DictReader(stream, delimiter='\t'))
        result['all_dsp_count'] = len(all_cells)
        result['all_dsp_table'] = str(args.all_cells)
        result['input_sha256'][args.all_cells.name] = hashlib.sha256(args.all_cells.read_bytes()).hexdigest()
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('passed', 'pe_count', 'dsp_count',
          'longest_cross_pe_bypass', 'longest_combinational_b_dsp_cells')}))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
