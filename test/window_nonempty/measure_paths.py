#!/usr/bin/env python3
"""测量缓存配置允许信号到窗口前端请求索引的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins
BOUNDARIES=('axi_linear_block_dma','conv_read_cache','conv_next_use_predictor',
            'conv_axi_read_guard','axi_write_page_guard','conv_axi_read_mux')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result={}
    for label in ('reference','current'):
        folder=args.source/label
        module=json.loads((folder/'mapped.json').read_text())['modules']['axi_dual_block_dma']
        summary=json.loads((folder/'summary.json').read_text())
        for name,origin in register_origins(folder/'pre_lut.il').items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=origin
        for name,cell in list(module['cells'].items()):
            if cell['type'].startswith('conv_read_cache'):
                # 分析标记只定义接口起点，实际网表没有新增寄存器。
                module['cells']['analysis_cache_cfg_ready']={'type':'FDRE','parameters':{},
                    'attributes':{'fpga_register_origin':'cache_cfg_ready input'},
                    'port_directions':{'Q':'output'},'connections':{'Q':cell['connections']['cfg_ready']}}
            if cell['type']=='$scopeinfo' or cell['type'].startswith(BOUNDARIES):
                del module['cells'][name]
        paths=connected_paths(module,limit=4,group_limit=10,
            root_filter=lambda n,c,p:n=='analysis_cache_cfg_ready',
            sink_filter=lambda n,c,p:'request_index_q' in c.get('attributes',{}).get('fpga_register_origin',''))
        assert paths['graph_complete']
        result[label]=dict(source_sha256=summary['source_sha256'],resources=summary['resources'],
            native_longest_register_path_cells=summary['paths']['longest_register_path_cells'],
            mapped_sha256=hashlib.sha256((folder/'mapped.json').read_bytes()).hexdigest(),targeted_paths=paths)
        print(label,paths['longest_register_path_cells'])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
