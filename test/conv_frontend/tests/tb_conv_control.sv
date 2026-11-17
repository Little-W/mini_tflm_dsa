// SPDX-License-Identifier: Apache-2.0
// Configuration/descriptor rejection and recovery; valid windows are all padding.
module tb_conv_control;
  import conv_im2col_pkg::*;
  logic unused_wr_last;
  logic clk;
  initial begin clk=0;forever #5 clk=~clk;end
  logic rst_n=0,cfg_valid=0,cfg_ready;
  conv_cfg_t cfg,good,bad;
  logic tile_valid=0,tile_ready;
  logic [31:0] tile_p0=0,tile_q0=0;
  logic [2:0] tile_rows=0,tile_cols=0;
  logic [1:0] tile_slot=0,wr_slot;
  logic wr_valid,wr_ready=1;
  logic [1:0] wr_row,wr_col,wr_mask;
  logic signed [15:0] wr_data[2];
  logic tile_done,tile_error,error,busy;
  logic [31:0] stat_hits,stat_misses,stat_read_bytes;
  logic arvalid,arready=0,rvalid=0,rready,rlast=0;
  logic [31:0] araddr,rdata=0;
  logic [7:0] arlen;
  logic [2:0] arsize;
  logic [1:0] arburst,rresp=0;
  int checked=0,written=0,cycles=0;
  conv_im2col_frontend #(.SIZE(4),.SLOT_W(2),.CACHE_SETS(2)) dut (
      .cfg_sched_r(32'd0),.cfg_sched_groups(32'd0),.tile_group(32'd0),.wr_last(unused_wr_last),.*);
    assign unused_prefetch[0]=dut.tb_observer.stat_prefetch_lines;
    assign unused_prefetch[1]=dut.tb_observer.stat_prefetch_used;
    assign unused_prefetch[2]=dut.tb_observer.stat_prefetch_wasted;
    assign unused_prefetch[3]=dut.tb_observer.stat_prefetch_unused;
    assign unused_prefetch[4]=dut.tb_observer.stat_prefetch_bytes;
    assign unused_prefetch[5]=dut.tb_observer.stat_prefetch_late;
    assign stat_hits=dut.tb_observer.stat_hits;
    assign stat_misses=dut.tb_observer.stat_misses;
    assign stat_read_bytes=dut.tb_observer.stat_read_bytes;


  logic [31:0] unused_prefetch[6];
  always @(posedge clk) if(rst_n) begin
    cycles<=cycles+1;
    if(cycles>10000) $fatal(1,"control timeout");
    if(arvalid || rready || stat_read_bytes!=0 || stat_hits!=0 || stat_misses!=0)
      $fatal(1,"invalid or padding task accessed memory");
    if(wr_valid) begin
      if(!busy || wr_slot!=2) $fatal(1,"bad padding write");
      for(int l=0;l<2;l++) if(wr_mask[l]) begin
        if(wr_data[l]!=0) $fatal(1,"padding offset was incorrectly applied");
        written=written+1;
      end
    end
    if(tile_done && tile_error) $fatal(1,"completion and failure asserted together");
  end

  task automatic configure(input conv_cfg_t value,input bit want_error);
    @(negedge clk);cfg=value;cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;cfg='0;
    while(busy) @(negedge clk);
    if(error!=want_error || busy || tile_done || tile_error)
      $fatal(1,"bad configuration result case=%0d error=%0b expected=%0b busy=%0b done=%0b tile_error=%0b",
        checked,error,want_error,busy,tile_done,tile_error);
    if(want_error && tile_ready) $fatal(1,"invalid configuration accepted a tile");
    checked=checked+1;
  endtask

  task automatic reject_tile(input logic[31:0] p,input logic[31:0] q,input logic[2:0] rows);
    configure(good,0);
    @(negedge clk);tile_p0=p;tile_q0=q;tile_rows=rows;tile_slot=2;tile_valid=1;
    do @(posedge clk);while(!tile_ready);
    @(negedge clk);tile_valid=0;
    if(!error || !tile_error || tile_done || busy || wr_valid) $fatal(1,"invalid descriptor not rejected");
    @(negedge clk);
    if(tile_error || tile_done || !error || tile_ready) $fatal(1,"error status/pulse contract");
    checked=checked+1;
  endtask

  initial begin
    cfg='0;good='0;
    good.input_h=1;good.input_w=1;good.input_c=1;good.group_c=1;
    good.kernel_h=1;good.kernel_w=1;good.output_h=2;good.output_w=2;
    good.stride_h=1;good.stride_w=1;good.dilation_h=1;good.dilation_w=1;
    good.pad_top=10;good.pad_left=10;good.input_offset=128;good.input_base=32'h1003;
    repeat(5) @(posedge clk);
    @(negedge clk);rst_n=1;
    bad=good;bad.input_h=0;configure(bad,1);
    bad=good;bad.stride_w=0;configure(bad,1);
    bad=good;bad.dilation_h=0;configure(bad,1);
    bad=good;bad.group_offset=1;configure(bad,1);
    bad=good;bad.input_offset=-128;configure(bad,1);
    bad=good;bad.input_offset=129;configure(bad,1);
    bad=good;bad.input_s16=1;bad.input_offset=0;configure(bad,1);
    bad=good;bad.input_s16=1;bad.input_base=32'h1000;configure(bad,1);
    bad=good;bad.input_base=32'hffffffff;configure(bad,1);
    bad=good;bad.input_h=65535;bad.input_w=65535;bad.input_c=65535;configure(bad,1);
    bad=good;bad.input_c=65535;bad.group_c=65535;bad.kernel_h=65535;bad.kernel_w=65535;configure(bad,1);
    reject_tile(0,0,0);
    reject_tile(0,0,5);
    reject_tile(0,1,1);
    reject_tile(4,0,1);
    reject_tile(32'hffffffff,0,1);
    configure(good,0);
    @(negedge clk);tile_p0=0;tile_q0=0;tile_rows=4;tile_slot=2;tile_valid=1;
    do @(posedge clk);while(!tile_ready);
    @(negedge clk);tile_valid=0;
    // A new invalid config must remain pending until the running tile completes.
    cfg='0;cfg_valid=1;
    do begin
      @(posedge clk);
      if(busy && cfg_ready) $fatal(1,"configuration changed while tile busy");
      if(error || tile_error) $fatal(1,"busy tile configuration was not immutable");
    end while(!tile_done);
    if(written!=16) $fatal(1,"padding tile incomplete");
    @(negedge clk);
    // Configuration was accepted on the edge that observed tile_done.
    if(!error || tile_ready) $fatal(1,"pending invalid config did not take effect");
    cfg_valid=0;
    configure(good,0);
    $display("RTL_CONTROL_PASS checks=%0d padding_writes=%0d cycles=%0d",checked,written,cycles);
    $finish;
  end
endmodule
