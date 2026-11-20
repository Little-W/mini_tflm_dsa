#!/usr/bin/env python3
"""统计 IA 写入输入到实际外部 RAM 命令寄存器的逐位连接路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins, resources


def measure(mapped, pre_lut):
    module = json.loads(mapped.read_text())['modules']['ia_loader_cache_mgr']
    usage = resources(module['cells'])
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    complete = connected_paths(module, limit=2, group_limit=2)
    inputs = ('wr_data', 'wr_valid', 'wr_col_base', 'compact_offset', 'compact_mode')
    for name in inputs:
        for index, bit in enumerate(module['ports'][name]['bits']):
            module['cells'][f'analysis_input_{name}_{index}'] = {
                'type': 'FDRE', 'attributes': {}, 'parameters': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': ['0'], 'Q': [bit]},
            }
    queries = {}
    for name in inputs:
        for output in ('data', 'mask', 'en'):
            prefix = 'analysis_input_' + name + '_'
            destination = 'ram_port_wr_' + output
            bits = set(module['ports'][destination]['bits'])
            result = connected_paths(module, limit=2, group_limit=2,
                root_filter=lambda n, c, p, prefix=prefix: n.startswith(prefix),
                sink_filter=lambda n, c, p, bits=bits: bool(bits.intersection(c['connections'].get('Q', []))))
            if not result['graph_complete']:
                raise RuntimeError('IA input path graph is incomplete')
            queries[name + '_to_' + destination] = result
    if not complete['graph_complete']:
        raise RuntimeError('IA register path graph is incomplete')
    return dict(resources=usage, register_paths=complete, input_paths=queries,
        mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest(),
        pre_lut_sha256=hashlib.sha256(pre_lut.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--cost', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {}
    for mapping, folder in [('native', args.native)] + ([('physical_cost', args.cost)] if args.cost else []):
        result[mapping] = {}
        for label in ('reference', 'current'):
            data = measure(folder / label / 'mapped.json', args.native / label / 'pre_lut.il')
            result[mapping][label] = data
            print(json.dumps(dict(mapping=mapping, version=label,
                logic_luts=data['resources']['logic_lut_cells'],
                register_depth=data['register_paths']['longest_register_path_cells'],
                input_depths={key: value['longest_register_path_cells'] for key, value in data['input_paths'].items()})))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
