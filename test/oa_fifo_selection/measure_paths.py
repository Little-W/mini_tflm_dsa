#!/usr/bin/env python3
"""测量写回索引选择和 FIFO 组启动的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def origin(cell):
    return cell.get('attributes', {}).get('fpga_register_origin', '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {}
    for label, folder in (('reference', args.reference), ('current', args.current)):
        mapped, pre_lut = folder / 'mapped.json', folder / 'pre_lut.il'
        module = json.loads(mapped.read_text())['modules']['oa_fifo_timing_top']
        for name, signal in register_origins(pre_lut).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = signal
        paths = {}
        for target in ('vec_valid_num_col_next_r', 'vec_valid_num_row_next_r'):
            paths['cfg_is_mode_to_' + target] = connected_paths(module,
                root_filter=lambda name, cell, port: origin(cell) == 'u_writer.cfg_is_mode',
                sink_filter=lambda name, cell, port: port == 'D' and
                origin(cell).startswith('u_writer.' + target + ' '))
        paths['next_group_to_row_tiles'] = connected_paths(module,
            root_filter=lambda name, cell, port: origin(cell).startswith('u_writer.row_group_next_base_idx '),
            sink_filter=lambda name, cell, port: port == 'D' and
            origin(cell).startswith('u_writer.co_next_row_tiles_q '))

        # 仅为输入端口建立分析起点，不改变网表数据通路或资源统计。
        for port in ('write_oa_granted', 'start_permitted'):
            module['cells']['analysis_' + port] = {
                'type': 'FDRE', 'parameters': {},
                'attributes': {'fpga_register_origin': 'analysis.' + port},
                'port_directions': {'C': 'input', 'D': 'input', 'CE': 'input', 'R': 'input', 'Q': 'output'},
                'connections': {'C': module['ports']['clk']['bits'], 'D': ['0'],
                                'CE': ['1'], 'R': ['0'], 'Q': module['ports'][port]['bits']}}
            paths[port + '_to_co_data_valid'] = connected_paths(module,
                root_filter=lambda name, cell, out: name == 'analysis_' + port,
                sink_filter=lambda name, cell, out: out == 'D' and origin(cell) == 'u_fifo.co_data_valid')
        for item in paths.values():
            assert item['graph_complete'] and item['longest_register_path_cells'] > 0
        report[label] = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
                         'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
                         'paths': paths}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({label: {name: item['longest_register_path_cells']
                             for name, item in row['paths'].items()} for label, row in report.items()}))


if __name__ == '__main__':
    main()
