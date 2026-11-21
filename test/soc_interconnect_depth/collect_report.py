#!/usr/bin/env python3
"""记录互连完整接口验证，并分别测量内部寄存器路径及指定输入边界路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/soc_axi_interconnect.sv')
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def measure(folder, expected):
    metrics = read(folder / 'metrics.json')
    manifest = read(folder / 'manifest.json')
    actual = [value for path, value in manifest['sources_sha256'].items()
              if Path(path).name == SOURCE.name]
    if actual != [expected] or not metrics['paths']['graph_complete']:
        raise ValueError('映射源码或组合图检查失败：' + str(folder))
    module = read(folder / 'mapped.json')['modules']['soc_axi_interconnect']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    marker = '@input_boundary/m_ram_rvalid'
    # 此标记只确定遍历起点；报告将端口路径与实际内部寄存器路径分别记录。
    module['cells'][marker] = dict(type='FDRE',
        connections={'Q': module['ports']['m_ram_rvalid']['bits']},
        port_directions={'Q': 'output'},
        attributes={'fpga_register_origin': 'input m_ram_rvalid'})
    boundary = connected_paths(module, limit=1, group_limit=0,
        root_filter=lambda name, cell, port: name == marker,
        sink_filter=lambda name, cell, port:
            cell.get('attributes', {}).get('fpga_register_origin') == 'ram_rd_active_q')
    if not boundary['graph_complete'] or not boundary['register_to_register_paths']:
        raise ValueError('指定端口路径未完整测量')
    return {
        'resources': metrics['resources'], 'graph_complete': True,
        'longest_internal_register_path_cells': metrics['paths']['longest_register_path_cells'],
        'input_boundary_path': {
            'start': 'm_ram_rvalid', 'end': 'ram_rd_active_q',
            'combinational_cells': boundary['longest_register_path_cells'],
            'scope': '模块输入至内部寄存器',
            'path': boundary['register_to_register_paths'][0],
        },
        'manifest_sha256': digest(folder / 'manifest.json'),
        'mapped_sha256': digest(folder / 'mapped.json'),
        'metrics_sha256': digest(folder / 'metrics.json'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--four-state', type=Path, required=True)
    parser.add_argument('--reference-mapping', type=Path, required=True)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    formal = read(args.formal / 'summary.json')
    four = read(args.four_state / 'summary.json')
    if not formal['passed'] or not four['passed']:
        raise ValueError('接口验证未全部通过')
    if formal['source_sha256'] != four['source_sha256']:
        raise ValueError('形式证明和四态检查使用的源码不一致')
    if digest(args.source_root / SOURCE) != formal['source_sha256']['current']:
        raise ValueError('当前生产源码与验证结果不一致')
    report = dict(passed=True, formal=formal, four_state=four,
        mapping={label: measure(folder, formal['source_sha256'][label]) for label, folder in
                 [('reference', args.reference_mapping), ('current', args.mapping)]},
        public_cycles_changed=False, physical_timing_150mhz_confirmed=None,
        collector_sha256=digest(Path(__file__)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_profiles': len(formal['runs']),
                     'equivalent_bits': formal['equivalent_bits'], 'four_state_cycles': four['cycles']}))


if __name__ == '__main__':
    main()
