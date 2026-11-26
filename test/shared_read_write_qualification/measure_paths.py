#!/usr/bin/env python3
"""从完整通道网表测量请求信号到实际存储使能及容量故障寄存器的级数。"""
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins
p=argparse.ArgumentParser();p.add_argument('--cost',type=Path,required=True);p.add_argument('--pre',type=Path,required=True);a=p.parse_args()
module=max(json.loads((a.cost/'mapped.json').read_text())['modules'].values(),key=lambda m:len(m.get('cells',{})))
for n,o in register_origins(a.pre/'pre_lut.il').items():
 if n in module['cells']:module['cells'][n].setdefault('attributes',{})['fpga_register_origin']=o
spare=max(b for n in module['netnames'].values() for b in n['bits'] if isinstance(b,int))+1
inputs=['i_ps_read_en','i_ps_write_en','i_access_enable','i_ia_read_en','i_ia_write_en','i_ps_read_addr','i_ps_write_addr']
inputs=[n for n in module['ports'] if any(n==base or n.startswith(base+'[') for base in inputs)]
for n in inputs:
 for i,b in enumerate(module['ports'][n]['bits']):
  module['cells'][f'analysis_{n}_{i}']=dict(type='FDRE',parameters={},attributes={'fpga_register_origin':n},port_directions={'D':'input','Q':'output'},connections={'D':[spare],'Q':[b]});spare+=1
paths={}
for port in ['i_ps_read_en','i_ps_write_en','i_access_enable','i_ia_read_en','i_ia_write_en','i_ps_read_addr','i_ps_write_addr','all_state']:
 root=None if port=='all_state' else lambda n,c,p,port=port: n.startswith('analysis_'+port)
 for sinkname,sink in [('shared_enable',lambda n,c,p:'g_shared_bank' in n and p in ['ENARDEN','ENBWREN','WEA','WEBWE']),('ps_read_enable',lambda n,c,p:'g_shared_bank' in n and p=='ENARDEN'),('ia_write_enable',lambda n,c,p:'g_shared_bank' in n and p=='WEA'),('ia_read_enable',lambda n,c,p:'g_shared_bank' in n and p=='ENBWREN'),('fixed_enable',lambda n,c,p:'g_fixed_channel' in n and p in ['ENARDEN','ENBWREN','WEA','WEBWE']),('fault',lambda n,c,p:'o_capacity_fault' in c.get('attributes',{}).get('fpga_register_origin',''))]:
  data=connected_paths(module,root_filter=root,sink_filter=sink,limit=3,group_limit=6);assert data['graph_complete'];paths[port+'_to_'+sinkname]=data
result={'mapped_sha256':hashlib.sha256((a.cost/'mapped.json').read_bytes()).hexdigest(),'pre_lut_sha256':hashlib.sha256((a.pre/'pre_lut.il').read_bytes()).hexdigest(),'paths':paths}
(a.cost/'targeted_paths.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({n:v['longest_register_path_cells'] for n,v in paths.items()}))
