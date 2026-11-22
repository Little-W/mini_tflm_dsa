#!/usr/bin/env python3
"""验证接收完成等式的逐位进位比较。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command,log):
    with log.open('w')as stream:
        result=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=120)
    if result.returncode:raise RuntimeError(str(log))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in('source-root','reference-root','tool-root','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    rel=Path('rtl/npu/conv/vector_engine.sv');current=read_current_source(args.source_root/rel);reference=read_current_source(args.reference_root/rel)
    pattern=r'add_equal #\([^\n]+\) u_window_count_equal \(.*?\n  \);'
    before=re.search(pattern,reference,re.S)[0];after=re.search(pattern,current,re.S)[0]
    model=out/'model.sv'
    model.write_text('''module count_property(
 input wire [31:0] window_count_i_value,window_count_i_increment,window_count_i_target,
 input wire window_count_i_carry,output wire identical
);
 wire original_equal,selected_equal;
'''+before.replace('u_window_count_equal','original').replace('window_count_o_equal','original_equal')+'\n'+
        after.replace('u_window_count_equal','selected').replace('window_count_o_equal','selected_equal')+'''
 assign identical=(original_equal===selected_equal);
endmodule
''')
    dependency=args.source_root/'rtl/common/add_equal.sv';script=out/'prove.ys'
    script.write_text(f'read_slang --top count_property -D SYNTHESIS=1 -D XILINX_FPGA=1 {dependency} {model}\n'
                      'prep -top count_property -flatten\nsat -verify -prove identical 1 -show-inputs -show-outputs\n')
    run([sys.executable,args.tool_root/'scripts/fpga/open_fpga_synth.py','--worker',script],out/'prove.log')
    bench=out/'bench.sv';bench.write_text('''module tb;
 logic [31:0] a,b,target;
 logic carry;
 wire identical;
 integer i,j;
 integer unsigned rng=32'hf718d4ba;
 function automatic integer unsigned random_next;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic[1:0] value);
  case(value)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 count_property dut(a,b,target,carry,identical);
 initial begin
  for(i=0;i<100000;i++)begin
   a=random_next();b=random_next();carry=four(2'(random_next()));
   target=(i%2==0)?a+b+carry:random_next();
   if(i%3==0)for(j=0;j<32;j++)a[j]=four(2'(random_next()));
   if(i%3==1)for(j=0;j<32;j++)b[j]=four(2'(random_next()));
   if(i%3==2)for(j=0;j<32;j++)target[j]=four(2'(random_next()));
   #1;if(identical!==1'b1)$fatal(1,"接收计数等式结果不一致");
  end
  $display("WINDOW_COUNT_PASS comparisons=%0d",i);$finish;
 end
endmodule
''')
    exe=out/'simulation.vvp'
    run(['/home/agent/.local/bin/iverilog','-g2012','-DXILINX_FPGA','-s','tb','-o',exe,dependency,model,bench],out/'compile.log')
    run(['/home/agent/.local/bin/vvp',exe],out/'simulate.log')
    report={'passed':True,'source_sha256':hashlib.sha256(current.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),
            'input_bits':97,'input_constraints':'none','formal_log_sha256':sha(out/'prove.log'),
            'four_state_comparisons':100000,'four_state_log_sha256':sha(out/'simulate.log'),
            'dependency_sha256':sha(dependency),'test_sha256':sha(Path(__file__))}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
