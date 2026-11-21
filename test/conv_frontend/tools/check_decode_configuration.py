#!/usr/bin/env python3
"""证明配置解码结果和连续通道条件的保存关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
source=a.source_root/'rtl/npu/conv/conv_im2col_frontend.sv'
package=a.source_root/'rtl/npu/conv/conv_im2col_pkg.sv'
text=source.read_text();digest=hashlib.sha256(source.read_bytes()).hexdigest()
function=re.search(r'  function automatic logic \[4:0\] power_shift\(.*?  endfunction',text,re.S).group(0)
start=text.index('  // 形状、移位量和连续通道条件随配置保存')
start=text.index('  always_ff',start)
stop=text.index('  function automatic logic [4:0] power_shift',start)
storage=text[start:stop]
assignments=re.findall(r'\bc\s*<=\s*([^;]+);',text)
assert assignments==["'0",'cfg'],assignments
config_branch=re.search(r'\(cfg_valid && cfg_ready\): begin(.*?)\bend\s*tile_commit:',text,re.S)
assert config_branch and re.search(r'\bc\s*<=\s*cfg;',config_branch[1])
assert re.search(r'if \(!rst_n\) begin\s*\{word_output_q, state\}.*?\bc\s*<=\s*\x27?0;',text,re.S)
mask_reset=re.search(r'last_group_channel_q <= (16\'hffff);',text).group(1)
mask_next=re.search(r'last_group_channel_q <= (cfg.group_c - 16\'d1);',text).group(1)
mask_assign=re.search(r'  assign group_range_channel\[2\] = [^;]+;',text).group(0)
module='''module proof(input logic clk,rst_n,cfg_valid,cfg_ready,
 input logic[31:0]q0,
 input conv_im2col_pkg::conv_cfg_t cfg,
 input logic group_shape_check_o_valid,kernel_shape_check_o_valid,output_shape_check_o_valid,
 output logic equivalent);
 import conv_im2col_pkg::*;
 conv_cfg_t c;
 logic group_shape_o_valid,kernel_shape_o_valid,output_shape_o_valid;
 logic[4:0]output_width_shift,group_width_shift,kernel_width_shift;
 logic linear_channel_layout_q;
 logic[15:0]last_group_channel_q;
 logic[5:0][15:0]group_range_channel;
 always_ff @(posedge clk or negedge rst_n) begin
  if(!rst_n)c<='0;
  else if(cfg_valid&&cfg_ready)c<=cfg;
 end
'''+function+'\n'+storage+f'''
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)last_group_channel_q<={mask_reset};
  else if(cfg_valid&&cfg_ready)last_group_channel_q<={mask_next};
 end
'''+mask_assign+'''
 assign equivalent=(output_width_shift===power_shift({16'd0,c.output_w}))&&
  (group_width_shift===power_shift({16'd0,c.group_c}))&&
  (kernel_width_shift===power_shift({16'd0,c.kernel_w}))&&
  (last_group_channel_q===(c.group_c-16'd1))&&
  (group_range_channel[2]===16'(q0&(32'(c.group_c)-1)))&&
  (linear_channel_layout_q===(c.group_c==c.input_c&&c.group_offset==16'd0&&c.dilation_w==16'd1));
endmodule
'''
sv=a.out/'decode_shift_invariant.sv';sv.write_text(module)
ys=a.out/'decode_shift_invariant.ys';ys.write_text('read_slang --top proof -DXILINX_FPGA=1 -DSYNTHESIS=1 '+shlex.quote(str(package))+' '+shlex.quote(str(sv))+'\nprep -top proof -flatten\nasync2sync\nopt\ncheck -assert\nsat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 -prove equivalent 1 -verify\nsat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify\n')
log=a.out/'decode_shift_invariant.log'
with log.open('w')as f:
 r=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=f,stderr=subprocess.STDOUT,timeout=60)
assert r.returncode==0 and log.read_text().count('SUCCESS!')==2,log
bench=a.out/'decode_shift_event.sv'
bench.write_text('''module tb;
 import conv_im2col_pkg::*;
 logic clk=0,rst_n=0,cfg_valid=0,cfg_ready=0;
 conv_cfg_t cfg;
 logic[15:0]output_width,group_channels,kernel_width;
 logic[15:0]input_channels,group_offset,dilation_width;
 logic[31:0]q0=0;
 logic equivalent;
 proof dut(.clk,.rst_n,.cfg_valid,.cfg_ready,.cfg,.q0,.group_shape_check_o_valid(1'b0),
  .kernel_shape_check_o_valid(1'b0),.output_shape_check_o_valid(1'b0),.equivalent);
 initial begin
 cfg='0;
 #1;clk=1;#1;if(equivalent!==1'b1)$fatal(1,"reset shift relation");
 clk=0;rst_n=1;
 for(integer sample=0;sample<30000;sample++)begin
  cfg_valid=$random;cfg_ready=$random;q0=$random;
  output_width=$random;group_channels=$random;kernel_width=$random;
  if(sample%3==0)group_channels[sample%16]=1'bx;
  if(sample%5==0)kernel_width[sample%16]=1'bz;
  if(sample%7==0)output_width[sample%16]=1'bx;
  input_channels=(sample%2)==0?group_channels:16'($random);
  group_offset=(sample%3)==0?16'($random):16'd0;
  dilation_width=(sample%5)==0?16'($random):16'd1;
  if(sample%17==0)input_channels[sample%16]=1'bx;
  if(sample%19==0)group_offset[sample%16]=1'bz;
  if(sample%23==0)dilation_width[sample%16]=1'bx;
  cfg.output_w=output_width;cfg.group_c=group_channels;cfg.kernel_w=kernel_width;
  cfg.input_c=input_channels;cfg.group_offset=group_offset;cfg.dilation_w=dilation_width;
  if(sample%11==0)cfg_valid=1'bx;
  if(sample%13==0)cfg_ready=1'bz;
  if(sample%127==0)rst_n=0;
  #1;clk=1;#1;
  if(equivalent!==1'b1)$fatal(1,"saved shift relation sample=%0d",sample);
  clk=0;rst_n=1;
 end
 $display("DECODE_SHIFT_EVENT_PASS cycles=30000 comparisons=180000");$finish;
 end
endmodule
''')
binary=a.out/'decode_shift_event.vvp'
subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb','-o',str(binary),str(package),str(sv),str(bench)],check=True,capture_output=True)
r=subprocess.run(['/home/agent/.local/bin/vvp',str(binary)],check=True,capture_output=True,text=True)
(a.out/'decode_shift_event.log').write_text(r.stdout+r.stderr)
assert 'comparisons=180000'in r.stdout
assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
report={'passed':True,'source_sha256':digest,'configuration_fields':['output_w','group_c','kernel_w','input_c','group_offset','dilation_w'],
 'binary_input_constraints':[],'reset_steps':2,'unbounded_induction_steps':1,
 'four_state_cycles':30000,'four_state_comparisons':180000,
 'properties':['Saved shift equals power_shift of the corresponding saved configuration field at every clock.',
 'Configuration reset and update use the original configuration enable and edge.',
 'The saved group mask and selected channel result preserve the full truncated arithmetic expression.',
 'The saved contiguous-channel condition equals the corresponding complete expression of the saved configuration.'],
 'proof_source_sha256':hashlib.sha256(sv.read_bytes()).hexdigest(),
 'proof_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
(a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
print(report)
