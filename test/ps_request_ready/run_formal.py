#!/usr/bin/env python3
"""证明已保存的 PS 请求资格与完整帧存储的逐周期行为。"""
import argparse,hashlib,json,re,runpy,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/ps_compact/ps_frame_store.sv'
CASES=runpy.run_path(str(ROOT/'test/ps_frame_ready/run_full.py'))['CASES']
sys.path.insert(0,str(ROOT/'test/ia_timing'))
from run_interface import port_declarations
COMBINATIONAL=('ready_prepare_context','ready_prepare_idle','ready_prepare_complete','ready_selected','u_frame_ready','prepare_state_eligible','prepare_read_state_eligible')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def instrument(source,label):
 for name in COMBINATIONAL:source=re.sub(r'\b'+name+r'\b',label+'_'+name,source)
 if label=='current':
  added='\n    // 完整实际模块已独立归纳证明这两项内部状态关系。\n    always_comb begin\n        assume(request_qualified_q == (configuration_ready && request_pending_q && request_q.legal && request_fits_q));\n        assume(!request_pending_q || (request_initial_or_other_q == (request_q.init || request_q.id != frame_id_q)));\n    end\n'
  source=source.replace('\nendmodule',added+'\nendmodule',1)
 return source

def property_model(source):
 ports=port_declarations(source)
 head=source[source.index('module ps_frame_store #('):source.index(') (')].replace('module ps_frame_store','module request_property_top',1)
 parameters=re.findall(r'parameter (?:integer|bit) (\w+)',head)
 wrapper=head+') (\n'+',\n'.join(f'input {kind} {name} {unpacked}'for direction,kind,name,unpacked in ports if direction=='input')+',\noutput wire [1:0] proof_properties\n);\n'
 wrapper+='ps_frame_store #('+','.join(f'.{p}({p})'for p in parameters)+') u_dut('+','.join(f'.{name}({name})'for direction,kind,name,unpacked in ports if direction=='input')+',.proof_properties(proof_properties));\nendmodule\n'
 source=source.replace('\n);',',\n output wire [1:0] proof_properties\n);',1).replace('\nendmodule','''
 assign proof_properties[0] = request_qualified_q == (configuration_ready && request_pending_q && request_q.legal && request_fits_q);
 assign proof_properties[1] = !request_pending_q || (request_initial_or_other_q == (request_q.init || request_q.id != frame_id_q));
endmodule''',1)
 return source+wrapper

def run(script,log):
 with log.open('w')as f:subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=600)
 return log.read_text()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',default='d7cb67be');p.add_argument('--source-root',type=Path,default=ROOT);p.add_argument('--cases',nargs='+',choices=tuple(CASES),default=list(CASES));p.add_argument('--mode',choices=['generic','fpga'],default='generic');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 root=a.source_root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
 actual=(root/SOURCE).read_text();reference=subprocess.check_output(['git','show',a.reference+':'+SOURCE],cwd=ROOT,text=True)
 files=resolve([root/SOURCE],root);hashes={str(f):digest(f)for f in files}
 definitions=['-USYNTHESIS','-UXILINX_FPGA']if a.mode=='generic'else['-DSYNTHESIS=1','-DXILINX_FPGA=1']
 model=out/'property.sv';model.write_text(property_model(actual));sources=resolve([model],root)
 references=out/'reference.sv';references.write_text(instrument(reference,'reference'))
 current=out/'current.sv';current.write_text(instrument(actual,'current'))
 records=[]
 for case in a.cases:
  params=CASES[case][2];folder=out/case;folder.mkdir(exist_ok=True)
  options=definitions+[f'-G{k}={v}'for k,v in params.items()]
  script,log=folder/'invariant.ys',folder/'invariant.log'
  script.write_text('read_slang --top request_property_top '+shlex.join(options+list(map(str,sources)))+'\nprep -top request_property_top -flatten\nmemory_map\nasync2sync\nopt -full\nsat -verify -tempinduct -seq 2 -maxsteps 8 -set-at 1 rst_n 0 -prove proof_properties 3\n')
  text=run(script,log);assert 'Induction step proven: SUCCESS!'in text
  invariant_hash=digest(log)
  commands=[]
  for label,path in [('reference',references),('current',current)]:
   dependencies=resolve([path],root)
   commands+=['read_slang --top ps_frame_store '+shlex.join(options+list(map(str,dependencies))),'prep -top ps_frame_store -flatten','memory_map','async2sync','opt_clean',f'rename ps_frame_store {label}',f'design -stash {label}']
  commands+=['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1','opt_clean','equiv_induct -set-assumes -seq 2','equiv_status -assert']
  script,log=folder/'equivalent.ys',folder/'equivalent.log';script.write_text('\n'.join(commands)+'\n')
  text=run(script,log);assert 'Equivalence successfully proven!'in text
  count=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text);assert count and int(count[2])==0
  row=dict(case=case,parameters=params,passed=True,equivalent_bits=int(count[1]),invariant_log_sha256=invariant_hash,parent_log_sha256=digest(log));records.append(row)
  print('PS_REQUEST_READY_PASS',a.mode,case,row['equivalent_bits'],flush=True)
  assert hashes=={str(f):digest(f)for f in files}
  (out/'summary.json').write_text(json.dumps(dict(passed=len(records)==len(a.cases),reference=a.reference,mode=a.mode,definitions=definitions,source_sha256=hashes,source_input_constraints=None,invariant_start='首次采样复位，随后全部外部输入及复位自由',parent_scope='全部公开输出、共同状态和存储内容；采用此前从完整实际模块独立证明的两项内部状态关系',parent_state_relations=['request_qualified_q == (configuration_ready && request_pending_q && request_q.legal && request_fits_q)','request_pending_q -> (request_initial_or_other_q == (request_q.init || request_q.id != frame_id_q))'],profiles=records,test_sha256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
