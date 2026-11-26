#!/usr/bin/env python3
"""对两个完整帧存储施加相同四态输入，并逐周期比较全部公开输出。"""
import argparse,hashlib,json,re,runpy,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test/ia_timing'))
from run_interface import port_declarations
SOURCE='rtl/npu/ps_compact/ps_frame_store.sv'
CASES=runpy.run_path(str(ROOT/'test/ps_frame_ready/run_full.py'))['CASES']

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def model(source,label):
 ports=port_declarations(source)
 header=source[:source.index(') (')+3]
 declarations=',\n'.join(f'    {direction} {kind} {name} {unpacked}'for direction,kind,name,unpacked in ports)
 source=header+'\n'+declarations+'\n);'+source[source.index('\n);')+3:]
 return source.replace('module ps_frame_store #(',f'module store_{label} #(',1).replace('always_comb','always @*')

def bench(source,cycles):
 ports=port_declarations(source);head=source[source.index('module ps_frame_store #('):source.index(') (')].replace('module ps_frame_store','module comparison',1)
 params=re.findall(r'parameter (?:integer|bit) (\w+)',head)
 s=head+''') (input wire clk,rst_n,input integer sample);
integer rng=32'h6178a459,accepted=0,written=0,phase,frames=0,writes=0,checks=0,unknown_cycles=0;
function automatic [31:0] random_word;
 rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
function automatic logic four(input logic [1:0] choice);
 case(choice)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
endfunction
'''
 for direction,kind,name,unpacked in ports:
  if direction=='input' and name not in ['clk','rst_n']:
   s+=re.sub(r'\b(?:wire|reg)\b','logic',kind)+' '+name+' '+unpacked+';\n'
 for label in ['reference','current']:
  for direction,kind,name,unpacked in ports:
   if direction=='output':s+=kind+' '+label+'_'+name+' '+unpacked+';\n'
  s+=f'store_{label} #('+','.join(f'.{p}({p})'for p in params)+f') u_{label}('+','.join(f'.{name}({label+"_" if direction=="output" else ""}{name})'for direction,kind,name,unpacked in ports)+');\n'
 s+='''initial begin
 cfg_valid=0;frame_request=0;frame_accept=0;write_valid=0;write_frame_end=0;replay_trigger=0;
 cfg_pool_bank_words=EXTERNAL_RAM?BANK_BYTES/16:POOL_BYTES/64;
 cfg_pool_bank_count=EXTERNAL_RAM?POOL_BYTES/BANK_BYTES:4;cfg_directory_stride=MAX_FRAME_ROWS;
 frame_id=0;frame_rows=1;frame_reserve_rows=1;frame_word_cap=4;frame_init=1;frame_final=0;force_raw_i=1;write_data=0;
 for(integer p=0;p<4;p++)ram_read_data[p]=0;
end
always @(negedge clk)begin
 phase=sample%128;
 if(phase==1)begin accepted=0;written=0;end
 cfg_valid=(sample%1024==2);
 frame_id=((sample/256)%FRAME_COUNT);
 frame_rows=1+((sample/128)%4);frame_reserve_rows=frame_rows;
 frame_init=((sample/128)%2==0);frame_final=!frame_init;
 frame_request=phase>=4 && phase<96 && !accepted;
 frame_accept=0;write_valid=accepted && written<frame_rows && phase%2==0;
 write_frame_end=write_valid && written+1==frame_rows;replay_trigger=0;
 for(integer i=0;i<16;i++)write_data[32*i+:32]=random_word();
 for(integer p=0;p<4;p++)ram_read_data[p]={random_word(),random_word(),random_word(),random_word()};
 if(phase>100 && phase<121)begin
  frame_request=four(2'(random_word()));write_valid=four(2'(random_word()));
  write_frame_end=four(2'(random_word()));replay_trigger=four(2'(random_word()));
  if(phase%3==0)frame_init=four(2'(random_word()));
  if(phase%5==0)frame_rows[sample%32]=four(2'(random_word()));
  if(phase%7==0)cfg_valid=four(2'(random_word()));
  unknown_cycles++;
 end
 #1;
 if(phase>=4 && phase<96)begin
  frame_accept=(reference_frame_ready===1'b1) && frame_request;
  replay_trigger=frame_accept && !frame_init;
 end else if(phase>100 && phase<121)frame_accept=four(2'(random_word()));
end
always @(posedge clk)begin
 if(!rst_n)begin accepted=0;written=0;end
 else begin
  if(frame_accept===1'b1)begin accepted=1;frames++;end
  if(write_valid===1'b1)begin written++;writes++;end
 end
 #1;
'''
 for direction,kind,name,unpacked in ports:
  if direction!='output':continue
  if unpacked:s+=f' for(integer p=0;p<4;p++)if(reference_{name}[p]!==current_{name}[p])$fatal(1,"PS public array differs {name} sample=%0d",sample);\n'
  else:s+=f' if(reference_{name}!==current_{name})$fatal(1,"PS public output differs {name} sample=%0d",sample);\n'
 s+=''' checks++;
end
final begin
 if(frames==0 || writes==0 || unknown_cycles==0)$fatal(1,"PS input coverage incomplete");
 $display("PS_REQUEST_FOUR_STATE_PROFILE_PASS max_rows=%0d external=%0d frames=%0d writes=%0d unknown=%0d checks=%0d",MAX_FRAME_ROWS,EXTERNAL_RAM,frames,writes,unknown_cycles,checks);
end
endmodule
module tb;
reg clk=1,rst_n=0;integer sample;
'''
 for i,(name,(_,_,params))in enumerate(CASES.items()):
  s+='comparison #('+','.join(f'.{p}({v})'for p,v in params.items())+f') u{i}(clk,rst_n,sample);\n'
 s+=f'''initial begin
 for(sample=0;sample<{cycles};sample++)begin
  rst_n=(sample%1024)>1;#5;clk=0;#5;clk=1;#2;
 end
 $display("PS_REQUEST_FOUR_STATE_ALL_PASS");$finish;
end
endmodule
'''
 return s

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',default='d7cb67be');p.add_argument('--out',type=Path,required=True);p.add_argument('--cycles',type=int,default=8192);a=p.parse_args()
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 source=(ROOT/SOURCE).read_text();ref=subprocess.check_output(['git','show',a.reference+':'+SOURCE],cwd=ROOT,text=True)
 current=out/'current.sv';current.write_text(model(source,'current'));reference=out/'reference.sv';reference.write_text(model(ref,'reference'));tb=out/'tb.sv';tb.write_text(bench(source,a.cycles))
 resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies'];sources=resolve([current,reference,tb],ROOT);hashes={str(p):digest(p)for p in sources};records=[]
 for mode in ['generic','fpga']:
  binary=out/(mode+'.vvp');flags=[]if mode=='generic'else['-DSYNTHESIS=1','-DXILINX_FPGA=1']
  for label,command in [('compile',['iverilog','-g2012','-s','tb',*flags,'-o',binary,*sources]),('run',['vvp',binary])]:
   with(out/(mode+'_'+label+'.log')).open('w')as f:subprocess.run(list(map(str,command)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=360)
  log=out/(mode+'_run.log');text=log.read_text();assert 'PS_REQUEST_FOUR_STATE_ALL_PASS'in text and text.count('PS_REQUEST_FOUR_STATE_PROFILE_PASS')==len(CASES);print(text,flush=True)
  records.append(dict(mode=mode,passed=True,profiles=list(CASES),cycles_per_profile=a.cycles,log_sha256=digest(log)))
 assert source==(ROOT/SOURCE).read_text()and hashes=={str(p):digest(p)for p in sources}
 (out/'summary.json').write_text(json.dumps(dict(passed=True,reference=a.reference,all_public_outputs_compared_each_cycle=True,source_sha256=hashes,profiles=records,test_sha256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
