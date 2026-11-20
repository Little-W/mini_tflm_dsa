#!/usr/bin/env python3
"""使用实际状态转移证明串行读取用途，数据条件保持任意。"""
from pathlib import Path
import json
from pyosys import libyosys
import sys,resource
out=Path(sys.argv[1]).resolve()
m=json.loads((out/'control_cells.json').read_text())['modules']['vector_engine_control_proof']
roots=[b for n in ('state','load_kind','global_pool') for b in m['netnames'][n]['bits']]+m['netnames']['proof_opcode']['bits']
drivers={}
for n,c in m['cells'].items():
 for p,d in c['port_directions'].items():
  if d=='output':
   for b in c['connections'][p]:
    if isinstance(b,int):drivers.setdefault(b,[]).append(n)
keep=set();seen=set();pending=list(roots)
while pending:
 b=pending.pop()
 if not isinstance(b,int) or b in seen:continue
 seen.add(b)
 for n in drivers.get(b,[]):
  c=m['cells'][n]
  if 'dff' in c['type'].lower():keep.add(n);continue
  for p,d in c['port_directions'].items():
   if d=='input':pending.extend(c['connections'][p])
cut=[n for n,c in m['cells'].items() if 'dff' in c['type'].lower() and n not in keep]
libyosys.run_pass('read_rtlil '+str(out/'control.il'))
libyosys.run_pass('cutpoint '+' '.join('c:'+n for n in cut))
libyosys.run_pass('opt -full')
libyosys.run_pass('write_json '+str(out/'control_mode_cells.json'))
m=json.loads((out/'control_mode_cells.json').read_text())['modules']['vector_engine_control_proof']
dependent=set(x for n in keep if n in m['cells'] for x in m['cells'][n]['connections']['Q'] if isinstance(x,int))
dependent.update(x for x in m['netnames']['proof_cfg_opcode']['bits'] if isinstance(x,int))
dependent.update(x for n in ('rst_n','start') for x in m['netnames'][n]['bits'] if isinstance(x,int))
changed=True
while changed:
 changed=False
 for n,c in m['cells'].items():
  if 'dff' in c['type'].lower() or c['type'].startswith('$any'):continue
  ins=[x for p,d in c['port_directions'].items() if d=='input' for x in c['connections'][p] if isinstance(x,int)]
  outs=[x for p,d in c['port_directions'].items() if d=='output' for x in c['connections'][p] if isinstance(x,int)]
  if dependent.intersection(ins) and not set(outs)<=dependent:dependent.update(outs);changed=True
boolean_cut=[]
for n,c in m['cells'].items():
 if 'dff' in c['type'].lower() or c['type'].startswith('$any') or c['type'] in ('$assert','$check','$assume'):continue
 outs=[x for p,d in c['port_directions'].items() if d=='output' for x in c['connections'][p] if isinstance(x,int)]
 if len(outs)==1 and not dependent.intersection(outs):boolean_cut.append(n)
libyosys.run_pass('cutpoint '+' '.join('c:'+n for n in boolean_cut))
libyosys.run_pass('opt -full')
libyosys.run_pass('write_rtlil '+str(out/'control_mode.il'))
libyosys.run_pass('stat')
(out/'control_abstraction.json').write_text(json.dumps({'preserved_registers':sorted(keep),'abstracted_registers':cut,'abstracted_data_predicates':boolean_cut},indent=2)+'\n')
libyosys.run_pass('sat -seq 2 -tempinduct -maxsteps 24 -set-init-zero -prove-asserts -verify -timeout 10 -dump_vcd '+str(out/'control_mode_counterexample.vcd'))

summary={'passed':True,'method':'Induction on actual control after replacing other register state and independent data predicates by unconstrained values','preserved_register_cells':len(keep),'abstracted_register_cells':len(cut),'abstracted_data_predicates':len(boolean_cut),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
(out/'control_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary),flush=True)
