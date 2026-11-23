module receive_write_tb;
  bit clk = 0;
  always #5 clk = ~clk;
  logic rst_n = 0, compact_mode = 0;
  logic signed [15:0] compact_offset = 0;
  logic [2:0] wr_slot = 0;
  logic [3:0] wr_row = 0, wr_col_base = 0;
  logic signed [15:0] wr_data [8];
  logic wr_valid [8];
  logic [4:0] slot_rows [8];
  wire [1:0] en;
  wire [9:0] addr [0:1];
  wire [127:0] data [0:1], shared;
  wire [15:0] mask [0:1];
  logic [127:0] expected_data [2], held_data [2], expected_shared, held_shared;
  logic [15:0] expected_mask [2], held_mask [2];
  logic [9:0] expected_addr [2], held_addr [2];
  logic [1:0] expected_en;
  bit [1:0] initialized_port = 0;
  bit initialized_shared = 0;
  integer col, source, n;

  ia_loader_cache_mgr #(.DATA_WIDTH(16), .SIZE(16), .BUS_WIDTH(64),
      .CACHE_BLOCKS(4), .RAM_WORD_ADDR_WIDTH(10),
      .p_dma_source_layout(1), .p_shared_write_stage(1)) dut (
    .clk, .rst_n, .compact_mode, .compact_offset, .cfg_cache_blocks(32'd0),
    .slot_base(3'd0), .ram_port_wr_en(en), .ram_port_wr_addr(addr),
    .ram_port_wr_data(data), .ram_port_wr_mask(mask), .ram_shared_wr_data(shared),
    .ram_port_rd_en(), .ram_port_rd_addr(), .ram_port_rd_data('{default:'0}),
    .wr_slot, .wr_row, .wr_col_base, .wr_data, .wr_valid, .wr_use_16bits(1'b0),
    .l1_start(1'b0), .l1_slot_start(3'd0), .l1_slot_end(3'd0),
    .l1_is_init(1'b0), .l1_calc_done(1'b0), .slot_rows,
    .tile_done(), .l1_done(), .ia_tile_start(), .ia_out(), .ia_row_valid(),
    .ia_is_init_data(), .ia_calc_done()
  );

  initial begin
    for (int i=0; i<8; i++) begin wr_data[i]=0; wr_valid[i]=0; slot_rows[i]=1; end
    for (int p=0; p<2; p++) begin held_data[p]='0; held_mask[p]='0; held_addr[p]='0; end
    held_shared='0;
    repeat (2) @(negedge clk);
    rst_n=1;
    for (n=0; n<85536; n++) begin
      compact_mode=(n<65536) ? 1'b1 : 1'($urandom);
      compact_offset=(n<65536) ? 16'(n >> 8) : 16'($urandom);
      wr_slot=3'($urandom); wr_row=4'($urandom);
      wr_col_base=4'($urandom);
      for (int i=0; i<8; i++) begin
        wr_data[i]=(n<65536) ? 16'(n) : 16'($urandom);
        wr_valid[i]=(n<65536) ? 1'b1 : (n%37==0 ? 1'b0 : 1'($urandom));
      end
      expected_en='0;
      for (int p=0; p<2; p++) begin expected_data[p]='0; expected_mask[p]='0; end
      expected_addr[0]=10'(({wr_slot,wr_row}) << (compact_mode ? 0 : 1));
      expected_addr[1]=expected_addr[0]+10'd1;
      for (col=0; col<16; col++) begin
        source=col-int'(wr_col_base);
        if (compact_mode) begin
          expected_data[0][col*8 +: 8]=8'(-compact_offset);
          if (source>=0 && source<8 && wr_valid[source]) begin
            expected_mask[0][col]=1;
            expected_data[0][col*8 +: 8]=8'(wr_data[source]-compact_offset);
          end
        end else if (source>=0 && source<8 && wr_valid[source]) begin
          expected_data[col/8][(col%8)*16 +: 16]=wr_data[source];
          expected_mask[col/8][(col%8)*2 +: 2]=2'b11;
        end
      end
      expected_en[0]=|expected_mask[0]; expected_en[1]=|expected_mask[1];
      expected_shared=expected_en[1] ? expected_data[1] : expected_data[0];
      for (int p=0; p<2; p++) if (expected_en[p]) begin
        held_data[p]=expected_data[p]; held_mask[p]=expected_mask[p]; held_addr[p]=expected_addr[p];
        initialized_port[p]=1;
      end
      if (|expected_en) begin held_shared=expected_shared; initialized_shared=1; end
      @(posedge clk); #1;
      if (en !== expected_en) $fatal(1,"enable mismatch iteration %0d",n);
      for (int p=0; p<2; p++) begin
        if (initialized_port[p] && (mask[p] !== held_mask[p] || addr[p] !== held_addr[p]))
          $fatal(1,"write metadata mismatch iteration %0d port %0d",n,p);
        if (en[p] && data[p] !== expected_data[p])
          $fatal(1,"write payload mismatch iteration %0d port %0d",n,p);
      end
      if ((|en) && shared !== expected_shared)
        $fatal(1,"shared write payload mismatch iteration %0d",n);
      @(negedge clk);
    end
    $display("PASS: 65536 exhaustive byte/offset pairs and 20000 random write cycles");
    $finish;
  end
endmodule
