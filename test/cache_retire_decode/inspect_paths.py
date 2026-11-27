#!/usr/bin/env python3
"""检查完整映射图以及请求行坐标到缓存释放序号寄存器的实际路径。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins


def existing(path):
    return path if path.exists() else path.with_suffix(path.suffix+'.gz')


def read(path):
    path=existing(path)
    return gzip.open(path,'rb').read() if path.suffix=='.gz' else path.read_bytes()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--mapped',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    raw=read(args.mapped/'mapped.json');modules=json.loads(raw)['modules']
    selected=[(name,value) for name,value in modules.items()
              if str(value.get('attributes',{}).get('top','0')).lstrip('0')=='1']
    assert len(selected)==1
    top,module=selected[0]
    for name,origin in register_origins(existing(args.source/'pre_lut.il')).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
    full=connected_paths(module,limit=24,group_limit=80)
    retire=connected_paths(module,limit=8,group_limit=8,
        root_filter=lambda name,cell,port:'request_y_q' in cell.get('attributes',{}).get('fpga_register_origin',''),
        sink_filter=lambda name,cell,port:'demand_retire' in cell.get('attributes',{}).get('fpga_register_origin',''))
    assert full['graph_complete'] and not full['combinational_cycle_nodes']
    assert retire['graph_complete'] and not retire['combinational_cycle_nodes']
    (args.out/'complete_paths.json').write_text(json.dumps(full,indent=2)+'\n')
    (args.out/'retire_paths.json').write_text(json.dumps(retire,indent=2)+'\n')
    metrics=json.loads((args.mapped/'metrics.json').read_text())
    summary=dict(top=top,resources=metrics['resources'],graph_complete=True,
        longest_register_path_cells=full['longest_register_path_cells'],
        request_y_to_demand_retire_cells=retire['longest_register_path_cells'],
        mapped_sha256=hashlib.sha256(raw).hexdigest(),
        source_manifest=json.loads((args.source/'manifest.json').read_text()))
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({key:summary[key] for key in ('top','longest_register_path_cells','request_y_to_demand_retire_cells')}))


if __name__=='__main__':
    main()
