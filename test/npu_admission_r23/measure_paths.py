#!/usr/bin/env python3
"""检查读写错误、取消和命令来源到实际配置接收的全部局部最长路径。"""
import argparse
import json
from pathlib import Path
import sys

from extract import ROOT,digest
sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths,register_origins,resources


def origin(cell):
    return cell.get('attributes',{}).get('fpga_register_origin','')


def match(value,name):
    return value==name or value.startswith(name+' [')


def measure(mapped,pre):
    module=json.loads(mapped.read_text())['modules']['measurement_top']
    for name,value in register_origins(pre).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=value
    result={'mapped_sha256':digest(mapped),'pre_lut_sha256':digest(pre),
        'resources':resources(module['cells']),
        'all_paths':connected_paths(module,limit=3,group_limit=12),'paths':{}}
    if not result['all_paths']['graph_complete']:
        raise RuntimeError('The mapped graph is incomplete')
    sources=('rd_context_count','read_guard_state','read_mux_state','read_mode',
        'write_guard_state','read_response_buffer','write_response_buffer',
        'rd_dma_done','dma_rd_error','wr_dma_done','dma_wr_error','abort_pending',
        'conv_error','ps_capacity_fault','shared_ram_capacity_fault','frame_mode_q','inner_done_valid',
        'inner_err_code','run_conv','run_vector','rd_command_client','rd_dma_start_q',
        'kernel_request','kernel_quiescent','ia_prefetch_idle','vector_rejected','vector_engine_ready',
        'ctrl_sa_ready','frame_scheduler_ready','cfg_stage0_valid','cfg_stage1_valid','cfg_stage2_valid',
        'operand_cache_idle','cfg_vector_enable','npu_start_pending_q','npu_start_warmup_q','all_sources')
    targets=('o_m_axi_rready','o_bus_error','o_abort','o_ia_granted','o_kernel_granted',
        'o_bias_granted','o_quant_granted','o_dw_granted','o_kernel_start','o_kernel_prefetch_idle',
        'o_sa_ready','o_cfg_start_event','o_vector_start')
    def source_match(key,cell):
        text=origin(cell)
        if key=='all_sources':return True
        patterns={
            'read_guard_state':('u_impl.u_read_pair.u_read_guard.state',),
            'read_mux_state':('u_impl.u_read_pair.u_read_mux.active','u_impl.u_read_pair.u_read_mux.owner',
                'u_impl.u_read_pair.u_read_mux.hold_grant','u_impl.u_read_pair.u_read_mux.held_owner',
                'u_impl.u_read_pair.u_read_mux.prefer_b'),
            'read_mode':('u_impl.u_read_pair.job_conv','u_impl.u_read_pair.job_read_guard'),
            'write_guard_state':('u_impl.u_write_guard.state',)}
        if key in patterns:return any(match(text,p) for p in patterns[key])
        if key=='read_response_buffer':return text.startswith('u_impl.u_r_buf.')
        if key=='write_response_buffer':return text.startswith('u_impl.u_b_buf.')
        return match(text,key)
    for source in sources:
        result['paths'][source]={}
        for target in targets:
            row=connected_paths(module,limit=1,group_limit=0,
                root_filter=lambda name,cell,port:source_match(source,cell),
                sink_filter=lambda name,cell,port:match(origin(cell),target))
            if not row['graph_complete']:raise RuntimeError('An observed graph is incomplete')
            result['paths'][source][target]={'connected':bool(row['register_to_register_paths']),
                'levels':row['longest_register_path_cells'],'path':row['register_to_register_paths'][:1]}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped',type=Path,required=True)
    parser.add_argument('--pre',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result={}
    for label in ('reference','current'):
        row=measure(args.mapped/label/'mapped.json',args.pre/label/'pre_lut.il')
        row['functional_verification']=json.loads((args.mapped/label/'summary.json').read_text())['functional_verification']
        result[label]=row
        print(json.dumps({'case':label,'logic_lut':row['resources']['logic_lut_cells'],
            'ff':row['resources']['flip_flops'],
            'paths':{source:{target:value['levels'] for target,value in row['paths'][source].items()}
                for source in ('rd_context_count','write_guard_state','read_response_buffer',
                    'write_response_buffer','rd_dma_done','dma_rd_error','wr_dma_done','dma_wr_error',
                    'abort_pending','all_sources')}},ensure_ascii=False),flush=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
