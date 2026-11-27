#!/usr/bin/env python3
"""核对矩阵引擎实际端口连接，并穷举帧完成与输入发送限定的四态关系。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test/bias_frame_issue'))
from run import digest,run,worker


def tokens(text):
    return re.sub(r'\s+','',re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S))


def instance(source,module):
    start=source.index('    '+module+' ')
    return source[start:source.index('\n    );',start)+7]


def connections(text,name):
    start=text.index(name+' (')+len(name)+1
    body=text[start+1:]
    result={}
    for match in re.finditer(r'\.(\w+)\s*\(',body):
        index=match.end();depth=1;last=index
        while depth:
            depth += (body[last]=='(')-(body[last]==')');last+=1
        result[match[1]]=tokens(body[index:last-1])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='8009b2f7')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_path=ROOT/'rtl/npu/top/npu_matrix_engine.sv';source=source_path.read_text()
    original=subprocess.check_output(['git','show',args.reference+':'+str(source_path.relative_to(ROOT))],cwd=ROOT,text=True)
    restored=source
    for module in ('npu_bias_address_zero','npu_bias_presence','npu_controller'):
        old,new=instance(original,module),instance(source,module)
        restored=restored.replace(new,old,1)
        if module=='npu_controller':
            a,b=connections(old,'u_npu_controller'),connections(new,'u_npu_controller')
            if b.pop('o_ia_issue_eligible')!='controller_issue_eligible' or b.pop('i_ia_issue_qualified')!='controller_issue_qualified' or a!=b:
                raise RuntimeError('控制器公开端口连接发生变化')
            if ".p_external_ia_issue(1'b1)" not in tokens(new):
                raise RuntimeError('控制器未选择外部组合发送资格')
    declarations=['logic exec_frame_bias_phase;','logic controller_issue_eligible;',
                  'logic controller_issue_qualified;','(* keep = 1 *) logic frame_issue_incomplete;']
    for declaration in declarations:
        if restored.count(declaration)!=1:
            raise RuntimeError('矩阵引擎内部连接声明不完整')
        restored=restored.replace(declaration,'',1)
    qualification=re.search(r'    assign frame_issue_incomplete\s*=.*?;',source,re.S)
    expected='''assign frame_issue_incomplete = !(frame_complete_i_active && frame_complete_i_eligible &&
        (frame_complete_i_store_seen || frame_complete_i_store_complete));'''
    if not qualification or tokens(qualification[0])!=tokens(expected):
        raise RuntimeError('帧内未完成条件不符合当前完成定义')
    restored=restored.replace(qualification[0],'',1)
    if tokens(restored)!=tokens(original):
        raise RuntimeError('矩阵引擎的其余功能发生变化')
    zero=connections(instance(source,'npu_bias_address_zero'),'u_bias_zero')
    expected_zero=dict(i_base="p_controller_bias_w'(i_bias_base)",i_ws_channel='frame_exec_column',
        i_is_channel='frame_exec_p0',i_is_mode='o_is_mode',o_zero='bias_zero_o_equal',
        i_issue_eligible='controller_issue_eligible',i_frame_mode='o_frame_mode_q',
        i_base_nonzero='bias_base_nonzero',i_frame_phase='exec_frame_bias_phase',
        i_visible_base_nonzero='controller_bias_base_nonzero',i_bias_available='bias_group_valid||bias_sleep',
        i_frame_incomplete='frame_issue_incomplete',i_output_complete='oa_calc_over',o_issue='controller_issue_qualified')
    if zero!=expected_zero:
        raise RuntimeError('偏置发送资格端口连接不完整')
    presence=connections(instance(source,'npu_bias_presence'),'u_bias_presence')
    old_presence=connections(instance(original,'npu_bias_presence'),'u_bias_presence')
    if presence.pop('o_frame_phase')!='exec_frame_bias_phase' or presence!=old_presence:
        raise RuntimeError('偏置帧位置连接发生变化')

    make=runpy.run_path(str(ROOT/'test/matrix_frame_complete/run.py'))['model']
    text=make(source,'completion_context')
    text=text.replace('output logic o_complete);','output logic o_complete, output logic o_allowed);')
    text=text.replace('logic exec_oa_complete;','logic exec_oa_complete;\nlogic frame_issue_incomplete;')
    text=text.replace('    assign o_complete = exec_oa_complete;',
        '    assign o_complete = exec_oa_complete;\n    assign o_allowed = o_frame_mode_q ? frame_issue_incomplete : !oa_calc_over;')
    model=out/'model.sv';model.write_text(text+'''// 同一生产完成条件必须允许且仅允许尚未完成的任务继续发送。
module proof(input wire [10:0] controls,output wire equal);
wire completed,allowed;
completion_context u_context(.i_controls(controls),.o_complete(completed),.o_allowed(allowed));
assign equal=allowed===!completed;
endmodule
''')
    helper=ROOT/'rtl/npu/top/npu_frame_complete_select.sv'
    tb=out/'tb.sv';tb.write_text('''// 十一项实际帧完成输入的全部四态组合。
module tb;
reg [10:0] controls;wire equal;integer checks=0;
proof u_proof(controls,equal);
initial begin
 for(integer sample=0;sample<4194304;sample++)begin
  for(integer bit_index=0;bit_index<11;bit_index++)begin
   case((sample>>(2*bit_index))&3)
   0:controls[bit_index]=0;1:controls[bit_index]=1;2:controls[bit_index]=1'bx;3:controls[bit_index]=1'bz;
   endcase
  end
  #1;checks++;if(equal!==1'b1)$fatal(1,"Frame issue differs controls=%b",controls);
 end
 $display("FRAME_ISSUE_BINDING_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    result=worker(['read_slang --top proof '+shlex.join(map(str,[model,helper])),
                   'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                   'prep -top proof -flatten','sat -verify -prove equal 1 -show-inputs'],out,'proof')
    if 'SUCCESS!' not in result:
        raise RuntimeError('帧完成组合证明未完成')
    binary=out/'binding.vvp'
    run(['iverilog','-g2012','-s','tb','-o',binary,model,helper,tb],out/'compile.log')
    result=run(['vvp',binary],out/'four_state.log')
    if 'PASS checks=4194304' not in result:
        raise RuntimeError(result)
    if source!=source_path.read_text():
        raise RuntimeError('验证期间矩阵引擎源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,reference=args.reference,
        remaining_matrix_functional_tokens_identical=True,all_connections_verified=True,
        arbitrary_input_formal_proven=True,four_state_checks=4194304,
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in (source_path,helper)},
        proof_sha256=digest(out/'proof.log'),four_state_sha256=digest(out/'four_state.log'),
        runner_sha256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)


if __name__=='__main__':
    main()
