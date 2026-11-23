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
              '--top', 'sta_pilot', '--report-output', 'z']
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
        assert result['requested_endpoint_paths']['z']['setup']['present']
        assert result['requested_endpoint_paths']['z']['setup']['endpoint'].startswith('z ')
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
    literal_netlist = out/'literal_outputs.v'
    literal_netlist.write_text(NETLIST.replace(
        'output q, output y, output z);',
        'output q, output y, output z, output tied_low, output unused_data, output registered_zero);').replace(
        'endmodule', "assign tied_low = 1'b0;\nassign unused_data = 1'bx;\n"
        "DFF_X1 ff_constant (\n .CK(clk), .D(1'b0), .Q(registered_zero)\n);\nendmodule"))
    literal_json = out/'literal_outputs.json'
    module = {'ports': {'tied_low': {'direction': 'output', 'bits': ['0']},
                        'unused_data': {'direction': 'output', 'bits': ['x']}}}
    literal_json.write_text(json.dumps({'modules': {'sta_pilot': module}}))
    run = subprocess.run([*common, '--netlist', str(literal_netlist), '--netlist-json',
                          str(literal_json), '--out', str(out/'literal_outputs')],
                         capture_output=True, text=True)
    (out/'literal_outputs.log').write_text(run.stdout+run.stderr)
    assert run.returncode == 0, run.stdout+run.stderr
    coverage = json.loads((out/'literal_outputs/summary.json').read_text())['timing_coverage']
    assert coverage['constant_output_endpoints'] == [{'endpoint': 'tied_low', 'value': '0'}]
    assert coverage['undefined_output_endpoints'] == [{'endpoint': 'unused_data', 'value': 'x'}]
    assert coverage['constant_cell_input_endpoints'] == [{'endpoint': 'ff_constant/D', 'value': '0'}]
    floating_netlist = out/'floating_output.v'
    floating_netlist.write_text(literal_netlist.read_text().replace("assign unused_data = 1'bx;", ''))
    module['ports']['unused_data']['bits'] = [42]
    floating_json = out/'floating_output.json'
    floating_json.write_text(json.dumps({'modules': {'sta_pilot': module}}))
    run = subprocess.run([*common, '--netlist', str(floating_netlist), '--netlist-json',
                          str(floating_json), '--out', str(out/'floating_output')],
                         capture_output=True, text=True)
    (out/'floating_output.log').write_text(run.stdout+run.stderr)
    assert run.returncode != 0
    assert 'timing coverage is incomplete' in run.stdout+run.stderr
    report = {'passed': True, 'path_groups_checked': list(results[0]['path_groups']),
              'load_sensitivity_checked': ['reg_to_output', 'input_to_output'],
              'unknown_cell_rejected': True, 'literal_outputs_classified': True,
              'literal_cell_input_classified': True,
              'selected_output_endpoint_checked': 'z',
              'unconstrained_signal_rejected': True,
              'nominal_result': str(out/'load5/summary.json'),
              'increased_load_result': str(out/'load10/summary.json')}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
