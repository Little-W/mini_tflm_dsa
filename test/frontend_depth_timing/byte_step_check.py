#!/usr/bin/env python3
"""证明固定字节步长的逐位进位与完整定宽加法一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,default=ROOT)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=args.source_root.resolve()/'rtl/npu/conv/conv_im2col_frontend.sv'
    text=source.read_text()
    function=re.search(r'      function automatic logic \[p_step_width:0\] add_byte_step\(.*?      endfunction',text,re.S).group(0)
    if text.count('assign low_s8 = add_byte_step(')!=1 or text.count('assign low_s16 = add_byte_step(')!=1:
        raise RuntimeError('字节步长的实际加法连接与证明入口不符')
    unit=out/'comparison.sv'
    unit.write_text('module comparison #(parameter int p_step_width=4)('
        'input logic[p_step_width-1:0] value,input logic[p_step_width:0] amount,'
        'output logic[p_step_width:0] actual,expected,output logic equivalent);\n'+function+
        "\nassign actual=add_byte_step(value,amount);\nassign expected={1'b0,value}+amount;\n"
        'assign equivalent=actual==expected;\nendmodule\n')
    bench=out/'fourstate.sv';bench.write_text(r'''
module tb;
 parameter integer WIDTH=4;
 logic[WIDTH-1:0] value;
 logic[WIDTH:0] amount,actual,expected;
 logic equivalent;
 integer pattern,step,bits,index,checks;
 comparison #(.p_step_width(WIDTH)) dut(.*);
 initial begin
  checks=0;
  for(pattern=0;pattern<(1<<(2*WIDTH));pattern=pattern+1) begin
   bits=pattern;
   for(index=0;index<WIDTH;index=index+1) begin
    case(bits&3)
     0:value[index]=0;
     1:value[index]=1;
     2:value[index]=1'bx;
     3:value[index]=1'bz;
    endcase
    bits=bits>>2;
   end
   for(step=0;step<(1<<WIDTH);step=step+1) begin
    amount=step;
    #1;
    if(actual !== expected) $fatal(1,"byte step mismatch");
    checks=checks+1;
   end
  end
  $display("BYTE_STEP_FOURSTATE_PASS width=%0d checks=%0d",WIDTH,checks);
  $finish;
 end
endmodule
''')
    profiles=[];checks=0
    for width in (2,3,4,5):
        script=out/f'w{width}.ys';log=out/f'w{width}.log'
        script.write_text('read_slang --top comparison -Gp_step_width='+str(width)+' '+shlex.quote(str(unit))+
            '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           stdout=stream,stderr=subprocess.STDOUT,check=True)
        sim=out/f'sim{width}';log=out/f'fourstate{width}.log'
        subprocess.run(['iverilog','-g2012','-s','tb',f'-Ptb.WIDTH={width}','-o',str(sim),str(unit),str(bench)],check=True)
        with log.open('w') as stream:
            subprocess.run(['vvp',str(sim)],stdout=stream,stderr=subprocess.STDOUT,check=True)
        profiles.append({'width':width,'passed':True});checks+=(4**width)*(2**width)
    summary={'passed':True,'input_assumptions':[], 'profiles':profiles,'fourstate_checks':checks,
        'source_sha256':{str(source):hashlib.sha256(source.read_bytes()).hexdigest()},
        'function_sha256':hashlib.sha256(function.encode()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('BYTE_STEP_ADDITION_PASS',len(profiles),checks,flush=True)
if __name__=='__main__':main()
