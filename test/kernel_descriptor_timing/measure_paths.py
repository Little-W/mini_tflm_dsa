#!/usr/bin/env python3
"""统计权重加载器寄存器与描述符输出之间的实际组合连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

OUTPUTS = ('ext_dma_start', 'load_weight_req', 'ext_dma_p0', 'ext_dma_q0',
           'ext_dma_base_addr')
REGISTERS = ('u_ctrl.group_base_col', 'u_ctrl.load_col_in_group',
             'u_ctrl.col_addr_offset', 'p0_base_q')


def measure(folder):
    mapped = folder / 'mapped.json'
    pre_lut = folder / 'pre_lut.il'
    module = json.loads(mapped.read_text())['modules']['kernel_loader']
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    next_bit = max(bit for cell in module['cells'].values()
                   for bits in cell['connections'].values() for bit in bits
                   if isinstance(bit, int)) + 1
    for output in OUTPUTS:
        name = 'analysis_output_' + output
        assert name not in module['cells']
        # 分析终点只表示输出边界，不改变生产网表或组合单元数。
        module['cells'][name] = {
            'type': 'FDRE', 'attributes': {}, 'parameters': {},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': module['ports'][output]['bits'], 'Q': [next_bit]},
        }
        next_bit += 1

    def paths(root_filter, sink_filter):
        result = connected_paths(module, limit=1, group_limit=0,
                                 root_filter=root_filter, sink_filter=sink_filter)
        if not result['graph_complete']:
            raise RuntimeError('Mapped connectivity graph is incomplete')
        selected = result['register_to_register_paths']
        return {'connected': bool(selected),
                'longest_path_cells': selected[0]['combinational_cells'] if selected else None,
                'longest_path': selected[0] if selected else None}

    result = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
              'outputs': {}, 'register_groups': {}}
    for output in OUTPUTS:
        result['outputs'][output] = paths(None, lambda n, c, p: n == 'analysis_output_' + output)
    for register in REGISTERS:
        def source_selected(name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin') or ''
            return origin.rsplit(' [', 1)[0] == register
        result['register_groups'][register] = paths(
            source_selected, lambda n, c, p: not n.startswith('analysis_output_'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {name: measure(args.synthesis / ('loader_' + name)) for name in ('reference', 'current')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({label: {group: {name: value['longest_path_cells'] for name, value in data[group].items()}
                             for group in ('outputs', 'register_groups')}
                      for label, data in report.items()}))


if __name__ == '__main__':
    main()
