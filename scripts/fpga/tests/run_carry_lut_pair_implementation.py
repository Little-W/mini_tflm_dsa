#!/usr/bin/env python3
"""检查 CARRY 输入 LUT 与独立逻辑共享位置后的布线、数值和配置。"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from placed_resources import placed_resources


DESIGN = """module soc_top (
    input wire clk,
    input wire [7:0] i_data,
    output wire [13:0] o_data
);
    wire [3:0] first_select;
    wire [3:0] first_sum;
    wire [3:0] first_carry;
    wire [3:0] second_sum;
    wire [3:0] second_carry;
    wire [3:0] independent_result;
    wire [3:0] captured_result;
    wire [13:0] capture_data;

    // 两级进位保留专用 CO3/CIN 连接，每个和位进入相同位置的寄存器。
    CARRY4 u_first (
        .DI(i_data[3:0]), .S(first_select), .CI(1'b0), .CYINIT(1'b0),
        .O(first_sum), .CO(first_carry)
    );
    CARRY4 u_second (
        .DI(i_data[3:0]), .S(i_data[7:4]), .CI(first_carry[3]), .CYINIT(1'b0),
        .O(second_sum), .CO(second_carry)
    );

    genvar bit_index;
    generate
        for (bit_index = 0; bit_index < 4; bit_index = bit_index + 1) begin : g_logic
            (* keep = 1 *) LUT2 #(.INIT(4'h6)) u_select (
                .I0(i_data[bit_index]), .I1(i_data[bit_index + 4]),
                .O(first_select[bit_index])
            );
            (* keep = 1 *) LUT3 #(.INIT(8'h96)) u_independent (
                .I0(i_data[bit_index]), .I1(i_data[(bit_index + 1) % 4]),
                .I2(i_data[bit_index + 4]), .O(independent_result[bit_index])
            );
            (* keep = 1 *) LUT2 #(.INIT(4'h6)) u_capture_logic (
                .I0(independent_result[bit_index]), .I1(i_data[7]),
                .O(captured_result[bit_index])
            );
        end
    endgenerate
    assign capture_data = {i_data[1:0], captured_result, second_sum, first_sum};

    generate
        for (bit_index = 0; bit_index < 14; bit_index = bit_index + 1) begin : g_capture
            FDRE #(.INIT(1'b0)) u_register (
                .C(clk), .CE(1'b1), .R(1'b0), .D(capture_data[bit_index]), .Q(o_data[bit_index])
            );
        end
    endgenerate
endmodule
"""


def check_shared_connections(module, pairing, fasm, tilegrid):
    grid = json.loads(tilegrid.read_text())
    sites = {site: (tile, kind) for tile, data in grid.items() for site, kind in data['sites'].items()}
    features = set(line.strip() for line in fasm.read_text().splitlines() if line.strip() and not line.startswith('#'))
    net_routes = {data['bits'][0]: data.get('attributes', {}).get('ROUTING', '')
                  for data in module['netnames'].values() if len(data['bits']) == 1}
    checked = []
    for pair in pairing['pairs']:
        upper = module['cells'][pair['upper']]['attributes']['NEXTPNR_BEL']
        lower = module['cells'][pair['lower']]['attributes']['NEXTPNR_BEL']
        assert upper.endswith('6LUT') and lower == upper[:-4] + '5LUT'
        carry = module['cells'][pair['carry']]
        assert int(carry['attributes'][f"X_CARRY_DI{pair['bit']}_VIA_X"], 2)
        site = carry['attributes']['NEXTPNR_BEL'].split('/')[0]
        letter = 'ABCD'[pair['bit']]
        assert upper == f'{site}/{letter}6LUT'
        bit = carry['connections'][f"DI{pair['bit']}"][0]
        selected = [part for part in net_routes[bit].split(';') if part.startswith(f'SITEPIP/{site}/{letter}CY0/')]
        assert selected == [f'SITEPIP/{site}/{letter}CY0/{letter}X'], (pair, selected)
        tile, kind = sites[site]
        site_x = int(re.search(r'_X([0-9]+)Y', site).group(1))
        prefix = f'{tile}.{kind}_X{site_x % 2}'
        # CY0 的默认选择为 X；O5 通过独立的 OUTMUX 输出。
        assert prefix + f'.CARRY4.{letter}CY0' not in features
        outmux = sorted(feature for feature in features if feature.startswith(prefix + f'.{letter}OUTMUX.'))
        assert outmux == [prefix + f'.{letter}OUTMUX.O5'], (pair, outmux)
        checked.append({'upper': pair['upper'], 'lower': pair['lower'], 'site': site, 'letter': letter,
                        'carry_di_source': letter + 'X', 'outmux_source': 'O5'})
    return {'passed': True, 'shared_connections': checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--package-pins', type=Path, required=True)
    parser.add_argument('--tilegrid', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    lock = args.lock_file.open('a') if args.lock_file else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    environment = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1', XC7_CARRY_TRIM_TAIL='1')
    design = folder / 'design.sv'
    design.write_text(DESIGN)
    prepare = folder / 'prepare.ys'
    prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                       'read_verilog -lib +/xilinx/cells_xtra.v\n'
                       f'read_verilog {design}\nhierarchy -check -top soc_top\n'
                       'clean\ncheck -assert\nblackbox =A:whitebox\n'
                       f'write_json {folder}/mapped.json\n')
    run_command([sys.executable, str(scripts.parent / 'open_fpga_synth.py'), '--worker', str(prepare)],
                folder, '01_prepare', environment)
    run_command([sys.executable, str(scripts.parent / 'open_fpga_implementation.py'), '--mapped', str(folder / 'mapped.json'),
                 '--nextpnr', str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()),
                 '--out', str(folder / 'pack'), '--through', 'pack', '--soc-package-pins',
                 str(args.package_pins.resolve()), '--allow-timing-failure'], folder, '02_pack', environment)
    packed = folder / 'pack/packed.json'
    paired = folder / 'paired.json'
    run_command([sys.executable, str(scripts.parent / 'pair_carry_luts.py'), '--packed', str(packed),
                 '--out', str(paired), '--report', str(folder / 'pairing.json')], folder, '03_pair', environment)
    pairing = json.loads((folder / 'pairing.json').read_text())
    assert pairing['pair_count'] == 4 and pairing['cell_contents_preserved'] and pairing['existing_constraints_preserved']
    summary = {'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
               'design_sha256': digest(design), 'mapped_sha256': digest(folder / 'mapped.json'),
               'pairing_script_sha256': digest(scripts.parent / 'pair_carry_luts.py'), 'pairing': pairing,
               'implementation_environment': {key: value for key, value in sorted(environment.items())
                                                if key.startswith(('XC7_', 'NEXTPNR_'))}, 'cases': {}}
    common = [str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()), '--freq', '150', '--seed', '1',
              '--strict-timing-graph', '--timing-allow-fail']
    for name, source in [('reference', packed), ('paired', paired), ('guided', folder / 'guided.json')]:
        case = folder / name
        case.mkdir(exist_ok=True)
        stages = {}
        case_pairing = pairing
        if name == 'guided':
            stages['pair'] = run_command([sys.executable, str(scripts.parent / 'pair_carry_luts.py'), '--packed', str(packed),
                '--placement-guide', str(folder / 'reference/placed.json'), '--maximum-site-distance', '8',
                '--out', str(source), '--report', str(folder / 'pairing_guided.json')], case, '03_pair', environment)
            case_pairing = json.loads((folder / 'pairing_guided.json').read_text())
            assert 0 < case_pairing['pair_count'] <= 4 and any(item['shared_variable_inputs'] == 0 for item in case_pairing['pairs'])
        stages['place'] = run_command(common + ['--json', str(source), '--no-pack', '--no-route',
            '--write', str(case / 'placed.json')], case, '04_place', environment)
        stages['route'] = run_command(common + ['--json', str(case / 'placed.json'), '--no-pack', '--no-place',
            '--write', str(case / 'routed.json'), '--fasm', str(case / 'design.fasm')], case, '05_route', environment)
        stages['check_function'] = run_command([sys.executable, str(scripts / 'check_physical_behavior.py'),
            '--mapped', str(folder / 'mapped.json'), '--packed', str(packed), '--physical', str(case / 'routed.json'),
            '--source', str(args.source.resolve()), '--init-checker', str(scripts / 'check_json_init.py'),
            '--out', str(case / 'physical_check')], case, '06_check_function', environment)
        stages['check_fasm'] = run_command([sys.executable, str(scripts / 'check_emitted_fasm.py'),
            '--physical', str(case / 'routed.json'), '--fasm', str(case / 'design.fasm'), '--lut-init',
            str(case / 'physical_check/physical_lut_init.json'), '--tilegrid', str(args.tilegrid.resolve()),
            '--out', str(case / 'emitted_fasm_check.json')], case, '07_check_fasm', environment)
        module = next(iter(json.loads((case / 'routed.json').read_text())['modules'].values()))
        resources = placed_resources(module)
        assert resources['placement_complete'] and not resources['resource_errors']
        shared_checks = check_shared_connections(module, case_pairing, case / 'design.fasm', args.tilegrid) if name != 'reference' else None
        summary['cases'][name] = {'passed': True, 'physical_lut_positions': resources['physical_lut_positions'],
            'stages': stages, 'routed_sha256': digest(case / 'routed.json'), 'fasm_sha256': digest(case / 'design.fasm'),
            'pairing': case_pairing if name != 'reference' else None, 'shared_connection_checks': shared_checks,
            'functional_checks': json.loads((case / 'physical_check/summary.json').read_text()),
            'emitted_fasm_checks': json.loads((case / 'emitted_fasm_check.json').read_text())}
        (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        print(name, resources['physical_lut_positions'], 'physical LUT positions; checks passed', flush=True)
    assert summary['cases']['paired']['physical_lut_positions'] <= summary['cases']['reference']['physical_lut_positions']
    if lock:
        lock.close()


if __name__ == '__main__':
    main()
