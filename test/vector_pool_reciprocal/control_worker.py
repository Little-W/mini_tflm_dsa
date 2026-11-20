#!/usr/bin/env python3
"""保留实际状态与分母更新，其余数据状态取任意值，证明消费边沿的读取关系。"""
from pathlib import Path
import json
import resource
import sys
from pyosys import libyosys

out = Path(sys.argv[1]).resolve()
module = json.loads((out/'control.json').read_text())['modules']['reciprocal_control']
roots = {bit for name in ('state', 'valid_taps', 'proof_sampled_taps')
         for bit in module['netnames'][name]['bits'] if isinstance(bit, int)}
drivers = {}
for name, cell in module['cells'].items():
    for port, direction in cell['port_directions'].items():
        if direction == 'output':
            for bit in cell['connections'][port]:
                if isinstance(bit, int):
                    drivers.setdefault(bit, []).append(name)
keep, seen = set(), set()
pending = list(roots)
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
            pending.extend(b for port, direction in cell['port_directions'].items()
                           if direction == 'input' for b in cell['connections'][port])
cut = []
for name, cell in list(module['cells'].items()):
    if 'dff' in cell['type'].lower() and name not in keep:
        bits = cell['connections']['Q']
        module['cells'][name] = {'hide_name': 1, 'type': '$anyseq',
            'parameters': {'WIDTH': format(len(bits), '032b')}, 'attributes': {},
            'port_directions': {'Y': 'output'}, 'connections': {'Y': bits}}
        cut.append(name)
abstracted = out/'abstracted.json'
abstracted.write_text(json.dumps({'modules': {'reciprocal_control': module}})+'\n')
libyosys.run_pass('read_json '+str(abstracted))
libyosys.run_pass('opt -full')
libyosys.run_pass('check -assert')
libyosys.run_pass('sat -seq 2 -tempinduct -maxsteps 8 -set-init-zero -prove-asserts -verify '
                 '-timeout 30 -show state -show valid_taps -show proof_sampled_taps -show rst_n -show start')
summary = {'passed': True, 'input_constraints': None,
           'actual_state_machine': True, 'actual_denominator_updates': True,
           'preserved_register_cells': sorted(keep), 'abstracted_register_cells': len(cut),
           'property': 'rst_n && state==AVG_START 时 valid_taps 等于前一时钟边沿读取的分母',
           'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
(out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(summary), flush=True)
