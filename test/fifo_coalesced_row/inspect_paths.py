#!/usr/bin/env python3
"""在完整写回和 FIFO 连接图中检查合并存储体、行上限及数据存储使能路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origin(cell):
    return cell.get('attributes',{}).get('fpga_register_origin','')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference-source','reference-mapped','current-source','current-mapped','out']:
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    report={}
    for label in ['reference','current']:
        source=getattr(args,label+'_source').resolve();mapped=getattr(args,label+'_mapped').resolve()
        module=json.loads((mapped/'mapped.json').read_text())['modules']['fifo_oa_row_timing_top']
        for name,value in register_origins(source/'pre_lut.il').items():
            if name in module['cells']: module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=value
        prefix='u_fifo.g_full.u_full.'
        results={}
        for start in ['co_current_bank','co_row_limit_q','bank_ready']:
          for target in ['ready_bank_count_q','data_storage','all_endpoints']:
            def root_filter(name,cell,port):
                return origin(cell).startswith(prefix+start+' [')
            def sink_filter(name,cell,port):
                if target=='ready_bank_count_q': return origin(cell).startswith(prefix+target+' [')
                if target=='data_storage': return cell['type'].startswith('RAMB')
                return True
            result=connected_paths(module,limit=3,group_limit=3,root_filter=root_filter,sink_filter=sink_filter)
            assert result['graph_complete'] and not result['combinational_cycle_nodes']
            key=start+'_to_'+target
            (out/(label+'_'+key+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            results[key]=result['longest_register_path_cells']
        metrics=json.loads((mapped/'metrics.json').read_text())
        report[label]=dict(paths=results,resources=metrics['resources'],
            longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
            graph_complete=metrics['paths']['graph_complete'],mapped_sha256=digest(mapped/'mapped.json'),
            source_sha256=json.loads((source/'manifest.json').read_text())['sources_sha256'])
        print(label,json.dumps(results,ensure_ascii=False),flush=True)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
