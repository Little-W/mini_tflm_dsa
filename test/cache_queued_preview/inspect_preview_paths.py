#!/usr/bin/env python3
"""在完整缓存连接图中检查预读组号选择和前台状态的寄存器路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, mapped, out = args.source.resolve(), args.mapped.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    module = json.loads((mapped/'mapped.json').read_text())['modules']['conv_windowed_cache']
    for name, origin in register_origins(source/'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    highest = max(bit for cell in module['cells'].values()
                  for bits in cell['connections'].values() for bit in bits if isinstance(bit, int))
    # 此终点仅用于观察已有组合网络，资源数据来自未添加终点的原始映射。
    observed = {'preview_match':'u_request_path.g_queued_preview_active.preview_match',
                'select_request_set_match':'select_request_set_match'}
    for origin, name in observed.items():
        bits = module['netnames'][name]['bits']
        assert len(bits) == 1
        highest += 1
        module['cells']['capture_'+origin] = {
            'type':'FDRE', 'parameters':{}, 'attributes':{'fpga_register_origin':origin},
            'port_directions':{'C':'input','CE':'input','R':'input','D':'input','Q':'output'},
            'connections':{'C':module['ports']['clk']['bits'], 'CE':['1'], 'R':['0'],
                           'D':bits, 'Q':[highest]}}
    results = {}
    for start in ('windowed_q', 'fg_state'):
        for end in ('preview_match', 'select_request_set_match', 'pf_hit_checked', 'pf_retire_q'):
            def root_filter(name, cell, port):
                value = cell.get('attributes', {}).get('fpga_register_origin', '')
                return value == start or value.startswith(start+' [')
            def sink_filter(name, cell, port):
                return port == 'D' and cell.get('attributes', {}).get('fpga_register_origin') == end
            report = connected_paths(module, limit=4, group_limit=4,
                                     root_filter=root_filter, sink_filter=sink_filter)
            assert report['graph_complete'] and not report['combinational_cycle_nodes']
            label = start+'_to_'+end
            (out/(label+'.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            results[label] = report['longest_register_path_cells']
    metrics = json.loads((mapped/'metrics.json').read_text())
    results.update(resources=metrics['resources'],
                   longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
                   graph_complete=metrics['paths']['graph_complete'],
                   mapped_sha256=digest(mapped/'mapped.json'),
                   source_sha256=json.loads((source/'manifest.json').read_text())['sources_sha256'])
    (out/'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in results.items() if '_to_' in k}, ensure_ascii=False))


if __name__ == '__main__':
    main()
