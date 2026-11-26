#!/usr/bin/env python3
"""测量完整窗口缓存及其预取重复、槽位选择和查询资格路径。"""
from pathlib import Path
import argparse,json,sys,subprocess,hashlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--out',type=Path,required=True)
 parser.add_argument('--reference',default='548bda54')
 args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
 reference=out/'reference.sv';reference.write_bytes(subprocess.check_output(['git','show',args.reference+':rtl/npu/dma/cache/conv_windowed_cache.sv'],cwd=ROOT))
 profile={'SETS':16,'WAYS':2,'LINE_BYTES':128,'BUS_WIDTH':64,'READ_WIDTH':64,'DEMAND_DEPTH':2}
 flags=['-DSYNTHESIS=1','-DXILINX_FPGA=1',*[f'-G{k}={v}' for k,v in profile.items()]]
 cases={n:{'top':'conv_windowed_cache','sources':[str(p)],'options':flags,'configuration':profile} for n,p in [('reference',reference),('current',ROOT/'rtl/npu/dma/cache/conv_windowed_cache.sv')]}
 config=out/'cases.json';config.write_text(json.dumps(cases,indent=2)+'\n')
 subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',config,'--cases',*cases,'--out',out/'mapping','--through','pre_lut'],check=True,cwd=ROOT)
 records={}
 for n in cases:
  source=out/'mapping'/n;cost=out/'cost'/n
  subprocess.run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',source,'--out',cost,'--mode','physical-cost','--delay-target-ps','6667','--wire-delay-ps','300','--max-lut-inputs','8'],check=True,cwd=ROOT)
  module=json.loads((cost/'mapped.json').read_text())['modules']['conv_windowed_cache']
  for name,origin in register_origins(source/'pre_lut.il','conv_windowed_cache').items():
   if name in module['cells']:module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
  record={name:json.loads((cost/(name+'.json')).read_text()) for name in ('manifest','summary')};record['directed']={}
  for name,origin,endpoint in [('offer_to_duplicate','offer_addr_q','offer_duplicate_q'),('queue_to_snapshot','request_count','u_request_path.lookup_snapshot_valid'),('slot_to_storage','pf_slot_map_q','u_prefetch_index.mem.')]:
   result=connected_paths(module,limit=1,group_limit=0,
    root_filter=lambda n,c,p,origin=origin:(c.get('attributes',{}).get('fpga_register_origin') or '').split(' [')[0]==origin,
    sink_filter=lambda n,c,p,endpoint=endpoint:n.startswith(endpoint) or (c.get('attributes',{}).get('fpga_register_origin') or '').split(' [')[0]==endpoint)
   if not result['graph_complete']:raise RuntimeError('路径分析图不完整：'+name)
   record['directed'][name]=result
  records[n]=record
  print(n,record['summary']['resources']['logic_lut_cells'],{k:v['longest_register_path_cells'] for k,v in record['directed'].items()},flush=True)
 (out/'measurement.json').write_text(json.dumps({'reference_commit':args.reference,'cases':records},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
