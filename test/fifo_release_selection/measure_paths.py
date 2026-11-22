#!/usr/bin/env python3
"""从已完成的 FIFO 映射结果提取合并尺寸到真实寄存器的完整组合路径。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys


def locate(folder, name):
    path = folder / name
    return path if path.exists() else path.with_name(path.name + '.gz')


def read_bytes(path):
    return gzip.open(path, 'rb').read() if path.suffix == '.gz' else path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.tool_root.resolve() / 'scripts/fpga'))
    from netlist_metrics import connected_paths, register_origins

    report = {'method': '仅在分析内存中把输入端口标记为起点；所有组合单元、连线和实际寄存器终点采用原映射网表。',
              'results': {}}
    for label, folder in (('reference', args.reference), ('current', args.current)):
        mapped = read_bytes(locate(folder, 'mapped.json'))
        module = json.loads(mapped)['modules']['vec_s8_to_fifo']
        for name, origin in register_origins(locate(folder, 'pre_lut.il')).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        for port in ('coalesce_cols', 'coalesce_rows'):
            for index, bit in enumerate(module['ports'][port]['bits']):
                if isinstance(bit, int):
                    module['cells'][f'analysis_{port}_{index}'] = {
                        'type': 'FDRE', 'parameters': {}, 'attributes': {'fpga_register_origin': port},
                        'connections': {'Q': [bit], 'D': ['0'], 'C': ['0'], 'CE': ['1'], 'R': ['0']},
                        'port_directions': {'Q': 'output', 'D': 'input', 'C': 'input', 'CE': 'input', 'R': 'input'}}
        groups = {}
        for source in ('coalesce_cols', 'coalesce_rows'):
            groups[source] = {}
            for endpoint in ('write_bank_blocked_q', 'next_write_bank_blocked_q', 'all_endpoints'):
                paths = connected_paths(module, limit=3, group_limit=3,
                    root_filter=lambda name, cell, port, source=source: name.startswith('analysis_' + source + '_'),
                    sink_filter=lambda name, cell, port, endpoint=endpoint:
                        not name.startswith('analysis_') and (endpoint == 'all_endpoints' or
                        cell.get('attributes', {}).get('fpga_register_origin', '').endswith('.' + endpoint)))
                if not paths['graph_complete'] or not paths['register_to_register_paths']:
                    raise RuntimeError('未得到完整的目标路径：' + label + '/' + source + '/' + endpoint)
                groups[source][endpoint] = paths
                print(label, source, endpoint, paths['longest_register_path_cells'], flush=True)
        metrics = json.loads(read_bytes(locate(folder, 'metrics.json')))
        report['results'][label] = {'resources': metrics['resources'],
            'internal_register_maximum_cells': metrics['paths']['longest_register_path_cells'],
            'mapped_sha256': hashlib.sha256(mapped).hexdigest(), 'port_paths': groups}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
