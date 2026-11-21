#!/usr/bin/env python3
"""验证通道数量和范围数据选择，保持现有寄存器使能与更新周期。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('event_domains', ROOT/'test/conv_frontend/tools/check_frontend_event_domains.py')
DOMAINS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOMAINS)


def assignment(text, name):
    return re.search(r'\s*assign '+re.escape(name)+r'\s*=.*?;', text, re.S).group().strip()


def tokens(text):
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    return re.findall(r'\w+|[^\w\s]', text)


def data_ports(width):
    return f'''input logic clk,
 input logic[2:0][{width-1}:0]active_update_candidate,column_update_candidate,
 input logic[2:0]candidate_allowed,column_allowed,'''


def model(text, name, width):
    generated = DOMAINS.module(text, name)
    generated = generated.replace(' output logic[20:0]result,output logic invariant);',
        data_ports(width)+f'output logic[{2*width+1}:0]value,\n output logic[20:0]result,output logic invariant);')
    extra = f'''localparam int TILE_COUNT_W={width};
 logic[{width-1}:0]active_update_value,column_update_value;
 logic[0:0]active_lane_update,column_lane_update;
 logic active_select_commit;
 logic[2:0]active_data_select;
'''
    if 'assign active_select_commit' in text:
        extra += assignment(text, 'active_select_commit')+'\n'
        for index in range(3):
            extra += assignment(text, f'active_data_select[{index}]')+'\n'
    for name in ('active_update_value','column_update_value','active_lane_update[lane]','column_lane_update[lane]'):
        extra += assignment(text, name).replace('[lane]','[0]')+'\n'
    extra += '''always_ff @(posedge clk) begin
 if(!rst_n)value<='0;
 else if(|active_update_select)
  value<={active_update_value,column_update_value,active_lane_update[0],column_lane_update[0]};
end
'''
    return generated.replace('endmodule',extra+'endmodule')


def wrapper(width, registered):
    return f'''module proof({DOMAINS.PORTS}{data_ports(width)}output logic equivalent);
 logic[20:0]current_result,reference_result;
 logic current_invariant,reference_invariant;
 logic[{2*width+1}:0]current_value,reference_value;
 current #(.REGISTER_DESCRIPTOR({registered}))u_current(.*,.result(current_result),.invariant(current_invariant),.value(current_value));
 reference #(.REGISTER_DESCRIPTOR({registered}))u_reference(.*,.result(reference_result),.invariant(reference_invariant),.value(reference_value));
 assign equivalent=(current_value===reference_value)&&(current_result===reference_result)&&current_invariant&&reference_invariant;
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    paths=[r/'rtl/npu/conv/conv_im2col_frontend.sv' for r in (args.source_root,args.reference_root)]
    current,reference=[p.read_text() for p in paths]
    hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    normalized=current.replace('  logic active_select_commit;','').replace('  logic [2:0] active_data_select;','').replace(assignment(current,'active_select_commit'),'')
    for index in range(3):
        normalized=normalized.replace(assignment(current,f'active_data_select[{index}]'),'')
    for name in ('active_update_value','column_update_value','active_lane_update[lane]','column_lane_update[lane]'):
        normalized=normalized.replace(assignment(normalized,name),assignment(reference,name))
    def counter_block(text):
        first=text.index('  assign active_update_select[0]')
        following=text.index('  // 保存前端配置、描述符和坐标状态。',first)
        if '  // 解码递增与配置边界的完整结果' in text[first:following]:
            following=text.index('  // 解码递增与配置边界的完整结果',first)
        return text[first:following]
    if tokens(counter_block(normalized))!=tokens(counter_block(reference)):
        raise RuntimeError('Counter update statements differ')
    rows=[]
    for width in (3,4,5,6,9,17):
        for registered in (0,1):
            name=f'w{width}_r{registered}'
            sv,ys,log=[args.out/(name+suffix) for suffix in ('.sv','.ys','.log')]
            sv.write_text(model(current,'current',width)+model(reference,'reference',width)+wrapper(width,registered))
            ys.write_text('read_slang --top proof '+shlex.quote(str(sv))+
                '\nprep -top proof -flatten\ncheck -assert\n'
                'sat -seq 2 -set-at 1 rst_n 0 -set-def-inputs -set-init-def -prove-skip 1 -prove equivalent 1 -verify\n'
                'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -set-def-inputs -set-init-def -prove equivalent 1 -verify\n')
            with log.open('w')as stream:
                run=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                    stdout=stream,stderr=subprocess.STDOUT,timeout=120)
            if run.returncode or 'Induction step proven: SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
            rows.append({'count_width':width,'register_descriptor':registered,'passed':True,
                'reset_steps':2,'unbounded_induction_steps':1,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})

    declarations=[];names=[];total=0
    for field in DOMAINS.PORTS.split('input logic')[1:]:
        field=field.strip().rstrip(',').strip()
        matched=re.match(r'\[(\d+):(\d+)\]',field)
        width=1
        if matched:
            width=int(matched[1])-int(matched[2])+1;field=field[matched.end():]
        for name in field.strip().split(','):
            name=name.strip()
            if name=='rst_n':continue
            if not re.fullmatch(r'\w+',name):raise RuntimeError(('Port parsing',name))
            declarations.append(f'logic[{width-1}:0]{name};');names.append(name);total+=width
    declarations+=['logic[2:0][4:0]active_update_candidate,column_update_candidate;',
        'logic[2:0]candidate_allowed,column_allowed;']
    names+=['active_update_candidate','column_update_candidate','candidate_allowed','column_allowed'];total+=36
    simulations=[]
    for registered in (0,1):
        source=args.out/f'four_state_r{registered}.sv'
        body=(args.out/f'w5_r{registered}.sv').read_text().replace(' st_t state;',' logic[21:0]state;').replace("st_t'(22'b1<<state_index)","(22'b1<<state_index)")
        source.write_text(body+'''module tb;
 logic clk=0,rst_n=0;wire equivalent;
'''+ '\n'.join(declarations)+f'''
 proof dut(.*);
 logic[{total-1}:0]pattern;
 integer checks=0;
 task automatic cycle;
  #1;clk=1;#1;
  if(dut.current_value!==dut.reference_value)$fatal(1,"active data comparison");
  checks++;clk=0;#1;
 endtask
 initial begin
  pattern='0;{{{','.join(names)}}}=pattern;cycle();rst_n=1;
  for(integer sample=0;sample<20000;sample++)begin
   for(integer bit_index=0;bit_index<{total};bit_index++)pattern[bit_index]=$urandom_range(0,1);
   if(sample%3==0)pattern[sample%{total}]=1'bx;
   if(sample%5==0)pattern[(sample*7)%{total}]=1'bz;
   {{{','.join(names)}}}=pattern;cycle();
  end
  $display("ACTIVE_DATA_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
        binary=args.out/f'four_state_r{registered}.vvp'
        subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb','-o',str(binary),str(source)],capture_output=True,check=True)
        run=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],capture_output=True,text=True,check=True,timeout=60)
        log=args.out/f'four_state_r{registered}.log';log.write_text(run.stdout+run.stderr)
        if 'checks=20001'not in run.stdout:raise RuntimeError('Four-state coverage')
        simulations.append({'register_descriptor':registered,'cycles':20001,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    if hashes!=[hashlib.sha256(p.read_bytes()).hexdigest()for p in paths]:raise RuntimeError('Source changed')
    report={'passed':True,'source_sha256':hashes[0],'reference_sha256':hashes[1],
        'counter_update_statements_equal':True,'event_state_encoding':'One-hot or zero from unrestricted five-bit index',
        'data_input_constraints':[],'proofs':rows,'four_state':simulations,'four_state_cycles':40002}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
