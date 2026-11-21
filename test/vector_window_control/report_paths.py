#!/usr/bin/env python3
"""统计窗口接口、配置检查、坐标判断和结果选择的实际组合路径。"""
from pathlib import Path
import argparse
import gzip
import json
import sys


def read_json(path):
    if path.exists():return json.loads(path.read_text())
    with gzip.open(str(path)+'.gz','rt')as stream:return json.load(stream)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--tool-root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();sys.path.insert(0,str(args.tool_root/'scripts/fpga'))
    from netlist_metrics import connected_paths,register_origins
    module=read_json(args.source/'mapped.json')['modules']['vector_engine']
    source=args.source/'pre_lut.il'
    if not source.exists():source=Path(str(source)+'.gz')
    for name,origin in register_origins(source).items():
        if name in module['cells']:module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
    def origin(cell):return cell.get('attributes',{}).get('fpga_register_origin','')
    for name in('win_rsp_mask','win_rsp_valid','win_rsp_error','win_rsp_col','rd_valid','rd_col_base'):
        if name not in module['ports']:continue
        bits=module['ports'][name]['bits']
        module['cells']['interface_'+name]={'type':'FDRE','parameters':{},
            'attributes':{'fpga_register_origin':name},
            'connections':{'C':['0'],'CE':['1'],'R':['0'],'D':['0']*len(bits),'Q':bits},
            'port_directions':{'C':'input','CE':'input','R':'input','D':'input','Q':'output'}}
    acc_bits=set(module['ports']['o_ps_write_data']['bits'])
    report={}
    for sink in('window_write_pending','window_response_count_ok_q','window_bank_valid','window_bank_index','shared_weight_write_pending'):
        report['input_to_'+sink]=connected_paths(module,limit=4,group_limit=4,
            root_filter=lambda name,cell,port:name.startswith('interface_'),
            sink_filter=lambda name,cell,port,sink=sink:sink in origin(cell) and port in('D','CE'))
    for name,root,sink in(
        ('coordinate_bounds_to_valid',lambda n,c,p:any(word in origin(c)for word in('dilation_x_min','dilation_y_min','stride_x_min','stride_y_min')),lambda n,c,p:'dw_in_bounds' in origin(c) and p in('D','CE')),
        ('register_to_config_state',lambda n,c,p:not n.startswith('interface_'),lambda n,c,p:'u_config_check.state' in origin(c) and p in('D','CE')),
        ('compute_group_to_accumulator',lambda n,c,p:any(word in origin(c)for word in('compute_index','compute_pool_group')),lambda n,c,p:p=='D' and bool(acc_bits.intersection(c['connections'].get('Q',[]))))):
        report[name]=connected_paths(module,limit=4,group_limit=4,root_filter=root,sink_filter=sink)
    report['analysis_boundary']='Input registers mark module ports for analysis only; RTL and mapped hardware are unchanged'
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({name:{'cells':value['longest_register_path_cells'],'complete':value['graph_complete']}for name,value in report.items()if isinstance(value,dict)}))


if __name__=='__main__':main()
