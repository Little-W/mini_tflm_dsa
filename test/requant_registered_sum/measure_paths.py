#!/usr/bin/env python3
"""统计两个量化寄存加法阶段的输入、输出和使能组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, parameter, register_origins, resources


def stage_matches(name, cell, stage, candidate):
    if candidate:
        return (f'.u_{stage}_sum.g_dsp.u_dsp' in name or
                (stage == 'product' and '.u_product.g_dsp.u_add.u_dsp' in name))
    origin = cell.get('attributes', {}).get('fpga_register_origin', '')
    register = 'product_high_s2' if stage == 'product' else 'rounded_s10'
    return f'.{register} ' in origin


def measure(directory, candidate):
    source = directory / 'mapped.json'
    module = json.loads(source.read_text())['modules']['vec_requant']
    for name, origin in register_origins(directory / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    result = {'mapped_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'resources': resources(module['cells']), 'stages': {}}
    result['dsp_by_preg'] = {
        str(preg): sum(cell['type'] == 'DSP48E1' and parameter(cell, 'PREG') == preg
                      for cell in module['cells'].values()) for preg in (0, 1)}
    for stage in ('product', 'rounding'):
        selected = lambda name, cell, port: stage_matches(name, cell, stage, candidate)
        endpoints = {'A', 'B', 'C', 'PCIN', 'CARRYIN'} if candidate else {'D'}
        enables = {'CEP'} if candidate else {'CE'}
        paths = {
            'input': connected_paths(
                module, limit=1, group_limit=0,
                sink_filter=lambda name, cell, port: selected(name, cell, port) and port in endpoints),
            'output': connected_paths(
                module, limit=1, group_limit=0,
                root_filter=lambda name, cell, port: selected(name, cell, port) and port in {'P', 'Q'}),
            'enable': connected_paths(
                module, limit=1, group_limit=0,
                sink_filter=lambda name, cell, port: selected(name, cell, port) and port in enables),
        }
        result['stages'][stage] = {}
        for direction, analysis in paths.items():
            assert analysis['graph_complete'], analysis['unclassified_cell_types']
            records = analysis['register_to_register_paths']
            if not records and direction != 'enable':
                raise RuntimeError(f'No {stage} {direction} path in {directory}')
            result['stages'][stage][direction] = records[0] if records else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {
        'method': 'Connected register-to-register graph; DSP input paths end at the primitive input and output paths start at PREG. DSP internal and routing delay require device timing analysis.',
        'reference': measure(args.synthesis / 'reference', False),
        'registered_sums': measure(args.synthesis / 'registered_sums', True),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    for label in ('reference', 'registered_sums'):
        for stage, paths in result[label]['stages'].items():
            print(label, stage, {direction: path['combinational_cells'] if path else None
                                 for direction, path in paths.items()})


if __name__ == '__main__':
    main()
