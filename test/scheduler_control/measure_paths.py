#!/usr/bin/env python3
"""记录帧调度器实际映射后的候选控制与完整寄存器路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['ps_window_scheduler']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin

    def candidate_sources(name, cell, port):
        origin = cell.get('attributes', {}).get('fpga_register_origin', '')
        return origin.startswith(('opened ', 'cursor ', 'live '))

    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest()}
    for label, root in (('all_registers', None), ('candidate_sources', candidate_sources)):
        result = connected_paths(module, limit=10, group_limit=30, root_filter=root)
        if not result['graph_complete']:
            raise RuntimeError('Mapped connectivity graph is incomplete')
        report[label] = result
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({name: report[name]['longest_register_path_cells']
                      for name in ('all_registers', 'candidate_sources')}))


if __name__ == '__main__':
    main()
