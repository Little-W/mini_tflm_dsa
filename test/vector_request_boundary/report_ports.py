#!/usr/bin/env python3
"""报告向量关键接口的实际组合连接，不计入外围寄存器级数。"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys


def read_json(path):
    if path.exists():
        return json.loads(path.read_text())
    with gzip.open(str(path) + '.gz', 'rt') as stream:
        return json.load(stream)


def analyze(folder, tool_root):
    sys.path.insert(0, str(tool_root / 'scripts/fpga'))
    from netlist_metrics import connected_paths, register_origins
    module = read_json(folder / 'mapped.json')['modules']['vector_engine']
    origins_file = folder / 'pre_lut.il'
    if not origins_file.exists():
        origins_file = Path(str(origins_file) + '.gz')
    for name, origin in register_origins(origins_file).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    next_bit = max(bit for net in module['netnames'].values()
                   for bit in net['bits'] if isinstance(bit, int)) + 1
    output_names = ('win_req_valid', 'o_weight_read_addr', 'o_weight_read_en', 'o_weight_write_en')
    for name in output_names:
        bits = module['ports'][name]['bits']
        result = list(range(next_bit, next_bit + len(bits)))
        next_bit += len(bits)
        module['cells']['interface_output_' + name] = dict(
            type='FDRE', parameters={}, attributes={'fpga_register_origin': name},
            connections=dict(C=['0'], CE=['1'], R=['0'], D=bits, Q=result),
            port_directions=dict(C='input', CE='input', R='input', D='input', Q='output'))
    input_bits = module['ports']['i_weight_read_valid']['bits']
    module['cells']['interface_input_weight_valid'] = dict(
        type='FDRE', parameters={}, attributes={'fpga_register_origin': 'i_weight_read_valid'},
        connections=dict(C=['0'], CE=['1'], R=['0'], D=['0'], Q=input_bits),
        port_directions=dict(C='input', CE='input', R='input', D='input', Q='output'))
    report = {}
    for output in output_names:
        report['register_to_' + output] = connected_paths(
            module, limit=4, group_limit=4,
            root_filter=lambda name, cell, port: not name.startswith('interface_'),
            sink_filter=lambda name, cell, port, output=output: name == 'interface_output_' + output and port == 'D')
    report['weight_valid_to_window_request'] = connected_paths(
        module, limit=4, group_limit=4,
        root_filter=lambda name, cell, port: name == 'interface_input_weight_valid',
        sink_filter=lambda name, cell, port: name == 'interface_output_win_req_valid' and port == 'D')
    def register_name(cell):
        return cell.get('attributes', {}).get('fpga_register_origin', '').split(' ')[0]

    pool_name = 'state_pool_store' if any(register_name(cell) == 'state_pool_store'
                                        for cell in module['cells'].values()) else 'state'
    pool_bits = {bit for cell in module['cells'].values() if register_name(cell) == pool_name
                 for bit in cell['connections'].get('Q', [])}
    assert pool_bits
    accumulator_bits = set(module['ports']['o_ps_write_data']['bits'])
    report['pool_control_to_accumulator'] = connected_paths(
        module, limit=4, group_limit=4,
        root_filter=lambda name, cell, port: bool(pool_bits.intersection(cell['connections'].get('Q', []))),
        sink_filter=lambda name, cell, port: port == 'D' and
            bool(accumulator_bits.intersection(cell['connections'].get('Q', []))))
    report['analysis_boundary'] = 'The added netlist endpoints only mark module ports; no RTL or synthesized hardware is changed'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--tool-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.source.resolve(), args.tool_root.resolve())
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: dict(cells=value['longest_register_path_cells'],
                               connected=bool(value['register_to_register_paths']),
                               complete=value['graph_complete'])
                      for key, value in report.items() if isinstance(value, dict)}))


if __name__ == '__main__':
    main()
