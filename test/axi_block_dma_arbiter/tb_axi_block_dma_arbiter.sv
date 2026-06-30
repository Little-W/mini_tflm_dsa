module tb_axi_block_dma_arbiter;
  localparam int SIZE = 8;
  localparam int DATA_WIDTH = 32;
  localparam int KERNEL_WIDTH = 32;
  localparam int BUS_WIDTH = 32;
  localparam int REG_WIDTH = 32;
  localparam int CACHE_BLOCKS = 4;
  localparam int MEM_DEPTH = 256;

  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic ia_req, ia_granted, ia_start, ia_busy, ia_done;
  logic ia_is_write, ia_linear_read_mode, ia_use_16bits;
  logic [REG_WIDTH-1:0] ia_base_addr, ia_row_stride, ia_rows_to_read;
  logic [3:0] ia_burst_len_m1;
  logic [$clog2(CACHE_BLOCKS)-1:0] ia_slot_id;
  logic signed [REG_WIDTH-1:0] ia_lhs_zp;
  logic [$clog2(CACHE_BLOCKS)-1:0] ia_wr_slot;
  logic [$clog2(SIZE)-1:0] ia_wr_row, ia_wr_col_base;
  logic signed [DATA_WIDTH-1:0] ia_wr_data [BUS_WIDTH/8];
  logic ia_wr_valid [BUS_WIDTH/8];
  logic ia_wr_use_16bits;

  logic kernel_req, kernel_granted, kernel_start, kernel_busy, kernel_done;
  logic kernel_is_write, kernel_linear_read_mode, kernel_use_16bits, kernel_slot_id;
  logic [REG_WIDTH-1:0] kernel_base_addr, kernel_row_stride, kernel_rows_to_read;
  logic [3:0] kernel_burst_len_m1;
  logic signed [REG_WIDTH-1:0] kernel_lhs_zp;
  logic [$clog2(SIZE)-1:0] kernel_wr_row, kernel_wr_col_base;
  logic signed [KERNEL_WIDTH-1:0] kernel_wr_data [BUS_WIDTH/8];
  logic kernel_wr_valid [BUS_WIDTH/8];

  logic bias_req, bias_granted, bias_start, bias_busy, bias_done;
  logic bias_is_write, bias_linear_read_mode, bias_use_16bits, bias_slot_id;
  logic [REG_WIDTH-1:0] bias_base_addr, bias_row_stride, bias_rows_to_read;
  logic [3:0] bias_burst_len_m1;
  logic signed [REG_WIDTH-1:0] bias_lhs_zp;
  logic bias_wr_slot, bias_wr_use_16bits;
  logic [$clog2(SIZE)-1:0] bias_wr_row, bias_wr_col_base;
  logic signed [7:0] bias_wr_data [BUS_WIDTH/8];
  logic bias_wr_valid [BUS_WIDTH/8];

  logic quant_req, quant_granted, quant_start, quant_busy, quant_done;
  logic quant_is_write, quant_linear_read_mode, quant_use_16bits, quant_slot_id;
  logic [REG_WIDTH-1:0] quant_base_addr, quant_row_stride, quant_rows_to_read;
  logic [3:0] quant_burst_len_m1;
  logic signed [REG_WIDTH-1:0] quant_lhs_zp;
  logic [BUS_WIDTH-1:0] quant_raw_data;
  logic quant_raw_valid;

  logic oa_req, oa_granted, oa_start, oa_busy, oa_done;
  logic oa_is_write, oa_linear_read_mode, oa_use_16bits, oa_slot_id;
  logic [REG_WIDTH-1:0] oa_base_addr, oa_row_stride, oa_rows_to_read;
  logic [3:0] oa_burst_len_m1;
  logic signed [REG_WIDTH-1:0] oa_lhs_zp;
  logic [BUS_WIDTH-1:0] oa_src_wdata;
  logic [BUS_WIDTH/8-1:0] oa_src_wmask;
  logic oa_src_wvalid, oa_src_wready;

  logic m_axi_arvalid, m_axi_arready;
  logic [REG_WIDTH-1:0] m_axi_araddr;
  logic [7:0] m_axi_arlen;
  logic [2:0] m_axi_arsize;
  logic [1:0] m_axi_arburst;
  logic m_axi_rvalid, m_axi_rready;
  logic [BUS_WIDTH-1:0] m_axi_rdata;
  logic [1:0] m_axi_rresp;
  logic m_axi_rlast;
  logic m_axi_awvalid, m_axi_awready;
  logic [REG_WIDTH-1:0] m_axi_awaddr;
  logic [7:0] m_axi_awlen;
  logic [2:0] m_axi_awsize;
  logic [1:0] m_axi_awburst;
  logic m_axi_wvalid, m_axi_wready;
  logic [BUS_WIDTH-1:0] m_axi_wdata;
  logic [BUS_WIDTH/8-1:0] m_axi_wstrb;
  logic m_axi_wlast;
  logic m_axi_bvalid, m_axi_bready;
  logic [1:0] m_axi_bresp;

  logic [BUS_WIDTH-1:0] mem [0:MEM_DEPTH-1];

  axi_block_dma_arbiter #(
    .DATA_WIDTH(DATA_WIDTH),
    .KERNEL_WIDTH(KERNEL_WIDTH),
    .SIZE(SIZE),
    .DMA_SIZE(SIZE),
    .BUS_WIDTH(BUS_WIDTH),
    .REG_WIDTH(REG_WIDTH),
    .CACHE_BLOCKS(CACHE_BLOCKS)
  ) u_arb (
    .clk(clk),
    .rst_n(rst_n),
    .ia_req(ia_req),
    .ia_granted(ia_granted),
    .ia_start(ia_start),
    .ia_is_write(ia_is_write),
    .ia_linear_read_mode(ia_linear_read_mode),
    .ia_base_addr(ia_base_addr),
    .ia_row_stride(ia_row_stride),
    .ia_rows_to_read(ia_rows_to_read),
    .ia_burst_len_m1(ia_burst_len_m1),
    .ia_slot_id(ia_slot_id),
    .ia_use_16bits(ia_use_16bits),
    .ia_lhs_zp(ia_lhs_zp),
    .ia_busy(ia_busy),
    .ia_done(ia_done),
    .ia_wr_slot(ia_wr_slot),
    .ia_wr_row(ia_wr_row),
    .ia_wr_col_base(ia_wr_col_base),
    .ia_wr_data(ia_wr_data),
    .ia_wr_valid(ia_wr_valid),
    .ia_wr_use_16bits(ia_wr_use_16bits),
    .kernel_req(kernel_req),
    .kernel_granted(kernel_granted),
    .kernel_start(kernel_start),
    .kernel_is_write(kernel_is_write),
    .kernel_linear_read_mode(kernel_linear_read_mode),
    .kernel_base_addr(kernel_base_addr),
    .kernel_row_stride(kernel_row_stride),
    .kernel_rows_to_read(kernel_rows_to_read),
    .kernel_burst_len_m1(kernel_burst_len_m1),
    .kernel_slot_id(kernel_slot_id),
    .kernel_use_16bits(kernel_use_16bits),
    .kernel_lhs_zp(kernel_lhs_zp),
    .kernel_busy(kernel_busy),
    .kernel_done(kernel_done),
    .kernel_wr_row(kernel_wr_row),
    .kernel_wr_col_base(kernel_wr_col_base),
    .kernel_wr_data(kernel_wr_data),
    .kernel_wr_valid(kernel_wr_valid),
    .bias_req(bias_req),
    .bias_granted(bias_granted),
    .bias_start(bias_start),
    .bias_is_write(bias_is_write),
    .bias_linear_read_mode(bias_linear_read_mode),
    .bias_base_addr(bias_base_addr),
    .bias_row_stride(bias_row_stride),
    .bias_rows_to_read(bias_rows_to_read),
    .bias_burst_len_m1(bias_burst_len_m1),
    .bias_slot_id(bias_slot_id),
    .bias_use_16bits(bias_use_16bits),
    .bias_lhs_zp(bias_lhs_zp),
    .bias_busy(bias_busy),
    .bias_done(bias_done),
    .bias_wr_slot(bias_wr_slot),
    .bias_wr_row(bias_wr_row),
    .bias_wr_col_base(bias_wr_col_base),
    .bias_wr_data(bias_wr_data),
    .bias_wr_valid(bias_wr_valid),
    .bias_wr_use_16bits(bias_wr_use_16bits),
    .quant_req(quant_req),
    .quant_granted(quant_granted),
    .quant_start(quant_start),
    .quant_is_write(quant_is_write),
    .quant_linear_read_mode(quant_linear_read_mode),
    .quant_base_addr(quant_base_addr),
    .quant_row_stride(quant_row_stride),
    .quant_rows_to_read(quant_rows_to_read),
    .quant_burst_len_m1(quant_burst_len_m1),
    .quant_slot_id(quant_slot_id),
    .quant_use_16bits(quant_use_16bits),
    .quant_lhs_zp(quant_lhs_zp),
    .quant_busy(quant_busy),
    .quant_done(quant_done),
    .quant_raw_data(quant_raw_data),
    .quant_raw_valid(quant_raw_valid),
    .oa_req(oa_req),
    .oa_granted(oa_granted),
    .oa_start(oa_start),
    .oa_is_write(oa_is_write),
    .oa_linear_read_mode(oa_linear_read_mode),
    .oa_base_addr(oa_base_addr),
    .oa_row_stride(oa_row_stride),
    .oa_rows_to_read(oa_rows_to_read),
    .oa_burst_len_m1(oa_burst_len_m1),
    .oa_slot_id(oa_slot_id),
    .oa_use_16bits(oa_use_16bits),
    .oa_lhs_zp(oa_lhs_zp),
    .oa_src_wdata(oa_src_wdata),
    .oa_src_wmask(oa_src_wmask),
    .oa_src_wvalid(oa_src_wvalid),
    .oa_src_wready(oa_src_wready),
    .oa_busy(oa_busy),
    .oa_done(oa_done),
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
    .m_axi_bresp(m_axi_bresp)
  );

  logic rd_mem_active;
  logic [REG_WIDTH-1:0] rd_mem_addr;
  logic [8:0] rd_mem_left;
  logic wr_mem_active;
  logic [REG_WIDTH-1:0] wr_mem_addr;
  logic [8:0] wr_mem_left;

  wire ar_hs = m_axi_arvalid && m_axi_arready;
  wire r_hs = m_axi_rvalid && m_axi_rready;
  wire aw_hs = m_axi_awvalid && m_axi_awready;
  wire w_hs = m_axi_wvalid && m_axi_wready;
  wire b_hs = m_axi_bvalid && m_axi_bready;

  assign m_axi_arready = !rd_mem_active && !m_axi_rvalid;
  assign m_axi_awready = !wr_mem_active && !m_axi_bvalid;
  assign m_axi_wready = wr_mem_active && !m_axi_bvalid;
  assign m_axi_rresp = 2'b00;
  assign m_axi_bresp = 2'b00;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rd_mem_active <= 1'b0;
      rd_mem_addr <= '0;
      rd_mem_left <= '0;
      m_axi_rvalid <= 1'b0;
      m_axi_rdata <= '0;
      m_axi_rlast <= 1'b0;
    end else begin
      if (ar_hs) begin
        rd_mem_active <= 1'b1;
        rd_mem_addr <= m_axi_araddr;
        rd_mem_left <= {1'b0, m_axi_arlen} + 9'd1;
      end
      if (r_hs) begin
        if (rd_mem_left <= 9'd1) begin
          m_axi_rvalid <= 1'b0;
          m_axi_rlast <= 1'b0;
          rd_mem_active <= 1'b0;
          rd_mem_left <= '0;
        end else begin
          rd_mem_left <= rd_mem_left - 9'd1;
          rd_mem_addr <= rd_mem_addr + REG_WIDTH'(BUS_WIDTH / 8);
          m_axi_rdata <= mem[(rd_mem_addr + REG_WIDTH'(BUS_WIDTH / 8)) >> 2];
          m_axi_rlast <= (rd_mem_left == 9'd2);
        end
      end else if (rd_mem_active && !m_axi_rvalid) begin
        m_axi_rvalid <= 1'b1;
        m_axi_rdata <= mem[rd_mem_addr >> 2];
        m_axi_rlast <= (rd_mem_left == 9'd1);
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_mem_active <= 1'b0;
      wr_mem_addr <= '0;
      wr_mem_left <= '0;
      m_axi_bvalid <= 1'b0;
    end else begin
      if (aw_hs) begin
        wr_mem_active <= 1'b1;
        wr_mem_addr <= m_axi_awaddr;
        wr_mem_left <= {1'b0, m_axi_awlen} + 9'd1;
      end
      if (w_hs) begin
        for (int b = 0; b < BUS_WIDTH / 8; b++) begin
          if (m_axi_wstrb[b]) mem[wr_mem_addr >> 2][b*8 +: 8] <= m_axi_wdata[b*8 +: 8];
        end
        if ((wr_mem_left <= 9'd1) || m_axi_wlast) begin
          wr_mem_active <= 1'b0;
          wr_mem_left <= '0;
          m_axi_bvalid <= 1'b1;
        end else begin
          wr_mem_left <= wr_mem_left - 9'd1;
          wr_mem_addr <= wr_mem_addr + REG_WIDTH'(BUS_WIDTH / 8);
        end
      end
      if (b_hs) m_axi_bvalid <= 1'b0;
    end
  end

  task automatic pulse_starts();
    begin
      wait (kernel_granted && oa_granted);
      @(posedge clk);
      kernel_start <= 1'b1;
      oa_start <= 1'b1;
      @(posedge clk);
      kernel_start <= 1'b0;
      oa_start <= 1'b0;
    end
  endtask

  task automatic send_write_beat(input logic [31:0] data);
    begin
      while (!oa_src_wready) @(posedge clk);
      oa_src_wdata <= data;
      oa_src_wmask <= 4'hF;
      oa_src_wvalid <= 1'b1;
      @(posedge clk);
      oa_src_wvalid <= 1'b0;
      oa_src_wdata <= '0;
      oa_src_wmask <= '0;
    end
  endtask

  int rd_cnt;
  logic signed [KERNEL_WIDTH-1:0] rd_cap [0:3];
  logic kernel_done_seen;
  logic oa_done_seen;
  logic overlap_seen;

  always_ff @(posedge clk) begin
    int idx;
    idx = rd_cnt;
    if (!rst_n) begin
      kernel_done_seen <= 1'b0;
      oa_done_seen <= 1'b0;
      overlap_seen <= 1'b0;
    end else begin
      if (kernel_done) kernel_done_seen <= 1'b1;
      if (oa_done) oa_done_seen <= 1'b1;
      if (kernel_busy && oa_busy) overlap_seen <= 1'b1;
    end
    if (kernel_wr_valid[0]) begin
      rd_cap[idx] <= kernel_wr_data[0];
      idx = idx + 1;
    end
    if (kernel_wr_valid[1]) begin
      rd_cap[idx] <= kernel_wr_data[1];
      idx = idx + 1;
    end
    rd_cnt <= idx;
  end

  initial begin
    ia_req = 1'b0;
    ia_start = 1'b0;
    ia_is_write = 1'b0;
    ia_linear_read_mode = 1'b0;
    ia_base_addr = '0;
    ia_row_stride = 32'd4;
    ia_rows_to_read = '0;
    ia_burst_len_m1 = '0;
    ia_slot_id = '0;
    ia_use_16bits = 1'b1;
    ia_lhs_zp = '0;

    kernel_req = 1'b0;
    kernel_start = 1'b0;
    kernel_is_write = 1'b0;
    kernel_linear_read_mode = 1'b0;
    kernel_base_addr = 32'h0;
    kernel_row_stride = 32'd4;
    kernel_rows_to_read = 32'd2;
    kernel_burst_len_m1 = 4'd0;
    kernel_slot_id = 1'b0;
    kernel_use_16bits = 1'b1;
    kernel_lhs_zp = '0;

    bias_req = 1'b0;
    bias_start = 1'b0;
    bias_is_write = 1'b0;
    bias_linear_read_mode = 1'b0;
    bias_base_addr = '0;
    bias_row_stride = 32'd4;
    bias_rows_to_read = '0;
    bias_burst_len_m1 = '0;
    bias_slot_id = 1'b0;
    bias_use_16bits = 1'b0;
    bias_lhs_zp = '0;

    quant_req = 1'b0;
    quant_start = 1'b0;
    quant_is_write = 1'b0;
    quant_linear_read_mode = 1'b0;
    quant_base_addr = '0;
    quant_row_stride = 32'd4;
    quant_rows_to_read = '0;
    quant_burst_len_m1 = '0;
    quant_slot_id = 1'b0;
    quant_use_16bits = 1'b0;
    quant_lhs_zp = '0;

    oa_req = 1'b0;
    oa_start = 1'b0;
    oa_is_write = 1'b1;
    oa_linear_read_mode = 1'b0;
    oa_base_addr = 32'h40;
    oa_row_stride = 32'd8;
    oa_rows_to_read = 32'd2;
    oa_burst_len_m1 = 4'd1;
    oa_slot_id = 1'b0;
    oa_use_16bits = 1'b0;
    oa_lhs_zp = '0;
    oa_src_wdata = '0;
    oa_src_wmask = '0;
    oa_src_wvalid = 1'b0;

    rd_cnt = 0;
    kernel_done_seen = 1'b0;
    oa_done_seen = 1'b0;
    overlap_seen = 1'b0;
    foreach (rd_cap[i]) rd_cap[i] = '0;
    for (int i = 0; i < MEM_DEPTH; i++) mem[i] = '0;
    mem[0] = 32'h0002_0001;
    mem[1] = 32'h0004_0003;

    rst_n = 1'b0;
    repeat (5) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    kernel_req = 1'b1;
    oa_req = 1'b1;
    pulse_starts();

    fork
      begin
        send_write_beat(32'h1122_3344);
        send_write_beat(32'h5566_7788);
        send_write_beat(32'h99aa_bbcc);
        send_write_beat(32'hddee_ff00);
      end
    join_none

    wait (kernel_done_seen && oa_done_seen);
    kernel_req = 1'b0;
    oa_req = 1'b0;
    repeat (2) @(posedge clk);

    if (!overlap_seen) begin
      $display("[AXI_ARB] FAIL no read/write busy overlap observed");
      $finish;
    end
    if (rd_cnt != 4 || rd_cap[0] != 32'sd1 || rd_cap[1] != 32'sd2 ||
        rd_cap[2] != 32'sd3 || rd_cap[3] != 32'sd4) begin
      $display("[AXI_ARB][READ] FAIL cnt=%0d cap=%0d,%0d,%0d,%0d",
               rd_cnt, rd_cap[0], rd_cap[1], rd_cap[2], rd_cap[3]);
      $finish;
    end
    if (mem[16] != 32'h1122_3344 || mem[17] != 32'h5566_7788 ||
        mem[18] != 32'h99aa_bbcc || mem[19] != 32'hddee_ff00) begin
      $display("[AXI_ARB][WRITE] FAIL mem=%08x,%08x,%08x,%08x",
               mem[16], mem[17], mem[18], mem[19]);
      $finish;
    end

    $display("[AXI_ARB] ALL PASS overlap=%0b", overlap_seen);
    repeat (5) @(posedge clk);
    $finish;
  end

  initial begin
    #2000000;
    $display("[AXI_ARB] TIMEOUT");
    $finish;
  end
endmodule
