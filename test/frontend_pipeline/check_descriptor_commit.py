#!/usr/bin/env python3
"""比较描述符提交模块的全部输出、四态传播和坐标组合级数。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys
import four_state_coverage as coverage

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'rtl/npu/conv/conv_descriptor_commit.sv'
REFERENCE=HERE/'descriptor_commit_reference.sv'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(script,log):
    with log.open('w')as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=240)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    text=SOURCE.read_text();ports=[]
    for line in text.splitlines():
        m=re.match(r'\s*(input|output)\s+(?:wire )?(.+?)\s+([io]_\w+),?\s*//',line)
        if m:ports.append(m.groups())
    parameter_text=text[text.index('#(')+2:text.index(') (')]
    parameters=re.findall(r'^\s*parameter (?:int|bit) (\w+)',parameter_text,re.M)
    connections=','.join('.'+n+'('+n+')'for d,t,n in ports if d=='input')
    declarations='\n'.join(t+' '+prefix+n+';'for prefix in ('actual_','reference_')for d,t,n in ports if d=='output')
    instance_params=','.join('.'+n+'('+n+')'for n in parameters)
    model=out/'comparison.sv'
    model.write_text('module commit_comparison #('+parameter_text+') (\n'+
        ',\n'.join('input wire '+t+' '+n for d,t,n in ports if d=='input')+',\noutput logic o_equivalent\n);\n'+
        declarations+'\n'+'\n'.join(module+' #('+instance_params+') u_'+prefix+'('+connections+','+
        ','.join('.'+n+'('+prefix+n+')'for d,t,n in ports if d=='output')+');'
        for module,prefix in [('conv_descriptor_commit','actual_'),('conv_descriptor_commit_reference','reference_')])+\
        '\nassign o_equivalent='+' && '.join('actual_'+n+' === reference_'+n for d,t,n in ports if d=='output')+';\nendmodule\n')
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources=resolver['with_dependencies']([SOURCE,REFERENCE,model],ROOT)
    hashes={str(p.relative_to(ROOT)):digest(p)for p in resolver['input_files'](sources,ROOT)if p.is_relative_to(ROOT)}
    proofs=[]
    for width in (33,35,40):
        for registered in (0,1):
            name=f'coord{width}_register{registered}';script,log=out/(name+'.ys'),out/(name+'.log')
            script.write_text(shlex.join(['read_slang','--top','commit_comparison','-DSYNTHESIS=1',
                '-I'+str(ROOT/'include'),f'-Gp_coord_w={width}',f'-Gp_register_descriptor={registered}',
                '-Gp_lanes=8','-Gp_slot_w=6','-Gp_line_bytes=128',*map(str,sources)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'+
                'prep -top commit_comparison -flatten\nsat -verify -prove o_equivalent 1\n')
            execute(script,log)
            if 'SUCCESS!'not in log.read_text():raise RuntimeError('完整描述符提交形式证明未完成')
            proofs.append(dict(coordinate_width=width,register_descriptor=registered,passed=True,log_sha256=digest(log)))
            print('DESCRIPTOR_COMMIT_FORMAL_PASS '+name,flush=True)
    # Icarus 使用同宽度直接赋值表示 packed struct 类型转换。
    simulation=[]
    for source in sources:
        target=out/('simulation_'+source.name)
        content=source.read_text()
        content=re.sub(r"prepared_tile_t'\((\w+)\)",r'\1',content)
        target.write_text(content);simulation.append(target)
    bench=out/'four_state.sv';constants=[]
    for line in parameter_text.splitlines():
        m=re.match(r'\s*(?:localparam|parameter) (int|bit) (\w+)\s*=\s*(.+)',line)
        if m:
            typ,name,value=m.groups();value=value.rstrip(',')
            value={'p_lanes':'8','p_slot_w':'6','p_line_bytes':'128'}.get(name,value)
            constants.append('localparam '+typ+' '+name+'='+value+';')
    names=','.join(n for d,t,n in ports if d=='input')
    widths=coverage.expanded_widths(out,'\n'.join(constants),
        '\n'.join(t+' '+n+';' for d,t,n in ports if d=='input'),
        [n for d,t,n in ports if d=='input'],[ROOT/'rtl/npu/conv/conv_im2col_pkg.sv'])
    input_width=sum(widths.values())
    bench.write_text('module commit_four_state;\n'+'\n'.join(constants)+'\n'+
        '\n'.join(t+' '+n+';'for d,t,n in ports if d=='input')+'\nlogic equivalent;\n'+
        'localparam int p_inputs='+str(input_width)+';\nlogic[p_inputs-1:0]stimulus;\nassign{'+names+'}=stimulus;\n'+
        'commit_comparison #('+instance_params+') u_compare('+connections+',.o_equivalent(equivalent));\n'+'''
integer random_state=32'h73716743;
function automatic integer random_word;
 random_state=random_state^(random_state<<13);random_state=random_state^(random_state>>17);
 random_state=random_state^(random_state<<5);return random_state;
endfunction
initial begin
 for(integer sample=0;sample<8192;sample++)begin
  for(integer index=0;index<p_inputs;index++)stimulus[index]=1'(random_word());
  case(sample%16)
   0:stimulus='0;1:stimulus='1;2:stimulus='x;3:stimulus='z;
   4,5,6,7:stimulus[sample%p_inputs]=1'bx;
   8,9,10,11:stimulus[sample%p_inputs]=1'bz;
   default:begin end
  endcase
  #1;if(equivalent!==1'b1)$fatal(1,"descriptor commit mismatch sample=%0d",sample);
 end
 $display("DESCRIPTOR_COMMIT_FOUR_STATE_PASS samples=8192");$finish;
end
endmodule
''')
    tb=bench.read_text()
    tb=tb.replace('initial begin',coverage.declarations('p_inputs')+'initial begin'+coverage.initialize('p_inputs',names),1)
    tb=tb.replace('  #1;if(equivalent',coverage.sample('p_inputs')+'  #1;if(equivalent',1)
    tb=tb.replace(' $display("DESCRIPTOR_COMMIT_FOUR_STATE_PASS',coverage.finish('p_inputs')+' $display("DESCRIPTOR_COMMIT_FOUR_STATE_PASS',1)
    bench.write_text(tb)
    binary,log=out/'four_state.vvp',out/'four_state.log'
    with log.open('w')as stream:
        subprocess.run(['iverilog','-g2012','-DSYNTHESIS=1','-I'+str(ROOT/'include'),'-s','commit_four_state',
                        '-o',str(binary),*map(str,simulation),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        subprocess.run(['vvp',str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
    if 'DESCRIPTOR_COMMIT_FOUR_STATE_PASS'not in log.read_text():raise RuntimeError('完整描述符提交四态比较未完成')
    if any(digest(ROOT/name)!=value for name,value in hashes.items()):raise RuntimeError('验证过程中提交模块源码发生变化')
    report=dict(passed=True,formal=proofs,four_state_samples=8192,four_state_coverage=coverage.result(log,widths),four_state_log_sha256=digest(log),source_sha256=hashes)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('DESCRIPTOR_COMMIT_PASS formal=6 four_state=8192',flush=True)


if __name__=='__main__':main()
