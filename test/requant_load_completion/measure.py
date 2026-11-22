#!/usr/bin/env python3
"""在相同生产参数下分别映射完整量化模块并记录实际寄存器路径。"""
from pathlib import Path
import argparse,collections,gzip,hashlib,json,os,re,shlex,shutil,subprocess,sys,time
from support import ROOT as REPO, reference_root, source_paths
sys.path.insert(0,str(REPO/'scripts/fpga'))
from netlist_metrics import analyze,connected_paths,register_origins
PARAMETERS={'BUS_WIDTH':64,'VLEN':16,'MAX_IA_REUSE':32,'ENABLE_S16':1,'p_compute_lanes':2,'p_input_rows':512,'p_parameter_output':0}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def signal_filter(pattern):
 expression=re.compile(pattern)
 return lambda name,cell,port:bool(expression.search(name+' '+str(cell.get('attributes',{}).get('fpga_register_origin',''))))
def archive(path):
 info={'sha256':sha(path),'bytes':path.stat().st_size}
 target=path.with_suffix(path.suffix+'.gz')
 with path.open('rb') as src,gzip.open(target,'wb',compresslevel=6) as dst:shutil.copyfileobj(src,dst)
 with gzip.open(target,'rb') as src:
  digest=hashlib.sha256()
  for block in iter(lambda:src.read(1024*1024),b''):digest.update(block)
 if digest.hexdigest()!=info['sha256']:raise RuntimeError('压缩内容不同')
 path.unlink();info['compressed_bytes']=target.stat().st_size;return info

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--source-root',type=Path,default=REPO);p.add_argument('--reference-root',type=Path);p.add_argument('--variants',nargs='+',choices=['reference','candidate'],default=['reference','candidate']);a=p.parse_args()
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 current=a.source_root.resolve();reference=a.reference_root.resolve() if a.reference_root else reference_root(out/'reference_source',current)
 roots={'reference':reference,'candidate':current}
 import pyosys
 env=os.environ.copy();env['PATH']=str(Path(pyosys.__file__).parent)+os.pathsep+env.get('PATH','')
 summary={'passed':False,'parameters':PARAMETERS,'variants':{}}
 for label in a.variants:
  folder=out/label;folder.mkdir(parents=True,exist_ok=True)
  source_root=roots[label];sources=source_paths(source_root);hashes={str(path.relative_to(source_root)):sha(path) for path in sources}
  manifest={'parameters':PARAMETERS,'sources_sha256':hashes,'defines':['SYNTHESIS','XILINX_FPGA'],'synthesis':'synth_xilinx -family xc7 -noiopad -noclkbuf -flatten'}
  (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
  pre=folder/'pre_lut.il';mapped=folder/'mapped.json'
  flags=' '.join(f'-G{k}={v}'for k,v in PARAMETERS.items())
  synth='synth_xilinx -top vec_requant -family xc7 -noiopad -noclkbuf -flatten'
  commands={
   '01_pre_lut':f'read_slang --top vec_requant -D SYNTHESIS=1 -D XILINX_FPGA=1 {flags} '+shlex.join(map(str,sources))+'\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\nread_verilog -lib -overwrite +/xilinx/cells_xtra.v\nhierarchy -check -top vec_requant\n'+synth+' -run begin:map_luts\nwrite_rtlil '+shlex.quote(str(pre))+'\n',
   '02_map_lut':'read_rtlil '+shlex.quote(str(pre))+'\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\nread_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'+synth+' -run map_luts:\ncheck -assert\nstat -tech xilinx\nwrite_json '+shlex.quote(str(mapped))+'\n'}
  start=time.monotonic();stages={}
  for stage,text in commands.items():
   ys=folder/(stage+'.ys');log=folder/(stage+'.log');ys.write_text(text);begin=time.monotonic()
   with log.open('w') as stream:subprocess.run([sys.executable,str(REPO/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],cwd=REPO,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=1200)
   stages[stage]={'elapsed_seconds':round(time.monotonic()-begin,3),'log_sha256':sha(log),'script_sha256':sha(ys)}
   print(json.dumps({'variant':label,'stage':stage,**stages[stage]}),flush=True)
  design=json.loads(mapped.read_text());module=design['modules']['vec_requant']
  for name,origin in register_origins(pre).items():
   if name in module['cells']:module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
  metrics=analyze(module,limit=30,group_limit=30)
  (folder/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
  paths=connected_paths(module,limit=30,group_limit=30,root_filter=signal_filter(r'quant_need_load_r'),sink_filter=signal_filter(r'(?:\bstate\b|cmd_has_more_r|cmd_valid_r|load_offset)'))
  (folder/'load_paths.json').write_text(json.dumps(paths,indent=2)+'\n')
  state_paths=connected_paths(module,limit=12,group_limit=12,root_filter=signal_filter(r'quant_need_load_r'),sink_filter=signal_filter(r'(?:^|[. ])state(?:\[|\s|$)'))
  (folder/'load_state_paths.json').write_text(json.dumps(state_paths,indent=2)+'\n')
  saved_paths=connected_paths(module,limit=12,group_limit=12,root_filter=signal_filter(r'cmd_has_more_r'),sink_filter=signal_filter(r'(?:^|[. ])state(?:\[|\s|$)'))
  (folder/'saved_more_state_paths.json').write_text(json.dumps(saved_paths,indent=2)+'\n')
  counts=collections.Counter(c['type']for c in module['cells'].values())
  record={'resources':metrics['resources'],'longest_register_path_cells':metrics['paths']['longest_register_path_cells'],'load_paths':paths['longest_register_path_cells'],'load_to_state_paths':state_paths['longest_register_path_cells'],'saved_more_to_state_paths':saved_paths['longest_register_path_cells'],'stages':stages,'elapsed_seconds':round(time.monotonic()-start,3),'cell_counts':dict(sorted(counts.items()))}
  record['archives']={p.name:archive(p)for p in (pre,mapped)}
  (folder/'summary.json').write_text(json.dumps(record,indent=2)+'\n');summary['variants'][label]=record
  if hashes!={str(path.relative_to(source_root)):sha(path)for path in sources}:raise RuntimeError('综合期间源文件发生变化')
  print(json.dumps({'variant':label,'resources':record['resources'],'longest':record['longest_register_path_cells'],'load_paths':record['load_paths'],'load_to_state_paths':record['load_to_state_paths']}),flush=True)
 summary['passed']=True;(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
if __name__=='__main__':main()
