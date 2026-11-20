#!/usr/bin/env python3
"""逐位对应全部寄存器，比较完整源的下一状态和公开输出。"""
from pathlib import Path
import json,hashlib,resource
from pyosys import libyosys
import sys,subprocess
out=Path(sys.argv[1]).resolve()
labels=('reference','candidate')
modules=[json.loads((out/(n+'.json')).read_text())['modules']['acc_'+n] for n in labels]
qbits=[{b for c in m['cells'].values() if 'dff' in c['type'].lower() for b in c['connections']['Q'] if isinstance(b,int)} for m in modules]
shared=set(modules[0]['netnames'])&set(modules[1]['netnames']);mapping={};reverse={};names={}
for name in sorted(shared):
 if name.startswith('$') or any(m['netnames'][name]['hide_name'] for m in modules):continue
 a,b=[m['netnames'][name]['bits'] for m in modules]
 if len(a)!=len(b):continue
 for index,(x,y) in enumerate(zip(a,b)):
  if x in qbits[0] and y in qbits[1]:
   assert x not in mapping or mapping[x]==y
   assert y not in reverse or reverse[y]==x
   mapping[x]=y;reverse[y]=x;names.setdefault(x,(name,index))
assert len(mapping)==len(qbits[0]) and len(reverse)==len(qbits[1])
order=sorted(qbits[0],key=lambda b:names[b]);output_bits=[]
for design_index,(label,m) in enumerate(zip(labels,modules)):
 next_bit=max(b for c in m['cells'].values() for p in c['connections'].values() for b in p if isinstance(b,int))+1
 next_values={}
 clock=m['ports']['clk']['bits']
 ffs=[(n,c) for n,c in m['cells'].items() if 'dff' in c['type'].lower()]
 for ff_index,(name,cell) in enumerate(ffs):
  assert cell['connections']['CLK']==clock
  assert int(cell['parameters']['CLK_POLARITY'],2)==1
  d=cell['connections']['D'];q=cell['connections']['Q']
  if cell['type']=='$aldff':
   load=cell['connections']['ALOAD'];reset=cell['connections']['AD']
   positive=int(cell['parameters']['ALOAD_POLARITY'],2)
   y=list(range(next_bit,next_bit+len(q)));next_bit+=len(q)
   m['cells'][f'proof_reset_mux_{ff_index}']={'hide_name':0,'type':'$mux',
     'parameters':{'WIDTH':format(len(q),'032b')},'attributes':{},
     'port_directions':{'A':'input','B':'input','S':'input','Y':'output'},
     'connections':{'A':d if positive else reset,'B':reset if positive else d,'S':load,'Y':y}}
   d=y
  else:assert cell['type']=='$dff',cell['type']
  for bit,value in zip(q,d):
   assert bit not in next_values
   next_values[bit]=value
  del m['cells'][name]
 state_order=order if design_index==0 else [mapping[b] for b in order]
 m['ports']['proof_current_state']={'direction':'input','bits':state_order}
 m['ports']['proof_next_state']={'direction':'output','bits':[next_values[b] for b in state_order]}
 for net in m['netnames'].values():net.get('attributes',{}).pop('init',None)
 m['attributes']['top']='0'
 p=out/(label+'_transition.json');p.write_text(json.dumps({'modules':{'acc_'+label:m}}))
 libyosys.run_pass('read_json '+str(p))
libyosys.run_pass('miter -equiv -make_outputs -make_assert -flatten acc_reference acc_candidate acc_transition_miter')
libyosys.run_pass('hierarchy -top acc_transition_miter')
libyosys.run_pass('opt -full')
libyosys.run_pass('stat')
libyosys.run_pass('write_json '+str(out/'miter.json'))
m=json.loads((out/'miter.json').read_text())['modules']['acc_transition_miter']
phase_names=[n for n in m['ports'] if n.endswith('proof_phase_legal')]
assert len(phase_names)==2,phase_names
libyosys.run_pass('design -reset')
subprocess.run([sys.executable,str(Path(__file__).with_name('operand_worker.py')),str(out)],check=True)
summary=json.loads((out/'operand_summary.json').read_text())
summary.update({'registered_state_bits':len(order),'register_cells_each':len(ffs),
 'primary_outputs_compared':len([p for p in modules[0]['ports'].values() if p['direction']=='output'])-2,
 'current_state_correspondence':'Every registered bit paired through an identical public RTL net name and bit index',
 'condition':'Three phase invariants proven on actual control logic with overapproximated data',
 'preparation_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
 'miter_sha256':hashlib.sha256((out/'miter.json').read_bytes()).hexdigest()})
(out/'transition_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print('ACC_TRANSITION_PASS',json.dumps(summary),flush=True)
