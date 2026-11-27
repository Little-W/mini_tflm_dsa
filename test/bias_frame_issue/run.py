#!/usr/bin/env python3
"""验证偏置地址、帧需求和完整矩阵控制器的同周期输入发送行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CHANGED = (
    'rtl/npu/control/npu_controller.sv',
    'rtl/npu/control/npu_ia_issue_select.sv',
    'rtl/npu/top/npu_bias_address_zero.sv',
    'rtl/npu/top/npu_bias_presence.sv',
)
ADDED = tuple('rtl/npu/top/' + name + '.sv' for name in (
    'npu_bias_channel_match', 'npu_bias_issue_reduce', 'npu_bias_issue_optional', 'npu_bias_issue_select'))
COMMON = tuple('rtl/common/' + name + '.sv' for name in (
    'add_equal', 'add_equal_bit', 'add_equal_reduce', 'increment_equal', 'increment_equal_pair'))
WIDTHS = (1, 2, 3, 8, 16, 28, 29, 32, 40, 64)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, timeout=600):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)
    return log.read_text()


def worker(commands, folder, name):
    script, log = folder/(name+'.ys'), folder/(name+'.log')
    script.write_text('\n'.join(commands)+'\n')
    return run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)


def ports(source):
    start = source.index('module npu_controller')
    header = source[start:source.index('\n);', start)]
    result = re.findall(r'^\s*(input|output)\s+(?:(?:wire|logic|reg|signed)\s+)*(\[[^]]+\])?\s*(\w+)', header, re.M)
    if len(result) < 40:
        raise RuntimeError('控制器端口解析不完整')
    return result


def control_model(reference, external, current):
    """使用全部真实控制器端口，并按矩阵模块的完整位宽连接偏置条件。"""
    declarations = []
    connections = []
    for direction, width, name in ports(reference):
        declarations.append(f'{direction} wire {width} {name}')
        connections.append('.bias_base(REG_WIDTH\'(bias_present))' if external and name == 'bias_base'
                           else f'.{name}({name})')
    if external:
        declarations += ['input wire [31:0] ws_channel', 'input wire [31:0] is_channel',
                         'input wire [4:0] bias_flags']
    text = ('// 完整控制器的公开输入、输出和真实内部寄存器参与形式比较。\n'
            'module model #(parameter REG_WIDTH=32, SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16, WEIGHT_WIDTH=16)(\n'
            + ',\n'.join(declarations) + '\n);\n')
    if external:
        text += '''localparam integer CW=REG_WIDTH<32?REG_WIDTH:32;
wire bias_present,address_zero,frame_phase,issue_eligible,issue_qualified;
npu_bias_presence u_presence(
 .i_frame_mode(bias_flags[0]),.i_base_nonzero(bias_base!='0),.i_is_mode(bias_flags[1]),
 .i_ws_final_bias(bias_flags[2]),.i_frame_final(bias_flags[3]),.i_frame_init(bias_flags[4]),
 .i_address_zero(address_zero),.i_visible_base_nonzero(CW'(bias_base)!='0),.o_present(bias_present)'''
        text += (',.o_frame_phase(frame_phase)' if current else '') + ');\n'
        text += '''npu_bias_address_zero #(.p_width(CW)) u_zero_address(
 .i_base(CW'(bias_base)),.i_ws_channel(ws_channel),.i_is_channel(is_channel),
 .i_is_mode(bias_flags[1]),.o_zero(address_zero)'''
        if current:
            text += ''',.i_issue_eligible(issue_eligible),.i_frame_mode(bias_flags[0]),
 .i_base_nonzero(bias_base!='0),.i_frame_phase(frame_phase),
 .i_visible_base_nonzero(CW'(bias_base)!='0),.i_bias_available(bias_valid||bias_sleep),
 .i_frame_incomplete(!oa_calc_over),.i_output_complete(oa_calc_over),.o_issue(issue_qualified)'''
        text += ');\n'
        if current:
            connections += ['.o_ia_issue_eligible(issue_eligible)', '.i_ia_issue_qualified(issue_qualified)']
    parameters = ','.join(f'.{name}({name})' for name in ('REG_WIDTH','SIZE','BUS_WIDTH','DATA_WIDTH','WEIGHT_WIDTH'))
    if external and current:
        parameters += ",.p_external_ia_issue(1'b1)"
    return text+'npu_controller #('+parameters+') u_controller(\n'+',\n'.join(connections)+');\nendmodule\n'


def control_proofs(out, snapshots, common, reference_text):
    classify = runpy.run_path(str(ROOT/'test/bias_shared_arithmetic/run_formal.py'))['combinational_names']
    records = []
    for mode in ('generic', 'fpga'):
        flags = ['-USYNTHESIS','-UXILINX_FPGA'] if mode == 'generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
        for external in (False, True):
            for width in (8,16,28,29,32,64):
                folder=out/f'{mode}_{"connected" if external else "default"}_{width}'
                folder.mkdir(exist_ok=True)
                excluded, states = set(), {}
                for label in ('reference','current'):
                    model=folder/(label+'.sv')
                    model.write_text(control_model(reference_text, external, label=='current'))
                    inputs=[model, *snapshots[label], *common]
                    worker(['read_slang --top model '+shlex.join(flags+[f'-GREG_WIDTH={width}', *map(str,inputs)]),
                            'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                            'prep -top model -flatten','opt -full',f'rename -top {label}',
                            'write_json '+shlex.quote(str(folder/(label+'_state.json'))),
                            'async2sync','opt -full','check -assert',
                            'write_rtlil '+shlex.quote(str(folder/(label+'.il')))], folder, label)
                    module=json.loads((folder/(label+'_state.json')).read_text())['modules'][label]
                    names,states[label]=classify(module)
                    excluded.update(names)
                blacklist=folder/'combinational_names.txt'
                blacklist.write_text('\n'.join(sorted(excluded))+'\n')
                result=worker(['read_rtlil '+shlex.quote(str(folder/'reference.il')),
                               'read_rtlil '+shlex.quote(str(folder/'current.il')),
                               'equiv_make -blacklist '+shlex.quote(str(blacklist))+' reference current equivalent',
                               'hierarchy -top equivalent','equiv_simple -seq 1','opt_clean',
                               'equiv_induct -seq 4','equiv_status -assert'],folder,'proof')
                count=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',result)
                if not count or int(count[2]):
                    raise RuntimeError(str(folder/'proof.log'))
                records.append(dict(mode=mode,external_qualification=external,reg_width=width,
                                    equivalent_bits=int(count[1]),state_signals=states,passed=True,
                                    proof_sha256=digest(folder/'proof.log')))
                print('BIAS_CONTROLLER_PASS',mode,external,width,count[1],flush=True)
    return records


def combinational_proofs(out, snapshots, common):
    reference=[]
    for path in snapshots['reference']:
        if path.stem in ('npu_bias_address_zero','npu_bias_presence'):
            renamed=out/('reference_'+path.name)
            renamed.write_text(path.read_text().replace('module '+path.stem,'module reference_'+path.stem,1))
            reference.append(renamed)
    model=out/'comb.sv'
    model.write_text('''// 任意地址、通道、帧位置和发送条件共同参与比较。
module bias_model #(parameter WIDTH=32)(
 input wire [WIDTH-1:0] base, // 当前偏置基址
 input wire [31:0] ws_channel,is_channel, // 两种数据流的通道序号
 input wire [10:0] flags, // 帧模式、基址范围、数据流、帧位置、发送和完成条件
 output wire [2:0] expected, // 参考地址零值、偏置需求及完整发送
 output wire [2:0] actual, // 当前实现对应结果
 output wire equal // 所有输出相等
);
wire phase;
reference_npu_bias_address_zero #(.p_width(WIDTH)) u_reference_address(
 .i_base(base),.i_ws_channel(ws_channel),.i_is_channel(is_channel),.i_is_mode(flags[2]),.o_zero(expected[0]));
reference_npu_bias_presence u_reference_presence(
 .i_frame_mode(flags[0]),.i_base_nonzero(flags[1]),.i_is_mode(flags[2]),.i_ws_final_bias(flags[3]),
 .i_frame_final(flags[4]),.i_frame_init(flags[5]),.i_address_zero(expected[0]),
 .i_visible_base_nonzero(flags[6]),.o_present(expected[1]));
npu_bias_address_zero #(.p_width(WIDTH)) u_address(
 .i_base(base),.i_ws_channel(ws_channel),.i_is_channel(is_channel),.i_is_mode(flags[2]),.o_zero(actual[0]),
 .i_issue_eligible(flags[7]),.i_frame_mode(flags[0]),.i_base_nonzero(flags[1]),.i_frame_phase(phase),
 .i_visible_base_nonzero(flags[6]),.i_bias_available(flags[8]),
 .i_frame_incomplete(flags[9]),.i_output_complete(flags[10]),.o_issue(actual[2]));
npu_bias_presence u_presence(
 .i_frame_mode(flags[0]),.i_base_nonzero(flags[1]),.i_is_mode(flags[2]),.i_ws_final_bias(flags[3]),
 .i_frame_final(flags[4]),.i_frame_init(flags[5]),.i_address_zero(actual[0]),
 .i_visible_base_nonzero(flags[6]),.o_present(actual[1]),.o_frame_phase(phase));
assign expected[2]=flags[7]&&(flags[8]||!expected[1])&&(flags[0]?flags[9]:!flags[10]);
assign equal=actual==expected;
endmodule
''')
    lines=['// 多种位宽共享任意四态输入，并覆盖地址回绕和数据流选择。',
           'module tb;',"reg [63:0] base;reg [31:0] ws_channel,is_channel;reg [10:0] flags;",
           "integer rng=32'h5a97321d,checks=0,choice;reg [138:0] known,values;"]
    for width in WIDTHS:
        lines += [f'wire [2:0] e{width},a{width};',f'bias_model #(.WIDTH({width})) u{width}(',
                  f'.base(base[{width-1}:0]),.ws_channel(ws_channel),.is_channel(is_channel),.flags(flags),',
                  f'.expected(e{width}),.actual(a{width}),.equal());']
    lines += ['function automatic [31:0] random_word;',
              'rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;endfunction',
              'task check;begin #1;']
    for width in WIDTHS:
        lines += [f'checks++;if(e{width}!==a{width})$fatal(1,"Bias issue WIDTH={width} base=%h ws=%h is=%h flags=%b expected=%b actual=%b",base,ws_channel,is_channel,flags,e{width},a{width});']
    lines += ['end endtask','initial begin',
              'for(integer sample=0;sample<16384;sample++)begin',
              'base={random_word(),random_word()};ws_channel=random_word();is_channel=random_word();flags=11\'(random_word());',
              'if(sample%4==0)base=-64\'(ws_channel<<2);',
              'if(sample%4==1)base=-64\'(is_channel<<2);check();end',
              'for(integer sample=0;sample<16384;sample++)begin',
              'for(integer bit_index=0;bit_index<139;bit_index++)begin',
              'case(random_word()%4)0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1\'bx;3:values[bit_index]=1\'bz;endcase end',
              '{base,ws_channel,is_channel,flags}=values;check();end',
              'for(integer sample=0;sample<16384;sample++)begin',
              'base=sample[0]?64\'d4:64\'d0;ws_channel=0;is_channel=32\'hffffffff;flags=11\'(random_word());',
              'for(integer bit_index=0;bit_index<7;bit_index++)begin',
              'case((sample>>(2*bit_index))&3)0:flags[bit_index]=0;1:flags[bit_index]=1;2:flags[bit_index]=1\'bx;3:flags[bit_index]=1\'bz;endcase end check();end',
              'for(integer sample=0;sample<64;sample++)begin',
              'known={random_word(),random_word(),random_word(),random_word(),11\'(random_word())};',
              'for(integer bit_index=0;bit_index<139;bit_index++)begin',
              'values=known;values[bit_index]=1\'bx;{base,ws_channel,is_channel,flags}=values;check();',
              'values=known;values[bit_index]=1\'bz;{base,ws_channel,is_channel,flags}=values;check();end end',
              '$display("BIAS_ISSUE_FOUR_STATE_PASS checks=%0d",checks);$finish;end endmodule']
    tb=out/'tb.sv';tb.write_text('\n'.join(lines)+'\n')
    inputs=[model,*reference,*snapshots['current'],*common]
    records=[]
    for mode in ('generic','fpga'):
        flags=['-USYNTHESIS','-UXILINX_FPGA'] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
        for width in WIDTHS:
            log=worker(['read_slang --top bias_model '+shlex.join(flags+[f'-GWIDTH={width}',*map(str,inputs)]),
                        'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                        'prep -top bias_model -flatten','sat -verify -prove equal 1 -show-inputs'],out,f'{mode}_comb_{width}')
            if 'SUCCESS!' not in log:
                raise RuntimeError(f'组合比较未通过 {mode} {width}')
        binary=out/(mode+'.vvp')
        run(['iverilog','-g2012','-s','tb',*(flags if mode=='fpga' else []),'-o',binary,*inputs,tb],out/(mode+'_compile.log'))
        result=run(['vvp',binary],out/(mode+'_four_state.log'))
        count=re.search(r'BIAS_ISSUE_FOUR_STATE_PASS checks=(\d+)',result)
        if not count:
            raise RuntimeError(str(out/(mode+'_four_state.log')))
        records.append(dict(mode=mode,widths=WIDTHS,formal_profiles=len(WIDTHS),
                            four_state_checks=int(count[1]),passed=True,
                            four_state_sha256=digest(out/(mode+'_four_state.log'))))
        print(result,flush=True)
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='8009b2f7')
    parser.add_argument('--section',choices=('control','combinational'),required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip()
    production=[ROOT/p for p in (*CHANGED,*ADDED,*COMMON,'rtl/npu/top/npu_matrix_engine.sv')]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in production}
    snapshots={}
    for label in ('reference','current'):
        folder=out/label;folder.mkdir(exist_ok=True);snapshots[label]=[]
        for relative in (*CHANGED,*ADDED) if label=='current' else CHANGED:
            target=folder/Path(relative).name
            target.write_bytes((ROOT/relative).read_bytes() if label=='current' else
                               subprocess.check_output(['git','show',revision+':'+relative],cwd=ROOT))
            snapshots[label].append(target)
    common=[ROOT/p for p in COMMON]
    if args.section=='control':
        records=control_proofs(out,snapshots,common,(out/'reference/npu_controller.sv').read_text())
    else:
        records=combinational_proofs(out,snapshots,common)
    if hashes!={str(p.relative_to(ROOT)):digest(p) for p in production}:
        raise RuntimeError('验证期间生产源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,reference_commit=revision,
        external_input_assumptions=[],source_sha256=hashes,profiles=records,
        runner_sha256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
