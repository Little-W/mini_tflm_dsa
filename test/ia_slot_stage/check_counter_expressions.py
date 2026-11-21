#!/usr/bin/env python3
"""检查 IA 计数运算独立结果的完整二态输入和四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PROFILES=((8,1),(8,8),(8,16),(16,8),(16,16),(16,32),(32,1),(32,8),(32,29),(32,32),(32,40),(64,32),(64,64))
REG_INPUTS=('l2_group_num','w_groups_total','horizontal_tile_num','cfg_ia_reuse_num','load_cursor_p0')
COUNT_INPUTS=('l1_idx','l1_idx_next','l2_tile_row_base')
OUTPUTS=('l2_group_last_idx','w_group_last_idx','last_col_tile_idx','l1_idx','l1_idx_next','l2_tile_row_base','load_cursor_p0')
ALIASES=('l2_group_last_value','w_group_last_value','last_column_value','l1_index_advance','l1_next_index_advance','l2_tile_row_advance','load_cursor_p0_advance')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    paths=[r/'rtl/npu/loaders/ia_loader_ctrl.sv'for r in(args.source_root,args.reference_root)]
    current,reference=[p.read_text()for p in paths]
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest()for p in paths]
    declarations='\n'.join(re.findall(r'  \(\* use_dsp = "yes" \*\) (?:count_t|logic \[REG_WIDTH-1:0\])[^;]+;',current))
    declarations='\n'.join(line for line in declarations.splitlines()if any(name in line for name in ALIASES))
    assignments='\n'.join(re.search(r'  assign '+name+r'\s*=.*?;',current,re.S).group()for name in ALIASES)
    compare=[]
    for index,(target,alias)in enumerate(zip(OUTPUTS,ALIASES)):
        cand=[x for x in re.findall(r'\b'+target+r'\s*<=([^;]+);',current)if alias in x]
        ref=[x for x in re.findall(r'\b'+target+r'\s*<=([^;]+);',reference)if ('+'in x or '-'in x)and "'0"!=x.strip()]
        if len(cand)!=1 or len(ref)!=1:raise RuntimeError(('Counter expression count',target,cand,ref))
        width='REG_WIDTH'if target=='load_cursor_p0'else'CNT_W'
        compare.extend([f'logic[{width}-1:0]current_{index},reference_{index};',
            f'assign current_{index}={cand[0]};',f'assign reference_{index}={ref[0]};',
            f'assign equal_bits[{index}]=current_{index}===reference_{index};'])
    ports=','.join(['input logic[REG_WIDTH-1:0]'+','.join(REG_INPUTS),'input logic[CNT_W-1:0]'+','.join(COUNT_INPUTS),'output logic equivalent'])
    module='module arithmetic #(parameter REG_WIDTH=32,CNT_W=29,SIZE=16)('+ports+');\ntypedef logic[CNT_W-1:0]count_t;\nlogic[6:0]equal_bits;\n'+declarations+'\n'+assignments+'\n'+'\n'.join(compare)+'\nassign equivalent=&equal_bits;\nendmodule\n'
    sv=args.out/'arithmetic.sv';sv.write_text(module)
    proofs=[]
    for rw,cw in PROFILES:
        name=f'r{rw}_c{cw}';wrapper=args.out/(name+'.sv');ports=','.join(['input logic['+str(rw-1)+':0]'+','.join(REG_INPUTS),'input logic['+str(cw-1)+':0]'+','.join(COUNT_INPUTS),'output logic equivalent'])
        wrapper.write_text('module proof('+ports+f');\narithmetic #(.REG_WIDTH({rw}),.CNT_W({cw}))dut(.*);\nendmodule\n')
        ys,log=args.out/(name+'.ys'),args.out/(name+'.log');ys.write_text('read_slang --top proof -DSYNTHESIS=1 '+shlex.join(map(str,(sv,wrapper)))+'\nprep -top proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w')as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=stream,stderr=subprocess.STDOUT,timeout=90)
        if result.returncode or'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
        proofs.append({'register_width':rw,'count_width':cw,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    tb=args.out/'four_state.sv';lines=['module tb;','logic[63:0]'+','.join(REG_INPUTS+COUNT_INPUTS)+';',f'wire[{len(PROFILES)-1}:0]equal_results;','integer checks=0;']
    for i,(rw,cw)in enumerate(PROFILES):
        ports=[f'.{name}({name}[{rw-1}:0])'for name in REG_INPUTS]+[f'.{name}({name}[{cw-1}:0])'for name in COUNT_INPUTS]+[f'.equivalent(equal_results[{i}])']
        lines.append(f'arithmetic #(.REG_WIDTH({rw}),.CNT_W({cw}))dut_{i}('+','.join(ports)+');')
    lines.append('initial begin\nfor(integer sample=0;sample<20000;sample++)begin')
    for i,name in enumerate(REG_INPUTS+COUNT_INPUTS):
        lines.extend([name+'={$random,$random};',f"if(sample%3==0){name}[(sample+{i})%64]=1'bx;",f"if(sample%5==0){name}[(sample*7+{i})%64]=1'bz;"])
    lines.append(f'''#1;if(equal_results!=={{{len(PROFILES)}{{1'b1}}}})$fatal(1,"counter expression propagation");
checks+={len(PROFILES)};
end
$display("IA_COUNTER_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule''');tb.write_text('\n'.join(lines)+'\n')
    binary=args.out/'four_state.vvp';subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb','-o',str(binary),str(sv),str(tb)],capture_output=True,check=True)
    run=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],capture_output=True,text=True,check=True,timeout=60);log=args.out/'four_state.log';log.write_text(run.stdout+run.stderr)
    if f'checks={20000*len(PROFILES)}'not in run.stdout:raise RuntimeError('Four-state coverage')
    if hashes!=[hashlib.sha256(p.read_bytes()).hexdigest()for p in paths]:raise RuntimeError('Source changed')
    report={'passed':True,'source_sha256':hashes[0],'reference_sha256':hashes[1],'binary_input_constraints':[],
        'proofs':proofs,'compared_counter_results':7,'four_state_comparisons':20000*len(PROFILES),'four_state_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
