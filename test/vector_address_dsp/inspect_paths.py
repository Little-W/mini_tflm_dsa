#!/usr/bin/env python3
"""检查实际映射后的读取地址路径及 DSP 输入的组合来源。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from map_wide_alu import combinational_inputs
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--require-address-dsp', action='store_true')
    args = parser.parse_args()
    design = json.loads(args.mapped.read_text())
    module = design['modules']['vector_engine']
    cells = module['cells']
    pre_lut = args.mapped.with_name('pre_lut.il')
    for cell_name, origin in register_origins(pre_lut).items():
        if cell_name in cells:
            cells[cell_name].setdefault('attributes', {})['fpga_register_origin'] = origin
    drivers = {}
    for name, cell in cells.items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for bit in bits:
                    if isinstance(bit, int):
                        assert bit not in drivers, f'Multiple output drivers: {bit}'
                        drivers[bit] = (name, port)
    target = [name for name, cell in cells.items()
              if cell['type'] == 'DSP48E1' and 'u_read_address' in name]
    if args.require_address_dsp:
        assert len(target) == 1
    upstream = []
    for name in target:
        pending = list(combinational_inputs(cells[name]))
        seen = set()
        while pending:
            bit = pending.pop()
            if bit in seen or bit not in drivers:
                continue
            seen.add(bit)
            parent, port = drivers[bit]
            cell = cells[parent]
            if cell['type'] == 'DSP48E1':
                upstream.append({'target': name, 'source': parent, 'output_port': port,
                                 'parameters': cell['parameters']})
                continue
            pending.extend(combinational_inputs(cell, port))
    assert not upstream, 'Address DSP is driven by another DSP through combinational logic'

    # 地址端口增加分析用采样终点，只建立组合路径终点，不参与资源统计。
    measured = copy.deepcopy(module)
    maximum = max(bit for cell in cells.values() for bits in cell['connections'].values()
                  for bit in bits if isinstance(bit, int))
    clk = module['ports']['clk']['bits'][0]
    for index, bit in enumerate(module['ports']['rd_base_addr']['bits']):
        measured['cells'][f'address_capture_{index}'] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': f'rd_base_addr [{index}]',
                           'src': 'analysis-only output sampling endpoint'},
            'port_directions': {'C': 'input', 'CE': 'input', 'R': 'input', 'D': 'input', 'Q': 'output'},
            'connections': {'C': [clk], 'CE': ['1'], 'R': ['0'], 'D': [bit], 'Q': [maximum + 1 + index]}}
    endpoint = lambda name, cell, port: name.startswith('address_capture_') and port == 'D'
    paths = connected_paths(measured, sink_filter=endpoint)
    state_paths = connected_paths(measured, sink_filter=endpoint,
        root_filter=lambda name, cell, port: cell.get('attributes', {}).get('fpga_register_origin', '').startswith('state '))
    assert paths['graph_complete'] and state_paths['graph_complete']
    assert state_paths['longest_register_path_cells'] > 0
    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
              'address_dsps': target, 'upstream_dsps_without_clocked_boundary': upstream,
              'paths_to_read_address': paths, 'state_paths_to_read_address': state_paths,
              'analysis_endpoint': 'The rd_base_addr output is sampled without adding combinational cells.',
              'passed': True}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'address_dsps': len(target), 'upstream_dsps': len(upstream),
                      'address_cells': paths['longest_register_path_cells'],
                      'state_to_address_cells': state_paths['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
