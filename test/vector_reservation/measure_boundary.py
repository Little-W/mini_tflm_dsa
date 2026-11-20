#!/usr/bin/env python3
"""检查窗口就绪输入至实际槽位占用寄存器的组合连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--netlist', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.netlist.read_text())['modules']['vector_engine']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    boundary_name = 'window_ready_input_boundary'
    module['cells'][boundary_name] = {
        'type': 'FDRE', 'parameters': {},
        'attributes': {'src': 'vector_engine.win_req_ready',
                       'fpga_register_origin': 'win_req_ready'},
        'port_directions': {'Q': 'output', 'D': 'input', 'C': 'input', 'CE': 'input', 'R': 'input'},
        'connections': {'Q': module['ports']['win_req_ready']['bits'], 'D': ['0'],
                        'C': ['0'], 'CE': ['0'], 'R': ['0']}}
    paths = connected_paths(
        module,
        root_filter=lambda name, cell, port: name == boundary_name,
        sink_filter=lambda name, cell, port: 'input_reserved' in
            cell.get('attributes', {}).get('fpga_register_origin', ''))
    for key in ('register_to_register_paths', 'distinct_register_path_groups'):
        for path in paths[key]:
            path['startpoint'].update(cell='vector_engine', type='MODULE_INPUT',
                                      port='win_req_ready', detail='module input', register_origin=None)
    result = {'scope': 'Module input win_req_ready to actual input_reserved data and control pins',
              'netlist_sha256': hashlib.sha256(args.netlist.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'paths': paths}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'combinational_cells': paths['longest_register_path_cells'],
                      'graph_complete': paths['graph_complete']}))


if __name__ == '__main__':
    main()
