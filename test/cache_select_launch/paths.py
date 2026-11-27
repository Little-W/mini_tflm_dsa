#!/usr/bin/env python3
"""检查完整缓存或前端网表中的替换发送、预取有效位与退休路径。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def existing(path):
    return path if path.exists() else path.with_suffix(path.suffix + '.gz')


def read(path):
    path = existing(path)
    return gzip.open(path, 'rb').read() if path.suffix == '.gz' else path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    raw = read(args.mapped / 'mapped.json')
    modules = json.loads(raw)['modules']
    selected = [(name, value) for name, value in modules.items()
                if str(value.get('attributes', {}).get('top', '0')).lstrip('0') == '1']
    assert len(selected) == 1
    top, module = selected[0]
    for name, origin in register_origins(existing(args.source / 'pre_lut.il')).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    metrics = json.loads((args.mapped / 'metrics.json').read_text())
    full = connected_paths(module, limit=24, group_limit=80)
    assert full['graph_complete'] and not full['combinational_cycle_nodes']
    (out / 'complete_paths.json').write_text(json.dumps(full, indent=2) + '\n')
    high = max(bit for cell in module['cells'].values() for bits in cell['connections'].values()
               for bit in bits if isinstance(bit, int))
    def observe(signal, source):
        nonlocal high
        matches = [name for name in module['netnames'] if name == signal or name.endswith('.' + signal)]
        if not matches:
            return False
        # 信号名选择公开缓存层，避免同一端口的层次别名重复添加观察点。
        name = min(matches, key=len)
        bits = module['netnames'][name]['bits']; assert len(bits) == 1
        high += 1
        module['cells']['observe_' + signal] = dict(type='FDRE', parameters={},
            attributes={'fpga_register_origin': 'observe.' + signal},
            port_directions={'C':'input', 'CE':'input', 'R':'input', 'D':'input', 'Q':'output'},
            connections={'C':module['ports']['clk']['bits'], 'CE':['1'], 'R':['0'],
                         'D':[high] if source else bits, 'Q':bits if source else [high]})
        return True
    observe('req_fire', True)
    observed_sinks = [name for name in ('select_launch', 'select_prefetch_launch') if observe(name, False)]
    roots = ('observe.req_fire', 'u_request_index_register.shift_q', 'request_addr_q',
             'request_y_q', 'windowed_q', 'fg_state', 'select_addr')
    sinks = ('pf_retire_q', 'pf_hit_checked', 'select_stage_valid', 'select_decision_valid',
             'select_way', 'fill_state', 'fill_end', *(('observe.' + name) for name in observed_sinks))
    results = {}
    def matching(cell, token):
        name = cell.get('attributes', {}).get('fpga_register_origin', '')
        return bool(re.search(r'(?:^|\.)' + re.escape(token) + r'(?: |\[|$)', name))
    for start in roots:
        if not any(matching(cell, start) for cell in module['cells'].values()):
            continue
        for end in sinks:
            report = connected_paths(module, limit=2, group_limit=2,
                root_filter=lambda name, cell, port: matching(cell, start),
                sink_filter=lambda name, cell, port: port in ('D', 'CE') and matching(cell, end))
            assert report['graph_complete'] and not report['combinational_cycle_nodes']
            key = start + '_to_' + end
            results[key] = report['longest_register_path_cells']
            (out / (key + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    summary = dict(top=top, resources=metrics['resources'],
        longest_register_path_cells=full['longest_register_path_cells'],
        graph_complete=True, combinational_cycle_nodes=[], paths=results,
        mapped_sha256=hashlib.sha256(raw).hexdigest(),
        mapped_source_manifest=json.loads((args.source / 'manifest.json').read_text()))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(dict(top=top, longest_register_path_cells=full['longest_register_path_cells'],
                         logic_lut_cells=metrics['resources']['logic_lut_cells'], paths=results)))


if __name__ == '__main__':
    main()
