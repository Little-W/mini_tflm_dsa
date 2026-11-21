#!/usr/bin/env python3
"""验证历史位置范围和预取换核位移的组合表达式。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]


def between(text,start,end):
    first=text.index(start);return text[first:text.index(end,first)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    source=args.source_root/'rtl/npu/conv/conv_im2col_frontend.sv'
    helper=args.source_root/'rtl/common/unsigned_compare.sv'
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in(source,helper)}
    text=source.read_text()
    assert re.findall(r'pf_fragment_dx_q\s*<=\s*([^;]+);',text)==['fragment_delta']
    history=between(text,'  assign history_limit_i_a =','  always_ff @(posedge clk or negedge rst_n) begin\n    if (!rst_n) p_wrap_target_q')
    fragment=between(text,"  assign fragment_distance =","  always_ff @(posedge clk or negedge rst_n) begin\n    if (!rst_n) begin\n      prefetch_phase")
    sv=args.out/'history_prefetch.sv'
    sv.write_text('''module proof(input logic last_p_valid,last_p_overflow_q,
 input logic [32:0] p_history_delta_q,input logic [15:0] output_w,
 input logic signed [32:0] tap_wrap_dx,input logic [31:0] pf_distance_q,
 output logic equivalent);
 typedef struct packed {logic[15:0]output_w;}config_t;config_t c;
 assign c.output_w=output_w;
 logic history_range_valid;
 logic[16:0]history_limit_i_a,history_limit_i_b;
 logic history_limit_o_less,unused_history_limit_equal;
 logic[32:0]fragment_distance,fragment_xor,fragment_carry;
 logic signed[32:0]fragment_delta,reference_fragment;
 logic reference_history;
'''+history+fragment+'''
 assign reference_fragment=tap_wrap_dx+$signed(33'(pf_distance_q))-33'sd1;
 assign reference_history=last_p_valid&&!last_p_overflow_q&&
   !(|p_history_delta_q[32:17])&&p_history_delta_q[16:0]<={1'b0,c.output_w};
 assign equivalent={history_range_valid,fragment_delta}==={reference_history,reference_fragment};
endmodule
''')
    results=[]
    for mode,defines in [('generic',[]),('fpga',['-DXILINX_FPGA=1']),('asic',['-DASIC_SYNTHESIS=1'])]:
        ys=args.out/(mode+'.ys');log=args.out/(mode+'.log')
        ys.write_text('read_slang --top proof -DSYNTHESIS=1 '+shlex.join(defines+list(map(str,(helper,sv))))+
            '\nprep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w')as stream:
            run=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                stdout=stream,stderr=subprocess.STDOUT,timeout=120)
        if run.returncode or 'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
        results.append({'mode':mode,'passed':True,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    tb=args.out/'four_state.sv'
    tb.write_text('''module tb;
 logic last_p_valid,last_p_overflow_q;
 logic[32:0]p_history_delta_q;
 logic[15:0]output_w;
 logic signed[32:0]tap_wrap_dx;
 logic[31:0]pf_distance_q;
 wire equivalent;
 proof dut(.*);
 logic[115:0]pattern;
 initial begin
  for(integer sample=0;sample<40000;sample++)begin
   for(integer bit_index=0;bit_index<116;bit_index++)pattern[bit_index]=$urandom_range(0,1);
   {last_p_valid,last_p_overflow_q,p_history_delta_q,output_w,tap_wrap_dx,pf_distance_q}=pattern;
   if(sample%2==0)begin last_p_valid=1;last_p_overflow_q=0;p_history_delta_q[32:17]=0;end
   if(sample%3==0)p_history_delta_q[15:0]=output_w;
   pattern={last_p_valid,last_p_overflow_q,p_history_delta_q,output_w,tap_wrap_dx,pf_distance_q};
   if(sample%3==0)pattern[sample%116]=1'bx;
   if(sample%5==0)pattern[(sample*7)%116]=1'bz;
   {last_p_valid,last_p_overflow_q,p_history_delta_q,output_w,tap_wrap_dx,pf_distance_q}=pattern;
   #1;if(equivalent!==1'b1)$fatal(1,"history prefetch four-state sample %0d",sample);
  end
  $display("HISTORY_PREFETCH_FOUR_STATE_PASS checks=40000");$finish;
 end
endmodule
''')
    events=[]
    for mode,defines in [('generic',[]),('fpga',['-DXILINX_FPGA=1']),('asic',['-DASIC_SYNTHESIS=1'])]:
        binary=args.out/(mode+'.vvp');log=args.out/(mode+'.event.log')
        subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb',*defines,'-o',str(binary),
            *map(str,(helper,sv,tb))],check=True,capture_output=True)
        run=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],check=True,capture_output=True,text=True,timeout=60)
        log.write_text(run.stdout+run.stderr)
        if 'checks=40000'not in run.stdout:raise RuntimeError(str(log))
        events.append({'mode':mode,'checks':40000,'passed':True,
            'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in(source,helper)}
    report={'passed':True,'source_sha256':hashes,'input_constraints':[],
        'formal_results':34,'formal':results,'event_simulations':events,'four_state_checks':120000}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'formal_modes':3,'result_bits':34,'four_state_checks':120000}))
if __name__=='__main__':main()
