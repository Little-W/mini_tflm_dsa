#!/usr/bin/env python3
"""保存实际配置控制与范围状态，将无关数据状态扩展为任意值。"""
from pathlib import Path
import json
import resource
import sys
from pyosys import libyosys

out = Path(sys.argv[1]).resolve()
module = json.loads((out/'control.json').read_text())['modules']['checked_ranges_control']
required = {'state', 'c', 'global_pool', 'input_range_mode', 'proof_check_context',
            'proof_config_success', 'proof_ranges_seen', 'proof_ranges_ok',
            'proof_cache_active', 'proof_cache_clear'}
required.update(name for name in module['netnames'] if name.startswith('u_config_check.') and
                not name.startswith(('u_config_check.multiply_low', 'u_config_check.multiply_high')))
roots = {bit for name in required for bit in module['netnames'].get(name, {}).get('bits', [])
         if isinstance(bit, int)}
drivers = {}
for name, cell in module['cells'].items():
    for port, direction in cell['port_directions'].items():
        if direction == 'output':
            for bit in cell['connections'][port]:
                if isinstance(bit, int): drivers.setdefault(bit, []).append(name)
keep, seen, pending = set(), set(), list(roots)
while pending:
    bit = pending.pop()
    if not isinstance(bit, int) or bit in seen: continue
    seen.add(bit)
    for name in drivers.get(bit, []):
        cell = module['cells'][name]
        if 'dff' in cell['type'].lower(): keep.add(name)
        else:
            pending.extend(b for port, direction in cell['port_directions'].items() if direction == 'input'
                           for b in cell['connections'][port])
product_bits = {bit for signal in ('u_config_check.multiply_low', 'u_config_check.multiply_high')
                for bit in module['netnames'].get(signal, {}).get('bits', []) if isinstance(bit, int)}
for name in list(keep):
    bits = {bit for bit in module['cells'][name]['connections']['Q'] if isinstance(bit, int)}
    if bits and bits <= product_bits:
        keep.remove(name)
cut = []
for name, cell in list(module['cells'].items()):
    if 'dff' in cell['type'].lower() and name not in keep:
        bits = cell['connections']['Q']
        module['cells'][name] = {'hide_name': 1, 'type': '$anyseq',
            'parameters': {'WIDTH': format(len(bits), '032b')}, 'attributes': {},
            'port_directions': {'Y': 'output'}, 'connections': {'Y': bits}}
        cut.append(name)
(out/'abstraction.json').write_text(json.dumps({'preserved': sorted(keep), 'abstracted': sorted(cut)}, indent=2)+'\n')
abstracted = out/'abstracted.json'
abstracted.write_text(json.dumps({'modules': {'checked_ranges_control': module}})+'\n')
libyosys.run_pass('read_json '+str(abstracted))
libyosys.run_pass('opt -full; memory_map; opt -full')
libyosys.run_pass('check -assert')
libyosys.run_pass('sat -seq 2 -tempinduct -maxsteps 8 -set-at 1 rst_n 0 -prove-asserts -verify '
                 '-timeout 60 -show state -show u_config_check.state -show u_config_check.range_index '
                 '-show proof_check_context -show proof_config_success -show proof_ranges_seen '
                 '-show proof_ranges_ok -show proof_cache_active -show proof_cache_clear '
                 '-show config_check_error -show rst_n -show start -dump_vcd '+str(out/'witness.vcd'))
summary = {'passed': True, 'input_data_constraints': None, 'initial_reset_cycle': 1,
           'initial_unreset_data': 'arbitrary', 'actual_state_machines': True,
           'preserved_register_cells': sorted(keep), 'abstracted_register_cells': sorted(cut),
           'properties': ['配置成功时全部范围已经检查', '长度高位与地址回绕检查保持',
                          '配置消费时全部起止地址与原表达式相同', '新配置及复位清除检查归属',
                          '四个槽位的分配优先级与未启用范围零值保持',
                          '检查启动、错误完成与复位同步清空保存范围'],
           'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
(out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'passed': True, 'peak_rss_bytes': summary['peak_rss_bytes']}), flush=True)
