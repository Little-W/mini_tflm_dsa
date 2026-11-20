#!/usr/bin/env python3
"""检查真实第六输入的 LUT 余因子共享及其物理配置。"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from placed_resources import placed_resources


def design_text(repeated_inputs=False, independent_luts=False):
    tables = [0x96A50F3C81E7D2B4, 0xD83174AC629BF05E, 0x8CE24F19A765B03D,
              0x53A6C19D2BE8704F, 0x76DC28E1A9035FB4, 0xB4809D36F17A2C5E,
              0x4B92E6C18A7F035D]
    lines = ['module soc_top (input wire clk, input wire [7:0] i_data,',
             '                output wire [13:0] o_data);',
             '    wire [13:0] capture_data;',
             '    // 每个 O6 使用六个动态输入，O5 使用同一真值表的低半区。']
    for index, table in enumerate(tables):
        inputs = [(pin + index) % 8 for pin in range(6)]
        if repeated_inputs and index == 5:
            inputs[1] = inputs[0]
        if repeated_inputs and index == 6:
            inputs[5] = inputs[2]
        if independent_luts:
            selected = index % 6
            upper_order = list(range(5))
            upper_order.insert(selected, 5)
            lower_order = list(reversed(range(5)))
            upper_table = 0
            lower_table = 0
            for address in range(64):
                original = sum(((address >> pin) & 1) << variable for pin, variable in enumerate(upper_order))
                upper_table |= ((table >> original) & 1) << address
            for address in range(32):
                original = sum(((address >> pin) & 1) << variable for pin, variable in enumerate(lower_order))
                lower_table |= ((table >> original) & 1) << address
            upper_pins = ', '.join(f'.I{pin}(i_data[{inputs[variable]}])' for pin, variable in enumerate(upper_order))
            lower_pins = ', '.join(f'.I{pin}(i_data[{inputs[variable]}])' for pin, variable in enumerate(lower_order))
            lines += [f"    LUT6 #(.INIT(64'h{upper_table:016x})) u_upper_{index} (",
                      f'        {upper_pins}, .O(capture_data[{2 * index}])', '    );',
                      f"    LUT5 #(.INIT(32'h{lower_table:08x})) u_lower_{index} (",
                      f'        {lower_pins}, .O(capture_data[{2 * index + 1}])', '    );']
        else:
            pins = ', '.join(f'.I{pin}(i_data[{inputs[pin]}])' for pin in range(6))
            lines += [f"    LUT6_2 #(.INIT(64'h{table:016x})) u_logic_{index} (",
                      f'        {pins},',
                      f'        .O6(capture_data[{2 * index}]), .O5(capture_data[{2 * index + 1}])',
                      '    );']
    lines += ['    genvar bit_index;', '    generate',
              '        for (bit_index = 0; bit_index < 14; bit_index = bit_index + 1) begin : g_capture',
              "            FDRE #(.INIT(1'b0)) u_register (",
              "                .C(clk), .CE(1'b1), .R(1'b0),",
              '                .D(capture_data[bit_index]), .Q(o_data[bit_index])',
              '            );', '        end', '    endgenerate', 'endmodule']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--package-pins', type=Path, required=True)
    parser.add_argument('--tilegrid', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    parser.add_argument('--repeated-inputs', action='store_true')
    parser.add_argument('--fuse-mapped', action='store_true')
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    lock = args.lock_file.open('a') if args.lock_file else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    env = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1', XC7_CARRY_TRIM_TAIL='1')
    env.pop('XC7_LUT_COFACTOR', None)
    design = folder / 'design.sv'
    if args.repeated_inputs and args.fuse_mapped:
        parser.error('Mapped fusion uses distinct input nets')
    design.write_text(design_text(args.repeated_inputs, args.fuse_mapped))
    prepare = folder / 'prepare.ys'
    prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                       'read_verilog -lib +/xilinx/cells_xtra.v\n'
                       f'read_verilog {design}\nhierarchy -check -top soc_top\n'
                       'clean\ncheck -assert\nblackbox =A:whitebox\n'
                       f'write_json {folder}/mapped.json\n')
    run_command([sys.executable, str(scripts.parent / 'open_fpga_synth.py'), '--worker', str(prepare)],
                folder, '01_prepare', env)
    fused = folder / 'mapped.json'
    fusion = None
    if args.fuse_mapped:
        fused = folder / 'fused.json'
        run_command([sys.executable, str(scripts.parent / 'fuse_lut_cofactors.py'), '--mapped',
                     str(folder / 'mapped.json'), '--out', str(fused), '--report', str(folder / 'fusion.json')],
                    folder, '01_fuse', env)
        fusion = json.loads((folder / 'fusion.json').read_text())
        assert fusion['pair_count'] == 7 and fusion['all_pair_truth_tables_verified']
    summary = {'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
               'design_sha256': digest(design), 'mapped_sha256': digest(folder / 'mapped.json'),
               'arch_place_sha256': digest(args.source / 'arch_place.cc'),
               'pack_sha256': digest(args.source / 'pack.cc'),
               'repeated_inputs': args.repeated_inputs, 'fusion': fusion, 'cases': {}}
    common = [str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()), '--freq', '150',
              '--seed', '1', '--strict-timing-graph', '--timing-allow-fail']
    for name in ('reference', 'cofactor'):
        case = folder / name
        case.mkdir(exist_ok=True)
        environment = dict(env)
        if name == 'cofactor':
            environment['XC7_LUT_COFACTOR'] = '1'
        stages = {}
        stages['pack'] = run_command([sys.executable, str(scripts.parent / 'open_fpga_implementation.py'),
            '--mapped', str(fused if name == 'cofactor' else folder / 'mapped.json'), '--nextpnr', str(args.nextpnr.resolve()),
            '--chipdb', str(args.chipdb.resolve()), '--out', str(case), '--through', 'pack',
            '--soc-package-pins', str(args.package_pins.resolve()), '--allow-timing-failure'],
            case, '02_prepare_pack', environment)
        stages['place'] = run_command(common + ['--json', str(case / 'packed.json'), '--no-pack', '--no-route',
            '--write', str(case / 'placed.json')], case, '03_place', environment)
        stages['placed_init'] = run_command([sys.executable, str(scripts / 'check_json_init.py'),
            '--packed', str(case / 'packed.json'), '--physical', str(case / 'placed.json'),
            '--source', str(args.source.resolve()), '--out', str(case / 'placed_init_check')],
            case, '04_check_placed_init', environment)
        # 从保存的布局文件重新读入并布线，检查阶段之间的输入与约束保持。
        stages['route'] = run_command(common + ['--json', str(case / 'placed.json'), '--no-pack', '--no-place',
            '--write', str(case / 'routed.json'), '--fasm', str(case / 'design.fasm')],
            case, '05_route', environment)
        stages['check_function'] = run_command([sys.executable, str(scripts / 'check_physical_behavior.py'),
            '--mapped', str(folder / 'mapped.json'), '--packed', str(case / 'packed.json'),
            '--physical', str(case / 'routed.json'), '--source', str(args.source.resolve()),
            '--init-checker', str(scripts / 'check_json_init.py'), '--out', str(case / 'physical_check')],
            case, '06_check_function', environment)
        stages['check_fasm'] = run_command([sys.executable, str(scripts / 'check_emitted_fasm.py'),
            '--physical', str(case / 'routed.json'), '--fasm', str(case / 'design.fasm'),
            '--lut-init', str(case / 'physical_check/physical_lut_init.json'),
            '--tilegrid', str(args.tilegrid.resolve()), '--out', str(case / 'emitted_fasm_check.json')],
            case, '07_check_fasm', environment)
        module = next(iter(json.loads((case / 'routed.json').read_text())['modules'].values()))
        resources = placed_resources(module)
        assert resources['placement_complete'] and not resources['resource_errors']
        marked = [c for c in module['cells'].values() if c['attributes'].get('X_LUT_COFACTOR_PAIR')]
        assert len(marked) == (14 if name == 'cofactor' else 0)
        summary['cases'][name] = {'passed': True, 'resources': resources, 'stages': stages,
            'routed_sha256': digest(case / 'routed.json'), 'fasm_sha256': digest(case / 'design.fasm'),
            'functional_checks': json.loads((case / 'physical_check/summary.json').read_text()),
            'emitted_fasm_checks': json.loads((case / 'emitted_fasm_check.json').read_text())}
        (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        print(name, resources['physical_lut_positions'], 'physical LUT positions; checks passed', flush=True)
    if not args.repeated_inputs:
        assert summary['cases']['reference']['resources']['physical_lut_positions'] == 14
    assert summary['cases']['cofactor']['resources']['physical_lut_positions'] == 7
    if lock:
        lock.close()


if __name__ == '__main__':
    main()
