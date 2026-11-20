#!/usr/bin/env python3
"""测量组首触发与索引状态至实际行索引寄存器的组合路径。"""
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
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {}
    for label, directory in [('reference', args.reference), ('current', args.current)]:
        mapped, pre_lut = directory / 'mapped.json', directory / 'pre_lut.il'
        module = json.loads(mapped.read_text())['modules']['bias_row_control']
        for name, signal in register_origins(pre_lut).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = signal
        row_bits = set(module['ports']['o_row_idx']['bits'])
        sink = lambda name, cell, port: bool(row_bits.intersection(cell['connections'].get('Q', [])))
        state_paths = connected_paths(module, sink_filter=sink)
        assert state_paths['graph_complete']
        input_paths = {}
        # 仅在分析图中标记输入端口，实际电路与资源统计保持原样。
        for port in ('send_ia_trigger', 'init_cfg_ia', 'is_mode', 'bias_sleep', 'acc_data_valid'):
            cell_name = 'analysis_' + port
            module['cells'][cell_name] = {
                'type': 'FDRE', 'parameters': {}, 'attributes': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': ['0'], 'Q': module['ports'][port]['bits']},
            }
            paths = connected_paths(module,
                root_filter=lambda name, cell, output: name == cell_name,
                sink_filter=sink)
            assert paths['graph_complete']
            input_paths[port] = paths
        if label == 'current':
            assert input_paths['send_ia_trigger']['longest_register_path_cells'] == 1
            assert input_paths['init_cfg_ia']['longest_register_path_cells'] == 1
            assert input_paths['bias_sleep']['longest_register_path_cells'] == 1
        report[label] = {
            'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
            'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
            'register_to_row_index': state_paths,
            'input_to_row_index': input_paths,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({label: {name: value['longest_register_path_cells']
                             for name, value in data['input_to_row_index'].items()}
                      for label, data in report.items()}))


if __name__ == '__main__':
    main()
