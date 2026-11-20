#!/usr/bin/env python3
"""在寄存器之间的实际布局与布线设计上检查独立路径报告。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from report_saved_timing import parse_paths


DESIGN = '''module soc_top (
    input wire clk,
    input wire [2:0] i_data,
    output wire [1:0] o_data
);
    wire [2:0] input_q;
    wire [1:0] result_d;
    FDRE #(.INIT(1'b0)) u_input0 (.C(clk), .CE(1'b1), .R(1'b0), .D(i_data[0]), .Q(input_q[0]));
    FDRE #(.INIT(1'b1)) u_input1 (.C(clk), .CE(1'b1), .R(1'b0), .D(i_data[1]), .Q(input_q[1]));
    FDRE #(.INIT(1'b0)) u_input2 (.C(clk), .CE(1'b1), .R(1'b0), .D(i_data[2]), .Q(input_q[2]));
    LUT3 #(.INIT(8'h96)) u_sum (.I0(input_q[0]), .I1(input_q[1]), .I2(input_q[2]), .O(result_d[0]));
    LUT2 #(.INIT(4'h6)) u_next (.I0(o_data[0]), .I1(input_q[0]), .O(result_d[1]));
    FDRE #(.INIT(1'b0)) u_result0 (.C(clk), .CE(1'b1), .R(1'b0), .D(result_d[0]), .Q(o_data[0]));
    FDRE #(.INIT(1'b1)) u_result1 (.C(clk), .CE(1'b1), .R(1'b0), .D(result_d[1]), .Q(o_data[1]));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--package-pins', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    lock = args.lock_file.open('a') if args.lock_file else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    scripts = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1', XC7_CARRY_TRIM_TAIL='1', NEXTPNR_REPORT_PATHS='1')
    design = folder / 'design.v'
    design.write_text(DESIGN)
    prepare = folder / 'prepare.ys'
    prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                       'read_verilog -lib +/xilinx/cells_xtra.v\n'
                       f'read_verilog {design}\nhierarchy -check -top soc_top\n'
                       f'clean\ncheck -assert\nblackbox =A:whitebox\nwrite_json {folder}/mapped.json\n')
    run_command([sys.executable, str(scripts / 'open_fpga_synth.py'), '--worker', str(prepare)],
                folder, '01_prepare', environment)
    run_command([sys.executable, str(scripts / 'open_fpga_implementation.py'), '--mapped', str(folder / 'mapped.json'),
                 '--nextpnr', str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()),
                 '--soc-package-pins', str(args.package_pins.resolve()), '--out', str(folder / 'implementation'),
                 '--refinement-iterations', '1', '--allow-timing-failure'], folder, '02_implement', environment)
    result = {'passed': True, 'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
              'design_sha256': digest(design), 'cases': {}}
    for index, name in enumerate(('placed', 'routed'), 3):
        case = folder / name
        case.mkdir(exist_ok=True)
        if name == 'placed':
            run_command([sys.executable, str(scripts / 'report_saved_timing.py'),
                         '--design', str(folder / 'implementation/placed.json'),
                         '--nextpnr', str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()),
                         '--out', str(case)], folder, f'{index:02d}_report_{name}', environment)
            report = json.loads((case / 'paths.json').read_text())
            assert report['input_design_preserved']
        else:
            physical = json.loads((folder / 'implementation/routed.json').read_text())
            cells = next(iter(physical['modules'].values()))['cells']
            metadata = {key: {'type': cell['type'], **cell.get('attributes', {})} for key, cell in cells.items()}
            report = {'paths': parse_paths((folder / 'implementation/04_route.log').read_text(), metadata),
                      'design_sha256': digest(folder / 'implementation/routed.json'),
                      'net_delay_source': 'Current routed interconnect'}
            (case / 'paths.json').write_text(json.dumps(report, indent=2) + '\n')
        assert report['paths'] and all(path['startpoint']['X_ORIG_TYPE'] == 'FDRE' and
                                       path['endpoint']['X_ORIG_TYPE'] == 'FDRE' and
                                       path['startpoint']['port'] == 'Q' and
                                       path['endpoint']['port'] == 'D' for path in report['paths'])
        for path in report['paths']:
            assert any(item['kind'] == 'source' and item['type'] == 'SLICE_LUTX' for item in path['segments'])
            assert any(item['kind'] == 'net' and item['delay_ns'] > 0 for item in path['segments'])
        result['cases'][name] = {'passed': True,
                                'analysis_mode': 'saved_placement' if name == 'placed' else 'implementation_log',
                                'path_count': len(report['paths']), 'paths_sha256': digest(case / 'paths.json'),
                                'design_sha256': report['design_sha256'],
                                'net_delay_source': report['net_delay_source']}
        if name == 'placed':
            result['cases'][name]['input_design_preserved'] = report['input_design_preserved']
    (folder / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Saved placement and routing path reports passed')
    if lock:
        lock.close()


if __name__ == '__main__':
    main()
