#!/usr/bin/env python3
"""统计候选字段寄存器至加载器内部寄存器和公开输出的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

OUTPUTS = ('prefetch_idle', 'load_weight_req', 'ext_dma_start',
           'ext_dma_burst_len_m1', 'ext_dma_base_addr')


def measure(folder):
    mapped = folder/'mapped.json'
    pre_lut = folder/'pre_lut.il'
    module = json.loads(mapped.read_text())['modules']['kernel_loader']
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    next_bit = max(b for n in module['netnames'].values() for b in n['bits'] if isinstance(b, int))+1
    for output in OUTPUTS:
        name = 'analysis_output_'+output
        module['cells'][name] = {
            'type': 'FDRE', 'attributes': {}, 'parameters': {},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': module['ports'][output]['bits'], 'Q': [next_bit]},
        }
        next_bit += 1

    def source_selected(name, cell, port):
        origin = cell.get('attributes', {}).get('fpga_register_origin', '')
        return origin.rsplit(' [', 1)[0] == 'candidate_fields_q'

    def paths(source, sink):
        result = connected_paths(module, limit=1, group_limit=0,
                                 root_filter=source, sink_filter=sink)
        if not result['graph_complete']:
            raise RuntimeError('Mapped connectivity graph is incomplete')
        selected = result['register_to_register_paths']
        return {'longest_path_cells': selected[0]['combinational_cells'] if selected else None,
                'longest_path': selected[0] if selected else None}

    result = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
              'candidate_to_outputs': {}, 'all_registers_to_outputs': {}}
    for output in OUTPUTS:
        sink = lambda name, cell, port: name == 'analysis_output_'+output
        result['candidate_to_outputs'][output] = paths(source_selected, sink)
        result['all_registers_to_outputs'][output] = paths(None, sink)
    result['candidate_to_registers'] = paths(
        source_selected, lambda name, cell, port: not name.startswith('analysis_output_'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {name: measure(args.synthesis/('loader_'+name)) for name in ('reference', 'current')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({n: {group: {port: path['longest_path_cells'] for port, path in d[group].items()}
                         for group in ('candidate_to_outputs', 'all_registers_to_outputs')}
                      for n, d in report.items()}))


if __name__ == '__main__':
    main()
