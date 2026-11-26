#!/usr/bin/env python3
"""在实际映射网表中测量指定输入到输出或内部存储端口的组合单元数。"""
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
    parser.add_argument('--inputs', nargs='+', required=True)
    parser.add_argument('--outputs', nargs='*', default=[])
    parser.add_argument('--sink-contains', default='')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    modules = json.loads(args.mapped.read_text())['modules']
    module = max(modules.values(), key=lambda item: len(item.get('cells', {})))
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    spare = max(bit for net in module['netnames'].values()
                for bit in net['bits'] if isinstance(bit, int)) + 1
    # 分析节点只标记模块边界，不参与综合，也不计入组合单元数量。
    for direction, ports in (('input', args.inputs), ('output', args.outputs)):
        for port in ports:
            for index, bit in enumerate(module['ports'][port]['bits']):
                name = f'analysis_{direction}_{port}_{index}'
                module['cells'][name] = dict(type='FDRE', parameters={}, attributes={},
                    port_directions={'D': 'input', 'Q': 'output'},
                    connections={'D': [spare if direction == 'input' else bit],
                                 'Q': [bit if direction == 'input' else spare]})
                spare += 1
    report = dict(mapped_sha256=hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
                  pre_lut_sha256=hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
                  paths={})
    for port in args.inputs:
        root = lambda name, cell, pin: name.startswith('analysis_input_' + port + '_')
        sink = (lambda name, cell, pin: name.startswith('analysis_output_')) if args.outputs else None
        if args.sink_contains:
            sink = lambda name, cell, pin: args.sink_contains in name
        paths = connected_paths(module, limit=3, group_limit=6, root_filter=root, sink_filter=sink)
        assert paths['graph_complete']
        report['paths'][port] = paths
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({port: data['longest_register_path_cells']
                      for port, data in report['paths'].items()}))


if __name__ == '__main__':
    main()
