#!/usr/bin/env python3
"""验证 CARRY4 尾部输入优化的布局、布线、功能和实际 FASM。"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

DESIGN = "module soc_top(input wire clk, input wire [7:0] i_data, output wire [13:0] o_data);\nwire [3:0] low1_o;\nwire [3:0] low1_co;\nwire [3:0] low2_o;\nwire [3:0] low2_co;\nwire [3:0] low3_o;\nwire [3:0] low3_co;\nwire [3:0] chain0_o;\nwire [3:0] chain0_co;\nwire [3:0] chain1_o;\nwire [3:0] chain1_co;\nwire [3:0] cyinit_o;\nwire [3:0] cyinit_co;\nCARRY4 u_low1 (.DI(4'b1010), .S({3'b010,i_data[0]}), .CI(1'b0), .CYINIT(i_data[1]), .O(low1_o), .CO(low1_co));\nCARRY4 u_low2 (.DI({2'b10,i_data[2:1]}), .S({2'b01,i_data[3:2]}), .CI(1'b0), .CYINIT(1'b0), .O(low2_o), .CO(low2_co));\nCARRY4 u_low3 (.DI({i_data[7],i_data[4:2]}), .S({i_data[6],i_data[5:3]}), .CI(1'b0), .CYINIT(1'b0), .O(low3_o), .CO(low3_co));\nCARRY4 u_chain0 (.DI(i_data[3:0]), .S(i_data[7:4]), .CI(1'b0), .CYINIT(1'b0), .O(chain0_o), .CO(chain0_co));\nCARRY4 u_chain1 (.DI(4'b1001), .S({3'b010,i_data[1]}), .CI(chain0_co[3]), .CYINIT(1'b0), .O(chain1_o), .CO(chain1_co));\nCARRY4 u_cyinit (.DI(4'b0000), .S(4'b1111), .CI(1'b0), .CYINIT(low3_co[2]), .O(cyinit_o), .CO(cyinit_co));\nwire [13:0] capture_data = {cyinit_o[0],chain1_o[0],chain0_o[0],i_data[7:6],low3_co[2],low3_o[2:0],low2_co[1],low2_o[1:0],low1_co[0],low1_o[0]};\ngenvar i; generate for(i=0;i<14;i=i+1) begin:g_capture FDRE #(.INIT(1'b0)) u_register(.C(clk),.CE(1'b1),.R(1'b0),.D(capture_data[i]),.Q(o_data[i])); end endgenerate\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True, help='nextpnr 的 xilinx 源码目录')
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--package-pins', type=Path, required=True)
    parser.add_argument('--tilegrid', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    sys.path.insert(0, str(scripts.parent))
    from open_fpga_synth import digest
    from open_fpga_implementation import run_command
    from placed_resources import placed_resources
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    lock = args.lock_file.open('a') if args.lock_file else None
    if lock:
        print('Waiting for implementation lock', flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
    binary, source, chipdb = args.nextpnr.resolve(), args.source.resolve(), args.chipdb.resolve()
    design = folder / 'design.sv'
    design.write_text(DESIGN)
    prepare = folder / 'prepare.ys'
    prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                       'read_verilog -lib +/xilinx/cells_xtra.v\n'
                       f'read_verilog {design}\nhierarchy -check -top soc_top\n'
                       'clean\ncheck -assert\nblackbox =A:whitebox\n'
                       f'write_json {folder}/mapped.json\n')
    env = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1')
    run_command([sys.executable, str(scripts.parent / 'open_fpga_synth.py'), '--worker', str(prepare)],
                folder, 'prepare', env)
    summary = {'nextpnr_sha256': digest(binary), 'chipdb_sha256': digest(chipdb),
               'source_sha256': digest(source / 'pack_carry_xc7.cc'),
               'design_sha256': digest(design), 'mapped_sha256': digest(folder / 'mapped.json'),
               'cases': {}}
    for name, enabled in [('reference', '0'), ('trimmed', '1')]:
        case = folder / name
        case.mkdir(exist_ok=True)
        env['XC7_CARRY_TRIM_TAIL'] = enabled
        place = [sys.executable, str(scripts.parent / 'open_fpga_implementation.py'),
                 '--mapped', str(folder / 'mapped.json'), '--nextpnr', str(binary),
                 '--chipdb', str(chipdb), '--out', str(case), '--through', 'place',
                 '--soc-package-pins', str(args.package_pins.resolve()), '--allow-timing-failure']
        run_command(place, case, 'implementation', env)
        route = [str(binary), '--chipdb', str(chipdb), '--freq', '150', '--seed', '1',
                 '--strict-timing-graph', '--timing-allow-fail', '--json', str(case / 'placed.json'),
                 '--no-pack', '--no-place', '--write', str(case / 'routed.json'),
                 '--report', str(case / 'routing_timing.json'), '--fasm', str(case / 'design.fasm')]
        route_stats = run_command(route, case, '04_route', env)
        check = [sys.executable, str(scripts / 'check_physical_behavior.py'),
                 '--mapped', str(folder / 'mapped.json'), '--packed', str(case / 'packed.json'),
                 '--physical', str(case / 'routed.json'), '--source', str(source),
                 '--init-checker', str(scripts / 'check_json_init.py'), '--out', str(case / 'physical_check')]
        run_command(check, case, 'physical_check', env)
        emitted = [sys.executable, str(scripts / 'check_emitted_fasm.py'),
                   '--physical', str(case / 'routed.json'), '--fasm', str(case / 'design.fasm'),
                   '--lut-init', str(case / 'physical_check/physical_lut_init.json'),
                   '--tilegrid', str(args.tilegrid.resolve()), '--out', str(case / 'emitted_fasm_check.json')]
        run_command(emitted, case, 'emitted_fasm_check', env)
        modules = json.loads((case / 'routed.json').read_text())['modules']
        module = next(item for item in modules.values() if item.get('cells'))
        resources = placed_resources(module)
        assert resources['placement_complete'] and not resources['resource_errors']
        resources.update(routing_completed=True, timing_150mhz_confirmed=None)
        (case / 'routed_resources.json').write_text(json.dumps(resources, indent=2) + '\n')
        summary['cases'][name] = {'passed': True, 'physical_lut_positions': resources['physical_lut_positions'],
            'route': route_stats, 'routed_sha256': digest(case / 'routed.json'), 'fasm_sha256': digest(case / 'design.fasm'),
            'functional_checks': json.loads((case / 'physical_check/summary.json').read_text()),
            'emitted_fasm_checks': json.loads((case / 'emitted_fasm_check.json').read_text())}
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(name, resources['physical_lut_positions'], 'physical LUT positions; checks passed', flush=True)
    assert summary['cases']['trimmed']['physical_lut_positions'] < summary['cases']['reference']['physical_lut_positions']
    if lock:
        lock.close()


if __name__ == '__main__':
    main()
