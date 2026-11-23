#!/usr/bin/env python3
"""Exercise path classification, load sensitivity, and linking with real OpenSTA."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


NETLIST = '''module sta_pilot(input clk, input rst_n, input a, input b,
                          output q, output y, output z);
wire qa, n1;
DFFR_X1 ff0 (.CK(clk), .RN(rst_n), .D(a), .Q(qa));
AND2_X1 g0 (.A1(qa), .A2(b), .ZN(n1));
DFFR_X1 ff1 (.CK(clk), .RN(rst_n), .D(n1), .Q(q));
BUF_X1 g1 (.A(qa), .Z(y));
AND2_X1 g2 (.A1(a), .A2(b), .ZN(z));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sta', required=True)
    parser.add_argument('--liberty', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    netlist = out/'pilot.v'
    netlist.write_text(NETLIST)
    driver = repo/'scripts/asic/run_opensta.py'
    common = [sys.executable, str(driver), '--sta', args.sta, '--liberty', str(args.liberty.resolve()),
              '--top', 'sta_pilot']
    results = []
    for load in (5, 10):
        folder = out/f'load{load}'
        run = subprocess.run([*common, '--netlist', str(netlist), '--out', str(folder),
                              '--output-load-ff', str(load)], capture_output=True, text=True)
        (out/f'load{load}.log').write_text(run.stdout+run.stderr)
        assert run.returncode == 0, run.stdout+run.stderr
        result = json.loads((folder/'summary.json').read_text())
        assert result['analysis_completed'] and result['setup_met']
        assert result['clock']['frequency_mhz'] == 150
        assert result['wire_model']['name'] == '5K_hvratio_1_1'
        assert 'set_wire_load_model' in (folder/'constraints.sdc').read_text()
        assert not (folder/'coverage.rpt').read_text().strip()
        for name, group in result['path_groups'].items():
            assert group['setup']['present'] and group['hold']['present'], name
            path = group['setup']
            assert abs(path['required_ns']-path['arrival_ns']-path['slack_ns']) < 2e-6
        results.append(result)
    for group in ('reg_to_output', 'input_to_output'):
        assert results[1]['path_groups'][group]['setup']['arrival_ns'] > results[0]['path_groups'][group]['setup']['arrival_ns']
    invalid = out/'unknown_cell.v'
    invalid.write_text(NETLIST.replace('AND2_X1 g2', 'UNKNOWN_CELL g2'))
    run = subprocess.run([*common, '--netlist', str(invalid), '--out', str(out/'unknown_cell')],
                         capture_output=True, text=True)
    assert run.returncode != 0
    log = (out/'unknown_cell/opensta.log').read_text().lower()
    assert 'black box' in log or 'blackbox' in log or 'error:' in log, log
    report = {'passed': True, 'path_groups_checked': list(results[0]['path_groups']),
              'load_sensitivity_checked': ['reg_to_output', 'input_to_output'],
              'unknown_cell_rejected': True, 'nominal_result': str(out/'load5/summary.json'),
              'increased_load_result': str(out/'load10/summary.json')}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
