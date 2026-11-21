#!/usr/bin/env python3
"""逐周期比较完整配置检查器的四态输出。"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        result=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:raise RuntimeError(str(log))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-root','reference-root','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    rel=Path('rtl/npu/conv/vector_config_check.sv')
    original=out/'reference.sv';selected=out/'selected.sv'
    original.write_text((args.reference_root/rel).read_text().replace('module vector_config_check #(', 'module vector_config_reference #(',1))
    selected.write_text((args.source_root/rel).read_text().replace('module vector_config_check #(', 'module vector_config_selected #(',1))
    text='''module profile #(parameter integer TILE=16,MAX_TAPS=49,POOL_MAX_TAPS=256)(
 input logic clk,rst_n,start,i_input_range,
 input vector_engine_pkg::vector_engine_cfg_t cfg,
 output wire ready,output wire identical
);
 wire ready_old,done_old,error_old,ready_new,done_new,error_new;
 wire [31:0] kernel_old,positions_old,kernel_new,positions_new;
 wire [63:0] input_old,output_old,weight_old,input_new,output_new,weight_new;
 wire [32:0] ends_old[4],ends_new[4];
 wire [3:0] ends_equal;
 vector_config_reference #(.TILE(TILE),.MAX_TAPS(MAX_TAPS),.POOL_MAX_TAPS(POOL_MAX_TAPS)) reference(
 .clk,.rst_n,.start,.i_input_range,.cfg,.ready(ready_old),.done(done_old),.error(error_old),
 .kernel_count(kernel_old),.position_count(positions_old),.input_bytes(input_old),.output_bytes(output_old),
 .weight_bytes(weight_old),.o_read_end(ends_old));
 vector_config_selected #(.TILE(TILE),.MAX_TAPS(MAX_TAPS),.POOL_MAX_TAPS(POOL_MAX_TAPS)) selected(
 .clk,.rst_n,.start,.i_input_range,.cfg,.ready(ready_new),.done(done_new),.error(error_new),
 .kernel_count(kernel_new),.position_count(positions_new),.input_bytes(input_new),.output_bytes(output_new),
 .weight_bytes(weight_new),.o_read_end(ends_new));
 for(genvar i=0;i<4;i++)assign ends_equal[i]=(ends_old[i]===ends_new[i]);
 assign identical=({ready_old,done_old,error_old,kernel_old,positions_old,input_old,output_old,weight_old}===
 {ready_new,done_new,error_new,kernel_new,positions_new,input_new,output_new,weight_new})&&(&ends_equal);
 assign ready=ready_new;
endmodule
module tb;
 import vector_engine_pkg::*;
 logic clk=0,rst_n=0,start=0,i_input_range=0;
 vector_engine_cfg_t cfg;
 logic [$bits(vector_engine_cfg_t)-1:0] mutated;
 wire [5:0] ready,identical;
 integer task_index,cycle,bit_index,comparisons=0;
 integer unsigned rng=32'h73bca149;
 function automatic integer unsigned random_next;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic[1:0] value);
  case(value)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 task tick;
  #1;clk=1;#1;
  if(identical!==6'h3f)$fatal(1,"配置输出在任务%0d周期%0d不一致",task_index,cycle);
  clk=0;comparisons+=6;
 endtask
'''
    profiles=((16,49,256),(4,49,256),(64,49,256),(2,1,1),(4,7,31),(16,255,65535))
    for i,(tile,taps,pool)in enumerate(profiles):
        text+=f'profile #(.TILE({tile}),.MAX_TAPS({taps}),.POOL_MAX_TAPS({pool})) p{i}(clk,rst_n,start,i_input_range,cfg,ready[{i}],identical[{i}]);\n'
    text+='''initial begin
 cfg='0;tick();rst_n=1;
 for(task_index=0;task_index<2048;task_index++)begin
  cfg='0;cfg.op=4'(task_index%16);
  cfg.length=16;cfg.input_base=32'h1000;cfg.rhs_base=32'h20000;cfg.output_base=32'h40000;
  cfg.multiplier_base=32'h60000;cfg.shift_base=32'h70000;
  cfg.activation_min=-128;cfg.activation_max=127;
  cfg.image.input_h=16;cfg.image.input_w=16;cfg.image.input_c=16;
  cfg.image.output_h=14;cfg.image.output_w=14;
  cfg.image.kernel_h=3;cfg.image.kernel_w=3;
  cfg.image.stride_h=1;cfg.image.stride_w=1;
  cfg.image.dilation_h=1;cfg.image.dilation_w=1;
  mutated=cfg;
  if(task_index%4==1)for(bit_index=0;bit_index<$bits(vector_engine_cfg_t);bit_index++)
   if(random_next()%13==0)mutated[bit_index]=1'(random_next());
  if(task_index%4==2)for(bit_index=0;bit_index<$bits(vector_engine_cfg_t);bit_index++)
   if(random_next()%17==0)mutated[bit_index]=four(2'(random_next()));
  if(task_index%4==3)begin
   cfg.image.kernel_h=16'(random_next());cfg.image.kernel_w=16'(random_next());mutated=cfg;
  end
  cfg=mutated;start=1;cycle=0;tick();start=0;
  for(cycle=1;cycle<64;cycle++)begin
   i_input_range=four(2'(random_next()));
   if(task_index%17==0&&cycle==4)rst_n=0;else rst_n=1;
   tick();
  end
  if(ready!==6'h3f)$fatal(1,"配置检查未在规定周期内完成");
 end
 $display("CONFIG_FOUR_STATE_PASS tasks=%0d comparisons=%0d",task_index,comparisons);$finish;
end
endmodule
'''
    bench=out/'bench.sv';bench.write_text(text);exe=out/'simulation.vvp'
    dependencies=[args.source_root/'rtl/npu/conv'/p for p in('conv_im2col_pkg.sv','vector_engine_pkg.sv')]
    dependencies.append(args.source_root/'rtl/common/parallel_prefix_add.sv')
    run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb','-o',exe,*dependencies,original,selected,bench],out/'compile.log')
    run(['/home/agent/.local/bin/vvp',exe],out/'simulate.log')
    report={'passed':True,'source_sha256':sha(args.source_root/rel),'reference_sha256':sha(args.reference_root/rel),
            'profiles':[{'tile':t,'max_taps':m,'pool_max_taps':p}for t,m,p in profiles],
            'tasks_per_profile':2048,'cycle_comparisons':786438,
            'signals_checked':'All public outputs every cycle, including all four read ends',
            'test_sha256':sha(Path(__file__)),'bench_sha256':sha(bench),'log_sha256':sha(out/'simulate.log')}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
