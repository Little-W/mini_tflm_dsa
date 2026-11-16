// SPDX-License-Identifier: Apache-2.0
// DW descriptor order and independent AXI/data accounting under random waits.
module tb_windowed_cache;
  import conv_im2col_pkg::*;
  parameter int CACHE_SETS=128, CACHE_POLICY=3;
  parameter bit PREFETCH=1;
  localparam int TRACK_BYTES=262144;
  logic unused_wr_last;
  logic clk=0;
  always #5 clk=~clk;
  logic rst_n=0,cfg_valid=0,cfg_ready,tile_valid=0,tile_ready;
  conv_cfg_t cfg;
  logic [31:0] tile_p0=0,tile_q0=0;
  logic [4:0] tile_rows=1,tile_cols=16;
  logic [2:0] tile_slot=0,wr_slot;
  logic wr_valid,wr_ready;
  logic [3:0] wr_row,wr_col,wr_mask;
  logic signed [15:0] wr_data[4];
  logic tile_done,tile_error,error,busy;
  logic [31:0] stat_hits,stat_misses,stat_read_bytes;
  logic [31:0] stat_prefetch_lines,stat_prefetch_used,stat_prefetch_wasted;
  logic [31:0] stat_prefetch_unused,stat_prefetch_bytes,stat_prefetch_late;
  logic arvalid,arready,rvalid,rready,rlast;
  logic [31:0] araddr,rdata;
  logic [7:0] arlen;
  logic [2:0] arsize;
  logic [1:0] arburst,rresp;
  logic [31:0] epoch=1;
  logic mem_active;
  longint unsigned read_bytes,ar_count,job_bytes,job_cycles,cycles=0;
  logic [31:0] rng=32'hba42a719;
  bit seen_element[TRACK_BYTES],seen_line[TRACK_BYTES/8];
  int h,w,channels,kh,kw,stride,dilation,pad,oh,ow,cb,active,position,y,x,ky,kx,iy,ix;
  int written,requests,unique_elements,all_elements,cold_requests,repeat_requests,cold_misses,repeat_misses;
  int last_misses;
  bit request_cold;
  logic [31:0] expected_addr;
  logic [31:0] allocation_base=32'h1000,allocation_bytes;
  bit trace_cache=0;
  int trace_channels=0;
  initial begin
    trace_cache=$test$plusargs("TRACE_CACHE");
    void'($value$plusargs("TRACE_CHANNELS=%d",trace_channels));
  end
  conv_im2col_frontend #(.SIZE(16),.SLOT_W(3),.LANES(4),.CACHE_SETS(CACHE_SETS),
    .CACHE_POLICY(CACHE_POLICY)) dut(.cfg_sched_r(0),.cfg_sched_groups(0),.tile_group(0),.wr_last(unused_wr_last),.*);
  axi_counted_memory #(.TRACK_BASE(32'h1000),.TRACK_BYTES(TRACK_BYTES)) mem(
    .clk,.rst_n,.allocation_base,.allocation_bytes,.epoch,.block_ar(1'b0),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,
    .read_bytes,.ar_count,.active(mem_active));
  assign wr_ready=rng[3] || rng[7];
  always @(posedge clk) if (rst_n) begin
    cycles<=cycles+1;
    rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
    if (dut.cache_req_valid && dut.cache_req_ready) begin
      request_cold=!seen_line[((dut.cache_req_addr&32'hfffffff0)-(allocation_base&32'hfffffff0))>>4];
      seen_line[((dut.cache_req_addr&32'hfffffff0)-(allocation_base&32'hfffffff0))>>4]=1;
      if (request_cold) cold_requests++;else repeat_requests++;
    end
    if (wr_valid && wr_ready) begin
      if (wr_row!=0 || wr_slot!=0) $fatal(1,"wrong destination");
      for(int l=0;l<4;l++) if (wr_mask[l]) begin
        logic [31:0] a;
        logic signed [7:0] value;
        a=expected_addr+32'(wr_col)+32'(l);
        value=8'((a*32'd29)^(a>>4)^epoch);
        if (wr_data[l] != 16'(value)+16'sd7) $fatal(1,"window data mismatch addr=%h got=%0d expected=%0d",a,wr_data[l],16'(value)+16'sd7);
        written++;
        if (!seen_element[a-allocation_base]) begin seen_element[a-allocation_base]=1;unique_elements++;end
        all_elements++;
      end
    end
  end
  always @(negedge clk) if(rst_n) begin
    if (int'(stat_misses)>last_misses) begin
      if (request_cold) cold_misses++;else repeat_misses++;
    end
    last_misses=int'(stat_misses);
  end
  generate if (CACHE_POLICY==3) begin : g_trace
    always @(posedge clk) if (rst_n && trace_cache && (trace_channels==0 || trace_channels==channels)) begin
      if (dut.cache_req_valid && dut.cache_req_ready && !dut.u_cache.g_window.u_window.lookup_hit)
        $display("WINDOW_DEMAND_MISS cycle=%0d channel=%0d position=%0d tap=%0d address=%h",cycles,cb,position,ky*kw+kx,dut.cache_req_addr);
      if (dut.u_cache.g_window.u_window.pf_push)
        $display("WINDOW_PREFETCH cycle=%0d channel=%0d position=%0d tap=%0d address=%h",cycles,cb,position,ky*kw+kx,
          dut.u_cache.g_window.u_window.pf_offer_addr);
      if (dut.u_cache.g_window.u_window.select_launch)
        $display("WINDOW_FILL cycle=%0d prefetch=%0d address=%h",cycles,
          dut.u_cache.g_window.u_window.select_prefetch,dut.u_cache.g_window.u_window.select_addr);
    end
  end endgenerate
  task automatic run_case(input string name,input int th,tw,tc,tk,ts,td,tp,input int offset);
    int descriptors;
    h=th;w=tw;channels=tc;kh=tk;kw=tk;stride=ts;dilation=td;pad=tp;
    oh=(h+2*pad-dilation*(kh-1)-1)/stride+1;
    ow=(w+2*pad-dilation*(kw-1)-1)/stride+1;
    allocation_base=32'h1000+32'(offset);allocation_bytes=32'(h*w*channels);
    @(negedge clk);
    cfg='0;cfg.input_base=allocation_base;
    cfg.input_h=16'(h);cfg.input_w=16'(w);cfg.input_c=16'(channels);cfg.group_c=16'(channels);
    cfg.kernel_h=16'(kh);cfg.kernel_w=16'(kw);cfg.output_h=16'(oh);cfg.output_w=16'(ow);
    cfg.stride_h=16'(stride);cfg.stride_w=16'(stride);cfg.dilation_h=16'(dilation);cfg.dilation_w=16'(dilation);
    cfg.pad_top=16'(pad);cfg.pad_left=16'(pad);cfg.input_offset=7;
    cfg.windowed=1;cfg.prefetch_enable=PREFETCH;cfg_valid=1;
    do @(posedge clk);while(!cfg_ready);
    @(negedge clk);cfg_valid=0;
    for(int i=0;i<TRACK_BYTES;i++) seen_element[i]=0;
    for(int i=0;i<TRACK_BYTES/8;i++) seen_line[i]=0;
    unique_elements=0;all_elements=0;cold_requests=0;repeat_requests=0;cold_misses=0;repeat_misses=0;last_misses=0;
    job_bytes=read_bytes;job_cycles=cycles;descriptors=0;
    for(cb=0;cb<channels;cb+=16) begin
      active=channels-cb<16 ? channels-cb : 16;
      for(position=0;position<oh*ow;position++) begin
        y=position/ow;x=position%ow;
        for(ky=0;ky<kh;ky++) for(kx=0;kx<kw;kx++) begin
          iy=y*stride-pad+ky*dilation;ix=x*stride-pad+kx*dilation;
          if(iy>=0 && ix>=0 && iy<h && ix<w) begin
            expected_addr=allocation_base+32'((iy*w+ix)*channels+cb);
            written=0;tile_p0=32'(position);tile_q0=32'((ky*kw+kx)*channels+cb);tile_cols=5'(active);
            @(negedge clk);tile_valid=1;
            do @(posedge clk);while(!tile_ready);
            @(negedge clk);tile_valid=0;
            do @(posedge clk);while(!tile_done && !tile_error);
            @(negedge clk);
            if(error || tile_error || written!=active) $fatal(1,"window transfer failed %s count=%0d expected=%0d",name,written,active);
            descriptors++;
          end
        end
      end
    end
    while(busy) @(negedge clk);
    if(mem_active || rvalid || 64'(stat_read_bytes)!=read_bytes-job_bytes) $fatal(1,"external byte accounting mismatch");
    if(stat_prefetch_lines!=stat_prefetch_used+stat_prefetch_wasted+stat_prefetch_unused) $fatal(1,"prefetch accounting mismatch");
    if (32'(cold_requests+repeat_requests)!=stat_hits+stat_misses) $fatal(1,"demand accounting mismatch");
    $display("WINDOW_CACHE_CASE name=%s cache_bytes=%0d policy=%0d prefetch=%0d descriptors=%0d cycles=%0d hits=%0d misses=%0d cold_requests=%0d repeat_requests=%0d cold_misses=%0d repeat_misses=%0d demand_hit_pct=%0.6f read_bytes=%0d input_bytes=%0d elements=%0d unique_elements=%0d element_reuse_pct=%0.6f pf_lines=%0d pf_used=%0d pf_wasted=%0d pf_unused=%0d pf_bytes=%0d pf_late=%0d",name,CACHE_SETS*2*16,CACHE_POLICY,PREFETCH,descriptors,cycles-job_cycles,stat_hits,stat_misses,cold_requests,repeat_requests,cold_misses,repeat_misses,100.0*real'(stat_hits)/real'(stat_hits+stat_misses),stat_read_bytes,allocation_bytes,all_elements,unique_elements,100.0*(1.0-real'(unique_elements)/real'(all_elements)),stat_prefetch_lines,stat_prefetch_used,stat_prefetch_wasted,stat_prefetch_unused,stat_prefetch_bytes,stat_prefetch_late);
  endtask
  initial begin
    cfg='0;allocation_bytes=1;written=0;last_misses=0;
    repeat(5) @(posedge clk);@(negedge clk);rst_n=1;
    run_case("dw32_c8_k3_s1",32,32,8,3,1,1,1,0);
    run_case("dw16_c16_k3_s1",16,16,16,3,1,1,1,0);
    run_case("dw32_c16_k3_s2",32,32,16,3,2,1,1,0);
    run_case("dw16_c32_k3_s1",16,16,32,3,1,1,1,0);
    run_case("dw8_c64_k3_s1",8,8,64,3,1,1,1,0);
    run_case("dw8_c128_k3_s2",8,8,128,3,2,1,1,0);
    run_case("dw9x11_c7_k5_d2_s2",9,11,7,5,2,2,4,3);
    run_case("pointwise8_c16_k1",8,8,16,1,1,1,0,0);
    run_case("pointwise1_c3_k1",1,1,3,1,1,1,0,1);
    $display("WINDOW_CACHE_PASS");$finish;
  end
  initial begin #1000000000;$fatal(1,"window cache timeout");end
endmodule
