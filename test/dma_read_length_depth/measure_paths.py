#!/usr/bin/env python3
"""在完整双通道 DMA 映射图中测量线性 DMA 寄存器路径及固定目标。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origin(cell):
    return cell.get('attributes', {}).get('fpga_register_origin', '')


def measure(folder):
    metrics = json.loads((folder / 'metrics.json').read_text())
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest['top'] != 'axi_dual_block_dma' or metrics['paths']['graph_complete'] is not True:
        raise RuntimeError('完整 DMA 类型或组合图覆盖不正确：' + str(folder))
    module = json.loads((folder / 'mapped.json').read_text())['modules'][manifest['top']]
    for name, value in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = value
    selections = dict(
        linear_state=('u_linear.', 'u_linear.'),
        follow_length=('u_linear.rd_follow_beats', 'u_linear.rd_arlen_r'),
        follow_address=('u_linear.rd_follow_beats', 'u_linear.rd_follow_addr'))
    paths = {}
    for label, (start, end) in selections.items():
        part = connected_paths(module, limit=1, group_limit=1,
            root_filter=lambda name, cell, port: origin(cell).startswith(start),
            sink_filter=lambda name, cell, port: origin(cell).startswith(end))
        if part['graph_complete'] is not True or not part['register_to_register_paths']:
            raise RuntimeError('寄存器目标路径未完整计算：' + label)
        paths[label] = part
    return dict(source_manifest=manifest, resources=metrics['resources'],
        whole_dma_register_paths=metrics['paths'], selected_register_paths=paths,
        report_sha256={name: digest(folder / name) for name in
            ('mapped.json', 'pre_lut.il', 'metrics.json', 'manifest.json')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-folder', type=Path, required=True)
    parser.add_argument('--current-folder', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    results = {label: measure(getattr(args, label + '_folder'))
               for label in ('reference', 'current')}
    first = results['reference']['source_manifest']
    second = results['current']['source_manifest']
    if first['parameters'] != second['parameters'] or first['options'] != second['options']:
        raise RuntimeError('两次完整模块测量参数不同')
    sources = set(first['sources_sha256']) | set(second['sources_sha256'])
    changes = [name for name in sources if first['sources_sha256'].get(name) !=
               second['sources_sha256'].get(name)]
    if changes != [SOURCE]:
        raise RuntimeError('两次完整模块测量存在其他源码变化：' + str(changes))
    results.update(scope='相同外围源码的完整双通道 DMA，固定寄存器起点和终点',
        runner_sha256=digest(Path(__file__)), physical_timing_confirmed=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    for label in ('reference', 'current'):
        part = results[label]
        print(label, {name: value['longest_register_path_cells'] for name, value in
                      part['selected_register_paths'].items()})


if __name__ == '__main__':
    main()
