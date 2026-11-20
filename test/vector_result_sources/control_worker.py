#!/usr/bin/env python3
"""保留真实配置和控制状态，证明全部结果写入来源互斥。"""
from pathlib import Path
import json
import resource
import sys
from pyosys import libyosys


def check_drivers(module):
    driven = {}
    for name, cell in module['cells'].items():
        for port, direction in cell['port_directions'].items():
            if direction != 'output':
                continue
            for bit in cell['connections'][port]:
                if isinstance(bit, int):
                    assert bit not in driven, (bit, driven.get(bit), name, port)
                    driven[bit] = (name, port)


out = Path(sys.argv[1]).resolve()
module = json.loads((out / 'control.json').read_text())['modules']['vector_domain_control']
root_names = ('state', 'load_kind', 'q_active', 'proof_opcode', 'proof_min', 'proof_max', 'proof_offset', 'u_config_check.state', 'u_config_check.error')
roots = {b for name in root_names for b in module['netnames'][name]['bits'] if isinstance(b, int)}
drivers = {}
for name, cell in module['cells'].items():
    for port, direction in cell['port_directions'].items():
        if direction == 'output':
            for bit in cell['connections'][port]:
                if isinstance(bit, int):
                    drivers.setdefault(bit, []).append(name)
keep = set()
pending = list(roots)
seen = set()
while pending:
    bit = pending.pop()
    if not isinstance(bit, int) or bit in seen:
        continue
    seen.add(bit)
    for name in drivers.get(bit, []):
        cell = module['cells'][name]
        if 'dff' in cell['type'].lower():
            keep.add(name)
        else:
            pending.extend(b for p, d in cell['port_directions'].items()
                           if d == 'input' for b in cell['connections'][p])
cut = [name for name, cell in module['cells'].items()
       if 'dff' in cell['type'].lower() and name not in keep]
for name in cut:
    cell = module['cells'][name]
    bits = cell['connections']['Q']
    module['cells'][name] = {'hide_name': 1, 'type': '$anyseq',
        'parameters': {'WIDTH': format(len(bits), '032b')}, 'attributes': {},
        'port_directions': {'Y': 'output'}, 'connections': {'Y': bits}}
check_drivers(module)
(out / 'register_abstracted.json').write_text(json.dumps({'modules': {'vector_domain_control': module}}))
libyosys.run_pass('read_json ' + str(out / 'register_abstracted.json'))
libyosys.run_pass('opt -full')
libyosys.run_pass('write_json ' + str(out / 'control_mode.json'))
module = json.loads((out / 'control_mode.json').read_text())['modules']['vector_domain_control']
dependent = {b for name in keep if name in module['cells']
             for b in module['cells'][name]['connections']['Q'] if isinstance(b, int)}
dependent.update(b for name in ('proof_cfg_opcode', 'rst_n', 'start')
                 for b in module['netnames'][name]['bits'] if isinstance(b, int))
changed = True
while changed:
    changed = False
    for name, cell in module['cells'].items():
        if 'dff' in cell['type'].lower() or cell['type'].startswith('$any'):
            continue
        ins = {b for p, d in cell['port_directions'].items() if d == 'input'
               for b in cell['connections'][p] if isinstance(b, int)}
        outs = {b for p, d in cell['port_directions'].items() if d == 'output'
                for b in cell['connections'][p] if isinstance(b, int)}
        if dependent.intersection(ins) and not outs <= dependent:
            dependent.update(outs)
            changed = True
boolean_cut = []
for name, cell in module['cells'].items():
    if ('dff' in cell['type'].lower() or cell['type'].startswith('$any') or
            cell['type'] in ('$assert', '$check', '$assume')):
        continue
    outs = [b for p, d in cell['port_directions'].items() if d == 'output'
            for b in cell['connections'][p] if isinstance(b, int)]
    predicate = cell['type'] in ('$eq', '$ne', '$lt', '$le', '$gt', '$ge', '$reduce_and', '$reduce_or', '$reduce_bool')
    if predicate and len(outs) == 1 and not dependent.intersection(outs):
        boolean_cut.append(name)
for name in boolean_cut:
    cell = module['cells'][name]
    bits = [b for port, direction in cell['port_directions'].items()
            if direction == 'output' for b in cell['connections'][port]]
    module['cells'][name] = {'hide_name': 1, 'type': '$anyseq',
        'parameters': {'WIDTH': format(len(bits), '032b')}, 'attributes': {},
        'port_directions': {'Y': 'output'}, 'connections': {'Y': bits}}
check_drivers(module)
(out / 'predicate_abstracted.json').write_text(json.dumps({'modules': {'vector_domain_control': module}}))
libyosys.run_pass('design -reset')
libyosys.run_pass('read_json ' + str(out / 'predicate_abstracted.json'))
libyosys.run_pass('opt -full')
libyosys.run_pass('write_rtlil ' + str(out / 'control_abstracted.il'))
libyosys.run_pass('stat')
(out / 'abstraction.json').write_text(json.dumps({
    'preserved_registers': sorted(keep), 'abstracted_registers': cut,
    'abstracted_data_predicates': boolean_cut}, indent=2) + '\n')
libyosys.run_pass('sat -seq 2 -tempinduct -maxsteps 24 -set-init-zero -prove-asserts -verify '
                 '-timeout 30 -show state -show proof_opcode -show proof_min -show proof_max -show proof_offset -show u_config_check.state -show u_config_check.error -show rst_n -show start')
summary = {'passed': True, 'input_constraints': None, 'actual_vector_state_machine': True,
           'unique_output_drivers': True,
           'preserved_register_cells': len(keep), 'abstracted_register_cells': len(cut),
           'abstracted_data_predicates': len(boolean_cut),
           'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
(out / 'control_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary), flush=True)
