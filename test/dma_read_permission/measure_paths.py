#!/usr/bin/env python3
"""测量实际读取保护和请求复用模块的组合许可路径，端口仅作为分析边界。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins, resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['read_ready_top']
    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'resources': resources(module['cells'])}
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    report['internal_paths'] = connected_paths(module, limit=3, group_limit=3)
    next_bit = max(bit for net in module['netnames'].values() for bit in net['bits']
                   if isinstance(bit, int)) + 1
    for port, data in module['ports'].items():
        if port == 'clk':
            continue
        source = data['direction'] == 'input'
        for index, bit in enumerate(data['bits']):
            if not isinstance(bit, int):
                continue
            name = f'analysis_{"input" if source else "output"}_{port}_{index}'
            module['cells'][name] = {'type': 'FDRE', 'attributes': {}, 'parameters': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': [next_bit if source else bit],
                                'Q': [bit if source else next_bit]}}
            next_bit += 1
    paths = {}
    inputs = ('linear_araddr', 'linear_arlen', 'linear_arvalid', 'linear_rready',
              'fe_arvalid', 'fe_rready', 'm_axi_arready', 'm_axi_rvalid', 'm_axi_rlast')
    outputs = ('linear_arready', 'fe_arready', 'm_axi_arvalid', 'm_axi_rready', 'read_error')
    for source in inputs + ('mode', 'all_registers'):
        paths[source] = {}
        for output in outputs:
            def root(name, cell, port):
                if source == 'mode':
                    return cell.get('attributes', {}).get('fpga_register_origin', '') in ('job_conv', 'job_read_guard')
                if source == 'all_registers':
                    return not name.startswith('analysis_')
                return name.startswith('analysis_input_' + source + '_')

            row = connected_paths(module, limit=1, group_limit=0, root_filter=root,
                                  sink_filter=lambda name, cell, port: name.startswith('analysis_output_' + output + '_'))
            if not row['graph_complete']:
                raise RuntimeError('Read permission graph is incomplete')
            paths[source][output] = {'connected': bool(row['register_to_register_paths']),
                                    'combinational_cells': row['longest_register_path_cells'],
                                    'longest_path': row['register_to_register_paths'][:1]}
    report['port_paths'] = paths
    report['port_method'] = 'Only analysis copies add register boundaries; resources use the unmodified mapped module.'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'lut': report['resources']['logic_lut_cells'],
                      'ff': report['resources']['flip_flops'],
                      'internal_max': report['internal_paths']['longest_register_path_cells'],
                      'linear_araddr': {key: value['combinational_cells']
                                        for key, value in paths['linear_araddr'].items()},
                      'linear_arlen': {key: value['combinational_cells']
                                       for key, value in paths['linear_arlen'].items()}}))


if __name__ == '__main__':
    main()
