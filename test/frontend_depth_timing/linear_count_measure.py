#!/usr/bin/env python3
"""用相同设置测量线性 DMA 的计数资格及公开接口深度。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boundary_paths(folder):
    metrics = json.loads((folder / 'metrics.json').read_text())
    module = json.loads((folder / 'mapped.json').read_text())['modules']['axi_linear_block_dma']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    report = {'resources': metrics['resources'],
              'maximum_register_depth': metrics['paths']['longest_register_path_cells'],
              'outputs': {}}
    for port in ('rd_start_ready', 'rd_busy', 'rd_finish_beat', 'rd_done', 'rd_error',
                 'm_axi_rready', 'rd_raw_valid', 'm_axi_arvalid'):
        sink = '$output$' + port
        module['cells'][sink] = {
            'type': 'FDRE', 'connections': {'D': module['ports'][port]['bits']},
            'port_directions': {'D': 'input'}, 'attributes': {'fpga_register_origin': port}}
        paths = connected_paths(module, limit=1, group_limit=1,
                                sink_filter=lambda name, cell, pin: name == sink)
        del module['cells'][sink]
        report['outputs'][port] = {
            'cells': paths['longest_register_path_cells'],
            'path': next(iter(paths['register_to_register_paths']), None)}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    source = out / 'source'
    source.mkdir(parents=True, exist_ok=True)
    (source / 'include').mkdir(exist_ok=True)
    shutil.copytree(ROOT / 'rtl/common', source / 'rtl/common', dirs_exist_ok=True)
    parameters = {'SIZE': 64, 'BUS_WIDTH': 64, 'CACHE_BLOCKS': 64,
                  'READ_OUTSTANDING': 4, 'WRITE_OUTSTANDING': 4, 'RD_CONTEXT_DEPTH': 4}
    inputs, cases = {}, {}
    for label, original in (('reference', args.reference), ('candidate', args.candidate)):
        path = source / label / 'axi_linear_block_dma.sv'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original.read_bytes())
        inputs[label] = {'path': str(original.resolve()), 'sha256': digest(path)}
        cases[label] = {
            'top': 'axi_linear_block_dma', 'sources': [str(path.relative_to(source))],
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                       [f'-G{name}={value}' for name, value in parameters.items()],
            'parameters': parameters,
            'configuration': '线性 DMA，64 位总线，4 项读写事务和 4 项读描述符'}
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
               '--source-root', str(source), '--case-config', str(config),
               '--cases', *cases, '--out', str(out / 'synthesis'),
               '--max-register-path-cells', '14']
    if args.lock_file:
        command += ['--lock-file', str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)
    if any(digest(row['path']) != row['sha256'] for row in inputs.values()):
        raise RuntimeError('综合期间输入源码发生变化')
    details = {name: boundary_paths(out / 'synthesis' / name) for name in cases}
    summary = json.loads((out / 'synthesis/summary.json').read_text())
    report = {'inputs': inputs, 'parameters': parameters, 'tool': summary['tool'],
              'part': summary['part'], 'family': summary['family'],
              'method': 'synth_xilinx -top axi_linear_block_dma -family xc7 -noiopad -noclkbuf -flatten',
              'scope': 'Independent linear DMA; output depth starts at internal clocked storage and excludes external logic',
              'cases': {name: {'resources': row['resources'],
                               'maximum_register_depth': row['maximum_register_depth'],
                               'outputs': {port: value['cells'] for port, value in row['outputs'].items()}}
                        for name, row in details.items()}}
    (out / 'boundary_paths.json').write_text(json.dumps(details, indent=2) + '\n')
    (out / 'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out / 'measurement.json')


if __name__ == '__main__':
    main()
