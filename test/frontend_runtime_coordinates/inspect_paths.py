#!/usr/bin/env python3
"""在完整映射连接图中测量提交、接收和行末条件到坐标寄存器的路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    report={}
    for label in ('reference','current'):
        name='runtime_'+label
        mapped=args.mapping/(name+'_mapped')/'mapped.json'
        source=args.mapping/name/'pre_lut.il'
        module=json.loads(mapped.read_text())['modules']['registered_runtime']
        for key,value in register_origins(source).items():
            if key in module['cells']:
                module['cells'][key].setdefault('attributes',{})['fpga_register_origin']=value
        results={}
        checks = [(start,sink) for start in (
            'i_tile_commit_q','i_stream_operation_accept_q','i_chunk_reaches_end_q',
            'i_state_q','u_runtime.o_past_active')
            for sink in ('o_output_coordinate','o_kernel_coordinate')]
        checks += [('u_runtime.o_wrap_dx','o_wrap_dx'), ('u_runtime.o_configuration','o_wrap_dx')]
        for start,sink_name in checks:
            def root_filter(name,cell,pin):
                origin=cell.get('attributes',{}).get('fpga_register_origin','')
                return origin == start or origin.startswith(start+' ')
            def sink_filter(name,cell,pin):
                origin=cell.get('attributes',{}).get('fpga_register_origin','')
                return origin.startswith('u_runtime.'+sink_name+' ')
            paths=connected_paths(module,limit=3,group_limit=3,
                                  root_filter=root_filter,sink_filter=sink_filter)
            if not paths['graph_complete'] or paths['combinational_cycle_nodes']:
                raise RuntimeError('坐标路径连接统计不完整')
            key=start+'_to_'+sink_name
            (out/(label+'_'+key+'.json')).write_text(json.dumps(paths,ensure_ascii=False,indent=2)+'\n')
            results[key]=paths['longest_register_path_cells']
        metrics=json.loads((args.mapping/(name+'_mapped')/'metrics.json').read_text())
        report[label]=dict(paths=results,resources=metrics['resources'],
                          longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
                          mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest())
        print(label,json.dumps(results),flush=True)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
