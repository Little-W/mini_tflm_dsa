#!/usr/bin/env python3
"""验证寄存 LUT 配对的实际布局、布线、初值、控制与输出选择。"""
from __future__ import annotations

import argparse
import itertools
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from placed_resources import placed_resources
from check_json_init import module, names


def design(kind, same_enable=True):
    reset_port = {'FDRE': 'R', 'FDSE': 'S', 'FDCE': 'CLR', 'FDPE': 'PRE'}[kind]
    second_enable = 'i_data[5]' if same_enable else 'i_data[4]'
    return f'''module soc_top (
    input wire clk,
    input wire [6:0] i_data,
    output wire [1:0] o_data
);
    wire [1:0] captured_data;
    (* keep = 1 *) LUT3 #(.INIT(8'h96)) u_upper (
        .I0(i_data[0]), .I1(i_data[1]), .I2(i_data[2]), .O(captured_data[0])
    );
    (* keep = 1 *) LUT3 #(.INIT(8'he8)) u_lower (
        .I0(i_data[2]), .I1(i_data[3]), .I2(i_data[4]), .O(captured_data[1])
    );
    {kind} #(.INIT(1'b0)) u_upper_ff (
        .C(clk), .CE(i_data[5]), .{reset_port}(i_data[6]),
        .D(captured_data[0]), .Q(o_data[0])
    );
    {kind} #(.INIT(1'b1)) u_lower_ff (
        .C(clk), .CE({second_enable}), .{reset_port}(i_data[6]),
        .D(captured_data[1]), .Q(o_data[1])
    );
endmodule
'''


def check_registers(packed, routed, pairing, fasm, tilegrid):
    old, new = module(packed), module(routed)
    old_names, new_names = names(old), names(new)
    grid = json.loads(tilegrid.read_text())
    site_tiles = {site: (tile, kind) for tile, data in grid.items() for site, kind in data['sites'].items()}
    features = {line.strip() for line in fasm.read_text().splitlines() if line.strip() and not line.startswith('#')}
    routes = {data['bits'][0]: data.get('attributes', {}).get('ROUTING', '')
              for data in new['netnames'].values() if len(data['bits']) == 1}
    checked, comparisons = [], 0
    for name, current in new['cells'].items():
        if current['type'] != 'SLICE_FFX':
            continue
        reference = old['cells'][name]
        assert current['parameters'] == reference['parameters'], name
        kind = current['attributes']['X_ORIG_TYPE']
        assert kind == reference['attributes']['X_ORIG_TYPE'], name
        for port in ('D', 'Q', 'CK', 'CE', 'SR'):
            a, b = reference['connections'].get(port, []), current['connections'].get(port, [])
            assert len(a) == len(b), (name, port)
            for old_bit, new_bit in zip(a, b):
                assert old_names[old_bit] & new_names[new_bit], (name, port)
        site, bel = current['attributes']['NEXTPNR_BEL'].split('/')
        tile, site_kind = site_tiles[site]
        x = int(re.search(r'_X([0-9]+)Y', site).group(1))
        prefix = f'{tile}.{site_kind}_X{x % 2}'
        physical_initial = int(prefix + '.' + bel + '.ZINI' not in features)
        physical_reset = int(prefix + '.' + bel + '.ZRST' not in features)
        physical_sync = prefix + '.FFSYNC' in features
        initial = int(current['parameters']['INIT'], 2)
        assert physical_initial == initial
        assert physical_reset == int(kind in ('FDSE', 'FDPE'))
        assert physical_sync == (kind in ('FDRE', 'FDSE'))
        assert prefix + '.NOCLKINV' in features and prefix + '.CLKINV' not in features
        assert prefix + '.CEUSEDMUX' in features and prefix + '.SRUSEDMUX' in features
        for previous, data, enable, reset, edge in itertools.product((0, 1), repeat=5):
            expected = previous
            if kind in ('FDCE', 'FDPE') and reset:
                expected = int(kind == 'FDPE')
            elif edge:
                if reset:
                    expected = int(kind == 'FDSE')
                elif enable:
                    expected = data
            actual = previous
            if reset and (edge or not physical_sync):
                actual = physical_reset
            elif edge and enable:
                actual = data
            assert actual == expected, (name, previous, data, enable, reset, edge)
            comparisons += 1
        checked.append({'cell': name, 'bel': current['attributes']['NEXTPNR_BEL'],
                        'initial': initial, 'reset_value': physical_reset, 'synchronous_reset': physical_sync})
    for pair in pairing['pairs']:
        upper = new['cells'][pair['upper']]['attributes']['NEXTPNR_BEL']
        lower = new['cells'][pair['lower']]['attributes']['NEXTPNR_BEL']
        upper_ff = new['cells'][pair['upper_register']]['attributes']['NEXTPNR_BEL']
        lower_ff = new['cells'][pair['lower_register']]['attributes']['NEXTPNR_BEL']
        assert upper.endswith('6LUT') and lower == upper[:-4] + '5LUT'
        assert upper_ff == upper[:-4] + 'FF' and lower_ff == upper[:-4] + '5FF'
        site, bel = lower_ff.split('/')
        letter = bel[0]
        q_net = new['cells'][pair['lower_register']]['connections']['Q'][0]
        selected = [part for part in routes[q_net].split(';') if part.startswith(f'SITEPIP/{site}/{letter}OUTMUX/')]
        assert selected == [f'SITEPIP/{site}/{letter}OUTMUX/{letter}5FF_Q'], selected
        tile, site_kind = site_tiles[site]
        x = int(re.search(r'_X([0-9]+)Y', site).group(1))
        prefix = f'{tile}.{site_kind}_X{x % 2}.{letter}OUTMUX.'
        assert sorted(feature for feature in features if feature.startswith(prefix)) == [prefix + letter + '5Q']
    return {'passed': True, 'registers': checked, 'state_transition_comparisons': comparisons,
            'paired_register_outputs_checked': len(pairing['pairs'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--package-pins', type=Path, required=True)
    parser.add_argument('--tilegrid', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', default=['sync_reset', 'async_reset', 'sync_set', 'different_enable'])
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    environment = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1', XC7_CARRY_TRIM_TAIL='1')
    cases = {'sync_reset': ('FDRE', True), 'async_reset': ('FDCE', True),
             'sync_set': ('FDSE', True), 'different_enable': ('FDRE', False)}
    result = {'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
              'pairing_script_sha256': digest(scripts.parent / 'pair_registered_luts.py'), 'cases': {}}
    common = [str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()), '--freq', '150',
              '--seed', '1', '--strict-timing-graph', '--timing-allow-fail']
    for name in args.cases:
        kind, same_enable = cases[name]
        case = folder / name
        case.mkdir(exist_ok=True)
        source = case / 'design.sv'
        source.write_text(design(kind, same_enable))
        prepare = case / 'prepare.ys'
        prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                           'read_verilog -lib +/xilinx/cells_xtra.v\n'
                           f'read_verilog {source}\nhierarchy -check -top soc_top\n'
                           'clean\ncheck -assert\nblackbox =A:whitebox\n'
                           f'write_json {case}/mapped.json\n')
        run_command([sys.executable, str(scripts.parent / 'open_fpga_synth.py'), '--worker', str(prepare)],
                    case, '01_prepare', environment)
        run_command([sys.executable, str(scripts.parent / 'open_fpga_implementation.py'), '--mapped', str(case / 'mapped.json'),
                     '--nextpnr', str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()),
                     '--out', str(case / 'pack'), '--through', 'pack', '--soc-package-pins', str(args.package_pins.resolve()),
                     '--allow-timing-failure'], case, '02_pack', environment)
        packed, paired = case / 'pack/packed.json', case / 'paired.json'
        run_command([sys.executable, str(scripts.parent / 'pair_registered_luts.py'), '--packed', str(packed),
                     '--out', str(paired), '--report', str(case / 'pairing.json')], case, '03_pair', environment)
        pairing = json.loads((case / 'pairing.json').read_text())
        assert pairing['pair_count'] == int(same_enable) and pairing['cell_contents_preserved']
        records = {}
        for label, netlist in [('reference', packed), ('paired', paired)]:
            output = case / label
            output.mkdir(exist_ok=True)
            run_command(common + ['--json', str(netlist), '--no-pack', '--no-route', '--write', str(output / 'placed.json')],
                        output, '04_place', environment)
            resources = placed_resources(module(output / 'placed.json'))
            assert resources['placement_complete']
            assert resources['physical_lut_positions'] == (1 if label == 'paired' and same_enable else 2)
            run_command(common + ['--json', str(output / 'placed.json'), '--no-pack', '--no-place',
                        '--write', str(output / 'routed.json'), '--fasm', str(output / 'design.fasm')], output, '05_route', environment)
            run_command([sys.executable, str(scripts / 'check_json_init.py'), '--packed', str(packed),
                         '--physical', str(output / 'routed.json'), '--source', str(args.source.resolve()),
                         '--out', str(output / 'checks')], output, '06_check_init', environment)
            run_command([sys.executable, str(scripts / 'check_emitted_fasm.py'), '--physical', str(output / 'routed.json'),
                         '--fasm', str(output / 'design.fasm'), '--lut-init', str(output / 'checks/physical_lut_init.json'),
                         '--tilegrid', str(args.tilegrid.resolve()), '--out', str(output / 'fasm_checks.json')], output, '07_check_fasm', environment)
            checks = check_registers(packed, output / 'routed.json', pairing if label == 'paired' else {'pairs': []},
                                     output / 'design.fasm', args.tilegrid)
            records[label] = {'passed': True, 'placement_complete': True, 'routing_complete': True,
                              'physical_lut_positions': resources['physical_lut_positions'],
                              'lut_truth_checks': json.loads((output / 'checks/summary.json').read_text()),
                              'register_checks': checks, 'fasm_checks': json.loads((output / 'fasm_checks.json').read_text()),
                              'routed_sha256': digest(output / 'routed.json'), 'fasm_sha256': digest(output / 'design.fasm')}
        result['cases'][name] = {'passed': True, 'pairing': pairing, 'results': records}
        (folder / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'case': name, 'passed': True, 'pairs': pairing['pair_count']}), flush=True)


if __name__ == '__main__':
    main()
