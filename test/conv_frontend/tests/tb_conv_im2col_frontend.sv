// SPDX-License-Identifier: Apache-2.0
// Self-checking frontend RTL bench. Does NOT instantiate upstream npu_top.
// Generate vectors with tests/gen_rtl_vectors.py; run with +VECTORS=<path>.
module tb_conv_im2col_frontend;
  import conv_im2col_pkg::*;
  parameter int SIZE=16;
  parameter int CACHE_SETS=128, CACHE_WAYS=2, LINE_BYTES=16;
  parameter bit USE_TILE_PATH=0;
  localparam int CW=$clog2(SIZE), RW=$clog2(SIZE+1), MEM_BYTES=1048576;
  logic clk;
  initial begin clk=0; forever #5 clk=~clk; end
  logic rst_n=0, cfg_valid=0, cfg_ready;
  conv_cfg_t cfg;
  logic tile_valid=0,tile_ready;
  logic [31:0] tile_p0=0,tile_q0=0;
  logic [RW-1:0] tile_rows=0;
  logic [2:0] tile_slot=0;
  logic wr_valid,wr_ready;
  logic [2:0] wr_slot;
  logic [CW-1:0] wr_row,wr_col;
  logic signed [15:0] wr_data[2];
  logic [1:0] wr_mask;
  logic tile_done,tile_error,error,busy;
  logic [31:0] stat_hits,stat_misses,stat_read_bytes;
  logic arvalid,arready,rvalid,rready,rlast;
  logic [31:0] araddr,rdata;
  logic [7:0] arlen;
  logic [2:0] arsize;
  logic [1:0] arburst,rresp;
  byte unsigned memory[MEM_BYTES];
  int expected[SIZE][SIZE];
  bit seen[SIZE][SIZE];
  int active_rows=0, expected_slot=0, written;
  int unsigned input_base=0;
  longint unsigned input_end=0;
  longint unsigned job_bus_start=0;
  bit inject_error=0, error_injected;
  longint unsigned cycles,bus_byte_count;
  logic [31:0] lfsr;
  bit mem_active;
  int unsigned mem_addr,mem_left,mem_size;
  int jobs,ntiles,nbytes,expect_fault;
  int fd,rc,job,ti,v[22];
  byte unsigned tmp;
  string vectors;
  logic [31:0] virtual_stride;
  generate if (!USE_TILE_PATH) begin : g_direct
    conv_im2col_frontend #(.SIZE(SIZE),.SLOT_W(3),.CACHE_SETS(CACHE_SETS),.CACHE_WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES)) dut (
      .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg,
      .tile_valid,.tile_ready,.tile_p0,.tile_q0,.tile_rows,.tile_slot,
      .wr_valid,.wr_ready,.wr_slot,.wr_row,.wr_col,.wr_data,.wr_mask,
      .tile_done,.tile_error,.error,.busy,.stat_hits,.stat_misses,.stat_read_bytes,
      .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
    );
  end else begin : g_tile_path
    logic path_busy, use16;
    logic signed [15:0] data4[4];
    logic valid4[4];
    conv_ia_tile_path #(.SIZE(SIZE),.CACHE_BLOCKS(8),
      .CACHE_SETS(CACHE_SETS),.CACHE_WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES)) dut (
      .clk,.rst_n,.init_cfg(cfg_valid),.cfg_ready,.conv_cfg(cfg),
      .virtual_base(32'h40000000),.virtual_stride_b(virtual_stride),
      .tl_start(tile_valid && tile_ready),
      .tl_base_addr(32'h40000000 + tile_p0*virtual_stride + (tile_q0<<1)),
      .tl_rows_to_read(32'(tile_rows)),.tl_slot_id(tile_slot),
      .tl_busy(path_busy),.tl_tile_done(tile_done),.error,
      .tl_wr_slot(wr_slot),.tl_wr_row(wr_row),.tl_wr_col_base(wr_col),
      .tl_wr_data(data4),.tl_wr_valid(valid4),.tl_wr_use_16bits(use16),
      .stat_hits,.stat_misses,.stat_read_bytes,
      .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
    );
    assign busy=path_busy;
    assign tile_ready=!path_busy && !cfg_valid;
    assign tile_error=error;
    assign wr_valid=valid4[0] || valid4[1];
    assign wr_mask={valid4[1],valid4[0]};
    assign wr_data[0]=data4[0];
    assign wr_data[1]=data4[1];
    always @(posedge clk) if (rst_n) begin
      if (!use16 || valid4[2] || valid4[3]) $fatal(1,"invalid adapter lanes/precision");
    end
  end endgenerate

  // Memory channel model. AR and R payloads are retained until accepted.
  always @(posedge clk) begin
    if (!rst_n) begin
      arready<=0;rvalid<=0;rlast<=0;rdata<=0;rresp<=0;wr_ready<=0;
      mem_active=0; mem_addr=0;mem_left=0;mem_size=0;
      lfsr<=32'hca17cafe;cycles<=0;bus_byte_count<=0;
    end else begin
      if (wr_valid && !busy) $fatal(1,"write when frontend idle");
      cycles<=cycles+1;
      lfsr<={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
      wr_ready<=USE_TILE_PATH || lfsr[5] || lfsr[9];
      arready<=!mem_active && (lfsr[0] || lfsr[3]);
      if (arvalid && arready) begin
        if (mem_active) $fatal(1,"multiple outstanding requests in single-burst slave");
        if (arburst!=1 || !(arsize==0 || arsize==2)) $fatal(1,"unsupported AR");
        if ((araddr&4095)+((int'(arlen)+1)<<arsize)>4096) $fatal(1,"4 KiB crossing");
        mem_active=1;mem_addr=araddr;mem_left=int'(arlen)+1;mem_size=1<<arsize;
        arready<=0;
      end
      if (rvalid && rready) begin
        bus_byte_count<=bus_byte_count+64'(mem_size);
        rvalid<=0;mem_addr=mem_addr+mem_size;mem_left=mem_left-1;
        if (mem_left==0) mem_active=0;
      end else if (mem_active && !rvalid && lfsr[2]) begin
        if (mem_addr<input_base || 64'(mem_addr)+64'(mem_size)>input_end)
          $fatal(1,"out-of-range read addr=%h size=%0d bounds=%h..%h",mem_addr,mem_size,input_base,input_end);
        if (mem_size==4 && mem_addr[1:0]!=0) $fatal(1,"unaligned full-width burst");
        rdata<=32'ha5b6c7d8; // Invalid byte lanes deliberately not zero.
        for (int b=0;b<4;b++)
          if (b<mem_size) rdata[((mem_addr&3)+b)*8 +: 8]<=memory[mem_addr-input_base+unsigned'(b)];
        rlast<=mem_left==1;
        rresp<=(inject_error && !error_injected) ? 2'b10 : 2'b00;
        if (inject_error && !error_injected) error_injected=1;
        rvalid<=1;
      end
      if (wr_valid && wr_ready) begin
        if (32'(wr_slot)!=expected_slot) $fatal(1,"wrong slot");
        for (int l=0;l<2;l++) if (wr_mask[l]) begin
          if (32'(wr_row)>=active_rows || int'(wr_col)+l>=SIZE) $fatal(1,"write coordinate overflow");
          if (seen[wr_row][int'(wr_col)+l]) $fatal(1,"duplicate write");
          if (32'($signed(wr_data[l]))!=expected[wr_row][int'(wr_col)+l])
            $fatal(1,"mismatch job=%0d tile=%0d row=%0d col=%0d got=%0d exp=%0d",
              job,ti,wr_row,int'(wr_col)+l,$signed(wr_data[l]),expected[wr_row][int'(wr_col)+l]);
          seen[wr_row][int'(wr_col)+l]=1; written=written+1;
        end
      end
      if (cycles>100000000) $fatal(1,"global timeout");
    end
  end

  initial begin
    cfg='0;
    if (!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"missing +VECTORS");
    fd=$fopen(vectors,"r"); if (fd==0) $fatal(1,"cannot open vectors");
    rc=$fscanf(fd,"%d",jobs); if(rc!=1) $fatal(1,"bad vector header");
    repeat(5) @(posedge clk);
    @(negedge clk);rst_n=1;
    for(job=0;job<jobs;job++) begin
      for(int j=0;j<22;j++) begin rc=$fscanf(fd,"%d",v[j]); if(rc!=1)$fatal(1,"bad cfg"); end
      input_base=32'(v[0]);nbytes=v[21];input_end=64'(input_base)+64'(nbytes);
      if(nbytes<=0 || nbytes>MEM_BYTES || input_end>=64'h1_0000_0000)
        $fatal(1,"bench tensor bounds");
      job_bus_start=bus_byte_count;
      for(int j=0;j<nbytes;j++) begin
        rc=$fscanf(fd,"%h",tmp);if(rc!=1)$fatal(1,"bad input bytes");memory[j]=8'(tmp);
      end
      virtual_stride=32'(((v[6]*v[7]*v[4]+SIZE-1)/SIZE)*SIZE*2);
      if (virtual_stride==0) $fatal(1,"invalid virtual stride in vectors");
      cfg.input_base=32'(v[0]);cfg.input_h=16'(v[1]);cfg.input_w=16'(v[2]);cfg.input_c=16'(v[3]);
      cfg.group_c=16'(v[4]);cfg.group_offset=16'(v[5]);cfg.kernel_h=16'(v[6]);cfg.kernel_w=16'(v[7]);
      cfg.output_h=16'(v[8]);cfg.output_w=16'(v[9]);cfg.stride_h=16'(v[10]);cfg.stride_w=16'(v[11]);
      cfg.dilation_h=16'(v[12]);cfg.dilation_w=16'(v[13]);cfg.pad_top=16'(v[14]);cfg.pad_left=16'(v[15]);
      cfg.input_offset=16'(v[16]);cfg.input_s16=1'(v[17]);cfg.bypass_cache=1'(v[18]);
      expect_fault=v[19];inject_error=expect_fault!=0;error_injected=0;ntiles=v[20];
      @(negedge clk);cfg_valid=1;
      do @(posedge clk); while(!cfg_ready);
      @(negedge clk);cfg_valid=0;
      // Drive unrelated values after handshake: active configuration must be latched.
      cfg='0;
      if(error)$fatal(1,"valid cfg rejected");
      for(ti=0;ti<ntiles;ti++) begin
        for(int j=0;j<4;j++) begin rc=$fscanf(fd,"%d",v[j]);if(rc!=1)$fatal(1,"bad tile");end
        tile_p0=32'(v[0]);tile_q0=32'(v[1]);tile_rows=RW'(v[2]);tile_slot=3'(v[3]);
        active_rows=v[2];expected_slot=v[3];written=0;
        for(int r=0;r<SIZE;r++) for(int c=0;c<SIZE;c++) seen[r][c]=0;
        for(int r=0;r<active_rows;r++) for(int c=0;c<SIZE;c++) begin
          rc=$fscanf(fd,"%d",expected[r][c]);if(rc!=1)$fatal(1,"bad expected matrix");
        end
        @(negedge clk);tile_valid=1;
        do @(posedge clk);while(!tile_ready);
        @(negedge clk);tile_valid=0;
        do @(posedge clk);while(!tile_done && !tile_error);
        if(expect_fault!=0) begin
          if(!tile_error || !error || tile_done)$fatal(1,"read error not propagated");
        end else begin
          if(tile_error || error)$fatal(1,"unexpected frontend error");
          if(written!=active_rows*SIZE)$fatal(1,"missing tile outputs");
        end
        @(negedge clk);
      end
      if (64'(stat_read_bytes) != bus_byte_count-job_bus_start)
        $fatal(1,"read byte counter mismatch");
      if (mem_active || rvalid) $fatal(1,"job ended without draining accepted reads");
      $display("RTL_FRONTEND_JOB_PASS job=%0d tiles=%0d hits=%0d misses=%0d read_bytes=%0d fault=%0d",
        job,ntiles,stat_hits,stat_misses,stat_read_bytes,expect_fault);
    end
    $fclose(fd);
    $display("RTL_FRONTEND_PASS jobs=%0d cycles=%0d cache_sets=%0d cache_ways=%0d line_bytes=%0d tile_path=%0d (not upstream full NPU)",jobs,cycles,CACHE_SETS,CACHE_WAYS,LINE_BYTES,USE_TILE_PATH);
    $finish;
  end
endmodule
