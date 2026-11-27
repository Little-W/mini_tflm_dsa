#!/usr/bin/env python3
"""证明部分和接受限定在完整帧存储及四态读取控制中的同周期行为。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
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
from transition import prove as prove_transition

STORE='rtl/npu/ps_compact/ps_frame_store.sv'
HELPER='rtl/npu/ps_compact/ps_frame_read_enable.sv'
BUFFER='rtl/npu/buffers/ps_buffer.sv'


def wrapper(source,current):
    start=source.index('module ps_frame_store')
    end=source.index('\n);',start)+4
    header=source[start:end].replace('module ps_frame_store','module model',1)
    parameters=re.findall(r'parameter\s+(?:integer|bit|int(?:\s+unsigned)?)\s+(\w+)',header)
    port_text=header[header.index(') ('):]
    ports=re.findall(r'^\s*(?:input|output)\s+(?:(?:wire|logic|reg|signed)\s+)*(?:\[[^\n]+?\]\s*)?(\w+)',port_text,re.M)
    if len(ports)<30 or 'frame_accept_permit' not in ports:
        raise RuntimeError('帧存储端口解析不完整')
    connections=[]
    for name in ports:
        if name=='frame_accept_permit' and not current:
            continue
        value='frame_accept && frame_accept_permit' if name=='frame_accept' and not current else name
        connections.append(f'.{name}({value})')
    return ('// 所有帧存储端口和存储状态参与比较，执行模式限制保持同周期。\n'+header+'\n'
            +'ps_frame_store #('+','.join(f'.{name}({name})' for name in parameters)+') u_store(\n'
            +',\n'.join(connections)+');\nendmodule\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='8009b2f7')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--control-only',action='store_true')
    parser.add_argument('--profiles',nargs='+',choices=('production','compact','internal','rotating','odd_frames'),
                        default=('production','compact','internal','rotating','odd_frames'))
    parser.add_argument('--modes',nargs='+',choices=('generic','fpga'),default=('generic','fpga'))
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip()
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    classify=runpy.run_path(str(ROOT/'test/bias_shared_arithmetic/run_formal.py'))['combinational_names']
    cases=dict(runpy.run_path(str(ROOT/'test/ps_frame_ready/run_full.py'))['CASES'])
    cases['odd_frames']=('ps_frame_store',STORE,dict(MAX_FRAME_ROWS=47,FRAME_COUNT=3,POOL_BYTES=4096,BANK_BYTES=2048,EXTERNAL_RAM=0))
    dependencies=resolve([ROOT/STORE,ROOT/BUFFER],ROOT)
    hashes={str(p.relative_to(ROOT)):digest(p) for p in dependencies}
    current=(ROOT/STORE).read_text()
    original_store=subprocess.check_output(['git','show',revision+':'+STORE],cwd=ROOT,text=True)
    restored=re.sub(r'^\s*input\s+wire frame_accept_permit[^\n]*\n','\n',current,flags=re.M)
    restored=re.sub(r'^\s*wire frame_accept_selected = frame_accept && frame_accept_permit;\n','\n',restored,flags=re.M)
    restored=re.sub(r'\bframe_accept_selected\b','frame_accept',restored)
    restored=restored.replace('.i_accept_permit(frame_accept_permit),','')
    clean=lambda text:re.sub(r'\s+','',re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S))
    if clean(restored)!=clean(original_store):
        raise RuntimeError('帧存储的其余状态和数据处理发生变化')
    original_buffer=subprocess.check_output(['git','show',revision+':'+BUFFER],cwd=ROOT,text=True)
    expected=original_buffer.replace('.frame_accept(frame_accept && !direct_final_stream),',
        '.frame_accept(frame_accept), .frame_accept_permit(!direct_final_stream),')
    if expected!=(ROOT/BUFFER).read_text():
        raise RuntimeError('部分和缓冲器的其余功能发生变化')
    relation='''!i_fault && ((i_request && i_first_ready) ||
        ((i_request || (i_accept && i_accept_permit) || i_accepted) && i_continue_ready))'''
    component=out/'read_relation.sv'
    component.write_text('''// 完整端口组合关系独立证明，不限制接受资格与请求状态。
module proof(
 input wire [6:0] values, // 请求、接受、执行模式、帧状态和错误条件
 output wire equal // 生产读取选择与用于状态归纳的表达式相等
);
wire selected;
wire i_request=values[0],i_accept=values[1],i_accept_permit=values[2];
wire i_accepted=values[3],i_first_ready=values[4],i_continue_ready=values[5],i_fault=values[6];
ps_frame_read_enable u_actual(.i_request(i_request),.i_accept(i_accept),.i_accept_permit(i_accept_permit),
 .i_accepted(i_accepted),.i_first_ready(i_first_ready),.i_continue_ready(i_continue_ready),
 .i_fault(i_fault),.o_read_enable(selected));
assign equal=selected==('''+relation+''');
endmodule
''')
    component_proofs=[]
    for mode in args.modes:
        flags=['-USYNTHESIS','-UXILINX_FPGA'] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
        result=worker(['read_slang --top proof '+shlex.join(flags+[str(component),str(ROOT/HELPER)]),
                       'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                       'prep -top proof -flatten','sat -verify -prove equal 1 -show-inputs'],out,mode+'_read_relation')
        if 'SUCCESS!' not in result:
            raise RuntimeError('实际读取选择的完整端口关系未证明')
        component_proofs.append(dict(mode=mode,passed=True,log_sha256=digest(out/(mode+'_read_relation.log'))))
    sets={}
    for label in ('reference','current'):
        folder=out/label;folder.mkdir(exist_ok=True)
        inputs=[]
        for relative in (STORE,HELPER):
            path=folder/Path(relative).name
            path.write_bytes((ROOT/relative).read_bytes() if label=='current' else
                             subprocess.check_output(['git','show',revision+':'+relative],cwd=ROOT))
            inputs.append(path)
        model=folder/'model.sv';model.write_text(wrapper(current,label=='current'))
        sets[label]=resolve([model,*inputs],ROOT)

    def prove(job):
        name,mode=job;folder=out/(name+'_'+mode);folder.mkdir(exist_ok=True)
        flags=['-USYNTHESIS','-UXILINX_FPGA'] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
        flags += [f'-G{key}={value}' for key,value in cases[name][2].items()]
        states={}
        for label in ('reference','current'):
            worker(['read_slang --top model '+shlex.join(flags+list(map(str,sets[label]))),
                    'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                    'prep -top model -flatten','memory_map','opt -full',f'rename -top {label}',
                    'write_json '+shlex.quote(str(folder/(label+'_state.json'))),
                    'async2sync','opt -full','check -assert',
                    'write_rtlil '+shlex.quote(str(folder/(label+'.il')))],folder,label)
            module=json.loads((folder/(label+'_state.json')).read_text())['modules'][label]
            _,states[label]=classify(module)
        transition=prove_transition(folder,worker)
        record=dict(profile=name,mode=mode,parameters=cases[name][2],passed=True,
                    independently_proven_read_relation=True,transition=transition,
                    state_signal_count={k:len(v) for k,v in states.items()})
        record['intermediate_sha256']={p.name:digest(p) for p in folder.glob('*') if p.suffix in ('.json','.il')}
        for path in folder.glob('*'):
            if path.suffix in ('.json','.il'):
                path.unlink()
        print('PS_ACCEPT_COMPLETE_PASS',name,mode,transition['real_state_bits'],flush=True)
        return record

    records=[]
    if not args.control_only:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            records=list(pool.map(prove,((name,mode) for name in args.profiles for mode in args.modes)))
    tb=out/'tb.sv';tb.write_text('''// 穷举请求、接受、执行模式、存储状态和错误的全部四态组合。
module tb;
reg [6:0] values;wire selected;wire expected;integer checks=0;
ps_frame_read_enable u_dut(.i_request(values[0]),.i_accept(values[1]),.i_accept_permit(values[2]),
 .i_accepted(values[3]),.i_first_ready(values[4]),.i_continue_ready(values[5]),.i_fault(values[6]),.o_read_enable(selected));
assign expected=!values[6]&&((values[0]&&values[4])||
 ((values[0]||(values[1]&&values[2])||values[3])&&values[5]));
initial begin
 for(integer sample=0;sample<16384;sample++)begin
  for(integer bit_index=0;bit_index<7;bit_index++)begin
   case((sample>>(2*bit_index))&3)
   0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;
   endcase
  end
  #1;checks++;if(selected!==expected)$fatal(1,"PS read differs values=%b",values);
 end
 $display("PS_ACCEPT_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    four=[]
    for mode in args.modes:
        flags=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
        binary=out/(mode+'.vvp')
        run(['iverilog','-g2012','-s','tb',*flags,'-o',binary,ROOT/HELPER,tb],out/(mode+'_compile.log'))
        result=run(['vvp',binary],out/(mode+'_four_state.log'))
        if 'PASS checks=16384' not in result:
            raise RuntimeError(result)
        four.append(dict(mode=mode,checks=16384,passed=True,log_sha256=digest(out/(mode+'_four_state.log'))))
    if hashes!={str(p.relative_to(ROOT)):digest(p) for p in dependencies}:
        raise RuntimeError('验证期间部分和源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,reference_commit=revision,
        input_assumptions=[],all_public_outputs_and_state_compared=True,all_memory_contents_compared=True,
        buffer_remaining_source_identical=True,store_remaining_functional_tokens_identical=True,
        source_sha256=hashes,profiles=records,four_state=four,read_relation_proofs=component_proofs,
        proof_composition='实际组合表达式逐项检查；真实寄存器一一对应后比较全部状态转移输入与公开输出，读取 helper 另行证明完整端口关系',
        transition_runner_sha256=digest(Path(__file__).with_name('transition.py')),
        runner_sha256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
