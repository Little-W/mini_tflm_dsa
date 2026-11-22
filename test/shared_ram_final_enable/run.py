#!/usr/bin/env python3
"""验证共享 RAM 最终访问使能的命令、返回状态与四态传播。"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, timeout=180):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--tool-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--reference', default='9d75f75a34b5d0d57fffe0eb6f7d5a29769308d6')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); root = args.tool_root.resolve(); out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/buffers/ia_ps_shared_ram.sv'
    current = (args.source_root/relative).read_text()
    reference = subprocess.check_output(['git','show',args.reference+':'+relative],cwd=root,text=True)
    helper = root/'test/shared_ram_access_depth/run_formal.py'
    spec = importlib.util.spec_from_file_location('shared_access_model',helper)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model = module.miter(reference,current)
    for port,count in [('i_ia_read_en',2),('i_ia_write_en',2),('i_ps_read_en',4),('i_ps_write_en',4)]:
        model=model.replace(f'.{port}({port} & {{{count}{{i_access_enable}}}})',f'.{port}({port})')
    marker='channel_reference #('
    pos=model.index(marker);before,after=model[:pos],model[pos:]
    after=after.replace('.clk(clk), .rst_n(rst_n), .i_cfg_valid(i_cfg_valid),',
                        '.clk(clk), .rst_n(rst_n), .i_access_enable(i_access_enable), .i_cfg_valid(i_cfg_valid),',1)
    model=before+after
    target=out/'commands.sv';target.write_text(model)
    results=[]
    for size,banks in [(2048,6),(2048,8),(8192,7),(8192,9)]:
        for stage in [0,1]:
            label=f'b{size}_n{banks}_s{stage}';script=out/(label+'.ys');log=out/(label+'.log')
            script.write_text(shlex.join(['read_slang','--top','access_miter',f'-Gp_bank_bytes={size}',
                                         f'-Gp_total_bytes={size*banks}',f'-Gp_shared_write_stage={stage}',str(target)])+'\n'
                              'prep -top access_miter -flatten\nasync2sync\nopt_clean\n'
                              'sat -verify -tempinduct -seq 2 -set-at 1 rst_n 0 -prove equivalent 1\n')
            run([sys.executable,root/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
            assert 'Induction step proven: SUCCESS!' in log.read_text()
            results.append(dict(bank_bytes=size,banks=banks,shared_write_stage=stage,passed=True,log_sha256=sha(log)))
            print('SHARED_RAM_COMMANDS_PASS',label,flush=True)
    # 二态和四态检查使用同一个完整控制模型，物理 RAM 的每个命令均被观察。
    marker='module access_miter #('
    pos=model.index(marker)
    model=model[:pos]+model[pos:].replace(' == ',' === ')
    model=model.replace('always_comb','always @*').replace('input  wire logic i_access_enable = 1\'b1,','input  wire logic i_access_enable,')
    for prefix,count in [('ia',2),('ps',4)]:
        model=model.replace(f'input logic [p_addr_width-1:0] i_{prefix}_read_addr [{count}], i_{prefix}_write_addr [{count}],',
                            f'input logic [p_addr_width-1:0] i_{prefix}_read_addr [{count}],\n  input logic [p_addr_width-1:0] i_{prefix}_write_addr [{count}],')

    bench='''module comparison #(parameter p_bank_bytes=2048,p_total_bytes=14336,p_shared_write_stage=1,
 p_addr_width=$clog2(p_total_bytes/16),p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1))(
 input logic clk,rst_n,input logic [31:0] sample,output integer checks=0);
 reg i_access_enable,i_cfg_valid;reg [p_bank_count_width-1:0] i_cfg_ia_banks;
 reg [1:0] i_ia_read_en,i_ia_write_en;
 reg [p_addr_width-1:0] i_ia_read_addr[2],i_ia_write_addr[2];
 reg [127:0] i_ia_write_data[2],i_ia_shared_write_data;reg [15:0] i_ia_write_mask[2];
 reg [3:0] i_ps_read_en,i_ps_write_en;
 reg [p_addr_width-1:0] i_ps_read_addr[4],i_ps_write_addr[4];reg [127:0] i_ps_write_data[4];
 wire equivalent;integer unsigned rng=32'h716bf3ac;
 function automatic [31:0] random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic [1:0] v);
  case(v)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 access_miter #(.p_bank_bytes(p_bank_bytes),.p_total_bytes(p_total_bytes),
 .p_shared_write_stage(p_shared_write_stage)) dut(.*);
 always @(negedge clk)begin
  i_access_enable=sample%5==0?four(2'(random_word())):1'(random_word());
  i_cfg_valid=sample%5==0?four(2'(random_word())):(sample%17==0);
  i_cfg_ia_banks=p_bank_count_width'(1<<((sample/17)%3));
  if(sample%13==0)i_cfg_ia_banks[0]=four(2'(random_word()));
  for(integer p=0;p<4;p++)begin
   i_ps_read_en[p]=sample%5==0?four(2'(random_word())):1'(random_word());
   i_ps_write_en[p]=sample%5==0?four(2'(random_word())):1'(random_word());
   i_ps_read_addr[p]=p_addr_width'(random_word());i_ps_write_addr[p]=p_addr_width'(random_word());
   i_ps_write_data[p]={random_word(),random_word(),random_word(),random_word()};
   if(sample%7==0)i_ps_write_addr[p]=i_ps_read_addr[p];
   if(sample%11==0)i_ps_read_addr[p][sample%p_addr_width]=four(2'(random_word()));
   if(p<2)begin
    i_ia_read_en[p]=sample%5==0?four(2'(random_word())):1'(random_word());
    i_ia_write_en[p]=sample%5==0?four(2'(random_word())):1'(random_word());
    i_ia_read_addr[p]=p_addr_width'(random_word());i_ia_write_addr[p]=p_addr_width'(random_word());
    i_ia_write_mask[p]=16'(random_word());
    i_ia_write_data[p]={random_word(),random_word(),random_word(),random_word()};
    if(sample%7==0)i_ia_write_addr[p]=i_ia_read_addr[p];
    if(sample%11==0)begin
     i_ia_read_addr[p][sample%p_addr_width]=four(2'(random_word()));
     i_ia_write_mask[p][sample%16]=four(2'(random_word()));
    end
   end
  end
  i_ia_shared_write_data={random_word(),random_word(),random_word(),random_word()};
  #1;if(equivalent!==1'b1)$fatal(1,"Shared RAM commands differ before edge sample=%0d",sample);checks++;
 end
 always @(posedge clk)begin
  #1;if(equivalent!==1'b1)$fatal(1,"Shared RAM state differs after edge sample=%0d",sample);checks++;
 end
endmodule
module tb;reg clk=1,rst_n=0;reg [31:0] sample=0;integer count;
'''
    profiles=[(2048,6,0),(2048,8,1),(8192,7,1),(8192,9,0)]
    for i,(size,banks,stage) in enumerate(profiles):
        bench+=f'wire integer c{i};comparison #(.p_bank_bytes({size}),.p_total_bytes({size*banks}),.p_shared_write_stage({stage})) u{i}(clk,rst_n,sample,c{i});\n'
    bench+='''initial begin
 for(sample=0;sample<8192;sample++)begin
  rst_n=(sample>1 && sample%127!=0);#2;clk=0;#2;clk=1;#2;
 end
 count='''+'+'.join(f'c{i}'for i in range(len(profiles)))+''';
 $display("SHARED_RAM_FOUR_STATE_PASS comparisons=%0d",count);$finish;
end
endmodule
'''
    simulation=out/'four_state.sv';simulation.write_text(model+'\n'+bench)
    binary=out/'four_state.vvp';run(['iverilog','-g2012','-s','tb','-o',binary,simulation],out/'four_state_compile.log')
    run(['vvp',binary],out/'four_state.log',timeout=300)
    match=re.search(r'SHARED_RAM_FOUR_STATE_PASS comparisons=(\d+)',(out/'four_state.log').read_text());assert match
    assert current==(args.source_root/relative).read_text()
    report={'passed':True,'source_sha256':sha(args.source_root/relative),'reference_revision':args.reference,
            'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),'formal_profiles':results,
            'constraints':'First sampled cycle reset; all subsequent resets and inputs free',
            'four_state_profiles':len(profiles),'four_state_cycles_per_profile':8192,'four_state_comparisons':int(match[1]),
            'test_sha256':sha(Path(__file__)),'helper_sha256':sha(helper),'four_state_log_sha256':sha(out/'four_state.log')}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
