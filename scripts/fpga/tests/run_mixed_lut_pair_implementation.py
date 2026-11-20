#!/usr/bin/env python3
"""验证组合输出与寄存输出共享 LUT 后的实际配置。"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from placed_resources import placed_resources
from check_json_init import module
from run_registered_lut_pair_implementation import check_registers, design


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--package-pins', type=Path, required=True)
    parser.add_argument('--tilegrid', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    environment = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1', XC7_CARRY_TRIM_TAIL='1')
    common = [str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()), '--freq', '150',
              '--seed', '1', '--strict-timing-graph', '--timing-allow-fail']
    result = {'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
              'pairing_script_sha256': digest(scripts.parent / 'pair_mixed_luts.py'), 'cases': {}}
    for name, compatible in [('shared_inputs', True), ('six_inputs', False)]:
        case = folder / name
        case.mkdir(exist_ok=True)
        text = design('FDRE')
        text, count = re.subn(r"    FDRE #\(.INIT\(1'b1\)\) u_lower_ff \(.*?\n    \);",
                              '    assign o_data[1] = captured_data[1];', text, flags=re.S)
        assert count == 1
        if not compatible:
            text = text.replace('.I0(i_data[2]), .I1(i_data[3]), .I2(i_data[4])',
                                '.I0(i_data[3]), .I1(i_data[4]), .I2(i_data[5])')
        source = case / 'design.sv'
        source.write_text(text)
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
        run_command([sys.executable, str(scripts.parent / 'pair_mixed_luts.py'), '--packed', str(packed),
                     '--out', str(paired), '--report', str(case / 'pairing.json')], case, '03_pair', environment)
        pairing = json.loads((case / 'pairing.json').read_text())
        assert pairing['pair_count'] == int(compatible) and pairing['cell_contents_preserved']
        records = {}
        for label, netlist in [('reference', packed), ('paired', paired)]:
            output = case / label
            output.mkdir(exist_ok=True)
            run_command(common + ['--json', str(netlist), '--no-pack', '--no-route', '--write', str(output / 'placed.json')],
                        output, '04_place', environment)
            resources = placed_resources(module(output / 'placed.json'))
            assert resources['placement_complete']
            assert resources['physical_lut_positions'] == (1 if label == 'paired' and compatible else 2)
            run_command(common + ['--json', str(output / 'placed.json'), '--no-pack', '--no-place',
                         '--write', str(output / 'routed.json'), '--fasm', str(output / 'design.fasm')], output, '05_route', environment)
            run_command([sys.executable, str(scripts / 'check_json_init.py'), '--packed', str(packed),
                         '--physical', str(output / 'routed.json'), '--source', str(args.source.resolve()),
                         '--out', str(output / 'checks')], output, '06_check_init', environment)
            run_command([sys.executable, str(scripts / 'check_emitted_fasm.py'), '--physical', str(output / 'routed.json'),
                         '--fasm', str(output / 'design.fasm'), '--lut-init', str(output / 'checks/physical_lut_init.json'),
                         '--tilegrid', str(args.tilegrid.resolve()), '--out', str(output / 'fasm_checks.json')], output, '07_check_fasm', environment)
            registers = check_registers(packed, output / 'routed.json', {'pairs': []}, output / 'design.fasm', args.tilegrid)
            if label == 'paired' and compatible:
                placed = module(output / 'routed.json')
                pair = pairing['pairs'][0]
                upper = placed['cells'][pair['upper']]['attributes']['NEXTPNR_BEL']
                lower = placed['cells'][pair['lower']]['attributes']['NEXTPNR_BEL']
                ff = placed['cells'][pair['register']]['attributes']['NEXTPNR_BEL']
                assert upper.endswith('6LUT') and lower == upper[:-4] + '5LUT' and ff == upper[:-4] + 'FF'
                features = {line.strip() for line in (output / 'design.fasm').read_text().splitlines()}
                site, letter = upper[:-4].split('/')
                grid = json.loads(args.tilegrid.read_text())
                tiles = {s: (tile, kind) for tile, data in grid.items() for s, kind in data['sites'].items()}
                tile, kind = tiles[site]
                x = int(re.search(r'_X([0-9]+)Y', site).group(1))
                prefix = f'{tile}.{kind}_X{x % 2}.{letter}OUTMUX.'
                assert sorted(feature for feature in features if feature.startswith(prefix)) == [prefix + 'O5']
            records[label] = {'passed': True, 'placement_complete': True, 'routing_complete': True,
                              'physical_lut_positions': resources['physical_lut_positions'],
                              'lut_truth_checks': json.loads((output / 'checks/summary.json').read_text()),
                              'register_checks': registers,
                              'fasm_checks': json.loads((output / 'fasm_checks.json').read_text()),
                              'routed_sha256': digest(output / 'routed.json'), 'fasm_sha256': digest(output / 'design.fasm')}
        result['cases'][name] = {'passed': True, 'pairing': pairing, 'results': records}
        (folder / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'case': name, 'passed': True, 'pair_count': pairing['pair_count']}), flush=True)


if __name__ == '__main__':
    main()
