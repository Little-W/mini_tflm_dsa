#!/usr/bin/env python3
"""比较完整向量控制模块，并从原始语法树提取四态寄存器更新条件。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys
import pyslang

ROOT=Path(__file__).resolve().parents[2]
CONTROL=Path('rtl/npu/conv/vector_engine_control.sv')
HELPER=Path('rtl/npu/conv/vector_tap_update_select.sv')
MODES=(('generic',['-USYNTHESIS','-UXILINX_FPGA']),
       ('synthesis',['-DSYNTHESIS=1','-UXILINX_FPGA']),
       ('fpga',['-USYNTHESIS','-DXILINX_FPGA=1']),
       ('fpga_synthesis',['-DSYNTHESIS=1','-DXILINX_FPGA=1']))
NAMES=('i_state','i_config_done','i_config_error','i_dw_advance','i_tap_last_modulo',
       'i_dw_snapshot','i_position_more','i_output_column_last','i_compute_group_last',
       'i_global_pool','i_spatial','i_tap_last_wide')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command,log,timeout=600):
    with Path(log).open('w') as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=timeout)


def original_events(text):
    """只删除不写目标寄存器的语句，保留原 if/else 与 case 的控制顺序。"""
    tree=pyslang.syntax.SyntaxTree.fromText(text)
    block=next(m for m in tree.root.members if type(m).__name__=='ProceduralBlockSyntax'
               and re.search(r'\bweight_prefetch_q\s*<=',str(m)))
    reset=block.statement.statement.items[0]
    assert type(reset).__name__=='ConditionalStatementSyntax' and str(reset.predicate).strip()=='!rst_n'
    assignments=[]
    def prune(node):
        if not re.search(r'\b(?:weight_prefetch_q|input_y)\s*<=',str(node)):return ''
        kind=type(node).__name__
        if kind=='BlockStatementSyntax':
            parts=[p for item in node.items if (p:=prune(item))]
            return 'begin\n'+'\n'.join(parts)+'\nend' if parts else ''
        if kind=='ConditionalStatementSyntax':
            yes=prune(node.statement)
            no=prune(node.elseClause.clause) if node.elseClause else ''
            if not yes and not no:return ''
            return 'if ('+str(node.predicate)+') '+(yes or 'begin end')+(' else '+no if no else '')
        if kind=='CaseStatementSyntax':
            parts=[]
            for item in node.items:
                content=prune(item.clause)
                if content:
                    label=''.join(str(x) for x in item.expressions) if hasattr(item,'expressions') else 'default'
                    parts.append(label+': '+content)
            return 'case ('+str(node.expr)+')\n'+'\n'.join(parts)+'\nendcase' if parts else ''
        if kind=='ExpressionStatementSyntax':
            name=str(node.expr.left).strip();value=re.sub(r'\s+','',str(node.expr.right))
            if name=='weight_prefetch_q':
                keys=["tap_last_config?'0:weight_tap_nxt","tap_last_zero?'0:p_tap_count_w'(1)","tap_last_increment?'0:weight_tap_after_next"]
                index=keys.index(value);assignments.append((name,value));return f'o_weight_select[{index}]=1\'b1;'
            if name=='input_y':
                keys=['input_origin_y',"18'($signed(coordinate_step_o_value[3]))","18'(next_window_y)"]
                index=keys.index(value);assignments.append((name,value));return f'o_y_select[{index}]=1\'b1;'
            return ''
        raise ValueError('Unexpected target statement: '+kind)
    code=prune(reset.elseClause.clause);assert len(assignments)==12
    code=re.sub(r'\box\s*==\s*output_last_column\b','i_output_column_last',code)
    rename={'state':'i_state','config_check_done':'i_config_done','config_check_error':'i_config_error',
            'dw_tap_advance':'i_dw_advance','tap_last_modulo':'i_tap_last_modulo',
            'dw_snapshot_fire':'i_dw_snapshot','position_has_more':'i_position_more',
            'compute_group_last_q':'i_compute_group_last','global_pool':'i_global_pool',
            'spatial':'i_spatial','tap_last_wide':'i_tap_last_wide'}
    for old,new in rename.items():code=re.sub(r'\b'+old+r'\b',new,code)
    return code,assignments


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--reference',default='57b61b24')
    parser.add_argument('--jobs',type=int,default=2);args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    reference=out/'reference_control.sv';reference.write_bytes(subprocess.check_output(['git','show',args.reference+':'+str(CONTROL)],cwd=ROOT))
    sources={label:resolve([path],ROOT) for label,path in [('reference',reference),('current',ROOT/CONTROL)]}
    hashes={str(p):digest(p) for paths in sources.values() for p in paths};jobs=[]
    for mode,flags in MODES:
        for lanes in (8,16):
            name=f'{mode}_lanes{lanes}';options=['-Gp_tile=16','-Gp_bus_width=64','-Gp_dma_size=64',f'-Gp_pe_count={lanes}',f'-Gp_window_lanes={lanes}','-Gp_shared_storage_enable=1',f'-Gp_shared_quant_enable={int(lanes==16)}'];commands=[]
            for label,paths in sources.items():
                commands+=['read_slang --top vector_engine_control '+shlex.join(flags+options+list(map(str,paths))),
                  'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy','prep -top vector_engine_control -flatten',
                  'memory_map','async2sync','opt -full','rename -top '+label,'design -stash '+label]
            commands+=['design -copy-from reference -as reference reference','design -copy-from current -as current current',
              'equiv_make reference current proof','hierarchy -top proof','opt -full','equiv_simple -short -seq 1',
              'equiv_induct -seq 2','equiv_simple -seq 1','equiv_status -assert']
            script=out/(name+'.ys');script.write_text('\n'.join(commands)+'\n');jobs.append((name,mode,flags,lanes,script))
    def prove(job):
        name,mode,flags,lanes,script=job;log=out/(name+'.log')
        execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        text=log.read_text();assert 'Equivalence successfully proven!' in text
        row={'mode':mode,'macro_options':flags,'pe_count':lanes,'passed':True,
             'equivalence_points':int(re.findall(r'Found (\d+) \$equiv cells',text)[-1]),'log_sha256':digest(log)}
        print(json.dumps(row),flush=True);return row
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:proofs=list(pool.map(prove,jobs))
    events,assignments=original_events(reference.read_text())
    helper=(ROOT/HELPER).read_text();start=helper.index('(',helper.index('module vector_tap_update_select'));end=helper.index(');',start)
    ports=helper[start+1:end]
    model=out/'event_reference.sv';model.write_text('// 从原控制模块的十二处寄存器写入提取独热更新事件。\nmodule event_reference('+ports+');\nalways_comb begin\no_weight_select=\'0;o_y_select=\'0;\n'+events+'\nend\nendmodule\n')
    declarations='logic [5:0] i_state;\n'+'\n'.join('logic '+name+';' for name in NAMES[1:])
    connections=','.join('.'+name+'('+name+')' for name in NAMES)
    bench=out/'tb.sv';bench.write_text('''`timescale 1ns/1ps
// 枚举全部二态状态和控制组合，并逐位覆盖未知控制。
module tb;
'''+declarations+'''
logic [16:0] stimulus;
wire [5:0] expected,actual;
int unsigned random_state=32'hc54e9271;
integer checks=0;
assign {'''+','.join(NAMES)+'''}=stimulus;
event_reference reference_dut('''+connections+''',.o_weight_select(expected[2:0]),.o_y_select(expected[5:3]));
vector_tap_update_select current_dut('''+connections+''',.o_weight_select(actual[2:0]),.o_y_select(actual[5:3]));
function automatic int unsigned next_random();
 random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;
endfunction
task automatic check;
 #1;if(actual!==expected)$fatal(1,"tap update differs case=%0d value=%b expected=%b actual=%b",checks,stimulus,expected,actual);
 checks++;
endtask
initial begin
 for(integer value=0;value<131072;value++)begin stimulus=17'(value);check();end
 for(integer bit_index=0;bit_index<17;bit_index++)begin
  for(integer pattern=0;pattern<2048;pattern++)begin
   stimulus=17'(next_random());stimulus[bit_index]=1'bx;check();
   stimulus[bit_index]=1'bz;check();
  end
 end
 for(integer pattern=0;pattern<32768;pattern++)begin
  for(integer bit_index=0;bit_index<17;bit_index++)begin
   case(next_random()%4)0:stimulus[bit_index]=0;1:stimulus[bit_index]=1;2:stimulus[bit_index]=1'bx;3:stimulus[bit_index]=1'bz;endcase
  end
  check();
 end
 $display("TAP_UPDATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    dependencies=resolve([model,ROOT/HELPER],ROOT);four=[]
    for mode,flags in MODES:
        exe=out/(mode+'.vvp');defines=[v for v in flags if v.startswith('-D')]
        execute(['iverilog','-g2012','-s','tb',*defines,'-o',exe,*dependencies,bench],out/(mode+'_compile.log'))
        log=out/(mode+'_four_state.log');execute(['vvp',exe],log)
        assert 'TAP_UPDATE_PASS checks=233472' in log.read_text()
        four.append({'mode':mode,'macro_options':flags,'passed':True,'comparisons':233472,'log_sha256':digest(log)})
    assert all(digest(p)==h for p,h in hashes.items())
    (out/'summary.json').write_text(json.dumps({'passed':True,'reference_commit':args.reference,'input_constraints':[],
      'all_parent_outputs_and_state_compared':True,'formal':proofs,'four_state':four,'source_sha256':hashes,
      'extracted_original_assignments':assignments,'runner_sha256':digest(__file__)},indent=2)+'\n')


if __name__=='__main__':main()
