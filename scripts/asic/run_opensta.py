#!/usr/bin/env python3
"""Estimate mapped-block timing with OpenSTA and a nanosecond/femtofarad Liberty."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


PATH_GROUPS = ('reg_to_reg', 'input_to_reg', 'reg_to_output', 'input_to_output')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tcl_word(value: str | Path) -> str:
    text = str(value)
    for old, new in (('\\', '\\\\'), ('$', '\\$'), ('[', '\\['), (']', '\\]'),
                     ('"', '\\"'), ('\n', '\\n'), ('\r', '\\r')):
        text = text.replace(old, new)
    return '"' + text + '"'


def parse_path(text: str) -> dict:
    if 'No paths found.' in text or text.strip() == 'NO_PATHS':
        return {'present': False}
    number = r'([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)'
    result = {'present': True}
    for field, label in (('arrival_ns', 'data arrival time'), ('required_ns', 'data required time'),
                         ('slack_ns', 'slack')):
        match = re.search(r'^\s*' + number + r'\s+' + label + r'\b', text, re.MULTILINE)
        if match is None:
            raise ValueError(f'Missing {label} in OpenSTA path report')
        result[field] = float(match.group(1))
    for field, label in (('startpoint', 'Startpoint'), ('endpoint', 'Endpoint')):
        match = re.search(r'^' + label + r':\s*(.+)$', text, re.MULTILINE)
        if match is None:
            raise ValueError(f'Missing {label} in OpenSTA path report')
        result[field] = match.group(1).strip()
    result['met'] = result['slack_ns'] >= 0
    return result


def literal_cell_inputs(netlist: str, lib_cells: set[str]) -> dict[str, str]:
    """Read scalar literal pin connections from the mapped Verilog instances."""
    literals = {}
    identifier = r'(?:\\[^\s]+|[A-Za-z_][\w$]*)'
    instances = re.finditer(r'^\s*(' + identifier + r')\s+(' + identifier +
                           r')\s*\(\s*\n(.*?)^\s*\);', netlist, re.MULTILINE | re.DOTALL)
    for instance in instances:
        cell, name, pins = instance.groups()
        if cell not in lib_cells:
            continue
        for pin, value in re.findall(r'\.([A-Za-z_][\w$]*)\s*\(\s*1\s*\x27[bdh]([01xz])\s*\)',
                                     pins, re.IGNORECASE):
            literals[f'{name.lstrip(chr(92))}/{pin}'] = value.lower()
    return literals


def classify_coverage(report: str, module: dict | None, pin_literals: dict[str, str]) -> dict:
    """Separate literal endpoints from unconstrained signal endpoints."""
    literals = {}
    if module is not None:
        for name, port in module.get('ports', {}).items():
            if port['direction'] != 'output':
                continue
            bits = port['bits']
            offset = port.get('offset', 0)
            for position, bit in enumerate(bits):
                index = offset + (len(bits) - 1 - position if port.get('upto') else position)
                endpoint = name if len(bits) == 1 and not offset else f'{name}[{index}]'
                if bit in ('0', '1', 'x', 'z'):
                    literals[endpoint] = bit
    endpoints = []
    other_lines = []
    in_endpoints = False
    for line in report.splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r'Warning: There are \d+ unconstrained endpoints\.', line):
            in_endpoints = True
        elif in_endpoints and line.startswith('  '):
            endpoints.append(line.strip())
        else:
            in_endpoints = False
            other_lines.append(line)
    unmatched = [name for name in endpoints if name not in literals and name not in pin_literals]
    if unmatched or other_lines:
        raise RuntimeError(f'OpenSTA timing coverage is incomplete: endpoints={unmatched[:16]}, '
                           f'checks={other_lines[:8]}')
    return {
        'all_dynamic_endpoints_constrained': True,
        'constant_output_endpoints': [
            {'endpoint': name, 'value': literals[name]} for name in endpoints
            if literals.get(name) in ('0', '1')],
        'undefined_output_endpoints': [
            {'endpoint': name, 'value': literals[name]} for name in endpoints
            if literals.get(name) in ('x', 'z')],
        'constant_cell_input_endpoints': [
            {'endpoint': name, 'value': pin_literals[name]} for name in endpoints
            if pin_literals.get(name) in ('0', '1')],
        'undefined_cell_input_endpoints': [
            {'endpoint': name, 'value': pin_literals[name]} for name in endpoints
            if pin_literals.get(name) in ('x', 'z')],
        'literal_endpoints_have_no_data_timing_paths': True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sta', default='sta')
    parser.add_argument('--liberty', type=Path, required=True)
    parser.add_argument('--netlist', type=Path, required=True)
    parser.add_argument('--netlist-json', type=Path)
    parser.add_argument('--top', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--clock-port', default='clk')
    parser.add_argument('--reset-port', action='append')
    parser.add_argument('--frequency-mhz', type=float, default=150.0)
    parser.add_argument('--input-transition-ns', type=float, default=0.1)
    parser.add_argument('--output-load-ff', type=float, default=5.0)
    parser.add_argument('--wire-load-model', default='5K_hvratio_1_1')
    parser.add_argument('--library-name', default='NangateOpenCellLibrary')
    parser.add_argument('--operating-condition', default='typical')
    parser.add_argument('--report-output', action='append', default=[],
                        help='Also report setup and hold paths to this scalar output port')
    args = parser.parse_args()
    if args.frequency_mhz <= 0 or args.input_transition_ns < 0 or args.output_load_ff < 0:
        parser.error('Frequency must be positive and transition/load must be nonnegative')
    executable = shutil.which(args.sta)
    if executable is None:
        parser.error('OpenSTA executable was not found')
    executable = Path(executable).resolve()
    liberty, netlist, out = args.liberty.resolve(), args.netlist.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    lib_text = liberty.read_text()
    if re.search(r'time_unit\s*:\s*"1ns"', lib_text) is None or re.search(
            r'capacitive_load_unit\s*\(\s*1\s*,\s*ff\s*\)', lib_text, re.IGNORECASE) is None:
        raise ValueError('The analysis requires Liberty time_unit=1ns and capacitive_load_unit=(1,ff)')
    lib_cells = set(re.findall(r'\bcell\s*\(\s*"?([^\s"()]+)"?\s*\)', lib_text))
    tracked = [Path(__file__).resolve(), executable, liberty, netlist]
    top_module = None
    if args.netlist_json:
        mapped_json = args.netlist_json.resolve()
        design = json.loads(mapped_json.read_text())
        top_module = design['modules'][args.top]
        missing = sorted({c['type'] for c in top_module.get('cells', {}).values()} - lib_cells)
        if missing:
            raise ValueError(f'Mapped top contains cells absent from Liberty: {missing[:16]}')
        tracked.append(mapped_json)
    source_hashes = {str(path): sha256(path) for path in tracked}
    period = 1000.0 / args.frequency_mhz
    setup_uncertainty = period * 0.1
    hold_uncertainty = min(period * 0.05, 0.125)
    io_delay = period * 0.2
    reset_names = args.reset_port or ['rst_n']
    reset_words = ' '.join(tcl_word(name) for name in reset_names)
    script = f'''read_liberty {tcl_word(liberty)}
read_verilog {tcl_word(netlist)}
if {{![link_design {tcl_word(args.top)}]}} {{error "OpenSTA could not link the mapped design"}}
set_operating_conditions -library {tcl_word(args.library_name)} {tcl_word(args.operating_condition)}
set_wire_load_mode top
set_wire_load_model -name {tcl_word(args.wire_load_model)} -library {tcl_word(args.library_name)}
set clk_ports [get_ports {tcl_word(args.clock_port)}]
if {{[llength $clk_ports] != 1}} {{error "Expected one clock port"}}
create_clock -name CORE_CLK -period {period:.12g} $clk_ports
set_clock_transition {args.input_transition_ns:.12g} [get_clocks CORE_CLK]
set_clock_uncertainty -setup {setup_uncertainty:.12g} [get_clocks CORE_CLK]
set_clock_uncertainty -hold {hold_uncertainty:.12g} [get_clocks CORE_CLK]
set reset_ports [get_ports -quiet [list {reset_words}]]
if {{[llength $reset_ports] > 0}} {{
    set_false_path -from $reset_ports
    set_ideal_network $reset_ports
    set_input_delay -max 0 -clock CORE_CLK $reset_ports
    set_input_delay -min 0 -clock CORE_CLK $reset_ports
}}
set data_inputs {{}}
foreach port [all_inputs] {{
    if {{[lsearch -exact $clk_ports $port] < 0 && [lsearch -exact $reset_ports $port] < 0}} {{
        lappend data_inputs $port
    }}
}}
set data_outputs [all_outputs]
if {{[llength $data_inputs] > 0}} {{
    set_input_delay -max {io_delay:.12g} -clock CORE_CLK $data_inputs
    set_input_delay -min 0 -clock CORE_CLK $data_inputs
    set_input_transition {args.input_transition_ns:.12g} $data_inputs
}}
if {{[llength $data_outputs] > 0}} {{
    set_output_delay -max {io_delay:.12g} -clock CORE_CLK $data_outputs
    set_output_delay -min 0 -clock CORE_CLK $data_outputs
    set_load {args.output_load_ff:.12g} $data_outputs
}}
set reg_outputs [all_registers -output_pins]
set reg_inputs [all_registers -data_pins]
puts "STA_ANALYSIS_PORTS inputs=[llength $data_inputs] outputs=[llength $data_outputs] register_outputs=[llength $reg_outputs] register_inputs=[llength $reg_inputs]"
check_setup -verbose > {tcl_word(out/'coverage.rpt')}
report_clock_properties > {tcl_word(out/'clocks.rpt')}
write_sdc -no_timestamp -digits 9 {tcl_word(out/'constraints.sdc')}
report_check_types -all_violators -max_transition -digits 6 > {tcl_word(out/'transition_violations.rpt')}
'''
    groups = {'reg_to_reg': ('reg_outputs', 'reg_inputs'),
              'input_to_reg': ('data_inputs', 'reg_inputs'),
              'reg_to_output': ('reg_outputs', 'data_outputs'),
              'input_to_output': ('data_inputs', 'data_outputs')}
    for name, (starts, ends) in groups.items():
        for kind, delay in (('setup', 'max'), ('hold', 'min')):
            path = out / f'{name}_{kind}.rpt'
            script += f'''if {{[llength ${starts}] > 0 && [llength ${ends}] > 0}} {{
    report_checks -from ${starts} -to ${ends} -path_delay {delay} -group_count 1 -endpoint_count 1 -format full_clock_expanded -fields {{capacitance slew input_pin net}} -digits 6 > {tcl_word(path)}
}} else {{
    set f [open {tcl_word(path)} w]
    puts $f "NO_PATHS"
    close $f
}}
'''
    endpoint_files = {}
    for name in dict.fromkeys(args.report_output):
        filename = re.sub(r'[^A-Za-z0-9_]', '_', name)
        if filename in endpoint_files.values():
            raise ValueError('Requested endpoint report filenames must be distinct')
        endpoint_files[name] = filename
        script += f'''set report_endpoint [get_ports {tcl_word(name)}]
if {{[llength $report_endpoint] != 1}} {{error "Expected one requested output endpoint"}}
'''
        for kind, delay in (('setup', 'max'), ('hold', 'min')):
            path = out / f'endpoint_{filename}_{kind}.rpt'
            script += f'''report_checks -from [concat $reg_outputs $data_inputs] -to $report_endpoint -path_delay {delay} -group_count 1 -endpoint_count 1 -format full_clock_expanded -fields {{capacitance slew input_pin net}} -digits 6 > {tcl_word(path)}
'''
    script += 'puts "STA_ANALYSIS_COMPLETE"\n'
    script = 'if {[catch {\n' + script + '''} message]} {
    puts stderr "STA_ANALYSIS_ERROR $message"
    exit 1
}
exit 0
'''
    script_file = out/'analysis.tcl'
    script_file.write_text(script)
    command = [str(executable), '-no_init', '-exit', str(script_file)]
    completed = subprocess.run(command, cwd=out, capture_output=True, text=True)
    log = completed.stdout + completed.stderr
    (out/'opensta.log').write_text(log)
    forbidden = re.search(r'(?im)^.*(?:\bError:|STA_ANALYSIS_ERROR|black[- ]?box|unresolved reference).*$', log)
    if completed.returncode or 'STA_ANALYSIS_COMPLETE' not in log or forbidden:
        raise RuntimeError('OpenSTA did not complete cleanly; inspect ' + str(out/'opensta.log'))
    if source_hashes != {str(path): sha256(path) for path in tracked}:
        raise RuntimeError('Analysis inputs changed during OpenSTA execution')
    coverage = classify_coverage((out/'coverage.rpt').read_text(), top_module,
                                 literal_cell_inputs(netlist.read_text(), lib_cells))
    transition_text = (out/'transition_violations.rpt').read_text()
    transition_rows = re.findall(
        r'^\s*(\S+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+\(VIOLATED\)',
        transition_text, re.MULTILINE)
    if len(transition_rows) != transition_text.count('(VIOLATED)'):
        raise RuntimeError('OpenSTA maximum-transition report could not be parsed completely')
    transition_violations = [
        {'pin': pin, 'limit_ns': float(limit), 'transition_ns': float(transition),
         'slack_ns': float(slack)} for pin, limit, transition, slack in transition_rows]
    sdc_file = out/'constraints.sdc'
    sdc_text = sdc_file.read_text()
    if re.search(r'^set_wire_load_model\b', sdc_text, re.MULTILINE) is None:
        sdc_file.write_text(sdc_text + 'set_wire_load_model -name ' +
                           tcl_word(args.wire_load_model) + ' -library ' + tcl_word(args.library_name) + '\n')
    groups_result = {name: {kind: parse_path((out/f'{name}_{kind}.rpt').read_text())
                           for kind in ('setup', 'hold')} for name in PATH_GROUPS}
    endpoint_results = {name: {kind: parse_path((out/f'endpoint_{filename}_{kind}.rpt').read_text())
                               for kind in ('setup', 'hold')}
                        for name, filename in endpoint_files.items()}
    count = re.search(r'STA_ANALYSIS_PORTS inputs=(\d+) outputs=(\d+) register_outputs=(\d+) register_inputs=(\d+)', log)
    if count is None:
        raise RuntimeError('OpenSTA did not report path boundary counts')
    if not any(group['setup']['present'] for group in groups_result.values()):
        raise RuntimeError('OpenSTA found no constrained setup paths')
    for name, result in groups_result.items():
        setup = result['setup']
        if setup['present']:
            external = io_delay * (int(name.startswith('input_')) + int(name.endswith('_output')))
            setup['data_arrival_excluding_external_input_delay_ns'] = setup['arrival_ns'] - (
                io_delay if name.startswith('input_') else 0.0)
            setup['external_io_budget_ns'] = external
    record = {'analysis_completed': True, 'top': args.top,
              'scope': 'Mapped standard-cell block with explicit module-boundary timing constraints',
              'clock': {'frequency_mhz': args.frequency_mhz, 'period_ns': period,
                        'setup_uncertainty_ns': setup_uncertainty, 'hold_uncertainty_ns': hold_uncertainty,
                        'clock_transition_ns': args.input_transition_ns, 'clock_network': 'ideal'},
              'interfaces': {'input_delay_max_ns': io_delay, 'input_delay_min_ns': 0,
                             'output_delay_max_ns': io_delay, 'output_delay_min_ns': 0,
                             'input_transition_ns': args.input_transition_ns,
                             'output_load_ff': args.output_load_ff, 'false_path_reset_ports': reset_names},
              'wire_model': {'kind': 'Liberty statistical wire-load model', 'name': args.wire_load_model,
                             'library': args.library_name, 'extracted_parasitics': False},
              'liberty': {'path': str(liberty), 'operating_condition': args.operating_condition,
                          'time_unit': 'ns', 'capacitance_unit': 'fF'},
              'boundary_counts': dict(zip(('inputs', 'outputs', 'register_outputs', 'register_inputs'),
                                         map(int, count.groups()))),
              'path_groups': groups_result,
              'requested_endpoint_paths': endpoint_results,
              'setup_met': all(g['setup'].get('met', True) for g in groups_result.values()),
              'hold_met': all(g['hold'].get('met', True) for g in groups_result.values()),
              'max_transition_met': not transition_violations,
              'transition_violations': transition_violations,
              'transition_report': str(out/'transition_violations.rpt'),
              'source_sha256': source_hashes,
              'analysis_script_sha256': sha256(script_file),
              'constraints_sha256': sha256(sdc_file),
              'coverage_report': str(out/'coverage.rpt'),
              'timing_coverage': coverage,
              'sta_version': subprocess.check_output([str(executable), '-version'], text=True).strip(),
              'command': command}
    (out/'summary.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({key: record[key] for key in ('analysis_completed', 'top', 'setup_met', 'hold_met', 'path_groups')}, indent=2))


if __name__ == '__main__':
    main()
