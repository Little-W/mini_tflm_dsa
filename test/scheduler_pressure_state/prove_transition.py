#!/usr/bin/env python3
"""用实际寄存器状态对应关系证明调度器的输出和一步状态转移。"""
from pathlib import Path
import argparse,hashlib,json,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/control/ps_window_scheduler.sv')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare(config):
 from pyosys import libyosys as ys
 out=Path(config['out']);design=ys.Design();commands=[]
 def run(c):commands.append(c);ys.run_pass(c,design)
 models={};saved={}
 for label in ['reference','current']:
  src=out/'inputs'/label
  files=[src/RTL]+sorted(p for p in (src/'rtl/common').glob('*')if p.suffix in ['.sv','.v'])
  options=' '.join(f'-G{k}={v}'for k,v in config['parameters'].items())
  run(f'read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 {options} --top ps_window_scheduler '+shlex.join(map(str,files)))
  run('prep -top ps_window_scheduler -flatten; memory_map; opt_clean')
  run(f'rename ps_window_scheduler {label}')
  run('write_json '+shlex.quote(str(out/f'{label}.json')))
  run('write_rtlil '+shlex.quote(str(out/f'{label}.il')))
  models[label]=json.loads((out/f'{label}.json').read_text())['modules'][label]
  saved[label]=set(b for cell in models[label]['cells'].values()if 'ff' in cell['type'].lower()for b in cell['connections'].get('Q',[])if isinstance(b,int))
  run('design -reset')
 names=set(models['reference']['netnames'])&set(models['current']['netnames'])
 names=sorted(names,key=lambda n:(n.startswith('$'),-len(models['reference']['netnames'][n]['bits']),n))
 seen={'reference':set(),'current':set()};selected=[]
 for name in names:
  nets={label:models[label]['netnames'][name]for label in models};width=len(nets['reference']['bits'])
  if width!=len(nets['current']['bits']):continue
  for i in range(width):
   bits={label:nets[label]['bits'][i]for label in models}
   if all(bits[label]in saved[label]and bits[label]not in seen[label]for label in models):
    selected.append({'name':name,'bit':i,'width':width,'mapped_bits':bits})
    for label in models:seen[label].add(bits[label])
 missing=saved['reference']-seen['reference']
 if missing:raise RuntimeError('参考状态未全部对应：'+str(sorted(missing)))
 extra=saved['current']-seen['current']
 allowed=set(b for n in ['command_buffer_recoverable','command_buffer_opening']for b in models['current']['netnames'][n]['bits'])
 if extra!=allowed:raise RuntimeError('新增状态集合不符：'+str(extra))
 for label in models:
  text=(out/f'{label}.il').read_text();end=text.rfind('\nend\n')
  body=f'\n  wire width {len(selected)} output {len(models[label]["ports"])+1} \\formal_shared_state\n'
  sigs=['\\'+r['name']+(f' [{r["bit"]}]'if r['width']>1 else'')for r in selected]
  body+='  connect \\formal_shared_state { '+' '.join(sigs)+' }\n'
  target=out/f'{label}_state.il';target.write_text(text[:end]+body+text[end:])
  run('read_rtlil '+shlex.quote(str(target)))
 run('async2sync; opt_clean')
 run('miter -equiv -make_outcmp -make_outputs reference current equivalent')
 run('prep -top equivalent -flatten; opt_clean')
 run('write_rtlil '+shlex.quote(str(out/'transition_miter.il')))
 run('sat -verify -seq 1 -timeout 30 -set in_rst_n 0 -set cmp_formal_shared_state 1 -prove trigger 0')
 run('sat -verify -seq 1 -timeout 30 -set cmp_formal_shared_state 1 -set gate_formal_hold_ok 1 -prove trigger 0')
 text=(out/'transition_miter.il').read_text();marks={}
 import re
 for line in text.splitlines():
  if line.lstrip().startswith('wire'):
   for name in ['gold_formal_shared_state','gate_formal_shared_state']:
    if line.endswith('# \\'+name):
     match=re.search(r'wire width (\d+) output \d+ (\S+)',line);marks[name]=(int(match[1]),match[2])
    elif line.split()[-1]=='\\'+name:
     match=re.search(r'wire width (\d+) output \d+ (\S+)',line);marks[name]=(int(match[1]),match[2])
 assert marks['gold_formal_shared_state'][0]==len(selected)==marks['gate_formal_shared_state'][0]
 addition='';groups=[]
 for group,start in enumerate(range(0,len(selected),128)):
  end=min(start+128,len(selected))-1;width=end-start+1;name=f'formal_group_{group}'
  addition+=f"\n  wire \\{name}\n  cell $eq \\{name}_compare\n    parameter \\A_SIGNED 0\n    parameter \\B_SIGNED 0\n    parameter \\A_WIDTH {width}\n    parameter \\B_WIDTH {width}\n    parameter \\Y_WIDTH 1\n    connect \\A {marks['gold_formal_shared_state'][1]} [{end}:{start}]\n    connect \\B {marks['gate_formal_shared_state'][1]} [{end}:{start}]\n    connect \\Y \\{name}\n  end\n"
  groups.append(dict(group=group,first_bit=start,last_bit=end,bits=width,signal=name))
 stop=text.rfind('\nend\n');assert stop>=0
 grouped=out/'transition_groups.il';grouped.write_text(text[:stop]+addition+text[stop:])
 run('design -reset');run('read_rtlil '+shlex.quote(str(grouped)));run('hierarchy -top equivalent')
 for group in groups:
  run('sat -verify -seq 2 -timeout 45 -set-at 1 cmp_formal_shared_state 1 -set-at 1 gate_formal_hold_ok 1 -prove '+group['signal']+' 1 -prove-skip 1')
  group['passed']=True
 assert sum(group['bits']for group in groups)==len(selected)
 (out/'groups.json').write_text(json.dumps({'state_bits':len(selected),'groups':groups},indent=2)+'\n')
 (out/'state_mapping.json').write_text(json.dumps({'common_state_bits':len(selected),'reference_state_bits':len(saved['reference']),'current_state_bits':len(saved['current']),'added_state_bits':len(extra),'register_bits':selected},indent=2)+'\n')
 (out/'operations.json').write_text(json.dumps({'commands':commands},indent=2)+'\n')
 print(json.dumps({'passed':True,'common_state_bits':len(selected),'added_state_bits':len(extra)}),flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--worker',type=Path);p.add_argument('--source-root',type=Path);p.add_argument('--reference-root',type=Path);p.add_argument('--out',type=Path);p.add_argument('--profiles',nargs='+',default=['4:4:4','16:16:32']);a=p.parse_args()
 if a.worker:prepare(json.loads(a.worker.read_text()));return
 a.out.mkdir(parents=True,exist_ok=True);profiles=[]
 for profile in a.profiles:
  size,frames,reuse=map(int,profile.split(':'));out=a.out/profile.replace(':','_');out.mkdir(exist_ok=True);sources={}
  for label,source in [('reference',a.reference_root),('current',a.source_root)]:
   for file in [source/RTL,*sorted(p for p in (source/'rtl/common').glob('*')if p.suffix in ['.sv','.v'])]:
    dst=out/'inputs'/label/file.relative_to(source);dst.parent.mkdir(parents=True,exist_ok=True);text=file.read_text();sources[str(file)]=digest(file)
    if file==source/RTL:
     text=text.replace('lookahead_count_k);','lookahead_count_k,\n    output logic formal_hold_ok);',1)
     expr='1\'b1'if label=='reference'else '''!(command_active && command_buffer_valid) &&
        (!command_active || phase == OPENING || phase == SWEEPING || phase == DRAINING) &&
        (!command_buffer_valid || (candidate_found &&
        command_buffer_recoverable == (!frame_final && protected_valid && live[protected_id] &&
            protected_id != command_buffer_id && (phase == OPENING || phase == SWEEPING)) &&
        command_buffer_opening == (phase == OPENING)))'''
     text=text.replace('`ifdef NPU_SIM_ASSERT','    assign formal_hold_ok = '+expr+';\n\n`ifdef NPU_SIM_ASSERT',1)
    dst.write_text(text)
  config={'out':str(out),'parameters':{'SIZE':size,'FRAME_COUNT':frames,'MAX_REUSE_TILES':reuse},'source_sha256':sources};cfg=out/'config.json';cfg.write_text(json.dumps(config,indent=2)+'\n')
  log=out/'proof.log'
  with log.open('w')as f:r=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(cfg)],stdout=f,stderr=subprocess.STDOUT,timeout=240)
  if r.returncode:raise RuntimeError(str(log))
  mapping=json.loads((out/'state_mapping.json').read_text());row=dict(parameters=config['parameters'],passed=True,common_state_bits=mapping['common_state_bits'],added_state_bits=mapping['added_state_bits'],log_sha256=digest(log),log=str(log));profiles.append(row);print(json.dumps(row),flush=True)
 (a.out/'summary.json').write_text(json.dumps({'passed':True,'profiles':profiles,'unconstrained_external_inputs':True,'proof_method':'实际模块的公共寄存器状态对应、已独立证明的新状态不变量、完整公开输出与一步状态转移 SAT'},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
