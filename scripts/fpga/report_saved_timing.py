#!/usr/bin/env python3
"""读取已保存的布局结果，输出时序图遍历得到的路径分段。"""
from __future__ import annotations

import argparse
import fcntl
import gc
import json
import os
from pathlib import Path
import re

from open_fpga_implementation import chipdb_identity, run_command
from open_fpga_synth import digest
from netlist_metrics import register_origins


def parse_paths(text, cell_metadata):
    paths = []
    current = None
    for raw in text.splitlines():
        line = re.sub(r'^Info:\s*', '', raw)
        if line.startswith('Critical path report for '):
            current = {'description': line.removesuffix(':'), 'segments': []}
            paths.append(current)
            continue
        if current is None:
            continue
        match = re.fullmatch(r'([0-9.]+)\s+([0-9.]+)\s+(Source|Setup)\s+(.+)', line)
        if match:
            delay, total, kind, pin = match.groups()
            cell, port = pin.rsplit('.', 1)
            segment = {'kind': kind.lower(), 'delay_ns': float(delay), 'total_ns': float(total),
                       'cell': cell, 'port': port, **cell_metadata.get(cell, {})}
            current['segments'].append(segment)
            if kind == 'Source' and 'startpoint' not in current:
                current['startpoint'] = {'cell': cell, 'port': port, **cell_metadata.get(cell, {})}
            if kind == 'Setup':
                current['endpoint'] = {'cell': cell, 'port': port, **cell_metadata.get(cell, {})}
            continue
        match = re.fullmatch(r'([0-9.]+)\s+([0-9.]+)\s+Net (.+) budget ([^ ]+) ns (.+)', line)
        if match:
            delay, total, name, budget, locations = match.groups()
            current['segments'].append({'kind': 'net', 'delay_ns': float(delay), 'total_ns': float(total),
                                        'net': name, 'budget_ns': float(budget), 'locations': locations})
            continue
        if line.startswith('Sink '):
            cell, port = line[5:].rsplit('.', 1)
            endpoint = {'cell': cell, 'port': port, **cell_metadata.get(cell, {})}
            current['segments'][-1]['sink'] = endpoint
            current['endpoint'] = endpoint
            continue
        match = re.fullmatch(r'([0-9.]+) ns logic, ([0-9.]+) ns routing', line)
        if match:
            current['logic_delay_ns'], current['net_delay_ns'] = map(float, match.groups())
            current = None
    if not paths or any('logic_delay_ns' not in path for path in paths):
        raise RuntimeError('The selected binary did not emit complete path reports')
    unique = {}
    for path in paths:
        unique.setdefault(json.dumps(path, sort_keys=True), path)
    return list(unique.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, required=True)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--part', default='xc7a200tfbg484-3')
    parser.add_argument('--freq', type=float, default=150.0)
    parser.add_argument('--register-origins', type=Path, help='Saved pre_lut.il containing register Q names')
    parser.add_argument('--dsp-connections', action='store_true', help='Report long connections of combinational DSP data paths')
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    if args.freq <= 0:
        parser.error('--freq must be positive')
    design, binary, chipdb = args.design.resolve(), args.nextpnr.resolve(), args.chipdb.resolve()
    if chipdb_identity(chipdb)['device'] != args.part:
        parser.error('The device database does not match --part')
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    lock = args.lock_file.open('a') if args.lock_file else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    before = digest(design)
    data = json.loads(design.read_bytes())
    if len(data['modules']) != 1:
        parser.error('A saved implementation must contain one flattened module')
    module = next(iter(data['modules'].values()))
    step = module.get('attributes', {}).get('step')
    if step != 'place':
        parser.error('The input must be a completed placement design')
    metadata = {}
    origins = register_origins(args.register_origins) if args.register_origins else {}
    for name, cell in module['cells'].items():
        attributes = cell.get('attributes', {})
        metadata[name] = {'type': cell['type']}
        if name in origins:
            metadata[name]['register_origin'] = origins[name]
        if cell['type'] == 'DSP48E1_DSP48E1':
            metadata[name]['dsp_registers'] = {key: int(value, 2) if isinstance(value, str) and re.fullmatch('[01]+', value) else value
                                             for key, value in cell.get('parameters', {}).items() if key.endswith('REG')}
        for key in ('src', 'hdlname', 'X_ORIG_TYPE', 'NEXTPNR_BEL'):
            if key in attributes:
                metadata[name][key] = attributes[key]
    del module, data
    gc.collect()
    environment = dict(os.environ, NEXTPNR_REPORT_PATHS='1')
    if args.dsp_connections:
        environment['NEXTPNR_REPORT_DSP_NETS'] = '1'
    command = [str(binary), '--chipdb', str(chipdb), '--json', str(design),
               '--no-pack', '--no-place', '--no-route', '--freq', str(args.freq),
               '--strict-timing-graph', '--timing-allow-fail', '--report', str(folder / 'timing.json')]
    stage = run_command(command, folder, 'report_paths', environment)
    paths = parse_paths((folder / 'report_paths.log').read_text(), metadata)
    if digest(design) != before:
        raise RuntimeError('The saved implementation changed during path reporting')
    result = {'implementation_step': step, 'part': args.part, 'frequency_mhz_target': args.freq,
              'clock_period_ns': 1000 / args.freq, 'design_sha256': before,
              'nextpnr_binary_sha256': digest(binary), 'chipdb_sha256': digest(chipdb),
              'input_design_preserved': True, 'timing_model_complete': False,
              'timing_150mhz_confirmed': None,
              'net_delay_source': 'Placement distance estimates',
              'delay_decimal_places': 1, 'stage': stage, 'paths': paths}
    if args.register_origins:
        result['register_origins_sha256'] = digest(args.register_origins)
    if args.dsp_connections:
        dsp = json.loads((folder / 'timing.json').read_text()).get('combinational_dsp_connections')
        if dsp is None:
            raise RuntimeError('The selected binary did not emit DSP connection reports')
        for group in ('longest_connections', 'longest_per_dsp'):
            for connection in dsp[group]:
                for kind in ('driver', 'sink', 'dsp'):
                    if kind + '_cell' in connection:
                        connection[kind + '_metadata'] = metadata[connection[kind + '_cell']]
        result['combinational_dsp_connections'] = dsp
    (folder / 'paths.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(paths)} complete path reports from saved {step} design')
    if lock:
        lock.close()


if __name__ == '__main__':
    main()
