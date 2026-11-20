#!/usr/bin/env python3
"""测量偏置驻留结果、读行数与完整模块的实际寄存器路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

OUTPUTS = ('bias_valid', 'bias_group_valid')
REGISTER_SINKS = {
    'dma_rows_to_read': ('ext_dma_rows_to_read', 'u_ctrl.dma_rows_to_read'),
    'ws_cache_valid': ('u_buffer.ws_cache_valid',),
    'ws_issue_count': ('u_buffer.ws_issue_count',),
}
SOURCES = ('u_ctrl.current_block_idx', 'u_ctrl.group_blocks_needed',
           'u_buffer.bank_block_idx', 'u_buffer.bank_end_q', 'u_ctrl.load_block_idx')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['bias_loader']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin

    def path(root=None, sink=None):
        result = connected_paths(module, limit=1, group_limit=0, root_filter=root, sink_filter=sink)
        if not result['graph_complete']:
            raise RuntimeError('Mapped connectivity graph is incomplete')
        return {'longest_path_cells': result['longest_register_path_cells'],
                'longest_path': result['register_to_register_paths'][:1]}

    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'complete_module': path()}
    report['register_sink_paths'] = {}
    for target, origins in REGISTER_SINKS.items():
        sink = lambda name, cell, port: cell.get('attributes', {}).get('fpga_register_origin', '').split(' [')[0] in origins
        if not any(sink(name, cell, '') for name, cell in module['cells'].items()):
            raise RuntimeError(f'Register origin was not found: {target}')
        report['register_sink_paths'][target] = path(sink=sink)
    next_bit = max(b for n in module['netnames'].values() for b in n['bits'] if isinstance(b, int))+1
    for output in OUTPUTS:
        for index, bit in enumerate(module['ports'][output]['bits']):
            module['cells'][f'analysis_{output}_{index}'] = {
                'type': 'FDRE', 'attributes': {}, 'parameters': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': [bit], 'Q': [next_bit]},
            }
            next_bit += 1
    report['output_paths'] = {}
    report['source_paths'] = {}
    for output in OUTPUTS:
        sink = lambda name, cell, port: name.startswith(f'analysis_{output}_')
        report['output_paths'][output] = path(sink=sink)
    for source in SOURCES:
        root = lambda name, cell, port: cell.get('attributes', {}).get('fpga_register_origin', '').split(' [')[0] == source
        report['source_paths'][source] = {}
        for output in OUTPUTS:
            sink = lambda name, cell, port: name.startswith(f'analysis_{output}_')
            report['source_paths'][source][output] = path(root, sink)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'module_register_max': report['complete_module']['longest_path_cells'],
                      'outputs': {k: v['longest_path_cells'] for k, v in report['output_paths'].items()},
                      'source_paths': {k: {p: v['longest_path_cells'] for p, v in values.items()}
                                       for k, values in report['source_paths'].items()}}))


if __name__ == '__main__':
    main()
