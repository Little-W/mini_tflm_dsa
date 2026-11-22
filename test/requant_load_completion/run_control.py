#!/usr/bin/env python3
"""比较完整量化装载控制、参数存储状态与 DMA 端口。"""
from pathlib import Path
import argparse,hashlib,json,re,runpy,shlex,subprocess,sys
from support import ROOT as REPO, reference_root
RTL=Path('rtl/npu/writeback/vec_requant.sv')
helper=runpy.run_path(str(REPO/'test/requant_parameter_ports/run_formal.py'))

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def controller(source,label):
 raw=source.read_text();text=helper['control_wrapper'](raw)
 text=text.replace('    output logic load_quant_req,quant_params_valid,','    output wire formal_command_more,\n    output wire [2:0] formal_command_invariants,\n    output logic load_quant_req,quant_params_valid,')
 if label=='reference':
  first=raw.index('  // 末拍比较并行计算');end=raw.index('\n  // ----------------------------',first)
  extra=raw[first:end].replace('g_load_completion_compare','g_formal_command_compare').replace('g_generic_load_completion_compare','g_formal_generic_command_compare')
  extra=re.sub(r'\bbeats_expect\b','formal_command_words',extra)
  extra=re.sub(r'\bload_has_more\b','formal_more_comparison',extra)
  extra='''  logic formal_more_comparison;
  wire [VLEN_CNT_W-1:0] formal_command_words = cmd_busy ? beats_expect : cmd_beats_expect_r;
'''+extra+'''
  assign formal_command_more = (cmd_busy || cmd_valid_r) && formal_more_comparison;
  assign formal_command_invariants = 3'b111;
'''
 else:
  extra='''  assign formal_command_more = (cmd_busy || cmd_valid_r) && cmd_has_more_r;
  assign formal_command_invariants = {!(cmd_busy && cmd_valid_r),
      !(cmd_busy || cmd_valid_r) || ((state == LOAD) && load_meta_valid),
      !cmd_busy || (beats_expect == cmd_beats_expect_r)};
'''
 return text.replace('endmodule',extra+'\nendmodule')

def execute(folder,name,commands):
 ys=folder/(name+'.ys');log=folder/(name+'.log');ys.write_text('\n'.join(commands)+'\n')
 with log.open('w') as f:r=subprocess.run([sys.executable,str(REPO/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],cwd=REPO,stdout=f,stderr=subprocess.STDOUT,timeout=600)
 if r.returncode:raise RuntimeError(str(log)+'\n'+log.read_text()[-4500:])
 return log

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--source-root',type=Path,default=REPO);p.add_argument('--reference-root',type=Path);p.add_argument('--profiles',nargs='+',default=['4:32:1:1:1','16:64:2:32:1','16:64:16:2:1','8:64:1:4:0']);a=p.parse_args()
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 current=a.source_root.resolve()
 reference=a.reference_root.resolve() if a.reference_root else reference_root(out/'reference',current)
 roots={'reference':reference,'candidate':current}
 snapshots={};hashes={}
 for label,source_root in roots.items():
  paths=[source_root/'rtl/npu/writeback/requant_pkg.sv',source_root/RTL,*sorted((source_root/'rtl/common').glob('*'))]
  snapshots[label]=[]
  for source in paths:
   if source.suffix not in ('.sv','.v'):continue
   target=out/'sources'/label/source.relative_to(source_root);target.parent.mkdir(parents=True,exist_ok=True)
   target.write_text(controller(source,label)) if source.relative_to(source_root)==RTL else target.write_bytes(source.read_bytes())
   snapshots[label].append(target);hashes[str(source)]=sha(source)
 report={'passed':False,'inputs_constrained':False,'memory_read_data_constrained':False,'source_sha256':hashes,'comparison':'全部装载控制状态、公开 DMA 端口、WS 存储状态与 IS 存储驱动端口','profiles':[]}
 for profile in a.profiles:
  vlen,bus,lanes,reuse,per_channel=map(int,profile.split(':'));folder=out/profile.replace(':','_');folder.mkdir(exist_ok=True)
  flags=f'-D SYNTHESIS=1 -D XILINX_FPGA=1 -GVLEN={vlen} -GBUS_WIDTH={bus} -Gp_compute_lanes={lanes} -GMAX_IA_REUSE={reuse} -Gp_input_rows={vlen*reuse} -GENABLE_S16=1 -GENABLE_PER_CHANNEL={per_channel}'
  models={}
  for label,paths in snapshots.items():
   raw=folder/(label+'_raw.json');execute(folder,label+'_elaborate',[f'read_slang --top quant_parameter_control {flags} '+shlex.join(map(str,paths)),'prep -top quant_parameter_control -flatten','opt_clean','write_json '+shlex.quote(str(raw))])
   design=json.loads(raw.read_text());module=design['modules']['quant_parameter_control'];models[label]=helper['memory_interfaces'](module)
   for index,name in enumerate(list(module['netnames'])):
    if name.startswith('u_remaining_words.') or name in ('remaining_words','remaining_words_inverse','unused_remaining_words_carry','burst_word_index','chunk_words','chunk_need_cur','burst_len_cur'):
     value=module['netnames'].pop(name);value['hide_name']=1;module['netnames'][f'$arithmetic_{label}_{index}']=value
   (folder/(label+'.json')).write_text(json.dumps({'modules':{label:module}},separators=(',',':'))+'\n')
  if models['reference']!=models['candidate']:raise RuntimeError('存储模型配置不同')
  log=execute(folder,'equivalence',[
   'read_json '+shlex.quote(str(folder/'reference.json')),'memory_map','opt_clean','design -stash reference',
   'read_json '+shlex.quote(str(folder/'candidate.json')),'memory_map','opt_clean','design -stash candidate',
   'design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
   'equiv_make reference candidate equivalent','hierarchy -top equivalent','async2sync','opt_clean','opt_merge',
   'equiv_simple -short -seq 1','opt_clean','equiv_induct -seq 4','equiv_status -assert'])
  match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log.read_text())
  if not match or int(match[2]):raise RuntimeError(str(log))
  row={'vlen':vlen,'bus_width':bus,'compute_lanes':lanes,'reuse':reuse,'per_channel':per_channel,'passed':True,'equivalent_bits':int(match[1]),'abstract_memories':len(models['reference']),'log_sha256':sha(log)}
  report['profiles'].append(row);print(json.dumps(row),flush=True)
 if any(sha(Path(p))!=v for p,v in hashes.items()):raise RuntimeError('源文件发生变化')
 report['passed']=True;report['equivalent_bits']=sum(r['equivalent_bits']for r in report['profiles']);(out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
