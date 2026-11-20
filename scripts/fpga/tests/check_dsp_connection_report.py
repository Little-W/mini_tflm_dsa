#!/usr/bin/env python3
"""从布局网表和器件坐标独立检查组合 DSP 连接报告。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re


DATA_REGISTERS = ('AREG', 'BREG', 'CREG', 'DREG', 'ADREG', 'MREG', 'PREG', 'ACASCREG', 'BCASCREG')
CONTROL_REGISTERS = ('INMODEREG', 'OPMODEREG', 'ALUMODEREG', 'CARRYINREG', 'CARRYINSELREG')
INPUT_PORTS = {'A', 'ACIN', 'INMODE', 'D', 'B', 'BCIN', 'OPMODE', 'ALUMODE', 'CARRYINSEL',
               'C', 'MULTSIGNIN', 'PCIN', 'CARRYIN', 'CARRYCASCIN'}
OUTPUT_PORTS = {'P', 'PCOUT', 'CARRYOUT', 'CARRYCASCOUT', 'MULTSIGNOUT', 'PATTERNDETECT',
                'PATTERNBDETECT', 'OVERFLOW', 'UNDERFLOW', 'ACOUT', 'BCOUT'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parameter(value):
    return int(value.strip(), 2) if isinstance(value, str) else int(value)


def base_port(port):
    return re.sub(r'(?:\[\d+\]|\d+)$', '', port)


def check(design, report, tilegrid):
    with design.open() as stream:
        module = next(iter(json.load(stream)['modules'].values()))
    with report.open() as stream:
        result = json.load(stream)
    with tilegrid.open() as stream:
        grid = json.load(stream)
    cells = module['cells']
    assert module['attributes']['step'] == 'place'
    assert result['design_sha256'] == digest(design)
    assert result['input_design_preserved']
    summary = result['combinational_dsp_connections']
    coords = {site: (value['grid_x'], value['grid_y'])
              for value in grid.values() for site in value.get('sites', {})}
    dsp = {name for name, cell in cells.items() if cell['type'] == 'DSP48E1_DSP48E1'
           and not any(parameter(cell['parameters'].get(key, 0)) for key in DATA_REGISTERS)}
    assert len(dsp) == summary['data_path_combinational_dsp_cells']
    control_registered = sorted(name for name in dsp if any(
        parameter(cells[name]['parameters'].get(key, 0)) for key in CONTROL_REGISTERS))
    drivers, users = {}, defaultdict(list)
    for name, cell in cells.items():
        for port, bits in cell['connections'].items():
            assert len(bits) <= 1, (name, port)
            if not bits or not isinstance(bits[0], int):
                continue
            bit = bits[0]
            direction = cell['port_directions'][port]
            if direction == 'output':
                assert bit not in drivers, (name, port)
                drivers[bit] = (name, port)
            elif direction == 'input':
                users[bit].append((name, port))
    arcs = {}
    per_dsp = defaultdict(float)
    same_tile_arcs = 0
    for bit, (driver, output) in drivers.items():
        dc = cells[driver]
        dbel = dc['attributes'].get('NEXTPNR_BEL')
        if not dbel or dc['type'] in ('PSEUDO_GND', 'PSEUDO_VCC'):
            continue
        driver_dsp = driver in dsp and base_port(output) in OUTPUT_PORTS
        for sink, port in users[bit]:
            sc = cells[sink]
            sbel = sc['attributes'].get('NEXTPNR_BEL')
            if not sbel:
                continue
            sink_dsp = sink in dsp and base_port(port) in INPUT_PORTS
            if not driver_dsp and not sink_dsp:
                continue
            a, b = coords[dbel.split('/')[0]], coords[sbel.split('/')[0]]
            if a == b:
                # 同一 tile 的局部估计不超过 0.7 ns；长连接排序独立检查只使用跨 tile 项。
                delay = None
                same_tile_arcs += 1
            else:
                dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
                delay = ((30 * min(dx, 18) + 10 * max(dx - 18, 0)
                          + 60 * min(dy, 6) + 20 * max(dy - 6, 0) + 300) * 3 // 2) / 1000
            key = (driver, output, sink, port)
            assert key not in arcs
            arcs[key] = (bit, delay)
            for member in {driver if driver_dsp else None, sink if sink_dsp else None} - {None}:
                per_dsp[member] = max(per_dsp[member], delay or 0.7)
    assert len(arcs) == summary['incident_connections']
    verified = 0
    for group in ('longest_connections', 'longest_per_dsp'):
        entries = summary[group]
        assert [x['delay_ns'] for x in entries] == sorted((x['delay_ns'] for x in entries), reverse=True)
        for item in entries:
            key = tuple(item[x] for x in ('driver_cell', 'driver_port', 'sink_cell', 'sink_port'))
            bit, delay = arcs[key]
            assert module['netnames'][item['net']]['bits'] == [bit]
            assert cells[item['driver_cell']]['attributes']['NEXTPNR_BEL'] == item['driver_bel']
            assert cells[item['sink_cell']]['attributes']['NEXTPNR_BEL'] == item['sink_bel']
            assert delay is not None and abs(delay - item['delay_ns']) < 1e-9
            if group == 'longest_per_dsp':
                assert item['dsp_cell'] in dsp
                assert item['dsp_cell'] in (item['driver_cell'], item['sink_cell'])
                assert per_dsp[item['dsp_cell']] == delay
            verified += 1
    top = summary['longest_connections']
    if top:
        expected = sorted((delay for _, delay in arcs.values() if delay is not None), reverse=True)[:20]
        assert len(top) == min(20, len(arcs))
        assert [x['delay_ns'] for x in top] == expected
        assert not same_tile_arcs or expected[-1] > 0.7
    separate = summary['longest_per_dsp']
    assert len({x['dsp_cell'] for x in separate}) == len(separate)
    assert [x['delay_ns'] for x in separate] == sorted(per_dsp.values(), reverse=True)[:10]
    return {'passed': True, 'design_sha256': digest(design), 'report_sha256': digest(report),
            'tilegrid_sha256': digest(tilegrid), 'data_path_combinational_dsp_cells': len(dsp),
            'data_path_combinational_dsp_with_registered_controls': control_registered,
            'incident_connections': len(arcs), 'same_tile_connections': same_tile_arcs,
            'checked_report_entries': verified, 'all_reported_connections_match_netlist': True,
            'longest_cross_tile_delays_match_device_coordinates': True,
            'top_connection_and_distinct_dsp_order_verified': True,
            'net_delay_source': 'Placement distance estimates'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--tilegrid', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = check(args.design, args.report, args.tilegrid)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
