#!/usr/bin/env python3
"""统计完整 IA 模块及最终输出组标志到 DMA 请求的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['ia_loader']
    for name, saved in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = saved

    def path(source=None, sink=None):
        report = connected_paths(module, limit=1, group_limit=0,
                                 root_filter=source, sink_filter=sink)
        if not report['graph_complete']:
            raise RuntimeError('Mapped connectivity graph is incomplete')
        return {'longest_path_cells': report['longest_register_path_cells'],
                'longest_path': report['register_to_register_paths'][:1]}

    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'complete_module': path()}
    next_bit = max(bit for cell in module['cells'].values()
                   for bits in cell['connections'].values() for bit in bits if isinstance(bit, int)) + 1
    outputs = ('load_ia_req', 'ext_dma_start')
    for output in outputs:
        for index, bit in enumerate(module['ports'][output]['bits']):
            # 端点仅用于读取公开输出的组合路径，不加入综合资源统计。
            module['cells'][f'analysis_output_{output}_{index}'] = {
                'type': 'FDRE', 'attributes': {}, 'parameters': {},
                'port_directions': {'D': 'input', 'Q': 'output'},
                'connections': {'D': [bit], 'Q': [next_bit]},
            }
            next_bit += 1
    final_bits = set(module['ports']['ps_frame_final']['bits'])
    final_source = lambda name, cell, port: bool(final_bits.intersection(cell['connections'].get(port, [])))
    report['output_paths'] = {}
    report['frame_final_paths'] = {}
    for output in outputs:
        sink = lambda name, cell, port: name.startswith('analysis_output_' + output + '_')
        report['output_paths'][output] = path(sink=sink)
        report['frame_final_paths'][output] = path(final_source, sink)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'module_register_max': report['complete_module']['longest_path_cells'],
                      'outputs': {name: item['longest_path_cells']
                                  for name, item in report['output_paths'].items()},
                      'frame_final': {name: item['longest_path_cells']
                                      for name, item in report['frame_final_paths'].items()}}))


if __name__ == '__main__':
    main()
