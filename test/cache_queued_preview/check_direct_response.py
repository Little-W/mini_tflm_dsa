#!/usr/bin/env python3
"""检查同拍预读响应的数据选择、错误资格和反压保存的四态结果。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PORTS='''input logic preview_active,req_fire,fast_hit_response,
input logic [DQ_CW-1:0] response_count,outstanding_count,
input logic [READ_WIDTH-1:0] saved_response_data,core_rsp_data,
input logic saved_response_error,core_rsp_valid,core_rsp_ready,rsp_ready'''
NAMES=('preview_active','req_fire','fast_hit_response','response_count','outstanding_count',
       'saved_response_data','core_rsp_data','saved_response_error','core_rsp_valid','core_rsp_ready','rsp_ready')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(name,source):
    first=source.index('  if (DEMAND_DEPTH > 1) begin : g_registered_response')
    last=source.index('  end else begin : g_single_response',first)
    block=source[first:last].replace('if (DEMAND_DEPTH > 1)','if (1)',1)+'  end\n'
    return f'''// 从实际请求模块提取返回组合过程，保留全部四态条件。
module {name} #(parameter integer DQ_CW=2,READ_WIDTH=8,parameter bit p_preview_request=1)(
{PORTS},output logic [READ_WIDTH+4:0] observed);
logic rsp_valid,rsp_error,rsp_success,rsp_failure,response_push;
logic [READ_WIDTH-1:0] rsp_data;
{block}
assign observed={{response_push,rsp_failure,rsp_success,rsp_error,rsp_valid,rsp_data}};
endmodule
'''


def bench(width,enabled):
    declarations=PORTS.replace('input logic','logic').replace(',\n',';\n')+';\n'
    connect=','.join('.'+n+'('+n+')' for n in NAMES)
    fields=','.join(NAMES)
    return f'''`timescale 1ns/1ps
// 枚举预读资格及队列计数关键位的四态组合，并随机检查全部未知返回数据。
module tb;
localparam integer DQ_CW={width},READ_WIDTH=8,W=7+2*DQ_CW+2*READ_WIDTH;
{declarations}
logic [READ_WIDTH+4:0] actual,expected;
logic [W-1:0] stimulus;
integer checks=0;
int unsigned random_state=32'h74d8c9a3;
assign {{{fields}}}=stimulus;
reference #(.DQ_CW(DQ_CW),.p_preview_request({enabled})) u_ref({connect},.observed(expected));
current #(.DQ_CW(DQ_CW),.p_preview_request({enabled})) u_cur({connect},.observed(actual));
function automatic logic value4(input integer n);
  case(n)0:value4=0;1:value4=1;2:value4=1'bx;default:value4=1'bz;endcase
endfunction
function automatic int unsigned next_random();
  random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;
  return random_state;
endfunction
task automatic initialize;
  for(integer b=0;b<W;b++)stimulus[b]=1'(next_random());
endtask
task automatic check;
  #1;if(actual!==expected)$fatal(1,"direct response case=%0d current=%h reference=%h",checks,actual,expected);
  checks++;
endtask
initial begin
  for(integer scenario=0;scenario<16384;scenario++)begin
    for(integer pattern=0;pattern<4;pattern++)begin
      initialize();
      for(integer b=0;b<3;b++)stimulus[W-1-b]=value4((scenario>>(2*b))&3);
      for(integer b=0;b<2;b++)begin
        stimulus[W-4-b]=value4((scenario>>(6+2*b))&3);
        stimulus[W-4-DQ_CW-b]=value4((scenario>>(10+2*b))&3);
      end
      stimulus[3]=value4(pattern);check();
    end
  end
  for(integer scenario=0;scenario<20000;scenario++)begin
    initialize();
    for(integer b=0;b<W;b++)if((next_random()&7)==0)stimulus[b]=value4(2+(next_random()&1));
    check();
  end
  $display("CACHE_DIRECT_RESPONSE_PASS checks=%0d",checks);$finish;
end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    current=ROOT/'rtl/npu/dma/cache/conv_cache_request_path.sv'
    reference=Path(__file__).parent/'reference_request_path.sv'
    hashes={str(p):digest(p) for p in (current,reference)}
    models=out/'models.sv';models.write_text(model('reference',reference.read_text())+model('current',current.read_text()))
    connect=','.join('.'+n+'('+n+')' for n in NAMES);results=[]
    for width in (2,3):
        for enabled in (0,1):
            test=out/f'tb_{width}_{enabled}.sv';test.write_text(bench(width,enabled))
            proof=out/f'proof_{width}_{enabled}.sv';proof.write_text(f'''// 任意输入下比较全部返回数据与资格。
module proof #(parameter integer DQ_CW={width},READ_WIDTH=8)(
{PORTS},output logic match_result);
logic [READ_WIDTH+4:0] actual,expected;
reference #(.DQ_CW(DQ_CW),.p_preview_request({enabled})) u_ref({connect},.observed(expected));
current #(.DQ_CW(DQ_CW),.p_preview_request({enabled})) u_cur({connect},.observed(actual));
assign match_result=actual==expected;
endmodule
''')
            for mode,flags in (('generic',['-USYNTHESIS','-UXILINX_FPGA']),('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])):
                name=f'{mode}_{width}_{enabled}';script=out/(name+'.ys');log=out/(name+'.log')
                script.write_text('read_slang --top proof '+shlex.join(flags+[str(models),str(proof)])+
                    '\nprep -top proof -flatten\nopt -full\nsat -prove match_result 1 -verify\n')
                with log.open('w') as stream:
                    subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],check=True,stdout=stream,stderr=subprocess.STDOUT)
                binary=out/(name+'.vvp');compiler=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
                subprocess.run(['iverilog','-g2012','-s','tb','-o',binary]+compiler+[str(models),str(test)],check=True,capture_output=True)
                result=subprocess.run(['vvp',binary],check=True,capture_output=True,text=True)
                simlog=out/(name+'_four_state.log');simlog.write_text(result.stdout)
                count=int(re.search(r'PASS checks=(\d+)',result.stdout).group(1))
                row=dict(mode=mode,count_width=width,enabled=enabled,formal_passed=True,four_state_checks=count,
                    log_sha256=digest(log),simulation_log_sha256=digest(simlog));results.append(row);print(json.dumps(row),flush=True)
    assert all(digest(p)==h for p,h in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,cases=results,input_constraints=[]),indent=2)+'\n')


if __name__=='__main__':main()
