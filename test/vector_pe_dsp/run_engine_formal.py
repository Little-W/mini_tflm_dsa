#!/usr/bin/env python3
"""证明实际向量接入的使能、操作数选择、反馈及全部 PE 结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sections(source):
    first=source.index('  assign pe_operand_en =')
    last=source.index('  logic [ADD_INDEX_WIDTH-1:0] add_next_input_index;',first)
    return source[first:last]


def wrapper(block,tile,pes,reference=False):
    if reference:
        block=r'''
  logic reference_enable;
  assign reference_enable=dw_issue_fire || (state==EXECUTE && (!vector_hadamard || !writeback_busy));
  assign pe_operand_en=reference_enable;
  for(genvar lane=0;lane<PE_COUNT;lane++) begin:g_pe
    wire valid_lane=(TILE_INDEX_W+1)'(compute_index)+(TILE_INDEX_W+1)'(lane)<(TILE_INDEX_W+1)'(active);
    wire signed [15:0] reference_a=valid_lane ? input_lane[lane] : 16'sd0;
    wire signed [15:0] reference_b=depthwise ? 16'($signed(weight_lane[lane])) : rhs_lane[lane];
    wire signed [31:0] reference_acc=valid_lane ?
      ((depthwise && dw_commit_vld && dw_commit_index==compute_index) ? pe_result[lane] : accum_lane[lane]) : 32'sd0;
    vector_pe_reference #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_pe(
      .clk,.i_en(reference_enable),.i_op(pe_op),.i_a(reference_a),.i_b(reference_b),.i_acc(reference_acc),
      .o_result(pe_result[lane]));
  end
'''
    state=('g_pe[lane].u_pe.r_a',
           "(g_pe[lane].u_pe.r_op==PE_SUM ? 16'sd1 : g_pe[lane].u_pe.r_b)",
           "((g_pe[lane].u_pe.r_op==PE_MUL || g_pe[lane].u_pe.r_op==PE_MUL_UU || g_pe[lane].u_pe.r_op==PE_MUL_SU) ? 32'sd0 : g_pe[lane].u_pe.r_acc)",
           'g_pe[lane].u_pe.r_op') if reference else (
           'g_pe[lane].u_pe.a','g_pe[lane].u_pe.b','g_pe[lane].u_pe.acc','g_pe[lane].u_pe.op')
    return f'''module engine_pe_state #(
  parameter int TILE={tile},PE_COUNT={pes},
  parameter int TILE_INDEX_W=$clog2(TILE+PE_COUNT+1),ACTIVE_COUNT_W=$clog2(TILE+1)
)(
  input logic clk,depthwise,writeback_busy,vector_hadamard,dw_issue_fire,dw_commit_vld,
  input logic [5:0] state,
  input logic [TILE_INDEX_W-1:0] compute_index,dw_commit_index,
  input logic [ACTIVE_COUNT_W-1:0] active,
  input logic [2:0] pe_op,
  input logic signed [15:0] input_lane[PE_COUNT],rhs_lane[PE_COUNT],
  input logic signed [7:0] weight_lane[PE_COUNT],
  input logic signed [31:0] accum_lane[PE_COUNT],
  output wire signed [31:0] pe_result[PE_COUNT],
  output wire [PE_COUNT*16-1:0] state_a,state_b,
  output wire [PE_COUNT*32-1:0] state_acc,
  output wire [PE_COUNT*3-1:0] state_op
);
  import vector_engine_pkg::*;
  import vector_engine_control_pkg::*;
  logic pe_operand_en;
  logic signed [15:0] pe_a[PE_COUNT],pe_b[PE_COUNT];
  logic signed [31:0] pe_acc[PE_COUNT];
{block}
  for(genvar lane=0;lane<PE_COUNT;lane++) begin:g_observe
    assign state_a[lane*16+:16]={state[0]};
    assign state_b[lane*16+:16]={state[1]};
    assign state_acc[lane*32+:32]={state[2]};
    assign state_op[lane*3+:3]={state[3]};
  end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-rev',default='caace9471dafe0236f0e2a9a40b8ddb48bdb844d')
    args=parser.parse_args()
    root=args.source_root.resolve()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    engine=root/'rtl/npu/conv/vector_engine.sv'
    pe=root/'rtl/npu/conv/vector_pe.sv'
    packages=[root/'rtl/npu/conv'/name for name in
              ('conv_im2col_pkg.sv','vector_engine_pkg.sv','vector_engine_control_pkg.sv')]
    arithmetic_runner=ROOT/'test/vector_extremum/run.py'
    hashes={str(path):digest(path) for path in [engine,pe,*packages,Path(__file__),arithmetic_runner]}
    arithmetic=read_rtl_source(args.reference_rev+':rtl/npu/conv/vector_pe.sv',cwd=ROOT,text=True)
    adapter=runpy.run_path(str(arithmetic_runner))['clocked_reference']
    reference_pe=out/'reference_pe.sv'
    reference_pe.write_text(adapter(arithmetic).replace('module vector_pe #','module vector_pe_reference #',1))
    block=sections(engine.read_text())
    report={'passed':True,'source_sha256':hashes,'reference_revision':args.reference_rev,
            'reference_pe_sha256':digest(reference_pe),'input_constraints':None,'runs':[]}
    for tile,pes in [(1,1),(3,2),(16,8),(32,16)]:
        folder=out/f'tile{tile}_pe{pes}'
        folder.mkdir(exist_ok=True)
        commands=[]
        for label,reference in [('reference',True),('candidate',False)]:
            model=folder/(label+'.sv')
            model.write_text(wrapper(block,tile,pes,reference))
            paths=[*packages,reference_pe if reference else pe,model]
            commands+=['read_slang --top engine_pe_state '+shlex.join(map(str,paths)),
                       'prep -top engine_pe_state -flatten','memory_map','opt -full',
                       'rename -top '+label,'design -stash '+label]
        commands+=['design -copy-from reference -as reference reference',
                   'design -copy-from candidate -as candidate candidate',
                   'equiv_make reference candidate comparison','hierarchy -top comparison',
                   'equiv_simple -seq 2',
                   'equiv_induct -seq 3','equiv_status -assert']
        script=folder/'run.ys'
        script.write_text('\n'.join(commands)+'\n')
        log=folder/'formal.log'
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=240)
        counts=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log.read_text())
        if not counts or int(counts[2]):
            raise RuntimeError('PE 连接等价证明未完成：'+str(log))
        row={'tile':tile,'pe_count':pes,'passed':True,'compared_operand_state_bits':pes*67,
             'result_bits':pes*32,'equivalent_bits':int(counts[1]),'log_sha256':digest(log)}
        report['runs'].append(row)
        print(json.dumps(row),flush=True)
    if any(digest(path)!=value for path,value in hashes.items()):
        raise RuntimeError('验证期间输入源码变化')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
