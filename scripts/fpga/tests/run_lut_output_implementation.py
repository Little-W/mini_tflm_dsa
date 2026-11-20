#!/usr/bin/env python3
"""检查双输出 LUT 的独立输入、实际布局布线和配置真值。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from placed_resources import placed_resources
from check_json_init import logical_pins, module, names


def design(table, select, reverse=False, feedback=True):
    lower = 'admission_event' if reverse else 'ready'
    upper = 'ready' if reverse else 'admission_event'
    fourth = 'admission_start' if feedback else 'state[4]'
    return f'''module soc_top (
    input wire clk,
    input wire [5:0] i_data,
    output wire [1:0] o_data
);
    wire [5:0] state;
    wire calc_start, admission_start, admission_event, ready;
    assign o_data[0] = ready;
    for (genvar index = 0; index < 6; index = index + 1) begin : g_state
        FDRE #(.INIT(1'b0)) u_state (
            .C(clk), .CE(1'b1), .R(1'b0), .D(i_data[index]), .Q(state[index])
        );
    end
    LUT6_2 #(.INIT(64'h{table:016x})) u_admission (
        .I0(state[0]), .I1(state[1]), .I2(state[2]), .I3(state[3]),
        .I4({fourth}), .I5({select}), .O5({lower}), .O6({upper})
    );
    LUT2 #(.INIT(4'h8)) u_calc (
        .I0(ready), .I1(state[4]), .O(calc_start)
    );
    LUT2 #(.INIT(4'h8)) u_start (
        .I0(calc_start), .I1(state[5]), .O(admission_start)
    );
    FDRE #(.INIT(1'b0)) u_event (
        .C(clk), .CE(1'b1), .R(1'b0), .D(admission_event), .Q(o_data[1])
    );
endmodule
'''


def check_split(original, packed):
    old = json.loads(original.read_text())['modules']['soc_top']
    new = module(packed)
    old_names, new_names = names(old), names(new)
    primitive = old['cells']['u_admission']
    table = int(primitive['parameters']['INIT'], 2)
    select = primitive['connections']['I5'][0]
    fixed = int(select) if isinstance(select, str) and select in ('0', '1') else None
    comparisons = 0
    halves = {}
    for suffix, output in (('$LUT5', 'O5'), ('$LUT6', 'O6')):
        current = new['cells']['u_admission' + suffix]
        pins = logical_pins(current)
        for pin, bit in pins.items():
            source = primitive['connections'][pin][0]
            assert old_names[source] & new_names[bit], (output, pin)
        for assignment in range(64):
            values = {f'I{index}': (assignment >> index) & 1 for index in range(6)}
            if fixed is not None:
                values['I5'] = fixed
            original_index = sum(values[f'I{index}'] << index for index in range(6))
            if output == 'O5':
                original_index &= 31
            packed_index = sum(values[pin] << int(pin[1:]) for pin in pins)
            expected = (table >> original_index) & 1
            actual = (int(current['parameters']['INIT'], 2) >> packed_index) & 1
            assert actual == expected, (output, assignment)
            comparisons += 1
        halves[output] = {'connected_inputs': sorted(pins),
                          'input_connections_checked': len(pins)}
    return {'passed': True, 'output_comparisons': comparisons, 'halves': halves}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('nextpnr', 'chipdb', 'source', 'package-pins', 'tilegrid', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    environment = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_LUT_COFACTOR='1',
                       NEXTPNR_HEAP_MAX_ITERS='2', NEXTPNR_REFINE_MAX_ITERS='1')
    common = [str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()),
              '--freq', '150', '--seed', '1', '--strict-timing-graph', '--timing-allow-fail']
    cases = {
        'lower_output_feedback': (0x8000000080008000, "1'b1", False, True),
        'upper_output_feedback': (0x8000800080000000, "1'b1", True, True),
        'fixed_zero_select': (0xAAAAAAAA66666666, "1'b0", False, True),
        'variable_cofactor': (0x96E86996F00F0FF0, 'state[5]', False, False),
        'dependent_feedback': (0x8000000080000000, "1'b1", False, True),
    }
    report = {'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
              'packer_source_sha256': digest(args.source / 'pack.cc'),
              'runner_sha256': digest(Path(__file__)), 'cases': {}}
    for name, parameters in cases.items():
        folder = out / name
        folder.mkdir(exist_ok=True)
        source = folder / 'design.sv'
        source.write_text(design(*parameters))
        prepare = folder / 'prepare.ys'
        prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                           'read_verilog -lib +/xilinx/cells_xtra.v\n'
                           f'read_verilog -sv {source}\nhierarchy -check -top soc_top\n'
                           'clean\ncheck -assert\nblackbox =A:whitebox\n'
                           f'write_json {folder}/mapped.json\n')
        stages = {}
        stages['prepare'] = run_command(
            [sys.executable, str(scripts.parent / 'open_fpga_synth.py'), '--worker', str(prepare)],
            folder, '01_prepare', environment)
        implementation = folder / 'implementation'
        command = [sys.executable, str(scripts.parent / 'open_fpga_implementation.py'),
                   '--mapped', str(folder / 'mapped.json'), '--nextpnr', str(args.nextpnr.resolve()),
                   '--chipdb', str(args.chipdb.resolve()), '--out', str(implementation),
                   '--through', 'pack', '--soc-package-pins', str(args.package_pins.resolve()),
                   '--allow-timing-failure']
        if name == 'dependent_feedback':
            with (folder / '02_expected_rejection.log').open('w') as stream:
                result = subprocess.run(command, env=environment, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=120)
            log = (implementation / '02_pack.log').read_text()
            assert result.returncode != 0
            assert 'ERROR: timing analysis failed due to presence of combinatorial loops' in log
            report['cases'][name] = {'passed': True, 'genuine_combinational_cycle_rejected': True,
                                     'source_sha256': digest(source)}
            continue
        stages['pack'] = run_command(command, folder, '02_pack', environment)
        packed = implementation / 'packed.json'
        split_checks = check_split(folder / 'mapped.json', packed)
        stages['place'] = run_command(common + ['--json', str(packed), '--no-pack', '--no-route',
            '--write', str(folder / 'placed.json')], folder, '03_place', environment)
        stages['route'] = run_command(common + ['--json', str(folder / 'placed.json'), '--no-pack',
            '--no-place', '--write', str(folder / 'routed.json'), '--fasm', str(folder / 'design.fasm')],
            folder, '04_route', environment)
        stages['truth'] = run_command([sys.executable, str(scripts / 'check_json_init.py'),
            '--packed', str(packed), '--physical', str(folder / 'routed.json'),
            '--source', str(args.source.resolve()), '--out', str(folder / 'truth')],
            folder, '05_truth', environment)
        stages['fasm'] = run_command([sys.executable, str(scripts / 'check_emitted_fasm.py'),
            '--physical', str(folder / 'routed.json'), '--fasm', str(folder / 'design.fasm'),
            '--lut-init', str(folder / 'truth/physical_lut_init.json'),
            '--tilegrid', str(args.tilegrid.resolve()), '--out', str(folder / 'fasm_checks.json')],
            folder, '06_fasm', environment)
        resources = placed_resources(module(folder / 'routed.json'))
        truth = json.loads((folder / 'truth/summary.json').read_text())
        fasm = json.loads((folder / 'fasm_checks.json').read_text())
        assert resources['placement_complete'] and not resources['resource_errors']
        assert truth['passed'] and fasm['passed']
        report['cases'][name] = {'passed': True, 'placement_complete': True,
            'routing_complete': True, 'physical_lut_positions': resources['physical_lut_positions'],
            'split_checks': split_checks, 'truth_checks': truth, 'fasm_checks': fasm,
            'stages': stages, 'source_sha256': digest(source),
            'packed_sha256': digest(packed), 'routed_sha256': digest(folder / 'routed.json'),
            'fasm_sha256': digest(folder / 'design.fasm')}
        print(name, 'passed', flush=True)
    assert len(report['cases']) == len(cases)
    report['passed'] = all(case['passed'] for case in report['cases'].values())
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: value['passed'] for name, value in report['cases'].items()}), flush=True)


if __name__ == '__main__':
    main()
