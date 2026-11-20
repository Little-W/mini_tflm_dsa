#!/usr/bin/env python3
"""统计完整加载器中授予输入至启动、预取空闲及寄存状态的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def measure(folder):
    mapped, pre_lut = folder/'mapped.json', folder/'pre_lut.il'
    module = json.loads(mapped.read_text())['modules']['kernel_loader']
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    next_bit = max(bit for net in module['netnames'].values() for bit in net['bits']
                   if isinstance(bit, int))+1

    # 输入和输出端口仅在路径分析中作为寄存边界，资源仍取原始综合网表。
    module['cells']['analysis_grant'] = {
        'type': 'FDRE', 'attributes': {}, 'parameters': {},
        'port_directions': {'D': 'input', 'Q': 'output'},
        'connections': {'D': ['0'], 'Q': module['ports']['load_weight_granted']['bits']}}
    for port in ('prefetch_idle', 'ext_dma_start'):
        module['cells']['analysis_'+port] = {
            'type': 'FDRE', 'attributes': {}, 'parameters': {},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': module['ports'][port]['bits'], 'Q': [next_bit]}}
        next_bit += 1

    report = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(), 'paths': {}}
    for port in ('prefetch_idle', 'ext_dma_start'):
        for source in ('grant', 'registers'):
            row = connected_paths(module, limit=1, group_limit=0,
                root_filter=lambda name, cell, output: name == 'analysis_grant' if source == 'grant'
                    else not name.startswith('analysis_'),
                sink_filter=lambda name, cell, input_port: name == 'analysis_'+port)
            assert row['graph_complete']
            report['paths'][source+'_to_'+port] = row
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {label: measure(args.synthesis/('loader_'+label)) for label in ('reference', 'current')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({label: {name: row['longest_register_path_cells']
                             for name, row in rows['paths'].items()} for label, rows in report.items()}))


if __name__ == '__main__':
    main()
