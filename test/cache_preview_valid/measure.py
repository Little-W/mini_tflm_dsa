#!/usr/bin/env python3
"""统计完整缓存的连接路径，并单独检查预读输入到真实存储边界。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    helper = runpy.run_path(str(ROOT / 'test/conv_frontend/tools/measure_complete_paths.py'))

    def saved_path(name):
        path = args.synthesis / name
        return path if path.exists() else Path(str(path) + '.gz')

    mapped, pre = saved_path('mapped.json'), saved_path('pre_lut.il')
    data = helper['read_input'](mapped)
    module = json.loads(data)['modules']['conv_read_cache']
    for name, origin in register_origins(pre, top='conv_read_cache').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    report = helper['measure'](module, path_limit=30)
    observed, _ = helper['add_interface_boundaries'](module)
    scopes = {}
    for label, source, valid_only in (
        ('preview_index_to_storage', 'preview_index[', False),
        ('preview_address_to_storage', 'preview_addr[', False),
        ('preview_index_to_valid', 'preview_index[', True),
        ('preview_address_to_valid', 'preview_addr[', True),
        ('all_input_to_valid', 'interface ', True),
    ):
        starts, ends = set(), set()

        def select_root(name, cell, port):
            matched = source in cell.get('attributes', {}).get('fpga_register_origin', '')
            if matched:
                starts.add((name, port))
            return matched

        def select_sink(name, cell, port):
            attrs = cell.get('attributes', {})
            matched = attrs.get('measurement_boundary') is None
            if valid_only:
                matched &= port == 'D' and 'lookup_forwarded_valid_q' in attrs.get('fpga_register_origin', '')
            if matched:
                ends.add((name, port))
            return matched

        paths = connected_paths(observed, limit=10, group_limit=10,
                                root_filter=select_root, sink_filter=select_sink)
        assert paths['graph_complete']
        available = bool(starts and ends and paths['register_to_register_paths'])
        scopes[label] = {
            'selected_start_ports': len(starts),
            'selected_endpoint_ports': len(ends),
            'scope_available': available,
            'maximum_combinational_cells': paths['longest_register_path_cells'] if available else None,
            'paths': paths['register_to_register_paths'],
            'endpoint_depth_histogram': paths['endpoint_port_maximum_depth_histogram'],
            'graph_complete': paths['graph_complete'],
        }
    report['critical_scopes'] = scopes
    report['mapped_sha256'] = hashlib.sha256(data).hexdigest()
    report['pre_lut_sha256'] = hashlib.sha256(helper['read_input'](pre)).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({
        'resources': report['resources'],
        'groups': {key: value['maximum_combinational_cells'] for key, value in report['path_groups'].items()},
        'scopes': {key: value['maximum_combinational_cells'] for key, value in scopes.items()},
    }))


if __name__ == '__main__':
    main()
