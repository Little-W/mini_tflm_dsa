#!/usr/bin/env python3
"""对联合返回路径记录完整组合级数，端口寄存器只存在于分析副本。"""
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
    module = json.loads(args.mapped.read_text())['modules']['dma_return_admission_top']
    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'resources': resources(module['cells'])}
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    report['internal_paths'] = connected_paths(module, limit=5, group_limit=3)
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
    inputs = ('rd_context_count', 'fe_rready', 'm_axi_bready', 'rd_dma_done', 'dma_rd_error',
              'wr_dma_done', 'dma_wr_error', 'rd_command_client', 'rd_dma_start_q',
              'abort_pending', 'kernel_request', 'kernel_quiescent')
    outputs = ('m_axi_rready', 'bus_error', 'abort', 'ia_granted', 'kernel_granted',
               'bias_granted', 'quant_granted', 'dw_granted', 'kernel_idle', 'kernel_start')
    report['port_paths'] = {}
    for source in (*inputs, 'all_registers'):
        paths = {}
        for output in outputs:
            def root(name, cell, port):
                if source == 'all_registers':
                    return not name.startswith('analysis_')
                return name.startswith('analysis_input_' + source + '_')
            row = connected_paths(module, limit=1, group_limit=0, root_filter=root,
                sink_filter=lambda name, cell, port: name.startswith('analysis_output_' + output + '_'))
            if not row['graph_complete']:
                raise RuntimeError('Return path graph is incomplete')
            paths[output] = {'connected': bool(row['register_to_register_paths']),
                            'combinational_cells': row['longest_register_path_cells'],
                            'longest_path': row['register_to_register_paths'][:1]}
        report['port_paths'][source] = paths
    report['segments'] = {}
    for source, outputs in (
        ('guard_rready', ('m_axi_rready',)),
        ('m_axi_rready', ('bus_error',)),
        ('bus_error', ('abort',)),
        ('abort', ('ia_granted', 'kernel_granted', 'bias_granted', 'quant_granted', 'dw_granted')),
    ):
        net = module['netnames'][source]
        if len(net['bits']) != 1 or not isinstance(net['bits'][0], int):
            raise RuntimeError('Expected scalar segment boundary: ' + source)
        name = 'analysis_segment_' + source
        module['cells'][name] = {'type': 'FDRE', 'attributes': {}, 'parameters': {},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': [next_bit], 'Q': net['bits']}}
        next_bit += 1
        report['segments'][source] = {}
        for output in outputs:
            row = connected_paths(module, limit=1, group_limit=0,
                root_filter=lambda cell_name, cell, port: cell_name == name,
                sink_filter=lambda cell_name, cell, port: cell_name.startswith('analysis_output_' + output + '_'))
            if not row['graph_complete'] or not row['register_to_register_paths']:
                raise RuntimeError('Expected a complete connected segment: ' + source + ' -> ' + output)
            report['segments'][source][output] = {'combinational_cells': row['longest_register_path_cells'],
                'longest_path': row['register_to_register_paths'][0]}
        del module['cells'][name]
    report['port_method'] = 'Analysis-only register boundaries; resources are from the original mapped design.'
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'lut': report['resources']['logic_lut_cells'],
        'ff': report['resources']['flip_flops'],
        'internal_max': report['internal_paths']['longest_register_path_cells'],
        'rd_context_count': {key: value['combinational_cells']
                             for key, value in report['port_paths']['rd_context_count'].items()}}))


if __name__ == '__main__':
    main()
