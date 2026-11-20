#!/usr/bin/env python3
"""分别测量实际累加器与 RHS 写入的迟到控制输入和数据路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins,resources


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origin(cell):
    return cell.get('attributes',{}).get('fpga_register_origin','')


def match(value,prefix):
    return value==prefix or value.startswith(prefix+' [') or value.startswith(prefix+'[')


def analyze(mapped,pre):
    module=json.loads(mapped.read_text())['modules']['accumulator_write']
    for name,value in register_origins(pre).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=value
    result={'mapped_sha256':digest(mapped),'pre_lut_sha256':digest(pre),
        'resources':resources(module['cells']),'all_paths':connected_paths(module,limit=3,group_limit=5),
        'paths':{}}
    sources=('rd_raw_valid','soft_exp_we','soft_exp_index','rd_done','rd_error','soft_state',
             'c','state','active','compute_index',
             'rd_raw_data','soft_lut_data','rd_valid','rd_data','rd_col_base','all_sources')
    for source in sources:
        result['paths'][source]={}
        for target in ('acc_buf','rhs_buf'):
            row=connected_paths(module,limit=1,group_limit=0,
                root_filter=lambda name,cell,port: source=='all_sources' or match(origin(cell),source),
                sink_filter=lambda name,cell,port:match(origin(cell),target))
            if not row['graph_complete']:raise RuntimeError('The mapped write graph is incomplete')
            result['paths'][source][target]={'connected':bool(row['register_to_register_paths']),
                'levels':row['longest_register_path_cells'],'path':row['register_to_register_paths'][:1]}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();root=args.build.resolve();report={}
    for mode,folder,pre_folder in (
            ('native',root/'local/results',root/'local/results'),
            ('physical_cost',root/'cost',root/'local/results'),
            ('connected_physical_cost',root/'connected/cost',root/'connected/pre')):
        report[mode]={}
        for label in ('reference','current'):
            row=analyze(folder/label/'mapped.json',pre_folder/label/'pre_lut.il')
            report[mode][label]=row
            print(json.dumps({'mode':mode,'case':label,'logic_lut':row['resources']['logic_lut_cells'],
                'ff':row['resources']['flip_flops'],'maximum':row['all_paths']['longest_register_path_cells'],
                'levels':{s:{t:p['levels'] for t,p in v.items()} for s,v in row['paths'].items()}},ensure_ascii=False),flush=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
