#!/usr/bin/env python3
"""证明缓存字输出状态与主状态同步保存及通道选择的等价关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def tokens(text):
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    return re.findall(r'\w+|[^\w\s]',text)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    paths=[root/'rtl/npu/conv/conv_im2col_frontend.sv' for root in(args.source_root,args.reference_root)]
    current,reference=[path.read_text()for path in paths]
    hashes=[hashlib.sha256(path.read_bytes()).hexdigest()for path in paths]
    function=re.search(r'  function automatic logic state_uses_word\(.*?  endfunction',current,re.S).group()
    enum=re.search(r'  typedef enum logic \[21:0\] \{.*?\} st_t;',current,re.S).group()
    values=[]

    for match in re.finditer(r'\{word_output_q, state\}\s*<=\s*\{state_uses_word\((.*?)\), (.*?)\};',current):
        class_value,state_value=match.group(1),match.group(2)
        if tokens(class_value)!=tokens(state_value):
            raise RuntimeError('State and output format differ')
        values.append(state_value)

    if re.search(r'\bstate\s*<=',current) or re.search(r'\bword_output_q\s*<=',current):
        raise RuntimeError('Unpaired state assignment')
    if len(values)!=len(re.findall(r'\{word_output_q,\s*state\}\s*<=',current)) or not values:
        raise RuntimeError('State assignment coverage')
    reference_values=re.findall(r'\bstate\s*<=\s*([^;]+);',reference)
    if [tokens(value) for value in values]!=[tokens(value) for value in reference_values]:
        raise RuntimeError('State assignment value comparison')
    if current.count('(!word_output_q || word_lane_allowed[lane])')!=1:
        raise RuntimeError('Output range expression')
    sv=args.out/'word_state.sv'
    sv.write_text('''module proof(input logic clk,rst_n,update,
 input logic[21:0]next_state,input logic word_lane_allowed,output logic equivalent);
'''+enum+'\n'+function+'''
 st_t state;
 logic word_output_q;
 wire old_range=(!state[$clog2(STREAM)]&&!state[$clog2(WAIT_WORD)])||word_lane_allowed;
 wire current_range=!word_output_q||word_lane_allowed;
 always_ff @(posedge clk) begin
  if(!rst_n){word_output_q,state}<={state_uses_word(IDLE),IDLE};
  else if(update){word_output_q,state}<={state_uses_word(st_t'(next_state)),next_state};
 end
 assign equivalent=(word_output_q==state_uses_word(state))&&(old_range==current_range);
endmodule
''')
    ys=args.out/'proof.ys';log=args.out/'proof.log'
    ys.write_text('read_slang --top proof '+shlex.quote(str(sv))+'\nprep -top proof -flatten\ncheck -assert\n'
                  'sat -seq 2 -set-at 1 rst_n 0 -set-def-inputs -set-init-def -prove-skip 1 -prove equivalent 1 -verify\n'
                  'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -set-def-inputs -set-init-def -prove equivalent 1 -verify\n')
    with log.open('w')as stream:
        result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                              stdout=stream,stderr=subprocess.STDOUT,timeout=90)
    if result.returncode or 'Induction step proven: SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
    tb=args.out/'four_state.sv'
    tb.write_text('''module tb;
 logic clk=0,rst_n=0,update=0,word_lane_allowed=0;
 logic[21:0]next_state='0;wire equivalent;
 proof dut(.*);
 integer checks=0;integer random_state=32'h3519ac47;integer selector;
 function automatic logic symbol(input integer selection);
  case(selection&3)0:symbol=0;1:symbol=1;2:symbol=1'bx;default:symbol=1'bz;endcase
 endfunction
 task automatic cycle;
  #1;clk=1;#1;
  if(dut.word_output_q!==dut.state_uses_word(dut.state)||dut.old_range!==dut.current_range)$fatal(1,"word state");
  checks++;clk=0;#1;
 endtask
 initial begin
  cycle();rst_n=1;
  for(integer sample=0;sample<20000;sample++)begin
   for(integer bit_index=0;bit_index<22;bit_index++)next_state[bit_index]=symbol($random(random_state));
   update=symbol($random(random_state));word_lane_allowed=symbol($random(random_state));cycle();
  end
  $display("WORD_STATE_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
    # 四态仿真采用等宽向量承接主状态，保留同一状态位表达式。
    sim=args.out/'word_state_sim.sv'
    simulation=sv.read_text().replace('input st_t next_state','input logic [21:0] next_state').replace(' st_t state;',' logic [21:0] state;').replace("st_t'(next_state)",'next_state')
    sim.write_text(simulation)
    binary=args.out/'four_state.vvp';simlog=args.out/'four_state.log'
    subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(sim),str(tb)],check=True,capture_output=True,text=True)
    result=subprocess.run(['vvp',str(binary)],check=True,capture_output=True,text=True,timeout=30);simlog.write_text(result.stdout)
    if 'checks=20001'not in result.stdout:raise RuntimeError('Four-state checks')
    if hashes!=[hashlib.sha256(path.read_bytes()).hexdigest()for path in paths]:raise RuntimeError('Source changed')
    report={'passed':True,'source_sha256':hashes[0],'reference_sha256':hashes[1],
            'paired_state_assignments':len(values),'state_assignment_values_equal':True,
            'proof_scope':'Paired state writes and output word-range selection',
            'reset_steps':2,'unbounded_induction_steps':1,'next_state_input_constraints':[],
            'four_state_cycles':20001,'formal_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
            'four_state_log_sha256':hashlib.sha256(simlog.read_bytes()).hexdigest()}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print('WORD_STATE_PASS',report)


if __name__=='__main__':main()
