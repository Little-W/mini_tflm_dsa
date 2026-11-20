#!/usr/bin/env python3
"""统计行地址低位到 DMA 完成输出端口的实际组合连接。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def measure(folder):
    module = json.loads((folder/'mapped.json').read_text())['modules']['axi_linear_block_dma']
    for name, origin in register_origins(folder/'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    # 分析副本以零组合深度的端点表示输出边界，生产网表保持原样。
    endpoint = 'analysis_output_boundary'
    assert endpoint not in module['cells']
    module['cells'][endpoint] = {
        'type': 'FDRE',
        'connections': {'D': module['ports']['rd_finish_beat']['bits'], 'Q': ['0'],
                        'C': ['0'], 'CE': ['1'], 'R': ['0']},
        'port_directions': {'D': 'input', 'Q': 'output', 'C': 'input', 'CE': 'input', 'R': 'input'},
        'parameters': {}, 'attributes': {'fpga_register_origin': 'rd_finish_beat output boundary'}}
    starts = {f'rd_rsp_row_addr_cur [{bit}]' for bit in range(3)}
    result = connected_paths(
        module, limit=1, group_limit=0,
        root_filter=lambda name, cell, port: cell.get('attributes', {}).get('fpga_register_origin') in starts,
        sink_filter=lambda name, cell, port: name == endpoint)
    assert result['graph_complete'] and result['register_to_register_paths']
    path = result['register_to_register_paths'][0]
    return {'method': 'Production BUS64 netlist; row-address bits 0..2 to the combinational rd_finish_beat port. The analysis endpoint contributes no cells and is not part of the hardware.',
            'path': path}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {name: measure(args.synthesis/name) for name in ('reference', 'current')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print({name: item['path']['combinational_cells'] for name, item in report.items()})


if __name__ == '__main__':
    main()
