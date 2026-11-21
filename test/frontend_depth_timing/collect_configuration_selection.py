#!/usr/bin/env python3
"""核对前端配置表达式证明与局部映射，并保存固定寄存器端点的路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def measure(folder, kind, label, checked):
    name = kind + '_' + label
    manifest = read(folder / 'manifest.json')
    metrics = read(folder / 'metrics.json')
    if not metrics['paths']['graph_complete']:
        raise ValueError('映射图不完整：' + str(folder))
    for source in (name + '.sv', name + '_depth.sv'):
        actual = [value for path, value in manifest['sources_sha256'].items()
                  if Path(path).name == source]
        if actual != [checked['generated_source_sha256'][source]]:
            raise ValueError('映射表达式与证明源码不一致：' + source)
    report = dict(resources=metrics['resources'], graph_complete=True,
        longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
        manifest_sha256=digest(folder / 'manifest.json'),
        mapped_sha256=digest(folder / 'mapped.json'),
        metrics_sha256=digest(folder / 'metrics.json'))
    if kind == 'prefetch':
        module = read(folder / 'mapped.json')['modules'][name + '_depth']
        for cell_name, origin in register_origins(folder / 'pre_lut.il').items():
            if cell_name in module['cells']:
                module['cells'][cell_name].setdefault('attributes', {})['fpga_register_origin'] = origin
        # 输入寄存器的 33 至 48 位是 kernel_w；输出低 32 位是预读步长。
        roots = set(module['netnames']['input_q']['bits'][33:49])
        sinks = set(module['ports']['result']['bits'][:32])
        paths = connected_paths(module, limit=1, group_limit=0,
            root_filter=lambda name, cell, port:
                bool(set(cell.get('connections', {}).get('Q', [])) & roots),
            sink_filter=lambda name, cell, port:
                bool(set(cell.get('connections', {}).get('Q', [])) & sinks))
        if not paths['graph_complete'] or not paths['register_to_register_paths']:
            raise ValueError('固定端点路径未完整计算')
        report['kernel_width_to_prefetch_step'] = dict(
            combinational_cells=paths['longest_register_path_cells'],
            path=paths['register_to_register_paths'][0])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--validation', type=Path, required=True)
    for name in ('group-reference', 'group-current', 'prefetch-reference', 'prefetch-current'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    checked = read(args.validation / 'summary.json')
    source = args.source_root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    if not checked['passed'] or digest(source) != checked['source_sha256']['current']:
        raise ValueError('验证结果与当前前端源码不一致')
    mapping = {}
    for kind in ('group', 'prefetch'):
        mapping[kind] = {label: measure(getattr(args, kind + '_' + label), kind, label, checked)
                         for label in ('reference', 'current')}
    report = dict(passed=True, validation=checked, mapping=mapping,
        strict_four_state_checks=sum(row['strict_four_state_checks'] for row in checked['runs']),
        mapping_scope='实际组合表达式两端加入测试寄存器，完整结果位宽',
        public_cycles_changed=False, physical_timing_150mhz_confirmed=None,
        collector_sha256=digest(Path(__file__)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'profiles': len(checked['runs']),
                     'four_state_checks': report['strict_four_state_checks']}))


if __name__ == '__main__':
    main()
