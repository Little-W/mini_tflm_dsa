#!/usr/bin/env python3
"""统计 IA 装载完成输入到数据有效及分组就绪状态的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['ia_loader_ctrl']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    next_bit = max(bit for net in module['netnames'].values()
                   for bit in net['bits'] if isinstance(bit, int)) + 1
    for index, bit in enumerate(module['ports']['tl_tile_done']['bits']):
        module['cells'][f'analysis_completion_{index}'] = {
            'type': 'FDRE', 'attributes': {}, 'parameters': {},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': [next_bit], 'Q': [bit]},
        }
        next_bit += 1
    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(), 'paths': {}}
    for register in ('ia_data_valid', 'send_group_ready_r'):
        paths = connected_paths(module, limit=1, group_limit=0,
            root_filter=lambda name, cell, port: name.startswith('analysis_completion_'),
            sink_filter=lambda name, cell, port:
                cell.get('attributes', {}).get('fpga_register_origin', '').split(' [')[0] == register)
        if not paths['graph_complete']:
            raise RuntimeError('映射后的组合连接图不完整')
        report['paths'][register] = {'longest_path_cells': paths['longest_register_path_cells'],
            'longest_path': paths['register_to_register_paths'][:1]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({key: value['longest_path_cells'] for key, value in report['paths'].items()}))


if __name__ == '__main__':
    main()
