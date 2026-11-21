#!/usr/bin/env python3
"""验证选择加法器的通用分支、全部修改分支二值输入和严格四态传播。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,re,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
WIDTHS=(1,8,12,16,17,24,32,48,64,128)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_unmodified(text):
    text=re.sub(r'//[^\n]*|/\*.*?\*/','',text,flags=re.S)
    start=text.index('if ((p_width == 48) && p_split_12bit) begin : g_parallel')
    stop=text.index('end else begin : g_single',start)
    return re.sub(r'\s+','',text[:start]+'PARALLEL_48_BRANCH'+text[stop:])


FORMAL='''module compare #(parameter integer W=48,U=1,S=1)(
 input logic[W-1:0] a,b,c,input logic select_rhs,enable,output logic equivalent);
 wire[W-1:0] expected,actual;
 reference #(.p_width(W),.p_use_dsp(U),.p_split_12bit(S)) u_ref(a,b,c,select_rhs,enable,expected);
 candidate #(.p_width(W),.p_use_dsp(U),.p_split_12bit(S)) u_dut(a,b,c,select_rhs,enable,actual);
 assign equivalent=expected==actual;
endmodule
'''


FOUR='''module four_case #(parameter integer W=48,U=1,S=1)(output logic done);
 logic[W-1:0] a,b,c,base_a,base_b,base_c;
 logic select_rhs,enable;
 wire[W-1:0] expected,actual;
 integer count,pattern,select_code,enable_code,index,operand,symbol;
 reference #(.p_width(W),.p_use_dsp(U),.p_split_12bit(S)) u_ref(a,b,c,select_rhs,enable,expected);
 candidate #(.p_width(W),.p_use_dsp(U),.p_split_12bit(S)) u_dut(a,b,c,select_rhs,enable,actual);
 function automatic logic four_symbol(input integer value);
  case(value&3)
   0:four_symbol=0; 1:four_symbol=1; 2:four_symbol=1'bx; 3:four_symbol=1'bz;
  endcase
 endfunction
 task automatic check;
  begin
   #1;count=count+1;
   if(expected!==actual)$fatal(1,"select_add four-state mismatch W=%0d U=%0d S=%0d a=%b b=%b c=%b sel=%b en=%b expected=%b actual=%b",W,U,S,a,b,c,select_rhs,enable,expected,actual);
  end
 endtask
 initial begin
  done=0;count=0;
  for(pattern=0;pattern<8;pattern=pattern+1) begin
   for(index=0;index<W;index=index+1)begin
    case(pattern)
     0:begin base_a[index]=0;base_b[index]=0;base_c[index]=0;end
     1:begin base_a[index]=1;base_b[index]=1;base_c[index]=1;end
     2:begin base_a[index]=index%2;base_b[index]=!(index%2);base_c[index]=index%2;end
     3:begin base_a[index]=1;base_b[index]=index%12==0;base_c[index]=index%12==11;end
     4:begin base_a[index]=index%12==11;base_b[index]=1;base_c[index]=0;end
     5:begin base_a[index]=0;base_b[index]=index%2;base_c[index]=!(index%2);end
     6:begin base_a[index]=1'bx;base_b[index]=0;base_c[index]=1;end
     7:begin base_a[index]=index%2 ? 1'bx:1'bz;base_b[index]=index%3==0 ? 1'bx:1'b1;base_c[index]=index%3==1 ? 1'bz:1'b0;end
    endcase
   end
   for(select_code=0;select_code<4;select_code=select_code+1)begin
    for(enable_code=0;enable_code<4;enable_code=enable_code+1)begin
     select_rhs=four_symbol(select_code);enable=four_symbol(enable_code);
     a=base_a;b=base_b;c=base_c;check();
     for(operand=0;operand<3;operand=operand+1)begin
      for(index=0;index<W;index=index+1)begin
       for(symbol=2;symbol<4;symbol=symbol+1)begin
        a=base_a;b=base_b;c=base_c;
        case(operand)
         0:a[index]=four_symbol(symbol);
         1:b[index]=four_symbol(symbol);
         2:c[index]=four_symbol(symbol);
        endcase
        check();
       end
      end
     end
    end
   end
  end
  $display("FOUR_STATE_PASS W=%0d U=%0d S=%0d checked=%0d",W,U,S,count);
  done=1;
 end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    inputs={'reference':args.reference.resolve(),'candidate':args.candidate.resolve()}
    hashes={n:sha(p) for n,p in inputs.items()}
    texts={n:p.read_text() for n,p in inputs.items()}
    if normalize_unmodified(texts['reference'])!=normalize_unmodified(texts['candidate']):
        raise RuntimeError('通用分支或接口发生改变')
    units=[]
    for name,text in texts.items():
        path=out/(name+'.sv');path.write_text(re.sub(r'\bmodule select_add\b','module '+name,text,count=1));units.append(path)
    source=out/'compare.sv';source.write_text(FORMAL)
    def prove(profile):
        width,use,split=profile;name=f'w{width}_u{use}_s{split}'
        script=out/(name+'.ys');log=out/(name+'.log')
        script.write_text(f'read_slang --top compare -GW={width} -GU={use} -GS={split} '+shlex.join(map(str,units+[source]))+'\nprep -top compare -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT,check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():raise RuntimeError(name)
        return dict(width=width,use_dsp=use,split_12bit=split,passed=True,log_sha256=sha(log))
    profiles=[(w,u,s)for w in WIDTHS for u in (0,1) for s in (0,1)]
    with ThreadPoolExecutor(max_workers=2)as pool:records=list(pool.map(prove,profiles))
    bench=out/'four_state.sv';text=FOUR+f'module tb; wire[{len(profiles)-1}:0] done;\n'
    for index,(w,u,s)in enumerate(profiles):text+=f'four_case #(.W({w}),.U({u}),.S({s})) u_{index}(.done(done[{index}]));\n'
    text+='initial begin wait(&done);$finish;end endmodule\n';bench.write_text(text)
    simulation_units=[]
    for path in units:
        sim=path.with_name(path.stem+'_simulation.sv')
        sim.write_text(path.read_text().replace('    begin : g_generic','    generate\n    begin : g_generic',1).replace('\nendmodule','\n    endgenerate\nendmodule',1))
        simulation_units.append(sim)
    with (out/'compile.log').open('w')as log:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(out/'simulation.vvp'),*map(str,simulation_units),str(bench)],stdout=log,stderr=subprocess.STDOUT,check=True)
    with (out/'four_state.log').open('w')as log:
        subprocess.run(['vvp',str(out/'simulation.vvp')],stdout=log,stderr=subprocess.STDOUT,check=True)
    matches=re.findall(r'FOUR_STATE_PASS W=(\d+) U=(\d+) S=(\d+) checked=(\d+)',(out/'four_state.log').read_text())
    if len(matches)!=len(profiles):raise RuntimeError('四态覆盖未完成')
    if hashes!={n:sha(p)for n,p in inputs.items()}:raise RuntimeError('检查期间源码发生改变')
    report=dict(passed=True,source_sha256=hashes,source_paths={n:str(p)for n,p in inputs.items()},
                unchanged_generic_branches=True,changed_branch='p_width==48 && p_split_12bit',
                complete_changed_branch_input_bits=146,binary_cases=records,
                four_state_cases=[dict(width=int(w),use_dsp=int(u),split_12bit=int(s),checked=int(n),passed=True)for w,u,s,n in matches],
                strict_four_state_comparisons=sum(int(n)for w,u,s,n in matches),
                parameter_scope='Interface and all generic-width branches match structurally. The only changed 48-bit four-lane branch is proved for every binary input and both p_use_dsp values. Representative elaborations exercise both p_split_12bit values across all width partitions.')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items()if k not in ('binary_cases','four_state_cases')},indent=2))
if __name__=='__main__':main()
