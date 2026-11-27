#!/usr/bin/env python3
"""在完整缓存网表中统计响应就绪、保存计数和返回端口之间的组合路径。"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--dma',action='store_true',help='检查完整 DMA 中窗口计数到输出保存寄存器的连接')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    summary={}
    for label in ('reference','current'):
        mapped=args.mapping/(label+'_mapped')/'mapped.json'
        module=json.loads(mapped.read_text())['modules'][
            'axi_dual_block_dma' if args.dma else 'conv_windowed_cache']
        for key,value in register_origins(args.mapping/label/'pre_lut.il').items():
            if key in module['cells']:
                module['cells'][key].setdefault('attributes',{})['fpga_register_origin']=value
        next_bit=max(b for cell in module['cells'].values() for bits in cell['connections'].values()
                     for b in bits if isinstance(b,int))+1
        # 端口观察寄存器仅用于路径计算，资源数量取自未修改的生产网表。
        def endpoint(name,bits,is_input):
            nonlocal next_bit
            for index,bit in enumerate(bits):
                connections={'C':module['ports']['clk']['bits'],'CE':['1'],'R':['0'],
                             'D':[next_bit if is_input else bit],
                             'Q':[bit if is_input else next_bit]}
                next_bit+=1
                module['cells'][f'observe_{name}_{index}']={
                    'type':'FDRE','parameters':{},'attributes':{'fpga_register_origin':'port.'+name},
                    'port_directions':{'C':'input','CE':'input','R':'input','D':'input','Q':'output'},
                    'connections':connections}
        if args.dma:
            starts=['active_count','response_count','outstanding_count']
            outputs=['fe_output_data','fe_output_valid','fe_output_window','fe_output_mask',
                     'fe_output_last','fe_output_slot','fe_output_row','fe_output_col',
                     'fe_matrix_output_valid']
        else:
            endpoint('rsp_ready',module['ports']['rsp_ready']['bits'],True)
            outputs=[name for name in ('rsp_valid','rsp_data','rsp_error','rsp_success','rsp_failure')
                     if name in module['ports']]
            for name in outputs:endpoint(name,module['ports'][name]['bits'],False)
            starts=['port.rsp_ready','response_count','outstanding_count']
        results={}
        for start in starts:
            for end in outputs:
                def root_filter(name,cell,pin):
                    origin=cell.get('attributes',{}).get('fpga_register_origin','')
                    if args.dma:
                        return bool(re.search(r'(?:^|\.)'+re.escape(start)+r'(?: |\[|$)',origin))
                    return origin==start or origin.startswith(start+' ') or \
                           origin.startswith('u_request_path.'+start+' ') or origin=='u_request_path.'+start
                def sink_filter(name,cell,pin):
                    if args.dma:
                        origin=cell.get('attributes',{}).get('fpga_register_origin','')
                        return pin in ('D','CE') and bool(re.match(re.escape(end)+r'(?: |\[|$)',origin))
                    return pin=='D' and cell.get('attributes',{}).get('fpga_register_origin')=='port.'+end
                report=connected_paths(module,limit=3,group_limit=3,
                                       root_filter=root_filter,sink_filter=sink_filter)
                assert report['graph_complete'] and not report['combinational_cycle_nodes']
                key=start+'_to_'+end
                (out/(label+'_'+key+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                results[key]=report['longest_register_path_cells']
        metrics=json.loads((args.mapping/(label+'_mapped')/'metrics.json').read_text())
        summary[label]=dict(paths=results,resources=metrics['resources'],
            longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
            graph_complete=metrics['paths']['graph_complete'],
            mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest())
        print(label,json.dumps(results),flush=True)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
