#!/usr/bin/env python3
"""验证共享存储所有命令、状态、实际存储内容及每个周期的返回值。"""
import argparse, ast, hashlib, json, re, shlex, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/buffers/ia_ps_channel_ram.sv'
HELPERS=['rtl/npu/buffers/ps_channel_write_enable.sv', 'rtl/npu/buffers/ps_channel_request_fault.sv', 'rtl/npu/buffers/ia_channel_segment_enable.sv']
PROFILES=[(2048,6,0,0,0,0),(2048,8,1,0,0,1),(8192,7,1,1,1,1),(8192,7,0,0,0,0),(8192,9,0,0,0,1)]
FIELDS=['clk','rst_n','i_access_enable','i_cfg_valid','i_cfg_ia_banks','i_ia_read_en','i_ia_write_en','i_ia_read_addr','i_ia_write_addr','i_ia_write_data','i_ia_shared_write_data','i_ia_write_mask','i_ps_read_en','i_ps_write_en','i_ps_read_addr','i_ps_write_addr','i_ps_write_data']
PORTS='''input logic clk,rst_n,i_access_enable,i_cfg_valid,
 input logic [p_bank_count_width-1:0] i_cfg_ia_banks,
 input logic [1:0] i_ia_read_en,i_ia_write_en,
 input logic [p_addr_width-1:0] i_ia_read_addr[2],
 input logic [p_addr_width-1:0] i_ia_write_addr[2],
 input logic [127:0] i_ia_write_data[2],i_ia_shared_write_data,
 input logic [15:0] i_ia_write_mask[2],
 input logic [3:0] i_ps_read_en,i_ps_write_en,
 input logic [p_addr_width-1:0] i_ps_read_addr[4],
 input logic [p_addr_width-1:0] i_ps_write_addr[4],
 input logic [127:0] i_ps_write_data[4],
 output logic equivalent'''
MODELS='''// 任意返回数据在两个实例之间共用，所有实际存储命令独立逐位比较。
module proof_regfile #(parameter p_data_width=128,p_depth=128,p_addr_width=$clog2(p_depth),p_write_unit=8)(
 input logic clk,i_wr_en,i_rd_en,input logic [p_addr_width-1:0] i_wr_addr,i_rd_addr,
 input logic [p_data_width-1:0] i_wr_data,input logic [p_data_width/p_write_unit-1:0] i_wr_mask,
 input logic [255:0] i_proof_word,output logic [p_data_width-1:0] o_rd_data);
 assign o_rd_data=i_proof_word[127:0];
endmodule
module proof_role #(parameter p_depth=128,p_addr_width=$clog2(p_depth))(
 input logic clk,i_access_enable,i_a_enable,i_a_write,i_b_enable,i_b_write,
 input logic i_a_read_allowed=1'b1,
 input logic [p_addr_width-1:0] i_a_addr,i_b_addr,
 input logic [127:0] i_a_data,i_b_data,input logic [15:0] i_a_mask,
 input logic [255:0] i_proof_word,output logic [127:0] o_a_data,o_b_data);
 assign o_a_data=i_proof_word[127:0];assign o_b_data=i_proof_word[255:128];
endmodule
'''
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def instrument(s,label,abstract):
 if label=='reference':
  s=s.replace('.i_a_enable(port_a_enable), .i_a_write(ia_write_qualified),',
              ".i_a_enable(port_a_enable), .i_a_read_allowed(1'b1), .i_a_write(ia_write_qualified),")
 s=s.replace('module ia_ps_channel_ram #(',f'module channel_{label} #(',1)
 if abstract:
  s=s.replace('    input  wire logic clk','    input wire logic [16:0][255:0] proof_words, // 逐周期自由的同步存储返回数据\n    input  wire logic clk',1)
  blocks=[('regfile #(.p_data_width(128), .p_depth(p_rows)','0'),('regfile #(.p_data_width(128), .p_depth(p_chunk_rows)','1+4*(bank-1)+channel'),('regfile #(.p_data_width(128), .p_depth(p_fixed_rows)','1+4*(p_max_ia_banks-1)+channel'),('ia_ps_role_ram #(','1+4*(bank-1)+channel')]
  for start,index in blocks:
   position=s.index('.clk(clk)',s.index(start));s=s[:position]+f'.i_proof_word(proof_words[{index}]), '+s[position:]
  s=s.replace('regfile #(','proof_regfile #(').replace('ia_ps_role_ram #(','proof_role #(')
 return s

def pair(path,kind,depth):
 fields=['i_wr_en','i_rd_en','i_wr_addr','i_rd_addr','i_wr_mask','i_wr_data'] if kind=='reg' else ['i_access_enable','i_a_write','i_a_addr','i_a_data','i_a_mask','i_b_enable','i_b_write','i_b_addr','i_b_data']
 a,b='u_reference.'+path,'u_current.'+path
 left=[a+'.'+field for field in fields]
 right=[b+'.'+field for field in fields]
 if kind=='role':
  # 读取请求与独立资格共同决定物理端口的读取使能。
  left.append(a+'.i_a_enable && '+a+'.i_a_read_allowed')
  right.append(b+'.i_a_enable && '+b+'.i_a_read_allowed')
 result='assign commands_equal={'+','.join(left)+'} === {'+','.join(right)+'};\n'
 mem='mem' if kind=='reg' else 'memory'
 result+='''`ifdef CHECK_MEMORY
 always @(posedge clk)begin
  #1;
  for(integer row=0;row<'''+depth+''';row++)
   if('''+a+'.'+mem+'[row] !== '+b+'.'+mem+'''[row])
    $fatal(1,"Shared storage contents differ row=%0d",row);
 end
`endif
'''
 return result

def miter(reference,current,abstract):
 text=instrument(reference,'reference',abstract)+instrument(current,'current',abstract)
 if abstract:text+=MODELS
 text+='''\n// 所有物理命令、公开返回和配置状态均逐周期比较。
module channel_miter #(
 parameter p_bank_bytes=8192,p_total_bytes=57344,p_shared_write_stage=1,p_paired_ia_ports=1,
 parameter p_ia_nonempty_writes=1,p_allow_inactive_return_updates=1,
 parameter p_addr_width=$clog2(p_total_bytes/16),p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1)
)('''+('input logic [16:0][255:0] proof_words,\n' if abstract else '')+PORTS+''');
 localparam MAX_IA=p_total_bytes/p_bank_bytes>=8?4:2;
 localparam ROWS=p_bank_bytes/16,CHUNK=ROWS/4,FIXED=(p_total_bytes/p_bank_bytes-MAX_IA)*CHUNK;
 localparam INDEPENDENT=
`ifdef XILINX_FPGA
 p_allow_inactive_return_updates;
`else
 0;
`endif
 wire [127:0] reference_ia_data[2],current_ia_data[2],reference_ps_data[4],current_ps_data[4];
 wire reference_fault,current_fault;
 wire [1:0] ia_equal;
 wire [3:0] ps_equal,fixed_commands;
 wire [MAX_IA-2:0] chunk_equal;
 wire [MAX_IA-2:0][3:0] shared_commands;
 wire ia_commands;
'''
 parameters=['p_bank_bytes','p_total_bytes','p_shared_write_stage','p_paired_ia_ports','p_ia_nonempty_writes','p_allow_inactive_return_updates']
 for label in ['reference','current']:
  connections=[f'.{n}({n})' for n in FIELDS+(['proof_words'] if abstract else [])]
  connections += [f'.o_capacity_fault({label}_fault)',f'.o_ia_read_data({label}_ia_data)',f'.o_ps_read_data({label}_ps_data)']
  text+=f'channel_{label} #('+','.join(f'.{n}({n})' for n in parameters)+f') u_{label}('+','.join(connections)+');\n'
 text+='''for(genvar p=0;p<2;p++)begin:g_ia
 assign ia_equal[p]=(reference_ia_data[p] === current_ia_data[p]) &&
  (u_reference.ia_return_bank_q[p] === u_current.ia_return_bank_q[p]);
 end
 for(genvar p=0;p<4;p++)begin:g_ps
 assign ps_equal[p]=(reference_ps_data[p] === current_ps_data[p]) &&
  (u_reference.ps_return_select_q[p] === u_current.ps_return_select_q[p]);
 wire commands_equal;
'''+pair('g_fixed_channel[p].u_ram','reg','FIXED')+'''assign fixed_commands[p]=commands_equal;
 end
 begin:g_ia_commands
 wire commands_equal;
'''+pair('u_ia_ram','reg','ROWS')+'''assign ia_commands=commands_equal;
 end
 for(genvar bank=1;bank<MAX_IA;bank++)begin:g_shared
 assign chunk_equal[bank-1]=u_reference.g_shared_bank[bank].return_chunk_q === u_current.g_shared_bank[bank].return_chunk_q;
 for(genvar channel=0;channel<4;channel++)begin:g_channel
 if(INDEPENDENT)begin:g_independent
 wire commands_equal;
'''+pair('g_shared_bank[bank].g_channel[channel].g_qualified_response.u_ram','role','CHUNK')+'''assign shared_commands[bank-1][channel]=commands_equal;
 end else begin:g_held
 wire commands_equal;
'''+pair('g_shared_bank[bank].g_channel[channel].g_held_response.u_ram','reg','CHUNK')+'''assign shared_commands[bank-1][channel]=commands_equal;
 end
 end
 end
 assign equivalent=(reference_fault === current_fault) &&
 (u_reference.configured_q === u_current.configured_q) &&
 (u_reference.ia_banks_q === u_current.ia_banks_q) &&
 (u_reference.ia_layout_banks === u_current.ia_layout_banks) &&
 (u_reference.access_fault === u_current.access_fault) &&
 (&ia_equal) && (&ps_equal) && (&fixed_commands) && (&shared_commands) && (&chunk_equal) && ia_commands;
endmodule
'''
 return text

def execute(command,log,timeout=300):
 with log.open('w') as output:subprocess.run(list(map(str,command)),cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True,timeout=timeout)
 return log.read_text()

def bench(cycles):
 path=ROOT/'test/shared_role_ram/run_memory.py'
 tree=ast.parse(path.read_text())
 values=[n.value.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='bench' for t in n.targets) and isinstance(n.value,ast.Constant)]
 assert len(values)==1
 s=values[0]
 s=s.replace('p_addr_width=$clog2(p_total_bytes/16)', 'p_ia_nonempty_writes=0,p_allow_inactive_return_updates=1,p_addr_width=$clog2(p_total_bytes/16)')
 s=s.replace('role_miter #(', 'channel_miter #(').replace('.p_ia_nonempty_writes(p_paired_ia_ports))','.p_ia_nonempty_writes(p_ia_nonempty_writes),.p_allow_inactive_return_updates(p_allow_inactive_return_updates))')
 a=s.index(' for(genvar b=1;b<MAX_IA;b++)');b=s.index(' always @(posedge clk)begin\n  if(dut.u_current.memory_access_enabled)',a)
 s=s[:a]+s[b:]
 a=s.index('  if(dut.reference_fault !== dut.current_fault)');b=s.index('  if(dut.current_fault)faults++;',a)
 s=s[:a]+'''  if(equivalent!==1'b1)$fatal(1,"Channel command, state or return differs size=%0d banks=%0d sample=%0d",p_bank_bytes,BANKS,sample);
  if(!( |i_ps_read_en) && !(|i_ia_read_en))holds++;
'''+s[b:]
 s=s.replace(' || holds<500','').replace('ROLE_MEMORY_','CHANNEL_MEMORY_')
 for n,(size,banks,stage,paired,nonempty,allow) in enumerate(PROFILES):
  s+=f'wire integer checks{n};comparison #(.p_bank_bytes({size}),.p_total_bytes({size*banks}),.p_shared_write_stage({stage}),.p_paired_ia_ports({paired}),.p_ia_nonempty_writes({nonempty}),.p_allow_inactive_return_updates({allow})) u{n}(clk,rst_n,sample,checks{n});\n'
 s+=f'''initial begin
 for(sample=0;sample<{cycles};sample++)begin
  rst_n=(sample>1 && sample%4099!=0);#2;clk=0;#2;clk=1;#2;
 end
 $display("CHANNEL_MEMORY_ALL_PASS");$finish;
end
endmodule
'''
 return s

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',default='d9f7f15a');p.add_argument('--out',type=Path,required=True);p.add_argument('--modes',nargs='+',default=['generic','fpga'],choices=['generic','fpga']);p.add_argument('--skip-memory',action='store_true');p.add_argument('--memory-only',action='store_true');p.add_argument('--cycles',type=int,default=8192);a=p.parse_args()
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 reference=subprocess.check_output(['git','show',a.reference+':'+SOURCE],cwd=ROOT,text=True)
 current=(ROOT/SOURCE).read_text();hashes={n:digest(ROOT/n) for n in [SOURCE,*HELPERS,'rtl/npu/buffers/ia_ps_role_ram.sv','rtl/common/regfile.v','test/shared_role_ram/run_memory.py']}
 proof=out/'commands.sv';proof.write_text(miter(reference,current,True));records=[];memory=[]
 for mode in a.modes:
  flags=['-USYNTHESIS','-UXILINX_FPGA'] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
  if not a.memory_only:
   for profile in PROFILES:
    size,banks,stage,paired,nonempty,allow=profile;label=mode+'_'+'_'.join(map(str,profile))
    params=dict(p_bank_bytes=size,p_total_bytes=size*banks,p_shared_write_stage=stage,p_paired_ia_ports=paired,p_ia_nonempty_writes=nonempty,p_allow_inactive_return_updates=allow)
    commands='read_slang --top channel_miter '+shlex.join(flags+[f'-G{k}={v}' for k,v in params.items()]+[str(proof)]+[str(ROOT/n) for n in HELPERS])+'\nprep -top channel_miter -flatten\nasync2sync\nopt_clean\nsat -verify -tempinduct -seq 2 -maxsteps 8 -set-at 1 rst_n 0 -prove equivalent 1\n'
    script,log=out/(label+'.ys'),out/(label+'.log');script.write_text(commands)
    text=execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
    assert 'Induction step proven: SUCCESS!' in text
    records.append(dict(mode=mode,parameters=params,passed=True,log_sha256=digest(log)));print('CHANNEL_COMMAND_PASS',label,flush=True)
  if not a.skip_memory:
   model=miter(reference,current,False)+(ROOT/'rtl/common/regfile.v').read_text()+(ROOT/'rtl/npu/buffers/ia_ps_role_ram.sv').read_text()+bench(a.cycles)
   model=re.sub(r"(input\s+(?:wire\s+)?logic\s+(?:i_access_enable|i_a_read_allowed))\s*=\s*1'b1",r'\1',model)
   model=model.replace(" = 128'd0 /* 预先选择的共享物理存储块写数据 */",' /* 预先选择的共享物理存储块写数据 */').replace('always_comb','always @*').replace(' begin:g_ia_commands', ' if(1)begin:g_ia_commands')
   source=out/(mode+'_memory.sv');source.write_text(model);binary=out/(mode+'_memory.vvp');log=out/(mode+'_memory.log')
   execute(['iverilog','-g2012','-DCHECK_MEMORY=1']+([] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1'])+['-s','tb','-o',binary,source]+[ROOT/n for n in HELPERS],out/(mode+'_compile.log'))
   text=execute(['vvp',binary],log);assert 'CHANNEL_MEMORY_ALL_PASS' in text;assert text.count('CHANNEL_MEMORY_PROFILE_PASS')==len(PROFILES)
   memory.append(dict(mode=mode,passed=True,profiles=PROFILES,cycles_per_profile=a.cycles,log_sha256=digest(log),testbench_sha256=digest(source)));print(text,flush=True)
 assert hashes=={n:digest(ROOT/n) for n in hashes}
 (out/'summary.json').write_text(json.dumps(dict(passed=True,reference=a.reference,source_sha256=hashes,command_proofs=records,memory_tests=memory,input_constraints='首次采样复位，随后全部输入与复位自由',proof_scope='各物理存储读写的有效使能、地址、数据及掩码逐位相等；任意独立返回数据下的公开返回、配置和选择状态逐周期相等',test_sha256=digest(Path(__file__))),ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
