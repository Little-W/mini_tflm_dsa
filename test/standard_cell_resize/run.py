#!/usr/bin/env python3
"""Verify cell-function matching and slew repair with real Yosys and OpenSTA."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sta', required=True)
    parser.add_argument('--liberty', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo/'scripts/asic'))
    from resize_standard_cells import library_cells, stronger_cell
    library = library_cells(args.liberty)
    assert library['NOR2_X1']['signature'] == library['NOR2_X2']['signature']
    assert library['NOR2_X1']['signature'] != library['NAND2_X1']['signature']
    assert library['DFF_X1']['signature'] == library['DFF_X2']['signature']
    assert library['DFF_X1']['signature'] != library['DFFR_X1']['signature']
    assert stronger_cell('NOR2_X1', library) == 'NOR2_X2'
    mismatched = {key: value for key, value in library.items() if key in ('NOR2_X1', 'NOR2_X2')}
    mismatched['NOR2_X2'] = {**mismatched['NOR2_X2'], 'signature': library['NAND2_X1']['signature']}
    try:
        stronger_cell('NOR2_X1', mismatched)
    except RuntimeError:
        pass
    else:
        raise AssertionError('A different function must not be selected')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    netlist = out/'loaded_nor.v'
    netlist.write_text('''module loaded_nor(input clk, input rst_n, input a, input b,
                  output q, output [7:0] z);
DFFR_X1 ff0 (
 .CK(clk), .RN(rst_n), .D(a), .Q(q)
);
NOR2_X1 g0 (
 .A1(a), .A2(b), .ZN(z[0])
);
''' + '\n'.join(f'assign z[{index}] = z[0];' for index in range(1, 8)) + '\nendmodule\n')
    command = [sys.executable, str(repo/'scripts/asic/resize_standard_cells.py'),
               '--sta', args.sta, '--liberty', str(args.liberty.resolve()),
               '--netlist', str(netlist), '--top', 'loaded_nor', '--out', str(out/'resize')]
    with (out/'run.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    result = json.loads((out/'resize/summary.json').read_text())
    assert result['optimization_completed'] and result['max_transition_met']
    assert result['connectivity_unchanged'] and result['constraints_unchanged']
    assert result['all_replacements_functionally_identical']
    assert result['iterations'][0]['transition_violation_count'] > 0
    assert result['iterations'][-1]['transition_violation_count'] == 0
    assert result['raw_area']['standard_cell_count'] == result['optimized_area']['standard_cell_count']
    assert result['raw_area']['sequential_cell_count'] == result['optimized_area']['sequential_cell_count']
    assert all(change['instance'] == 'g0' for change in result['changes'])
    report = {'passed': True, 'combinational_functions_checked': True,
              'sequential_definitions_checked': True, 'different_function_rejected': True,
              'real_tool_slew_repair_checked': True, 'connectivity_unchanged': True,
              'result': str(out/'resize/summary.json')}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
