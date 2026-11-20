#!/usr/bin/env python3
"""比较完整 DMA 的寄存状态至读取完成输出的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def measure(folder):
    mapped = folder / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['axi_linear_block_dma']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    boundary = 'analysis_finish_output'
    if boundary in module['cells']:
        raise RuntimeError('Output analysis boundary already exists')
    # 读取副本只增加零组合深度的分析终点，实际综合网表保持原样。
    module['cells'][boundary] = {
        'type': 'FDRE', 'parameters': {},
        'connections': {'D': module['ports']['rd_finish_beat']['bits'], 'Q': ['0'],
                        'C': ['0'], 'CE': ['1'], 'R': ['0']},
        'port_directions': {'D': 'input', 'Q': 'output', 'C': 'input', 'CE': 'input', 'R': 'input'},
        'attributes': {'fpga_register_origin': 'rd_finish_beat output boundary'},
    }
    paths = connected_paths(module, limit=1, group_limit=0,
                            sink_filter=lambda name, cell, port: name == boundary)
    if not paths['graph_complete'] or not paths['register_to_register_paths']:
        raise RuntimeError('Mapped DMA path graph is incomplete')
    return {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
            'graph_complete': paths['graph_complete'],
            'path': paths['register_to_register_paths'][0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {'method': 'Clocked storage outputs to rd_finish_beat; the analysis endpoint adds zero cells',
              'reference': measure(args.reference), 'current': measure(args.current)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: result[name]['path']['combinational_cells'] for name in ('reference', 'current')}))


if __name__ == '__main__':
    main()
