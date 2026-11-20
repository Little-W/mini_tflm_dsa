#!/usr/bin/env python3
"""测量配置输入、已存分配结果及容量判断的实际组合路径。"""
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
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['allocation_measure']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin

    def paths(root=None, sink=None):
        result = connected_paths(module, limit=1, group_limit=0, root_filter=root, sink_filter=sink)
        if not result['graph_complete']:
            raise RuntimeError('Mapped connectivity graph is incomplete')
        return result

    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'internal_register_paths': paths(), 'output_paths': {}}
    spare = max(bit for net in module['netnames'].values() for bit in net['bits']
                if isinstance(bit, int)) + 1
    for output in ('o_ps_banks', 'o_allocation_invalid'):
        for index, bit in enumerate(module['ports'][output]['bits']):
            module['cells'][f'analysis_{output}_{index}'] = {
                'type': 'FDRE', 'parameters': {}, 'attributes': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': [bit], 'Q': [spare]},
            }
            spare += 1
        sink = lambda name, cell, port: name.startswith('analysis_' + output + '_')
        report['output_paths'][output] = paths(sink=sink)
    for name in ('cfg_shared_ia_banks', 'cfg_stream_compact'):
        for index, bit in enumerate(module['ports'][name]['bits']):
            module['cells'][f'analysis_input_{name}_{index}'] = {
                'type': 'FDRE', 'parameters': {}, 'attributes': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': [spare], 'Q': [bit]},
            }
            spare += 1
    root = lambda name, cell, port: name.startswith('analysis_input_')
    report['configuration_capture_paths'] = paths(root=root)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'register_max': report['internal_register_paths']['longest_register_path_cells'],
                      'outputs': {k: v['longest_register_path_cells'] for k, v in report['output_paths'].items()},
                      'capture_max': report['configuration_capture_paths']['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
