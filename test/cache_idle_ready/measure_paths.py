#!/usr/bin/env python3
"""测量填充状态到缓存配置允许端口的实际组合单元。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--current',type=Path,required=True)
    parser.add_argument('--proof',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();proof=json.loads(args.proof.read_text());assert proof['passed'];result={}
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    for label,folder,expected in [('reference',args.reference,proof['reference_sha256']),('current',args.current,proof['source_sha256'])]:
        summary=json.loads((folder/'summary.json').read_text())
        sources={Path(p).name:sha for p,sha in summary['source_sha256'].items()}
        assert sources['conv_read_cache.sv']==expected
        module=json.loads((folder/'mapped.json').read_text())['modules']['conv_windowed_cache']
        for name,origin in register_origins(folder/'pre_lut.il').items():
            if name in module['cells']:module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
        # 这个分析终点只标识公开端口，实际电路没有新增寄存器。
        module['cells']['analysis_cfg_ready']={'type':'FDRE','parameters':{},
            'attributes':{'fpga_register_origin':'cfg_ready output'},
            'port_directions':{'D':'input'},'connections':{'D':module['ports']['cfg_ready']['bits']}}
        paths={}
        for key,pattern in [('fill_state_to_cfg_ready',r'^fill_state(?: |$)'),('all_registers_to_cfg_ready',r'.')]:
            source=re.compile(pattern)
            paths[key]=connected_paths(module,limit=4,group_limit=4,
                root_filter=lambda n,c,p:bool(source.search(c.get('attributes',{}).get('fpga_register_origin',''))),
                sink_filter=lambda n,c,p:n=='analysis_cfg_ready')
            assert paths[key]['graph_complete']
        result[label]=dict(configuration=summary['configuration'],source_sha256=sources,resources=summary['resources'],
            native_longest_register_path_cells=summary['connected_path_metrics']['longest_register_path_cells'],
            mapped_sha256=digest(folder/'mapped.json'),pre_lut_sha256=digest(folder/'pre_lut.il'),targeted_paths=paths)
        print(label,{key:value['longest_register_path_cells'] for key,value in paths.items()},flush=True)
    for name,sha in result['current']['source_sha256'].items():
        if name!='conv_read_cache.sv':assert result['reference']['source_sha256'][name]==sha
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(dict(passed=True,cases=result),indent=2)+'\n')
if __name__=='__main__':main()
