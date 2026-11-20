#!/usr/bin/env python3
"""比较完整 DMA 的分段地址资源和实际寄存器间组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import analyze, connected_paths, register_origins


def measure(folder):
    mapped = folder / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['axi_linear_block_dma']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    result = analyze(module)
    if not result['paths']['graph_complete']:
        raise RuntimeError('完整 DMA 组合路径分析未完成')
    paths = {}
    for name, prefixes in (('read', ('rd_', 'm_axi_ar')), ('write', ('wr_', 'm_axi_aw', 'm_axi_w'))):
        measured = connected_paths(
            module, limit=3, group_limit=0,
            sink_filter=lambda cell_name, cell, port: cell.get('attributes', {}).get(
                'fpga_register_origin', '').startswith(prefixes))
        if not measured['graph_complete'] or not measured['register_to_register_paths']:
            raise RuntimeError('DMA 分段路径缺少实际寄存器终点：' + name)
        paths[name] = measured['register_to_register_paths']
    return {
        'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256((folder / 'source.sv').read_bytes()).hexdigest(),
        'resources': result['resources'],
        'graph_complete': result['paths']['graph_complete'],
        'longest_register_path_cells': result['paths']['longest_register_path_cells'],
        'longest_paths': result['paths']['register_to_register_paths'][:3],
        'segment_paths': paths,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {
        'analyzer_sha256': hashlib.sha256((ROOT / 'scripts/fpga/netlist_metrics.py').read_bytes()).hexdigest(),
        'reference': measure(args.reference),
        'current': measure(args.current),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: {'logic_lut': result[name]['resources']['logic_lut_cells'],
                            'path_cells': result[name]['longest_register_path_cells']}
                      for name in ('reference', 'current')}))


if __name__ == '__main__':
    main()
