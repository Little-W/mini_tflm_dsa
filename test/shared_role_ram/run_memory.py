#!/usr/bin/env python3
"""使用真实 RAM 数组检查全部存储内容、连续读取返回及四态访问行为。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/buffers/ia_ps_channel_ram.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='19d62e18')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=8192)
    args = parser.parse_args()
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=True)
    helper = Path(__file__).with_name('run_formal.py')
    spec = importlib.util.spec_from_file_location('shared_role_formal', helper)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    reference = subprocess.check_output(['git','show',args.reference+':'+SOURCE],cwd=ROOT,text=True)
    current = (ROOT/SOURCE).read_text()
    model = module.miter(reference,current)
    model = model.replace(module.MODELS, (ROOT/'rtl/common/regfile.v').read_text()+
                          (ROOT/'rtl/npu/buffers/ia_ps_role_ram.sv').read_text())
    model = model.replace('proof_common_memory #(', 'regfile #(')
    model = re.sub(r'^\s*input wire logic \[16:0\]\[127:0\] proof_words,.*\n', '', model, flags=re.M)
    model = model.replace(' input logic [16:0][127:0] proof_words,\n','')
    model = re.sub(r'\.i_proof_word\(proof_words\[[^\]]+\]\), ', '', model)
    model = model.replace(',.proof_words(proof_words)', '')
    model = model.replace(" = 1'b1 /* 允许当前计算通路访问共享存储 */", ' /* 允许当前计算通路访问共享存储 */')
    model = model.replace(" = 128'd0 /* 预先选择的共享物理存储块写数据 */", ' /* 预先选择的共享物理存储块写数据 */')
    model = re.sub(r"(input\s+(?:wire\s+)?logic\s+i_access_enable)\s*=\s*1'b1", r'\1', model)
    model = model.replace('always_comb', 'always @*')
    for prefix,count in [('ia',2),('ps',4)]:
        model = model.replace(f'input logic [p_addr_width-1:0] i_{prefix}_read_addr[{count}],i_{prefix}_write_addr[{count}],',
            f'input logic [p_addr_width-1:0] i_{prefix}_read_addr[{count}],\n input logic [p_addr_width-1:0] i_{prefix}_write_addr[{count}],')
    bench = r'''
module comparison #(parameter p_bank_bytes=2048,p_total_bytes=14336,p_shared_write_stage=1,p_paired_ia_ports=0,
 p_addr_width=$clog2(p_total_bytes/16),p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1))(
 input logic clk,rst_n,input integer sample,output integer checks=0);
 localparam ROWS=p_bank_bytes/16, CHUNK=ROWS/4, BANKS=p_total_bytes/p_bank_bytes;
 localparam MAX_IA=BANKS>=8?4:2;
 reg i_access_enable=0,i_cfg_valid=0;
 reg [p_bank_count_width-1:0] i_cfg_ia_banks=1;
 reg [1:0] i_ia_read_en=0,i_ia_write_en=0;
 reg [p_addr_width-1:0] i_ia_read_addr[2],i_ia_write_addr[2];
 reg [127:0] i_ia_write_data[2],i_ia_shared_write_data;
 reg [15:0] i_ia_write_mask[2];
 reg [3:0] i_ps_read_en=0,i_ps_write_en=0;
 reg [p_addr_width-1:0] i_ps_read_addr[4],i_ps_write_addr[4];
 reg [127:0] i_ps_write_data[4];
 wire equivalent;
 integer unsigned rng=32'h16a74359;
 integer cfg=1,phase=0,arow,brow,bank,limit;
 integer reads=0,writes=0,parallel_ops=0,pauses=0,holds=0,faults=0,configurations=0;
 role_miter #(.p_bank_bytes(p_bank_bytes),.p_total_bytes(p_total_bytes),
   .p_shared_write_stage(p_shared_write_stage),.p_paired_ia_ports(p_paired_ia_ports),
   .p_ia_nonempty_writes(p_paired_ia_ports)) dut(.*);
 function automatic [31:0] random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic [1:0] value);
  case(value)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 always @(negedge clk)begin
  phase=sample%257;
  i_access_enable=1;i_cfg_valid=0;
  i_ia_read_en=0;i_ia_write_en=0;i_ps_read_en=0;i_ps_write_en=0;
  if(phase==0)begin
   cfg=1<<((sample/257)%(MAX_IA==4?3:2));
   i_cfg_ia_banks=p_bank_count_width'(cfg);
   if((sample/257)%11==10)i_cfg_ia_banks=p_bank_count_width'(3);
   i_cfg_valid=1;i_access_enable=0;
  end else begin
   limit=(BANKS-cfg)*CHUNK;
   for(integer p=0;p<4;p++)begin
    arow=random_word()%limit;brow=(arow+1)%limit;
    i_ps_read_en[p]=phase>4 && (p+sample)%3!=0;
    i_ps_write_en[p]=phase<192 && (p+sample)%4!=0;
    i_ps_read_addr[p]=p_addr_width'(arow);
    i_ps_write_addr[p]=p_addr_width'(brow);
    i_ps_write_data[p]={random_word(),random_word(),random_word(),random_word()};
    if(p<2)begin
     bank=cfg==1?0:p;
     arow=random_word()%ROWS;brow=(arow+1)%ROWS;
     i_ia_read_en[p]=phase>4 && (sample+p)%3!=0 && (p==0 || cfg>1);
     i_ia_write_en[p]=phase<192 && (sample+p)%4!=0 && (p==0 || cfg>1);
     i_ia_read_addr[p]=p_addr_width'(arow*cfg+bank);
     i_ia_write_addr[p]=p_addr_width'(brow*cfg+bank);
     i_ia_write_mask[p]=16'(random_word());
     i_ia_write_data[p]={random_word(),random_word(),random_word(),random_word()};
    end
   end
   i_ia_shared_write_data={random_word(),random_word(),random_word(),random_word()};
   if(phase%17==0)i_access_enable=0;
   if(phase>208)begin
    i_access_enable=four(2'(random_word()));
    for(integer p=0;p<4;p++)begin
     i_ps_read_en[p]=four(2'(random_word()));i_ps_write_en[p]=four(2'(random_word()));
     i_ps_write_data[p][sample%128]=four(2'(random_word()));
     if(p<2)begin
      i_ia_read_en[p]=four(2'(random_word()));i_ia_write_en[p]=four(2'(random_word()));
      i_ia_write_mask[p][sample%16]=four(2'(random_word()));
      i_ia_write_data[p][sample%128]=four(2'(random_word()));
     end
    end
    if(phase%3==0)i_ia_read_addr[0][sample%p_addr_width]=four(2'(random_word()));
    if(phase%5==0)i_ps_write_addr[2][sample%p_addr_width]=four(2'(random_word()));
   end
   if(phase==240)begin
    i_access_enable=1;i_ia_write_en[0]=1;i_ia_read_en[0]=1;
    i_ia_write_mask[0]=16'hffff;i_ia_write_addr[0]=i_ia_read_addr[0];
   end
  end
 end
 for(genvar b=1;b<MAX_IA;b++)begin:g_bank
  for(genvar c=0;c<4;c++)begin:g_channel
   always @(posedge clk)begin
    #1;
    for(integer row=0;row<CHUNK;row++)begin
     if(dut.u_reference.g_shared_bank[b].g_channel[c].u_ram.mem[row] !==
        dut.u_current.g_shared_bank[b].g_channel[c].g_qualified_response.u_ram.memory[row])
       $fatal(1,"Shared memory differs size=%0d banks=%0d cycle=%0d bank=%0d channel=%0d row=%0d",p_bank_bytes,BANKS,sample,b,c,row);
    end
   end
  end
 end
 always @(posedge clk)begin
  if(dut.u_current.memory_access_enabled)begin
   reads+=$countones(i_ia_read_en)+$countones(i_ps_read_en);
   writes+=$countones(i_ia_write_en)+$countones(i_ps_write_en);
   if((|i_ia_read_en || |i_ps_read_en) && (|i_ia_write_en || |i_ps_write_en))parallel_ops++;
  end
  if(!i_access_enable)pauses++;
  if(i_cfg_valid)configurations++;
  #1;
  if(dut.reference_fault !== dut.current_fault)$fatal(1,"Capacity status differs cycle=%0d",sample);
  for(integer p=0;p<2;p++)begin
   if(dut.ia_seen[p] && !dut.current_fault)begin
    if(dut.reference_ia_data[p] !== dut.current_ia_data[p])
      $fatal(1,"IA return differs size=%0d banks=%0d cycle=%0d port=%0d",p_bank_bytes,BANKS,sample,p);
    if(!i_ia_read_en[p])holds++;
   end
  end
  for(integer p=0;p<4;p++)begin
   if(dut.ps_seen[p] && !dut.current_fault)begin
    if(dut.reference_ps_data[p] !== dut.current_ps_data[p])
      $fatal(1,"PS return differs size=%0d banks=%0d cycle=%0d port=%0d",p_bank_bytes,BANKS,sample,p);
    if(!i_ps_read_en[p])holds++;
   end
  end
  if(dut.current_fault)faults++;
  checks++;
 end
 final begin
  if(reads<500 || writes<500 || parallel_ops<100 || pauses<100 || holds<500 || configurations<16 || faults<10)
    $fatal(1,"Insufficient memory activity");
  $display("ROLE_MEMORY_PROFILE_PASS size=%0d banks=%0d stage=%0d paired=%0d reads=%0d writes=%0d parallel=%0d pauses=%0d holds=%0d configurations=%0d faults=%0d checks=%0d",
   p_bank_bytes,BANKS,p_shared_write_stage,p_paired_ia_ports,reads,writes,parallel_ops,pauses,holds,configurations,faults,checks);
 end
endmodule
module tb;
 reg clk=1,rst_n=0;integer sample;
'''
    profiles=[(2048,6,0,0),(2048,8,1,0),(8192,7,1,0),(8192,7,1,1),(8192,9,0,0)]
    for n,(size,banks,stage,paired) in enumerate(profiles):
        bench += f'wire integer checks{n};comparison #(.p_bank_bytes({size}),.p_total_bytes({size*banks}),.p_shared_write_stage({stage}),.p_paired_ia_ports({paired})) u{n}(clk,rst_n,sample,checks{n});\n'
    bench += f'''initial begin
 for(sample=0;sample<{args.cycles};sample++)begin
  rst_n=(sample>1 && sample%4099!=0);#2;clk=0;#2;clk=1;#2;
 end
 $display("ROLE_MEMORY_ALL_PASS");$finish;
end
endmodule
'''
    source=out/'memory.sv';source.write_text(model+'\n'+bench)
    binary=out/'memory.vvp'
    for label,command in [('compile',['iverilog','-g2012','-DXILINX_FPGA=1','-s','tb','-o',str(binary),str(source)]),('run',['vvp',str(binary)])]:
        with (out/(label+'.log')).open('w') as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
    log=(out/'run.log').read_text()
    assert 'ROLE_MEMORY_ALL_PASS' in log and log.count('ROLE_MEMORY_PROFILE_PASS')==len(profiles)
    assert current==(ROOT/SOURCE).read_text()
    report=dict(passed=True,reference=args.reference,cycles_per_profile=args.cycles,
        profiles=profiles,source_sha256=digest(ROOT/SOURCE),role_sha256=digest(ROOT/'rtl/npu/buffers/ia_ps_role_ram.sv'),
        test_sha256=digest(Path(__file__)),testbench_sha256=digest(source),log_sha256=digest(out/'run.log'),
        checks='每个共享 RAM 字在每拍后比较；当前配置首次有效读取后持续比较返回值；复位、暂停、配置切换、非法访问、四态控制及掩码')
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(log,flush=True)


if __name__=='__main__':main()
