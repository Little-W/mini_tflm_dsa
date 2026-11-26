#!/usr/bin/env python3
"""统计完整帧调度器的内部路径，以及任务切片输入到状态更新的路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def origin(cell):
    return cell.get('attributes', {}).get('fpga_register_origin', '').split(' [')[0].split('.')[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['ps_window_scheduler']
    for name, saved in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = saved

    def measure(source=None, sink=None):
        result = connected_paths(module, limit=1, group_limit=0,
                                 root_filter=source, sink_filter=sink)
        if not result['graph_complete']:
            raise RuntimeError('映射网表的组合连接图不完整')
        return {'longest_path_cells': result['longest_register_path_cells'],
                'longest_path': result['register_to_register_paths'][:1]}

    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'complete_module': measure()}
    next_bit = max(bit for net in module['netnames'].values()
                   for bit in net['bits'] if isinstance(bit, int)) + 1
    inputs = ('slice_tiles', 'reuse_rows')
    for input_name in inputs:
        for index, bit in enumerate(module['ports'][input_name]['bits']):
            if not isinstance(bit, int):
                continue
            module['cells'][f'analysis_input_{input_name}_{index}'] = {
                'type': 'FDRE', 'attributes': {}, 'parameters': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': [next_bit], 'Q': [bit]},
            }
            next_bit += 1
    report['configuration_inputs_to_phase'] = {}
    for input_name in inputs:
        source = lambda name, cell, port: name.startswith(f'analysis_input_{input_name}_')
        sink = lambda name, cell, port: origin(cell) == 'phase'
        report['configuration_inputs_to_phase'][input_name] = measure(source, sink)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'module_register_max': report['complete_module']['longest_path_cells'],
        'configuration_inputs': {key: value['longest_path_cells']
            for key, value in report['configuration_inputs_to_phase'].items()}}))


if __name__ == '__main__':
    main()
