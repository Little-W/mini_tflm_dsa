#!/usr/bin/env python3
"""验证矩阵控制器全部状态及输入发送资格的四态行为。"""
import argparse,hashlib,json,re,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/control/npu_controller.sv'
HELPER='rtl/npu/control/npu_ia_issue_select.sv'
FIELDS=[('bias_base',32),('compute_tail_count',2),('current_state',4)]+[(n,1)for n in ['bias_sleep','bias_valid','partial_sum_calc_over','partial_sum_advance_ready','oa_calc_over','ia_data_valid','ps_frame_ready','quant_params_valid','fifo_full_flag','ia_sending_done','shadow_ready','weight_resident','resident_used']]
WIDTH=sum(w for _,w in FIELDS)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def assignment(source,name):
 result=re.search(r'\bassign\s+'+name+r'\s*=.*?;',source,re.S)
 if result:return result[0]
 result=re.search(r'\bwire\s+'+name+r'\s*=.*?;',source,re.S);assert result
 return re.sub(r'\bwire\s+','assign ',result[0],count=1)
def model(source,label):
 names=['bias_ready_for_compute','compute_tail_pending','compute_tail_done','input_tail_ready','issue_ia_now','reuse_stationary_now','commit_now']
 if label=='reference':names+=['send_ia_trigger']
 else:
  names+=['issue_data_ready','issue_aux_ready','issue_state_ready','issue_tail_quant_ready']
  if re.search(r'\bassign\s+issue_operand_ready\b',source):names+=['issue_operand_ready']
  if re.search(r'\bassign\s+issue_bias_optional\b',source):names+=['issue_bias_optional']
 text=f'module {label}_control(input wire [{WIDTH-1}:0] values,output wire [1:0] result);\n'
 text+="localparam IA_START=4'b0011,WEIGHT_START=4'b0010;\n"
 offset=0
 for name,width in FIELDS:text+=f'wire [{width-1}:0] {name}=values[{offset}+:{width}];\n';offset+=width
 text+='wire '+','.join(names+([]if label=='reference'else['send_ia_trigger']))+';\n'
 text+='\n'.join(assignment(source,n)for n in names)+'\n'
 if label=='current':text+=re.search(r'    npu_ia_issue_select\s+\w+\s*\(.*?\n    \);',source,re.S)[0]+'\n'
 return text+'assign result={issue_ia_now,send_ia_trigger};\nendmodule\n'
def run(command,log):
 with log.open('w')as f:subprocess.run(list(map(str,command)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=360)
 return log.read_text()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',default='d7cb67be');p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 actual=ROOT/SOURCE;helper=ROOT/HELPER;source=actual.read_text();ref=subprocess.check_output(['git','show',a.reference+':'+SOURCE],cwd=ROOT,text=True)
 reference=out/'reference.sv';reference.write_text(ref);hashes={str(p):digest(p)for p in [actual,helper]};records=[]
 for mode in ['generic','fpga']:
  flags=['-USYNTHESIS','-UXILINX_FPGA']if mode=='generic'else['-DSYNTHESIS=1','-DXILINX_FPGA=1']
  for width in [8,16,28,29,32,64]:
   commands=[]
   for label,path in [('reference',reference),('current',actual)]:
    commands+=['read_slang --top npu_controller '+shlex.join(flags+[f'-GREG_WIDTH={width}','-GSIZE=16','-GBUS_WIDTH=64','-GDATA_WIDTH=8','-GWEIGHT_WIDTH=8',str(path),str(helper)]),'prep -top npu_controller -flatten','async2sync','opt_clean',f'rename npu_controller {label}',f'design -stash {label}']
   commands+=['design -copy-from reference -as reference reference','design -copy-from current -as current current','equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1','equiv_induct -seq 2','equiv_status -assert']
   script,log=out/f'{mode}_{width}.ys',out/f'{mode}_{width}.log';script.write_text('\n'.join(commands)+'\n')
   text=run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log);assert 'Equivalence successfully proven!'in text
   count=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text);assert count and int(count[2])==0
   records.append(dict(mode=mode,reg_width=width,passed=True,equivalent_bits=int(count[1]),log_sha256=digest(log)))
  print('CONTROLLER_COMPLETE_PASS',mode,flush=True)
 control=out/'control.sv';control.write_text(model(ref,'reference')+model(source,'current')+f'module proof(input wire [{WIDTH-1}:0] values,output wire equivalent);wire [1:0] a,b;reference_control u_a(values,a);current_control u_b(values,b);assign equivalent=a==b;endmodule\n')
 tb=out/'tb.sv';tb.write_text(f'''// 全部接收控制相同输入下的四态比较。
module tb;
reg [{WIDTH-1}:0] values,known;
wire [1:0] a,b;integer rng=32'h1e4138a7,checks=0,choice;
reference_control u_a(values,a);current_control u_b(values,b);
function automatic [31:0] random_word;
 rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
task check;
 begin #1;checks++;if(a!==b)$fatal(1,"Controller issue differs values=%h expected=%h actual=%h",values,a,b);end
endtask
initial begin
 for(integer sample=0;sample<131072;sample++)begin
  for(integer bit_index=0;bit_index<{WIDTH};bit_index++)begin
   choice=sample<65536 ? (random_word()%2) : (random_word()%4);
   case(choice)0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;endcase
  end
  check();
 end
 for(integer sample=0;sample<256;sample++)begin
  for(integer bit_index=0;bit_index<{WIDTH};bit_index++)known[bit_index]=1'(random_word());
  for(integer bit_index=0;bit_index<{WIDTH};bit_index++)begin values=known;values[bit_index]=1'bx;check();values[bit_index]=1'bz;check();end
 end
 values='x;check();values='z;check();
 $display("CONTROLLER_ISSUE_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
 four=[]
 for mode in ['generic','fpga']:
  flags=[]if mode=='generic'else['-DSYNTHESIS=1','-DXILINX_FPGA=1'];script,log=out/(mode+'_control.ys'),out/(mode+'_control.log')
  script.write_text('read_slang --top proof '+shlex.join((flags if flags else['-USYNTHESIS','-UXILINX_FPGA'])+[str(control),str(helper)])+'\nprep -top proof -flatten\nsat -verify -prove equivalent 1\n')
  text=run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log);assert 'SUCCESS!'in text
  binary=out/(mode+'.vvp');run(['iverilog','-g2012','-s','tb',*flags,'-o',binary,control,helper,tb],out/(mode+'_compile.log'))
  log=out/(mode+'_four_state.log');text=run(['vvp',binary],log);count=re.search(r'CONTROLLER_ISSUE_FOUR_STATE_PASS checks=(\d+)',text);assert count
  four.append(dict(mode=mode,passed=True,checks=int(count[1]),log_sha256=digest(log)));print(text,flush=True)
 assert hashes=={str(p):digest(p)for p in [actual,helper]}
 (out/'summary.json').write_text(json.dumps(dict(passed=True,reference=a.reference,source_sha256=hashes,external_input_assumptions=[],parent_proofs=records,control_proofs=four,test_sha256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
