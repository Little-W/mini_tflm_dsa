#!/usr/bin/env python3
"""测量线性 DMA 返回数据边界与接收资格寄存器的实际组合深度。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def return_paths(folder):
    module = json.loads((folder / 'mapped.json').read_text())['modules']['axi_linear_block_dma']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin

    def origin(cell):
        return cell.get('attributes', {}).get('fpga_register_origin', '')

    def longest(paths):
        return {'cells': paths['longest_register_path_cells'],
                'path': next(iter(paths['register_to_register_paths']), None)}

    report = {'outputs': {}, 'qualification_to_data': {}, 'receive_qualification': {}}
    for port in ('wr_data', 'wr_valid', 'rd_raw_valid', 'rd_raw_col_base'):
        sink = '$output$' + port
        module['cells'][sink] = {
            'type': 'FDRE', 'connections': {'D': module['ports'][port]['bits']},
            'port_directions': {'D': 'input'}, 'attributes': {'fpga_register_origin': port}}
        report['outputs'][port] = longest(connected_paths(
            module, limit=1, group_limit=1,
            sink_filter=lambda name, cell, pin: name == sink))
        if port == 'wr_data':
            for state in ('rd_rsp_valid_cols', 'rd_rsp_lane_in_data_r'):
                report['qualification_to_data'][state] = longest(connected_paths(
                    module, limit=1, group_limit=1,
                    root_filter=lambda name, cell, pin: origin(cell).split(' ')[0] == state,
                    sink_filter=lambda name, cell, pin: name == sink))
        del module['cells'][sink]
    for pin in ('D', 'CE'):
        report['receive_qualification'][pin] = longest(connected_paths(
            module, limit=1, group_limit=1,
            sink_filter=lambda name, cell, port: port == pin and
                origin(cell).split(' ')[0] == 'rd_rsp_lane_in_data_r'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    command = [sys.executable, str(Path(__file__).with_name('linear_count_measure.py')),
               '--reference', str(args.reference), '--candidate', str(args.candidate),
               '--out', str(out)]
    if args.lock_file:
        command += ['--lock-file', str(args.lock_file)]
    subprocess.run(command, cwd=ROOT, check=True)
    details = {name: return_paths(out / 'synthesis' / name) for name in ('reference', 'candidate')}
    (out / 'return_paths.json').write_text(json.dumps(details, indent=2) + '\n')
    report_path = out / 'measurement.json'
    report = json.loads(report_path.read_text())
    for name, sections in details.items():
        report['cases'][name]['return_paths'] = {
            section: {signal: item['cells'] for signal, item in paths.items()}
            for section, paths in sections.items()}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(report_path)


if __name__ == '__main__':
    main()
