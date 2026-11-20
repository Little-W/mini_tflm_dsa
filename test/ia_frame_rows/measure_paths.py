#!/usr/bin/env python3
"""统计 IA 帧行数输出及尾组配置寄存器的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

REGISTERS = ('cfg_ia_reuse_num', 'ia_reuse_num_act', 'rsp_rows_last_tile',
             'frame_last_rows_q', 'is_last_l2_group')
INPUTS = ('row_tail_tiles', 'k')


def origin(cell):
    return cell.get('attributes', {}).get('fpga_register_origin', '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['ia_loader']
    for name, saved in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = saved

    def path(source=None, sink=None):
        paths = connected_paths(module, limit=1, group_limit=0,
                                root_filter=source, sink_filter=sink)
        if not paths['graph_complete']:
            raise RuntimeError('Mapped connectivity graph is incomplete')
        return {'longest_path_cells': paths['longest_register_path_cells'],
                'longest_path': paths['register_to_register_paths'][:1]}

    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'complete_module': path()}
    next_bit = max(b for n in module['netnames'].values() for b in n['bits'] if isinstance(b, int))+1
    for index, bit in enumerate(module['ports']['ps_frame_rows']['bits']):
        module['cells'][f'analysis_output_rows_{index}'] = {
            'type': 'FDRE', 'attributes': {}, 'parameters': {},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': [bit], 'Q': [next_bit]},
        }
        next_bit += 1
    output_sink = lambda name, cell, port: name.startswith('analysis_output_rows_')
    report['all_registers_to_frame_rows'] = path(sink=output_sink)
    report['registers_to_frame_rows'] = {}
    for register in REGISTERS:
        source = lambda name, cell, port: origin(cell).split(' [')[0].split('.')[-1] == register
        report['registers_to_frame_rows'][register] = path(source, output_sink)

    for input_name in INPUTS:
        for index, bit in enumerate(module['ports'][input_name]['bits']):
            if not isinstance(bit, int):
                continue
            module['cells'][f'analysis_input_{input_name}_{index}'] = {
                'type': 'FDRE', 'attributes': {}, 'parameters': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': [next_bit], 'Q': [bit]},
            }
            next_bit += 1
    frame_register_sink = lambda name, cell, port: origin(cell).split(' [')[0].split('.')[-1] == 'frame_last_rows_q'
    report['inputs_to_saved_frame_rows'] = {}
    for input_name in INPUTS:
        source = lambda name, cell, port: name.startswith(f'analysis_input_{input_name}_')
        report['inputs_to_saved_frame_rows'][input_name] = path(source, frame_register_sink)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'module_register_max': report['complete_module']['longest_path_cells'],
                      'frame_rows_output': report['all_registers_to_frame_rows']['longest_path_cells'],
                      'registers': {k: v['longest_path_cells'] for k, v in report['registers_to_frame_rows'].items()},
                      'configuration_inputs': {k: v['longest_path_cells'] for k, v in report['inputs_to_saved_frame_rows'].items()}}))


if __name__ == '__main__':
    main()
