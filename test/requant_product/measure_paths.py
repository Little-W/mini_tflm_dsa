#!/usr/bin/env python3
"""统计量化乘法 DSP 的寄存配置、外部路径及专用级联连接。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, parameter, register_origins, resources


def multiplier(cell):
    return cell['type'] == 'DSP48E1' and cell['parameters'].get('USE_MULT') == 'MULTIPLY'


def sum_stage(name):
    return '.u_product_sum.g_dsp.u_dsp' in name or '.u_product.g_dsp.u_add.u_dsp' in name


def measure(folder, candidate):
    netlist = folder / 'mapped.json'
    module = json.loads(netlist.read_text())['modules']['vec_requant']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    dsp = {name: cell for name, cell in module['cells'].items() if cell['type'] == 'DSP48E1'}
    histogram = Counter((parameter(cell, 'AREG'), parameter(cell, 'BREG'), parameter(cell, 'PREG'))
                        for cell in dsp.values())
    result = {'mapped_sha256': hashlib.sha256(netlist.read_bytes()).hexdigest(),
              'resources': resources(module['cells']),
              'dsp_registers': [{'AREG': key[0], 'BREG': key[1], 'PREG': key[2], 'count': count}
                                for key, count in sorted(histogram.items())],
              'dsp_without_preg': sum(parameter(cell, 'PREG') == 0 for cell in dsp.values()),
              'paths': {}}
    analyses = {
        'multiply_input': connected_paths(
            module, limit=1, group_limit=0,
            sink_filter=lambda name, cell, port: multiplier(cell) and port in {'A', 'B'}),
        'product_output': connected_paths(
            module, limit=1, group_limit=0,
            root_filter=lambda name, cell, port: sum_stage(name) and port == 'P'),
        'rounding_output': connected_paths(
            module, limit=1, group_limit=0,
            root_filter=lambda name, cell, port: '.u_rounding_sum.g_dsp.u_dsp' in name and port == 'P'),
    }
    for name, analysis in analyses.items():
        assert analysis['graph_complete']
        result['paths'][name] = analysis['register_to_register_paths'][0]
    if candidate:
        cascades = []
        for name, cell in dsp.items():
            if not name.endswith('.u_product.g_dsp.u_add.u_dsp'):
                continue
            source = name.removesuffix('u_add.u_dsp') + 'g_partial[2].u_multiply.u_dsp'
            upstream = dsp[source]
            assert parameter(cell, 'PREG') == parameter(upstream, 'PREG') == 1
            assert cell['connections']['PCIN'] == upstream['connections']['PCOUT']
            cascades.append({'source': source, 'destination': name, 'direct_pcout_pcin': True})
        assert len(cascades) == 16
        result['registered_cascades'] = cascades
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {'method': 'External connected register paths; DSP internal arithmetic and device routing require timing analysis.',
              'reference': measure(args.synthesis / 'reference', False),
              'shared_product': measure(args.synthesis / 'shared_product', True)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    for label in ('reference', 'shared_product'):
        entry = result[label]
        print(label, entry['dsp_registers'],
              {name: path['combinational_cells'] for name, path in entry['paths'].items()})


if __name__ == '__main__':
    main()
