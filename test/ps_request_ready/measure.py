#!/usr/bin/env python3
"""统计完整帧存储中请求状态到帧就绪、读使能及容量故障的路径。"""
import argparse,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cost',type=Path,required=True);p.add_argument('--pre',type=Path,required=True);p.add_argument('--request-id-first-bit',type=int,default=50);a=p.parse_args()
 mapped=a.cost/'mapped.json';pre=a.pre/'pre_lut.il';m=json.loads(mapped.read_text())['modules']['ps_frame_store']
 for name,value in register_origins(pre).items():
  if name in m['cells']:m['cells'][name].setdefault('attributes',{})['fpga_register_origin']=value
 spare=max(bit for net in m['netnames'].values()for bit in net['bits']if isinstance(bit,int))+1
 for output in ['frame_ready','ram_read_en']:
  for index,bit in enumerate(m['ports'][output]['bits']):
   m['cells'][f'analysis_{output}_{index}']=dict(type='FDRE',parameters={},attributes={},port_directions={'D':'input','Q':'output'},connections={'D':[bit],'Q':[spare]});spare+=1
 def origin(cell):return cell.get('attributes',{}).get('fpga_register_origin','')
 def id_root(name,cell,port):
  match=re.fullmatch(r'request_q \[(\d+)\]',origin(cell));return bool(match and int(match[1])>=a.request_id_first_bit)
 paths={}
 for start in ['request_q','request_id','request_qualified_q','request_initial_or_other_q','all_state']:
  for end in ['frame_ready','ram_read_en','capacity_fault']:
   root=None if start=='all_state'else id_root if start=='request_id'else lambda n,c,p,start=start:origin(c).split(' ')[0]==start
   sink=(lambda n,c,p:origin(c).split(' ')[0]=='capacity_fault')if end=='capacity_fault'else lambda n,c,p,end=end:n.startswith('analysis_'+end+'_')
   data=connected_paths(m,root_filter=root,sink_filter=sink,limit=2,group_limit=2);assert data['graph_complete'];paths[start+'_to_'+end]=data
 report=dict(mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest(),pre_lut_sha256=hashlib.sha256(pre.read_bytes()).hexdigest(),request_id_first_bit=a.request_id_first_bit,paths=paths)
 (a.cost/'request_paths.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({n:p['longest_register_path_cells']for n,p in paths.items()}))
if __name__=='__main__':main()
