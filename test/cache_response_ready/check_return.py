#!/usr/bin/env python3
"""逐位比较生产响应队列与既有寄存返回实现的二态及四态结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
RELATIVE='rtl/npu/dma/cache/conv_cache_request_path.sv'
FIELDS=[('response_count','[DQ_CW-1:0]'),('saved_response_data','[READ_WIDTH-1:0]'),
        ('saved_response_error',''),('core_rsp_valid',''),('core_rsp_ready','')]
PORTS=',\n'.join('input logic '+width+' '+name for name,width in FIELDS)
CONNECT=','.join('.'+name+'('+name+')' for name,width in FIELDS)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(name,source):
    first=source.index('  if (DEMAND_DEPTH > 1) begin : g_registered_response')
    last=source.index('  end else begin : g_single_response',first)
    block=source[first:last]+'  end\n'
    return f'''// 使用生产队列返回过程，所有保存数据和状态均作为自由输入。
module {name} #(parameter integer DEMAND_DEPTH=2,READ_WIDTH=8,
parameter integer DQ_CW=$clog2(DEMAND_DEPTH+1))(
{PORTS},output logic[READ_WIDTH+4:0] observed);
logic rsp_valid,rsp_error,rsp_success,rsp_failure,response_push;
logic[READ_WIDTH-1:0] rsp_data;
{block}
assign observed={{response_push,rsp_failure,rsp_success,rsp_error,rsp_valid,rsp_data}};
endmodule
'''


def bench(depth,read_width):
    names=','.join(name for name,width in FIELDS)
    declarations='\n'.join('logic '+width+' '+name+';' for name,width in FIELDS)
    total_width=depth.bit_length()+read_width+3
    return f'''`timescale 1ns/1ps
// 枚举计数与保存事件的四态组合，并检查完整返回数据位。
module tb;
localparam integer DEMAND_DEPTH={depth},DQ_CW=$clog2(DEMAND_DEPTH+1),READ_WIDTH={read_width};
localparam integer W={total_width};
{declarations}
logic[W-1:0] stimulus;
logic[READ_WIDTH+4:0] actual,expected;
integer checks=0,valid_count=0,push_count=0,error_count=0;
int unsigned random_state=32'h74d8c9a3;
reference #(.DEMAND_DEPTH(DEMAND_DEPTH),.READ_WIDTH(READ_WIDTH)) u_ref({CONNECT},.observed(expected));
current #(.DEMAND_DEPTH(DEMAND_DEPTH),.READ_WIDTH(READ_WIDTH)) u_cur({CONNECT},.observed(actual));
function automatic logic value4(input integer n);
 case(n)0:value4=0;1:value4=1;2:value4=1'bx;default:value4=1'bz;endcase
endfunction
function automatic int unsigned next_random();
 random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;
 return random_state;
endfunction
task automatic initialize;
 for(integer b=0;b<W;b+=32)stimulus=(stimulus<<32)|W'(next_random());
 {{{names}}}=stimulus;
endtask
task automatic check;
 #1;
 if(actual!==expected)$fatal(1,"queue return case=%0d actual=%h expected=%h",checks,actual,expected);
 if(u_cur.rsp_valid===1'b1)valid_count++;
 if(u_cur.response_push===1'b1)push_count++;
 if(u_cur.rsp_failure===1'b1)error_count++;
 checks++;
endtask
initial begin
 if(W!=DQ_CW+READ_WIDTH+3 || $bits(stimulus)!=W ||
    $bits(response_count)!=DQ_CW || $bits(saved_response_data)!=READ_WIDTH)
   $fatal(1,"declared stimulus widths");
 for(integer scenario=0;scenario<(1<<(2*(DQ_CW+3)));scenario++)begin
   for(integer pattern=0;pattern<4;pattern++)begin
     initialize();
     for(integer b=0;b<DQ_CW;b++)response_count[b]=value4((scenario>>(2*b))&3);
     saved_response_error=value4((scenario>>(2*DQ_CW))&3);
     core_rsp_valid=value4((scenario>>(2*(DQ_CW+1)))&3);
     core_rsp_ready=value4((scenario>>(2*(DQ_CW+2)))&3);
     for(integer b=0;b<READ_WIDTH;b++)saved_response_data[b]=value4((b+pattern)&3);
     check();
   end
 end
 for(integer scenario=0;scenario<20000;scenario++)begin
   initialize();
   for(integer b=0;b<W;b++)if((next_random()&7)==0)stimulus[b]=value4(2+(next_random()&1));
   {{{names}}}=stimulus;check();
 end
 if(valid_count==0 || push_count==0 || error_count==0)$fatal(1,"queue coverage");
 $display("CACHE_REGISTERED_RESPONSE_PASS checks=%0d payload_width=%0d stimulus_width=%0d valid=%0d enqueue=%0d errors=%0d",
   checks,READ_WIDTH,W,valid_count,push_count,error_count);
 $finish;
end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='0d437ded9299a7ad5ab70f30884b5344399d4d22')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=ROOT/RELATIVE
    previous=subprocess.check_output(['git','show',args.reference+':'+RELATIVE],cwd=ROOT).decode()
    (out/'reference_request_path.sv').write_text(previous)
    models=out/'models.sv';models.write_text(model('reference',previous)+model('current',source.read_text()))
    source_hash=digest(source);results=[]
    for depth,width in ((2,8),(2,64),(4,128)):
        tb=out/f'tb_{depth}_{width}.sv';tb.write_text(bench(depth,width))
        proof=out/f'proof_{depth}_{width}.sv';proof.write_text(f'''
module proof #(parameter integer DEMAND_DEPTH={depth},READ_WIDTH={width},
parameter integer DQ_CW=$clog2(DEMAND_DEPTH+1))({PORTS},output logic match_result);
logic[READ_WIDTH+4:0] actual,expected;
reference #(.DEMAND_DEPTH(DEMAND_DEPTH),.READ_WIDTH(READ_WIDTH)) u_ref({CONNECT},.observed(expected));
current #(.DEMAND_DEPTH(DEMAND_DEPTH),.READ_WIDTH(READ_WIDTH)) u_cur({CONNECT},.observed(actual));
assign match_result=actual==expected;
endmodule
''')
        for mode,flags in (('generic',['-USYNTHESIS','-UXILINX_FPGA']),
                           ('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])):
            name=f'{mode}_{depth}_{width}';script=out/(name+'.ys');log=out/(name+'.log')
            script.write_text('read_slang --top proof '+shlex.join(flags+[str(models),str(proof)])+
                '\nprep -top proof -flatten\nopt -full\nsat -prove match_result 1 -verify\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                               check=True,stdout=stream,stderr=subprocess.STDOUT)
            binary=out/(name+'.vvp');compiler=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
            with (out/(name+'_compile.log')).open('w') as stream:
                subprocess.run(['iverilog','-g2012','-s','tb','-o',binary,*compiler,str(models),str(tb)],
                               check=True,stdout=stream,stderr=subprocess.STDOUT)
            result=subprocess.run(['vvp',binary],check=True,capture_output=True,text=True)
            simlog=out/(name+'_four_state.log');simlog.write_text(result.stdout)
            values={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',result.stdout)}
            assert values['payload_width']==width and values['stimulus_width']==depth.bit_length()+width+3
            row=dict(mode=mode,depth=depth,read_width=width,formal_passed=True,
                four_state_checks=values['checks'],coverage=values,log_sha256=digest(log),
                simulation_log_sha256=digest(simlog),testbench_sha256=digest(tb))
            results.append(row);print(json.dumps(row),flush=True)
    assert digest(source)==source_hash
    (out/'summary.json').write_text(json.dumps(dict(passed=True,reference=args.reference,
        source_sha256={str(source):source_hash},runner_sha256=digest(__file__),cases=results,
        input_constraints=[],compared_outputs=['rsp_valid','rsp_data','rsp_error','rsp_success',
                                            'rsp_failure','response_push']),indent=2)+'\n')


if __name__=='__main__':main()
