#!/usr/bin/env python3
"""测量保存的任务模式至实际 AXI 返回就绪和错误接收的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins


def measure(folder):
    mapped,pre_lut=folder/'mapped.json',folder/'pre_lut.il'
    module=json.loads(mapped.read_text())['modules']['read_ready_top']
    for name,origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
    next_bit=max(bit for net in module['netnames'].values() for bit in net['bits'] if isinstance(bit,int))+1
    for port in ('m_axi_rready','read_error'):
        module['cells']['analysis_'+port]={'type':'FDRE','attributes':{},'parameters':{},
            'port_directions':{'D':'input','Q':'output'},
            'connections':{'D':module['ports'][port]['bits'],'Q':[next_bit]}}
        next_bit+=1
    paths={}
    for port in ('m_axi_rready','read_error'):
        for source in ('mode','all_registers'):
            def root(name,cell,p):
                origin=cell.get('attributes',{}).get('fpga_register_origin','')
                return origin in ('job_conv','job_range','job_read_guard') if source=='mode' else not name.startswith('analysis_')
            row=connected_paths(module,limit=1,group_limit=0,root_filter=root,
                sink_filter=lambda name,cell,p:name=='analysis_'+port)
            assert row['graph_complete']
            paths[source+'_to_'+port]=row
    return {'mapped_sha256':hashlib.sha256(mapped.read_bytes()).hexdigest(),
        'pre_lut_sha256':hashlib.sha256(pre_lut.read_bytes()).hexdigest(),'paths':paths}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    rows={label:measure(args.synthesis/label) for label in ('reference','current')}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps({label:{name:row['longest_register_path_cells'] for name,row in item['paths'].items()}
        for label,item in rows.items()}))


if __name__=='__main__':main()
