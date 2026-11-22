#!/usr/bin/env python3
"""验证实际 WS、IS 与整张量参数选择的全部输入组合。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def assignment(source, name):
    match = re.search(r'\bassign\s+' + re.escape(name) + r'\s*=.*?;', source, re.S)
    if match is None:
        raise ValueError('未找到实际参数选择表达式：' + name)
    return match[0]


def wrapper(source, bus, lanes, observe):
    common = '\n'.join(assignment(source, name) for name in
        ('common_parameters', 'ws_parameters_select', 'common_product_parameters_s0'))
    selected = '\n'.join(assignment(source, name) for name in
        ('lane_multiplier', 'lane_amount', 'quant_multiplier_lane[lane]', 'quant_shift_lane[lane]'))
    return f'''module parameter_read_proof (
        input logic cfg_per_channel_eff,is_mode_r,ws_parameters_select_s0,per_channel_s0,
        input logic [15:0] i_row_index,i_read_index,
        input logic [{103*lanes-1}:0] i_ws,
        input logic [{103*(bus//32)-1}:0] i_is,
        input logic [102:0] i_tensor
    );
    localparam int VLEN={lanes},PARAM_BANKS={bus//32};
    localparam bit p_parameter_output={observe};
    localparam int p_bank_width=(PARAM_BANKS<=1)?1:$clog2(PARAM_BANKS);
    logic [p_bank_width-1:0] parameter_bank_s0;
    logic signed [31:0] ch_multiplier_lane_r[VLEN],ch_shift_lane_r[VLEN];
    logic signed [31:0] ws_multiplier_q[VLEN];
    logic [6:0] ws_amount_q[VLEN];
    logic [102:0] is_parameter[PARAM_BANKS];
    logic signed [31:0] ch_multiplier_is_sel,ch_shift_is_sel;
    logic signed [31:0] ch_product_multiplier_is_sel;
    logic [6:0] ch_product_amount_is_sel;
    logic signed [31:0] pt_multiplier_r,pt_shift_r,pt_product_multiplier_s0;
    logic [6:0] pt_product_amount_s0;
    logic [63:0] common_parameters;
    logic [38:0] common_product_parameters_s0;
    logic ws_parameters_select;
    logic signed [31:0] quant_multiplier_lane[VLEN],quant_shift_lane[VLEN];
    assign parameter_bank_s0=p_bank_width'(int'(i_read_index)%PARAM_BANKS);
    assign {{pt_multiplier_r,pt_shift_r,pt_product_multiplier_s0,pt_product_amount_s0}}=i_tensor;
    for(genvar bank=0;bank<PARAM_BANKS;bank++)begin:g_bank
        assign is_parameter[bank]=i_is[103*bank+:103];
    end
    assign {{ch_multiplier_is_sel,ch_shift_is_sel}}=is_parameter[int'(i_row_index)%PARAM_BANKS][102:39];
    assign {{ch_product_multiplier_is_sel,ch_product_amount_is_sel}}=is_parameter[parameter_bank_s0][38:0];
    {common}
    for(genvar lane=0;lane<VLEN;lane++)begin:g_lane
        logic signed [31:0] lane_multiplier;
        logic [6:0] lane_amount;
        logic [63:0] raw_expected;
        logic [38:0] product_expected;
        logic [102:0] actual,expected;
        assign {{ch_multiplier_lane_r[lane],ch_shift_lane_r[lane],ws_multiplier_q[lane],ws_amount_q[lane]}}=i_ws[103*lane+:103];
        assign raw_expected=!p_parameter_output ? 64'd0 : !cfg_per_channel_eff ? i_tensor[102:39] :
            is_mode_r ? is_parameter[int'(i_row_index)%PARAM_BANKS][102:39] : i_ws[103*lane+39+:64];
        assign product_expected=ws_parameters_select_s0 ? i_ws[103*lane+:39] :
            per_channel_s0 ? is_parameter[int'(i_read_index)%PARAM_BANKS][38:0] : i_tensor[38:0];
        {selected.replace('ws_multiplier_q :','ws_multiplier_q[lane] :').replace('ws_amount_q :','ws_amount_q[lane] :')}
        assign actual={{quant_multiplier_lane[lane],quant_shift_lane[lane],lane_multiplier,lane_amount}};
        assign expected={{raw_expected,product_expected}};
        always_comb assert(actual==expected);
    end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    path=ROOT/'rtl/npu/writeback/vec_requant.sv';source=path.read_text()
    summary={'passed':False,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'inputs_constrained':False,'profiles':[]}
    for bus in (32,64,96,128):
        for observe in (0,1):
            folder=out/f'bus{bus}_observe{observe}';folder.mkdir(exist_ok=True)
            unit=folder/'proof.sv';unit.write_text(wrapper(source,bus,16,observe))
            script=folder/'proof.ys';log=folder/'proof.log'
            script.write_text('read_slang --top parameter_read_proof '+shlex.quote(str(unit))+'\n'+
                'prep -top parameter_read_proof -flatten\nchformal -lower\nopt -full\n'+
                'sat -set-def-inputs -prove-asserts -verify\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                    stdout=stream,stderr=subprocess.STDOUT,check=True)
            assert 'SUCCESS!' in log.read_text()
            row={'bus_width':bus,'lanes':16,'parameter_output':bool(observe),'passed':True,
                 'compared_bits':1648,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
            summary['profiles'].append(row);print(json.dumps(row),flush=True)
    assert source==path.read_text()
    summary['passed']=True;(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':main()
