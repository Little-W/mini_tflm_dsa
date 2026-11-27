#!/usr/bin/env python3
"""在完整向量引擎连接图中统计读取模式到地址分量与地址输出的组合级数。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-root', type=Path, required=True)
    args = parser.parse_args()
    folder = args.mapping_root.resolve()
    summary = {}
    for label in ('reference', 'candidate'):
        source = folder/label
        mapped = folder/(label+'_cost')
        module = json.loads((mapped/'mapped.json').read_text())['modules']['vector_engine']
        for name, origin in register_origins(source/'pre_lut.il').items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        observed = copy.deepcopy(module)
        highest = max(bit for cell in module['cells'].values()
                      for bits in cell['connections'].values() for bit in bits if isinstance(bit, int))
        clock = module['ports']['clk']['bits'][0]
        interfaces = {
            'base': module['netnames']['u_address.read_address_base']['bits'],
            'offset': module['netnames']['u_address.read_address_offset']['bits'],
            'channel': module['netnames']['u_address.read_address_channel']['bits'],
            'address': module['ports']['rd_base_addr']['bits'],
        }
        # 采样终点只用于路径分析，资源数量取自原始映射网表。
        for interface, bits in interfaces.items():
            for index, bit in enumerate(bits):
                highest += 1
                observed['cells'][f'capture_{interface}_{index}'] = {
                    'type': 'FDRE', 'parameters': {},
                    'attributes': {'fpga_register_origin': f'{interface} [{index}]'},
                    'port_directions': {'C':'input', 'CE':'input', 'R':'input', 'D':'input', 'Q':'output'},
                    'connections': {'C':[clock], 'CE':['1'], 'R':['0'], 'D':[bit], 'Q':[highest]}}
        results = {}
        for origin in ('pool', 'soft_lut'):
            def starts(name, cell, port):
                return cell.get('attributes', {}).get('fpga_register_origin', '') == 'u_control.state_'+origin+'_read'
            for target in ('components', 'address'):
                def ends(name, cell, port):
                    prefix = 'capture_address_' if target == 'address' else ('capture_base_', 'capture_offset_', 'capture_channel_')
                    return port == 'D' and name.startswith(prefix)
                report = connected_paths(observed, limit=12, group_limit=12,
                                         root_filter=starts, sink_filter=ends)
                assert report['graph_complete'] and not report['combinational_cycle_nodes']
                assert report['longest_register_path_cells'] > 0
                name = origin+'_to_'+target
                (mapped/(name+'.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
                results[name] = report['longest_register_path_cells']
        metrics = json.loads((mapped/'metrics.json').read_text())
        results['resources'] = metrics['resources']
        results['longest_engine_register_path_cells'] = metrics['paths']['longest_register_path_cells']
        results['graph_complete'] = metrics['paths']['graph_complete']
        results['mapped_sha256'] = hashlib.sha256((mapped/'mapped.json').read_bytes()).hexdigest()
        results['source_sha256'] = json.loads((source/'manifest.json').read_text())['sources_sha256']
        summary[label] = results
        print(label, json.dumps({key:value for key,value in results.items() if key.endswith('components') or key.endswith('address')}, ensure_ascii=False))
    (folder/'selection_paths.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
