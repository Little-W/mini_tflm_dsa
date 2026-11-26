#!/usr/bin/env python3
"""比较完整前端状态选择模块的公开输出，允许任意状态位及四态输入。"""
from pathlib import Path
import argparse, hashlib, json, re, runpy, shlex, subprocess, sys
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate',type=Path)
parser.add_argument('--source-root',type=Path,default=ROOT)
parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--reference',default='32379597')
parser.add_argument('--modes',nargs='+',choices=('generic','fpga'),default=['generic','fpga'])
args=parser.parse_args();root=args.source_root.resolve()
args.candidate=(args.candidate or root/'rtl/npu/conv/conv_im2col_state_control.sv').resolve()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
original=subprocess.check_output(['git','show',args.reference+':rtl/npu/conv/conv_im2col_state_control.sv'],cwd=ROOT,text=True)
models=[]
for label,text in [('reference',original),('current',args.candidate.read_text())]:
    text=text.replace('module conv_im2col_state_control','module '+label+'_state_control').replace('unique case','case')
    p=out/(label+'.sv');p.write_text(text);models.append(p)
resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
deps=resolve(models,root)
ports=original[original.index(') (')+3:original.index('\n);')]
inputs=[];outputs=[];proof_ports=[];declarations=[]
for line in ports.splitlines():
    clean=line.split('//')[0].strip().rstrip(',')
    m=re.match(r'(input|output)\s+(.*)\s+(i_\w+|o_\w+)$',clean)
    if not m:continue
    direction,kind,name=m.groups()
    if direction=='input':inputs.append((kind,name));proof_ports.append(clean)
    else:
        outputs.append((kind,name))
        for label in ['reference','current']:declarations.append(kind+' '+label+'_'+name+';')
connections=[]
for label in ['reference','current']:
    conn=[f'.{name}({name})' for _,name in inputs]+[f'.{name}({label}_{name})' for _,name in outputs]
    connections.append(f'{label}_state_control #(.p_count_width(p_count_width)) u_{label}('+','.join(conn)+');')
expected='{'+','.join('reference_'+n for _,n in outputs)+'}'
actual='{'+','.join('current_'+n for _,n in outputs)+'}'
proof=out/'proof.sv';proof.write_text('module proof #(parameter p_count_width=5)(\n'+',\n'.join(proof_ports)+',\n output wire correct);\n'+'\n'.join(declarations+connections)+f'\nassign correct=({expected}=={actual});\nendmodule\n')
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in deps+[args.candidate]}
formal=[];four=[]
def run(command,log):
    with log.open('w') as f:subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=300)
for width in [1,5,9]:
    for mode in args.modes:
        synthesis=mode=='fpga'
        key=f'w{width}_s{int(synthesis)}';defines=['-DSYNTHESIS=1','-DXILINX_FPGA=1'] if synthesis else []
        script=out/(key+'.ys');log=out/(key+'.log')
        script.write_text('read_slang --top proof -Gp_count_width='+str(width)+' '+shlex.join((defines if synthesis else ['-USYNTHESIS','-UXILINX_FPGA'])+[str(p) for p in deps+[proof]])+'\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nprep -top proof -flatten\nopt -full\nsat -verify -prove correct 1 -show-inputs -show-outputs\n')
        run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],log)
        formal.append(dict(count_width=width,synthesis=synthesis,slang_definitions=defines if synthesis else ['-USYNTHESIS','-UXILINX_FPGA'],passed=True,log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        print(key+' FORMAL_PASS',flush=True)
        lines=['module tb;',f'localparam p_count_width={width};']
        for kind,name in inputs:
            kind=kind.replace('wire ','').replace('conv_im2col_frontend_pkg::st_t','logic [26:0]')
            lines.append(kind+' '+name+';')
        lines+=declarations+connections
        lines+=['integer seed=32\'h35629713, sample;','initial begin','for(sample=0;sample<32768;sample=sample+1)begin']
        for _,name in inputs:lines.append(f'{name}=$random(seed);')
        lines+=['case(sample%8)','0:i_state=27\'d1 << ((sample/8)%27);','1:i_state=0;','2:i_state=27\'d1 << ((sample/8)%27) | 27\'d1 << ((sample/16)%27);','3:i_state[(sample/8)%27]=1\'bx;','4:i_state[(sample/8)%27]=1\'bz;','5:i_stream_state[(sample/8)%27]=1\'bx;','6:i_descriptor_state[(sample/8)%27]=1\'bz;','default:;','endcase']
        scalar=[n for k,n in inputs if k.strip()=='wire logic']
        lines+=['if(sample%3==0)begin','case((sample/3)%'+str(2*len(scalar))+')']
        for i,n in enumerate(scalar):
            lines += [f'{2*i}:{n}=1\'bx;',f'{2*i+1}:{n}=1\'bz;']
        lines+=['endcase','end','#1;',f'if({expected} !== {actual}) $fatal(1,"state=%h sample=%0d expected=%h actual=%h",i_state,sample,{expected},{actual});','end','$display("STATE_CONTROL_PASS checks=32768");$finish;end endmodule']
        tb=out/(key+'_tb.sv');tb.write_text('\n'.join(lines)+'\n');binary=out/(key+'.vvp')
        run(['iverilog','-g2012','-s','tb',*defines,'-o',str(binary),*[str(p) for p in deps],str(tb)],out/(key+'_compile.log'))
        sim=out/(key+'_four.log');run(['vvp',str(binary)],sim)
        assert 'STATE_CONTROL_PASS checks=32768' in sim.read_text();binary.unlink()
        four.append(dict(count_width=width,synthesis=synthesis,passed=True,checks=32768,log_sha256=hashlib.sha256(sim.read_bytes()).hexdigest()))
        print(key+' FOUR_STATE_PASS',flush=True)
assert hashes=={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes}
(out/'summary.json').write_text(json.dumps(dict(passed=True,reference=args.reference,source_sha256=hashes,input_assumptions=[],case_semantics='标准 case 顺序选择，任意状态位组合均参与比较。',formal=formal,four_state=four,test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),ensure_ascii=False,indent=2)+'\n')
