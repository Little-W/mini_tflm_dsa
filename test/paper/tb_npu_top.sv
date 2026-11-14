`timescale 1ns/1ps
`ifndef TB_MEM_WORDS
`define TB_MEM_WORDS 8388608
`endif
`ifndef TB_IA_CACHE_BLOCKS
`define TB_IA_CACHE_BLOCKS 64
`endif
`ifndef TB_PS_FRAME_COUNT
`define TB_PS_FRAME_COUNT 25
`endif
module tb_npu_top;
 localparam SIZE=16;
 logic clk=0;always #5 clk=~clk;
 logic rst_n=0,calc_start=0;wire sa_ready,done_valid;wire[1:0] err_code;
 logic[31:0] cfg[32];logic[31:0] golden_mem[0:`TB_MEM_WORDS-1];
 logic[31:0] acc_reference[0:1048575];bit acc_seen[0:1048575];
 longint unsigned state_cycles[0:23];
 longint unsigned ps_read_bytes=0,ps_write_bytes=0;
 longint unsigned row_mode_count[16],fast_rows=0,fast_useful_rows=0,feedback_written_words=0,feedback_full_words=0;
 longint unsigned group_count=0,allocation_count=0;
 longint unsigned k_records[65536],k_exceptions[65536],k_read_bytes[65536],k_write_bytes[65536],k_c_bytes[65536],k_allocations[65536],k_input_wait[65536],k_dependency_wait[65536],k_preflight[65536],k_port_conflicts[65536];

 integer acc_count=0;bit use_acc_reference=0;string init_path,gold_path,case_path,acc_path,report_path;
 wire m_axi_arvalid;
 wire m_axi_arready;
 wire [31:0] m_axi_araddr;
 wire [7:0] m_axi_arlen;
 wire [2:0] m_axi_arsize;
 wire [1:0] m_axi_arburst;
 wire m_axi_rvalid;
 wire m_axi_rready;
 wire [31:0] m_axi_rdata;
 wire [1:0] m_axi_rresp;
 wire m_axi_rlast;
 wire m_axi_awvalid;
 wire m_axi_awready;
 wire [31:0] m_axi_awaddr;
 wire [7:0] m_axi_awlen;
 wire [2:0] m_axi_awsize;
 wire [1:0] m_axi_awburst;
 wire m_axi_wvalid;
 wire m_axi_wready;
 wire [31:0] m_axi_wdata;
 wire [3:0] m_axi_wstrb;
 wire m_axi_wlast;
 wire m_axi_bvalid;
 wire m_axi_bready;
 wire [1:0] m_axi_bresp;

 npu_top #(.SIZE(16),.DATA_WIDTH(8),.WEIGHT_WIDTH(8),.IA_CACHE_BLOCKS(`TB_IA_CACHE_BLOCKS),.PS_FRAME_COUNT(`TB_PS_FRAME_COUNT)) u_dut(
 .clk(clk),.rst_n(rst_n),.calc_start(calc_start),.sa_ready(sa_ready),.done_valid(done_valid),.done_ready(1'b1),.err_code(err_code),
 .cfg_operand_fetch64(1'b0),
 .cfg_16bits_ia(cfg[12][0]),
 .cfg_16x8(cfg[28][0]),
 .cfg_dataflow_mode(cfg[8][0]),
 .cfg_ia_reuse_num(cfg[6]),
 .cfg_w_reuse_num(cfg[7]),
 .cfg_row_groups({16'b0,cfg[30][15:0]}),
 .cfg_col_groups({16'b0,cfg[30][31:16]}),
 .cfg_row_tail_tiles({16'b0,cfg[31][15:0]}),
 .cfg_col_tail_tiles({16'b0,cfg[31][31:16]}),
 .lhs_base(cfg[14]),
 .rhs_base(cfg[15]),
 .dst_base(cfg[17]),
 .bias_base(cfg[16]),
 .lhs_zp(cfg[21]),
 .rhs_zp(cfg[22]),
 .dst_zp(cfg[23]),
 .q_mult_pt(cfg[24]),
 .q_shift_pt(cfg[25]),
 .use_per_channel(cfg[13][0]),
 .k(cfg[3]),
 .n(cfg[4]),
 .m(cfg[5]),
 .lhs_row_stride_b(cfg[18]),
 .rhs_col_stride_b(cfg[19]),
 .dst_row_stride_b(cfg[20]),
 .act_min(cfg[26]),
 .act_max(cfg[27]),
 .m_axi_arvalid(m_axi_arvalid),
 .m_axi_arready(m_axi_arready),
 .m_axi_araddr(m_axi_araddr),
 .m_axi_arlen(m_axi_arlen),
 .m_axi_arsize(m_axi_arsize),
 .m_axi_arburst(m_axi_arburst),
 .m_axi_rvalid(m_axi_rvalid),
 .m_axi_rready(m_axi_rready),
 .m_axi_rdata(m_axi_rdata),
 .m_axi_rresp(m_axi_rresp),
 .m_axi_rlast(m_axi_rlast),
 .m_axi_awvalid(m_axi_awvalid),
 .m_axi_awready(m_axi_awready),
 .m_axi_awaddr(m_axi_awaddr),
 .m_axi_awlen(m_axi_awlen),
 .m_axi_awsize(m_axi_awsize),
 .m_axi_awburst(m_axi_awburst),
 .m_axi_wvalid(m_axi_wvalid),
 .m_axi_wready(m_axi_wready),
 .m_axi_wdata(m_axi_wdata),
 .m_axi_wstrb(m_axi_wstrb),
 .m_axi_wlast(m_axi_wlast),
 .m_axi_bvalid(m_axi_bvalid),
 .m_axi_bready(m_axi_bready),
 .m_axi_bresp(m_axi_bresp));
 ddr_axi_mem_model #(.WIDTH(32),.ADDR_W(32),.MW(4),.DP(`TB_MEM_WORDS)) u_mem(
 .clk(clk),.rst_n(rst_n),
 .m_axi_arvalid(m_axi_arvalid),
 .m_axi_arready(m_axi_arready),
 .m_axi_araddr(m_axi_araddr),
 .m_axi_arlen(m_axi_arlen),
 .m_axi_arsize(m_axi_arsize),
 .m_axi_arburst(m_axi_arburst),
 .m_axi_rvalid(m_axi_rvalid),
 .m_axi_rready(m_axi_rready),
 .m_axi_rdata(m_axi_rdata),
 .m_axi_rresp(m_axi_rresp),
 .m_axi_rlast(m_axi_rlast),
 .m_axi_awvalid(m_axi_awvalid),
 .m_axi_awready(m_axi_awready),
 .m_axi_awaddr(m_axi_awaddr),
 .m_axi_awlen(m_axi_awlen),
 .m_axi_awsize(m_axi_awsize),
 .m_axi_awburst(m_axi_awburst),
 .m_axi_wvalid(m_axi_wvalid),
 .m_axi_wready(m_axi_wready),
 .m_axi_wdata(m_axi_wdata),
 .m_axi_wstrb(m_axi_wstrb),
 .m_axi_wlast(m_axi_wlast),
 .m_axi_bvalid(m_axi_bvalid),
 .m_axi_bready(m_axi_bready),
 .m_axi_bresp(m_axi_bresp));
 initial begin
  if(!$value$plusargs("INIT_MEM=%s",init_path))$fatal(1,"INIT_MEM required");
  if(!$value$plusargs("GOLDEN_MEM=%s",gold_path))$fatal(1,"GOLDEN_MEM required");
  if(!$value$plusargs("CASE_MEM=%s",case_path))$fatal(1,"CASE_MEM required");
  $readmemh(case_path,cfg);$readmemh(init_path,u_mem.mem_r);$readmemh(gold_path,golden_mem);
  if($value$plusargs("ACC_I32_MEM=%s",acc_path))begin
   use_acc_reference=1;$readmemh(acc_path,acc_reference,0,int'(cfg[3]*cfg[5])-1);
  end
  if($value$plusargs("TASK_REPORT=%s",report_path))begin end
  for(int i=0;i<1048576;i++)acc_seen[i]=0;
  for(int i=0;i<24;i++)state_cycles[i]=0;
  for(int i=0;i<16;i++)row_mode_count[i]=0;
  for(int i=0;i<65536;i++)begin k_records[i]=0;k_exceptions[i]=0;k_read_bytes[i]=0;k_write_bytes[i]=0;k_c_bytes[i]=0;k_allocations[i]=0;k_input_wait[i]=0;k_dependency_wait[i]=0;k_preflight[i]=0;k_port_conflicts[i]=0;end
  repeat(5)@(negedge clk);rst_n=1;repeat(4)@(negedge clk);calc_start=1;@(negedge clk);calc_start=0;
  wait(done_valid);
  if(err_code!=0)$fatal(1,"task error %0d state=%0d",err_code,u_dut.u_panel.state);
  repeat(12)@(negedge clk);
  for(int i=0;i<int'(cfg[10]);i++)assert(u_mem.mem_r[i]===golden_mem[i])else $fatal(1,"memory mismatch word=%0d got=%h expected=%h",i,u_mem.mem_r[i],golden_mem[i]);
  if(use_acc_reference)assert(acc_count==cfg[3]*cfg[5])else $fatal(1,"INT32 count %0d",acc_count);
  if(report_path!="")begin
   integer f;f=$fopen(report_path,"w");
   $fdisplay(f,"{\"passed\":true,\"INT32_values\":%0d,\"tile_commands\":%0d,\"MACs\":%0d,\"early_frames\":%0d,\"PS_peak_B\":%0d,\"PS_free_pages\":%0d}",acc_count,u_dut.u_panel.tile_commands,4096*u_dut.u_panel.tile_commands,u_dut.u_panel.early_frames,u_dut.u_panel.peak_ps,u_dut.u_panel.free_pages);$fclose(f);
   f=$fopen({report_path,".costs.json"},"w");
   $fwrite(f,"{\"state_cycles\":[");
   for(int i=0;i<24;i++)$fwrite(f,"%s%0d",i==0?"":",",state_cycles[i]);
   $fwrite(f,"],\"PS_bank_read_bytes\":%0d,\"PS_bank_write_bytes\":%0d,\"groups\":%0d,\"allocated_pages\":%0d,\"feedback_written_words\":%0d,\"feedback_full_words\":%0d,\"fast_rows\":%0d,\"fast_useful_rows\":%0d,\"row_mode_count\":[",ps_read_bytes,ps_write_bytes,group_count,allocation_count,feedback_written_words,feedback_full_words,fast_rows,fast_useful_rows);
   for(int i=0;i<16;i++)$fwrite(f,"%s%0d",i==0?"":",",row_mode_count[i]);
   $fdisplay(f,"]}");$fclose(f);
   f=$fopen({report_path,".k_stages.csv"},"w");
   $fdisplay(f,"K_stage,feedback_vectors,exception_INT32_values,feedback_read_bytes,feedback_write_bytes,final_C_store_bytes,allocated_high_pages,input_wait_cycles,dependency_wait_cycles,preflight_cycles,PS_port_conflicts,external_PS_bytes");
   for(int i=0;i<int'(cfg[4]>>4);i++)$fdisplay(f,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,0",i,k_records[i],k_exceptions[i],k_read_bytes[i],k_write_bytes[i],k_c_bytes[i],k_allocations[i],k_input_wait[i],k_dependency_wait[i],k_preflight[i],k_port_conflicts[i]);
   $fclose(f);
  end
  $display("[TB] PASS");$finish;
 end
 always @(posedge clk)begin
  #1ps;
  if(rst_n && u_dut.u_panel.acc_data_valid)begin
   for(int l=0;l<16;l++)begin
    integer rr,cc,index;
    rr=16*(int'(u_dut.u_panel.gr)+int'(u_dut.u_panel.acc_tile)%int'(u_dut.u_panel.group_rows))+int'(u_dut.u_panel.acc_row);
    cc=16*(int'(u_dut.u_panel.gc)+int'(u_dut.u_panel.acc_col))+l;
    index=cfg[8][0]?cc*int'(cfg[5])+rr:rr*int'(cfg[5])+cc;
    if(use_acc_reference)begin
     assert(!acc_seen[index])else $fatal(1,"repeated INT32 output index=%0d",index);
     assert(u_dut.u_panel.acc_data_out[l]===acc_reference[index])else $fatal(1,"INT32 mismatch index=%0d got=%0d expected=%0d",index,u_dut.u_panel.acc_data_out[l],$signed(acc_reference[index]));
     acc_seen[index]=1;
    end
    acc_count++;
   end
  end
 end
 always @(posedge clk)if(rst_n)begin
  if(u_dut.u_panel.group_start)group_count++;
  if(u_dut.u_panel.state>0 && u_dut.u_panel.state<22)begin
   state_cycles[u_dut.u_panel.state]++;
   for(int b=0;b<4;b++)begin
    if(u_dut.u_panel.u_ps.bank_re[b])ps_read_bytes+=16;
    if(u_dut.u_panel.u_ps.bank_we[b])ps_write_bytes+=16;
   end
  end
 end
 // Passive counters are indexed by the exact K tag of each serviced operation.
 always @(posedge clk)if(rst_n)begin
  if(u_dut.u_panel.core_valid)for(int b=0;b<4;b++)if(u_dut.u_panel.u_ps.bank_re[b])k_read_bytes[u_dut.u_panel.core_k]+=16;
  if(u_dut.u_panel.u_ps.sum_valid && !u_dut.u_panel.u_ps.sum_final)begin
   k_records[u_dut.u_panel.u_ps.sum_k]++;
   for(int l=0;l<16;l++)if(u_dut.u_panel.u_ps.sum_data[l][31:24]!={8{u_dut.u_panel.u_ps.sum_data[l][23]}})k_exceptions[u_dut.u_panel.u_ps.sum_k]++;
`ifndef GEMPACT_PCR_PS
   for(int b=0;b<4;b++)if(u_dut.u_panel.u_ps.bank_we[b])k_write_bytes[u_dut.u_panel.u_ps.sum_k]+=16;
`endif
  end
`ifdef GEMPACT_PCR_PS
  if(u_dut.u_panel.u_ps.writeback_nonfinal)begin
   integer written;written=0;
   for(int b=0;b<4;b++)if(u_dut.u_panel.u_ps.bank_we[b])begin
    k_write_bytes[u_dut.u_panel.u_ps.writeback_k]+=16;written++;
   end
   feedback_written_words+=written;
   feedback_full_words+=u_dut.u_panel.u_ps.writeback_desc[12:10];
   row_mode_count[u_dut.u_panel.u_ps.writeback_mode]++;
   if(u_dut.u_panel.u_ps.writeback_fast)begin
    fast_rows++;
    if(written<int'(u_dut.u_panel.u_ps.writeback_desc[12:10]))fast_useful_rows++;
   end
  end
`endif
  if(u_dut.u_panel.c_write_valid)k_c_bytes[u_dut.u_panel.c_write_k]+=16;
  if(u_dut.u_panel.u_ps.pop_page)begin k_allocations[u_dut.u_panel.qk]++;allocation_count++;end
  if(u_dut.u_panel.state==6)begin
   if(u_dut.u_panel.producer==3 && !u_dut.u_panel.panel_available)k_input_wait[u_dut.u_panel.qk]++;
   if(u_dut.u_panel.producer==0 && !u_dut.u_panel.predecessor_ready)k_dependency_wait[u_dut.u_panel.qk]++;
   if(u_dut.u_panel.producer==1 || u_dut.u_panel.producer==2)k_preflight[u_dut.u_panel.qk]++;
  end
`ifdef GEMPACT_PCR_PS
  if((u_dut.u_panel.core_valid && u_dut.u_panel.c_read_request) || (u_dut.u_panel.u_ps.writeback_nonfinal && u_dut.u_panel.c_write_valid))k_port_conflicts[u_dut.u_panel.qk]++;
`else
  if((u_dut.u_panel.core_valid && u_dut.u_panel.c_read_request) || (u_dut.u_panel.u_ps.sum_valid && !u_dut.u_panel.u_ps.sum_final && u_dut.u_panel.c_write_valid))k_port_conflicts[u_dut.u_panel.qk]++;
`endif
 end
 logic ar_stalled=0,aw_stalled=0,w_stalled=0;
 logic[44:0] old_ar,old_aw;
 logic[36:0] old_w;
 always @(posedge clk)begin
  if(!rst_n)begin ar_stalled<=0;aw_stalled<=0;w_stalled<=0;end
  else begin
   if(ar_stalled)assert(m_axi_arvalid && {m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst}===old_ar)else $fatal(1,"unstable AXI AR during backpressure");
   if(aw_stalled)assert(m_axi_awvalid && {m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst}===old_aw)else $fatal(1,"unstable AXI AW during backpressure");
   if(w_stalled)assert(m_axi_wvalid && {m_axi_wdata,m_axi_wstrb,m_axi_wlast}===old_w)else $fatal(1,"unstable AXI W during backpressure");
   ar_stalled<=m_axi_arvalid && !m_axi_arready;aw_stalled<=m_axi_awvalid && !m_axi_awready;w_stalled<=m_axi_wvalid && !m_axi_wready;
   old_ar<={m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst};old_aw<={m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst};old_w<={m_axi_wdata,m_axi_wstrb,m_axi_wlast};
  end
 end
 always @(posedge clk)if(rst_n)begin
  if(m_axi_arvalid && m_axi_arready)assert({1'b0,m_axi_araddr[11:0]}+((13'(m_axi_arlen)+1'b1)<<2)<=4096)else $fatal(1,"AR crosses a 4 KiB boundary");
  if(m_axi_awvalid && m_axi_awready)assert({1'b0,m_axi_awaddr[11:0]}+((13'(m_axi_awlen)+1'b1)<<2)<=4096)else $fatal(1,"AW crosses a 4 KiB boundary");
 end
 always @(posedge clk)if(rst_n && m_axi_awvalid && m_axi_awready)
  assert(m_axi_awaddr>=cfg[17] && m_axi_awaddr<cfg[17]+cfg[3]*cfg[20])else $fatal(1,"write outside final C");
 initial begin
  longint unsigned limit;limit=200000000;void'($value$plusargs("TB_TIMEOUT_CYCLES=%d",limit));repeat(limit)@(posedge clk);
  $fatal(1,"timeout engine=%0d scheduler=%0d qk=%0d row=%0d col=%0d",u_dut.u_panel.state,u_dut.u_panel.producer,u_dut.u_panel.qk,u_dut.u_panel.qcol,u_dut.u_panel.qcol);
 end
endmodule
