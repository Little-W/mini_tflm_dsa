#!/usr/bin/env python3
"""证明标量输入相等后，以相同任意乘积验证全部下一状态。"""
from pathlib import Path
import copy,json,resource
from pyosys import libyosys
import sys,hashlib
out=Path(sys.argv[1]).resolve()
original=json.loads((out/'miter.json').read_text())
m=original['modules']['acc_transition_miter']
operands=[[m['netnames'][prefix+'.'+name]['bits'] for name in ('multiplier_a','multiplier_b')] for prefix in ('gold','gate')]
phase=[m['ports'][prefix+'_proof_phase_legal']['bits'] for prefix in ('gold','gate')]
assert phase[0]==phase[1]
model=copy.deepcopy(m)
model['ports']={n:p for n,p in model['ports'].items() if p['direction']=='input'}
next_bit=max(b for c in model['cells'].values() for conn in c['connections'].values() for b in conn if isinstance(b,int))+1
model['ports']['phase_legal']={'direction':'output','bits':phase[0]}
model['ports']['operands_equal']={'direction':'output','bits':[next_bit]}
model['cells']={n:c for n,c in model['cells'].items() if c['type']!='$assert'}
model['cells']['operand_compare']={'type':'$eq','hide_name':0,'attributes':{},'parameters':{'A_WIDTH':format(64,'032b'),'B_WIDTH':format(64,'032b'),'Y_WIDTH':format(1,'032b'),'A_SIGNED':'0','B_SIGNED':'0'},'port_directions':{'A':'input','B':'input','Y':'output'},'connections':{'A':operands[0][0]+operands[0][1],'B':operands[1][0]+operands[1][1],'Y':[next_bit]}}
(out/'operand_miter.json').write_text(json.dumps({'modules':{'acc_transition_miter':model}}))
libyosys.run_pass('read_json '+str(out/'operand_miter.json'))
libyosys.run_pass('setattr -unset keep')
libyosys.run_pass('opt -full')
libyosys.run_pass('stat')
libyosys.run_pass('sat -set phase_legal 1 -prove operands_equal 1 -verify -timeout 30')
print('OPERANDS_EQUAL_PASS',flush=True)
libyosys.run_pass('design -reset')
# 已证明相等的两个标量输入，统一替换为同一组任意值。
sub={};fresh=[]
for a,b in zip(operands[0][0]+operands[0][1],operands[1][0]+operands[1][1]):
 if not isinstance(a,int) or not isinstance(b,int):
  value=a if not isinstance(a,int) else b
  if isinstance(a,int):sub[a]=value
  if isinstance(b,int):sub[b]=value
  if not isinstance(a,int) and not isinstance(b,int):assert a==b
 else:
  value=sub.get(a,sub.get(b))
  if value is None:next_bit+=1;value=next_bit;fresh.append(value)
  assert a not in sub or sub[a]==value
  assert b not in sub or sub[b]==value
  sub[a]=sub[b]=value
for c in m['cells'].values():
 for p,d in c['port_directions'].items():
  if d=='input':c['connections'][p]=[sub.get(b,b) if isinstance(b,int) else b for b in c['connections'][p]]
for p in m['ports'].values():
 if p['direction']=='output':p['bits']=[sub.get(b,b) if isinstance(b,int) else b for b in p['bits']]
m['ports']['proof_scalar_operands']={'direction':'input','bits':fresh}
(out/'miter_operands_abstracted.json').write_text(json.dumps(original))
libyosys.run_pass('read_json '+str(out/'miter_operands_abstracted.json'))
libyosys.run_pass('setattr -unset keep')
libyosys.run_pass('opt -full')
libyosys.run_pass('cutpoint t:$mul')
libyosys.run_pass('delete -output w:gold_* w:gate_*')
libyosys.run_pass('setattr -set keep 1 w:gold_proof_phase_legal w:gate_proof_phase_legal')
libyosys.run_pass('opt -full')
libyosys.run_pass('stat')
libyosys.run_pass('write_json '+str(out/'miter_abstracted.json'))
libyosys.run_pass('sat -set gold_proof_phase_legal 1 -set gate_proof_phase_legal 1 -prove-asserts -verify -timeout 60')
print('FULL_TRANSITION_PASS',resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,flush=True)
(out/'operand_summary.json').write_text(json.dumps({'passed':True,'scalar_operand_equivalence':True,'all_state_and_output_equivalence':True,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'abstracted_miter_sha256':hashlib.sha256((out/'miter_abstracted.json').read_bytes()).hexdigest()},indent=2)+'\n')
