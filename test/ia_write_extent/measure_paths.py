#!/usr/bin/env python3
"""统计 IA 有效位端口到写入范围存储的组合逻辑级数。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def read_json(path):
    if path.exists():
        return json.loads(path.read_text())
    with gzip.open(str(path)+'.gz', 'rt') as stream:
        return json.load(stream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--tool-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.tool_root/'scripts/fpga'))
    from netlist_metrics import connected_paths, register_origins
    report = {'scope': 'ext_dma_wr_valid input to slot_written_cols synchronous storage inputs',
              'upstream_modules_included': False, 'runs': {}}
    for label, directory in [('reference', args.reference), ('current', args.current)]:
        module = read_json(directory/'mapped.json')['modules']['ia_loader']
        source = directory/'pre_lut.il'
        if not source.exists():
            source = Path(str(source)+'.gz')
        for name, origin in register_origins(source).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        # 分析图使用专用起点表示输入端口，RTL 与实际综合网表均保持原样。
        for index, bit in enumerate(module['ports']['ext_dma_wr_valid']['bits']):
            module['cells'][f'analysis_input_{index}'] = {
                'type': 'FDRE', 'parameters': {},
                'attributes': {'fpga_register_origin': f'ext_dma_wr_valid[{index}]'},
                'port_directions': {'C': 'input', 'D': 'input', 'CE': 'input', 'R': 'input', 'Q': 'output'},
                'connections': {'C': ['0'], 'D': ['0'], 'CE': ['1'], 'R': ['0'], 'Q': [bit]}}
        metrics = read_json(directory/'metrics.json')
        entry = {'resources': metrics['resources'],
                 'register_path_requirement': metrics['register_path_requirement'], 'input_paths': {}}
        for target_port in ['DIADI', 'WEA']:
            entry['input_paths'][target_port] = connected_paths(
                module, limit=10, group_limit=10,
                root_filter=lambda name, cell, port: name.startswith('analysis_input_'),
                sink_filter=lambda name, cell, port: 'slot_written_cols' in name and port == target_port)
        entry['metrics_sha256'] = hashlib.sha256((directory/'metrics.json').read_bytes()).hexdigest()
        report['runs'][label] = entry
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    for label, entry in report['runs'].items():
        print(label, {port: paths['longest_register_path_cells'] for port, paths in entry['input_paths'].items()})


if __name__ == '__main__':
    main()
