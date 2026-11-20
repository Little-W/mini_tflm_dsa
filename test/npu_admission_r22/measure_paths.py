#!/usr/bin/env python3
"""统计实际测量寄存器间的偏置、故障及配置接收路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins,resources


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def origin(cell):return cell.get('attributes',{}).get('fpga_register_origin','')


def matches(value,key):return value==key or value.startswith(key+' [')


def measure(folder,pre,name):
    mapped=folder/name/'mapped.json'
    pre_lut=pre/name/'pre_lut.il'
    module=json.loads(mapped.read_text())['modules']['measurement_top']
    for cell,value in register_origins(pre_lut).items():
        if cell in module['cells']:
            module['cells'][cell].setdefault('attributes',{})['fpga_register_origin']=value
    report={'mapped_sha256':digest(mapped),'pre_lut_sha256':digest(pre_lut),
            'resources':resources(module['cells']),
            'all_paths':connected_paths(module,limit=5,group_limit=20),'paths':{}}
    if not report['all_paths']['graph_complete']:
        raise RuntimeError('The complete mapped graph was not analyzed')
    if name.startswith('bias_'):
        inputs=('bias_base','exec_channel','frame_mode_q','is_mode','ws_final_bias',
                'frame_command_final','frame_command_init','all_sources')
        outputs=('o_send_ia_trigger','o_observed_bias_address','controller_state','all_sinks')
    else:
        inputs=('write_guard_state','write_response_buffer','read_response_buffer','m_axi_rready',
                'rd_dma_done','dma_rd_error','wr_dma_done','dma_wr_error','abort_pending',
                'rd_command_client','rd_dma_start_q','kernel_request','kernel_quiescent','all_sources')
        outputs=('o_bus_error','o_abort','o_ia_granted','o_kernel_granted','o_bias_granted',
                 'o_quant_granted','o_dw_granted','o_kernel_prefetch_idle','o_sa_ready','o_cfg_start_event')
    def root_filter(key,cell):
        value=origin(cell)
        if key=='all_sources':return True
        if key=='write_guard_state':return matches(value,'u_impl.u_write_guard.state')
        if key=='write_response_buffer':return value.startswith('u_impl.u_b_buf.')
        if key=='read_response_buffer':return value.startswith('u_impl.u_r_buf.')
        return matches(value,key)
    def sink_filter(key,cell):
        value=origin(cell)
        if key=='all_sinks':return True
        if key=='controller_state':return value.startswith('u_impl.u_controller.')
        return matches(value,key)
    for source in inputs:
        report['paths'][source]={}
        for target in outputs:
            result=connected_paths(module,limit=1,group_limit=0,
                root_filter=lambda name,cell,port:root_filter(source,cell),
                sink_filter=lambda name,cell,port:sink_filter(target,cell))
            if not result['graph_complete']:raise RuntimeError('An observed path graph is incomplete')
            report['paths'][source][target]={'connected':bool(result['register_to_register_paths']),
                'combinational_cells':result['longest_register_path_cells'],
                'path':result['register_to_register_paths'][:1]}
    summary=json.loads((folder/name/'summary.json').read_text())
    report['functional_verification']=summary['functional_verification']
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped',type=Path,required=True)
    parser.add_argument('--pre',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result={}
    for name in ('bias_reference','bias_current','return_reference','return_current'):
        row=measure(args.mapped,args.pre,name)
        result[name]=row
        shown=('bias_base','exec_channel','all_sources') if name.startswith('bias_') else (
            'write_guard_state','write_response_buffer','read_response_buffer','m_axi_rready',
            'rd_dma_done','dma_rd_error','wr_dma_done','dma_wr_error','abort_pending')
        print(json.dumps({'case':name,'logic_lut':row['resources']['logic_lut_cells'],
            'ff':row['resources']['flip_flops'],
            'maximum_cells':row['all_paths']['longest_register_path_cells'],
            'paths':{source:{target:path['combinational_cells'] for target,path in row['paths'][source].items()}
                     for source in shown}},ensure_ascii=False),flush=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
