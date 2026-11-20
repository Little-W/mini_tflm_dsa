#!/usr/bin/env python3
"""比较加载器寄存器至调度器所见空闲信号的实际组合连接。"""
import argparse
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    helpers = runpy.run_path(str(ROOT / 'test/kernel_descriptor_timing/measure_paths.py'))
    measure = helpers['measure']
    measure.__globals__['OUTPUTS'] = ('prefetch_idle', 'load_weight_req', 'ext_dma_start', 'weight_data_valid')
    measure.__globals__['REGISTERS'] = ('prefetch_state', 'u_ctrl.load_repeat', 'comparison_match_q', 'comparison_valid_q')
    report = {'reference': measure(args.reference), 'current': measure(args.current)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({label: {group: {name: value['longest_path_cells'] for name, value in data[group].items()}
                             for group in ('outputs', 'register_groups')}
                      for label, data in report.items()}))


if __name__ == '__main__':
    main()
