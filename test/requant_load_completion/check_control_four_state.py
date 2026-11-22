#!/usr/bin/env python3
"""用实际配置过程和完整装载状态机逐周期检查四态控制结果。"""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
from support import ROOT, reference_root
RTL=Path('rtl/npu/writeback/vec_requant.sv')
REGISTERS=['s16_mode','serial_per_channel_q','pt_multiplier_r','pt_shift_r','activation_min_r','activation_max_r','dst_offset_r','k_r','m_r','ia_reuse_num_r','has_tiles_r','ia_reuse_mask_tile_r','mul_base_r','sh_base_r','is_mode_r','last_row_tile','last_col_tile','lane_need_q','state','load_phase','quant_params_valid','row_in_tile_cnt','rd_beats_cnt','beats_expect','cmd_busy','cmd_valid_r','cmd_base_addr_r','cmd_burst_len_m1_r','cmd_beats_expect_r','load_meta_valid','quant_need_load_r','quant_tile_idx_load_r','load_quant_req','tile_col','tile_row','load_offset','all_tiles_done']
PORTS=['dma_start','dma_is_write','dma_linear_read_mode','dma_base_addr','dma_row_stride','dma_rows_to_read','dma_burst_len_m1','dma_slot_id','dma_use_16bits','dma_lhs_zp']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def unit(path,label):
 text=path.read_text();first=text.index('\n);')+3
 stop=text.index('  // ----------------------------\n  // 逐通道参数存储',first)
 start=text.index('  // ----------------------------\n  // 主状态机与参数装载',stop)
 end=text.index('  // ----------------------------\n  // 数据通路（',start)
 body=text[first:stop]+text[start:end]
 header=f'''module control_{label} #(
 parameter integer BUS_WIDTH=64,VLEN=16,REG_WIDTH=32,MAX_IA_REUSE=32,
 parameter integer ENABLE_PER_CHANNEL=1,ENABLE_IS_MODE=1,
 parameter bit ENABLE_S16=1,
 parameter integer p_compute_lanes=2,p_input_rows=VLEN*MAX_IA_REUSE,
 parameter bit p_parameter_output=1
)(
 input logic clk,rst_n,init_cfg,cfg_per_channel,cfg_dataflow_mode,cfg_s16,
 input logic signed [31:0] activation_min_in,activation_max_in,dst_offset_in,multiplier_in,shift_in,
 input logic [31:0] k,m,ia_reuse_num_in,
 input logic load_quant_granted,dma_raw_valid,
 input logic i_row_consume,i_tile_done,
 output wire [4095:0] observed
);
 logic load_quant_req,quant_params_valid,dma_start,dma_is_write,dma_linear_read_mode,dma_slot_id,dma_use_16bits;
 logic [REG_WIDTH-1:0] dma_base_addr,dma_row_stride,dma_rows_to_read;
 logic signed [REG_WIDTH-1:0] dma_lhs_zp;
 logic [7:0] dma_burst_len_m1;
 logic row_consume_valid,row_consume_tile_done;
 assign row_consume_valid=i_row_consume;
 assign row_consume_tile_done=i_tile_done;
'''
 joined=','.join(REGISTERS+PORTS)
 return header+body+f'\n localparam int observed_width=16 + 2 + 5*TILE_CNT_W + 4*VLEN_CNT_W + 5*REG_WIDTH + 2*8 + 14*32;\n assign observed={{{joined}}};\nendmodule\n'
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--source-root',type=Path,default=ROOT);parser.add_argument('--reference-root',type=Path);args=parser.parse_args()
 out=args.out.resolve();out.mkdir(parents=True,exist_ok=True);paths=[];hashes={}
 current=args.source_root.resolve();reference=args.reference_root.resolve() if args.reference_root else reference_root(out/'reference',current)
 roots={'reference':reference,'candidate':current}
 for label,source_root in roots.items():
  source=source_root/RTL;helper=source_root/'rtl/common/parallel_prefix_add.sv';hashes[label]={'rtl':sha(source),'helper':sha(helper)};p=out/(label+'.sv')
  text=unit(source,label)+helper.read_text();text=re.sub(r'\bparallel_prefix_add\b','parallel_prefix_add_'+label,text);p.write_text(text);paths.append(p)
 tb=out/'tb.sv';tb.write_text('''module tb;
 logic clk=0,rst_n=0,init_cfg=0,cfg_per_channel=1,cfg_dataflow_mode=0,cfg_s16=0;
 logic signed [31:0] activation_min_in=-128,activation_max_in=127,dst_offset_in=0,multiplier_in=32'h10000,shift_in=32'h20000;
 logic [31:0] k=0,m=0,ia_reuse_num_in=1;
 logic load_quant_granted=0,dma_raw_valid=0,i_row_consume=0,i_tile_done=0;
 wire [4095:0] expected[3],observed[3];
 logic [31:0] seed=32'hbaf104e9;
 integer checks=0,more=0,commands=0,completed=0,reconfigured_busy=0,reset_busy=0,unknown_cycles=0;
 for(genvar profile=0;profile<3;profile++)begin:g_profile
  localparam V=(profile==0)?4:16,B=(profile==0)?32:64,L=(profile==1)?2:V,R=(profile==0)?2:32;
  control_reference #(.VLEN(V),.BUS_WIDTH(B),.p_compute_lanes(L),.MAX_IA_REUSE(R)) u_reference(.*,.observed(expected[profile]));
  control_candidate #(.VLEN(V),.BUS_WIDTH(B),.p_compute_lanes(L),.MAX_IA_REUSE(R)) u_candidate(.*,.observed(observed[profile]));
 end
 function automatic [31:0] random_word;
  seed=seed*32'd1664525+32'd1013904223;random_word={seed[15:0],seed[31:16]} ^ seed;
 endfunction
 task automatic compare;
  for(integer profile=0;profile<3;profile++)begin
   if(expected[profile]!==observed[profile])$fatal(1,"Control differs cycle=%0d profile=%0d",checks/6,profile);
   checks++;
  end
 endtask
 initial begin
  for(integer sample=0;sample<16384;sample++)begin
   clk=0;
   rst_n=1;init_cfg=0;
   load_quant_granted=random_word();dma_raw_valid=random_word();
   i_row_consume=(random_word()&7)==0;i_tile_done=(random_word()&7)==0;
   if(sample%128==0)begin
    rst_n=0;
    k=1+random_word()%96;m=1+random_word()%48;ia_reuse_num_in=1<<(sample/128%4);
    cfg_per_channel=(sample/128%8)!=0;cfg_dataflow_mode=1'(sample/128);cfg_s16=1'(sample/256);
    if(sample/128%8==3)k[(sample/1024)%32]=1'bx;
    if(sample/128%8==5)m[(sample/1024)%32]=1'bz;
    if(sample/128%8==7)ia_reuse_num_in[(sample/1024)%8]=1'bx;
   end else if(sample%128==1) init_cfg=1;
   else if(sample%128==70 && sample/128%7==5) init_cfg=1;
   else if(sample%128==66 && sample/128%11==0) rst_n=0;
   else if(sample%128>2)begin
    case(sample%29)
     0:load_quant_granted=1'bx;
     1:load_quant_granted=1'bz;
     2:dma_raw_valid=1'bx;
     3:dma_raw_valid=1'bz;
     4:i_row_consume=1'bx;
     5:i_tile_done=1'bz;
     6:init_cfg=1'bx;
     7:rst_n=1'bz;
     default:begin end
    endcase
   end
   #1;compare();
   if((^{rst_n,init_cfg,load_quant_granted,dma_raw_valid,i_row_consume,i_tile_done,k,m,ia_reuse_num_in})===1'bx)unknown_cycles++;
   if(init_cfg===1'b1 && g_profile[1].u_reference.cmd_busy===1'b1)reconfigured_busy++;
   if(rst_n===1'b0 && g_profile[1].u_reference.cmd_busy===1'b1)reset_busy++;
   if(g_profile[1].u_reference.dma_start===1'b1)commands++;
   if(g_profile[1].u_reference.quant_params_valid===1'b1)completed++;
   if(g_profile[1].u_reference.rsp_hskd===1'b1 &&
      (g_profile[1].u_reference.rd_beats_cnt+5'd2)>=g_profile[1].u_reference.beats_expect &&
      g_profile[1].u_reference.load_has_more===1'b1)more++;
   clk=1;#1;compare();
  end
  if(commands==0 || completed==0 || more==0 || reset_busy==0 || reconfigured_busy==0 || unknown_cycles==0)$fatal(1,"Coverage incomplete commands=%0d complete=%0d more=%0d reset=%0d reconfigure=%0d",commands,completed,more,reset_busy,reconfigured_busy);
  $display("REQUANT_CONTROL_FOUR_STATE_PASS cycles=16384 profiles=3 checks=%0d bits=%0d,%0d,%0d commands=%0d completed_cycles=%0d more=%0d reset_busy=%0d reconfigured_busy=%0d unknown_cycles=%0d",checks,g_profile[0].u_reference.observed_width,g_profile[1].u_reference.observed_width,g_profile[2].u_reference.observed_width,commands,completed,more,reset_busy,reconfigured_busy,unknown_cycles);
  $finish;
 end
endmodule
''')
 files=[current/'rtl/npu/writeback/requant_pkg.sv',*paths,tb]
 with (out/'compile.log').open('w') as f:subprocess.run(['iverilog','-g2012','-s','tb','-o',str(out/'simulation'),*map(str,files)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=60)
 with (out/'run.log').open('w') as f:subprocess.run(['vvp',str(out/'simulation')],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=300)
 log=(out/'run.log').read_text();pattern=r'REQUANT_CONTROL_FOUR_STATE_PASS cycles=(\d+) profiles=(\d+) checks=(\d+) bits=(\d+),(\d+),(\d+) commands=(\d+) completed_cycles=(\d+) more=(\d+) reset_busy=(\d+) reconfigured_busy=(\d+) unknown_cycles=(\d+)'
 match=re.search(pattern,log)
 if not match:raise RuntimeError(str(out/'run.log'))
 values=list(map(int,match.groups()));report={'passed':True,'source_sha256':hashes,'strict_four_state':True,'cycles':values[0],'profiles':values[1],'comparisons':values[2],'observed_bits':values[3:6],'commands':values[6],'completed_cycles':values[7],'continued_chunks':values[8],'reset_busy':values[9],'reconfigured_busy':values[10],'unknown_input_cycles':values[11],'compared_registers':REGISTERS,'public_dma_outputs':PORTS}
 (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
