module tb_axi_dual_block_dma;
  localparam int SIZE = 8;
  localparam int DATA_WIDTH = 32;
  localparam int BUS_WIDTH = 32;
  localparam int REG_WIDTH = 32;
  localparam int CACHE_BLOCKS = 4;
  localparam int MEM_DEPTH = 256;

  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic rd_start;
  logic rd_linear_read_mode;
  logic [REG_WIDTH-1:0] rd_base_addr;
  logic [REG_WIDTH-1:0] rd_row_stride;
  logic [REG_WIDTH-1:0] rd_rows_to_read;
  logic [REG_WIDTH-1:0] rd_valid_cols;
  logic [3:0] rd_burst_len_m1;
  logic [$clog2(CACHE_BLOCKS)-1:0] rd_slot_id;
  logic rd_use_16bits;
  logic signed [REG_WIDTH-1:0] rd_lhs_zp;
  logic rd_busy;
  logic rd_done;

  logic wr_start;
  logic [REG_WIDTH-1:0] wr_base_addr;
  logic [REG_WIDTH-1:0] wr_row_stride;
  logic [REG_WIDTH-1:0] wr_rows_to_write;
  logic [3:0] wr_burst_len_m1;
  logic wr_busy;
  logic wr_done;

  logic [BUS_WIDTH-1:0] src_wdata;
  logic [BUS_WIDTH/8-1:0] src_wmask;
  logic src_wvalid;
  logic src_wready;

  logic m_axi_arvalid;
  logic m_axi_arready;
  logic [REG_WIDTH-1:0] m_axi_araddr;
  logic [7:0] m_axi_arlen;
  logic [2:0] m_axi_arsize;
  logic [1:0] m_axi_arburst;
  logic m_axi_rvalid;
  logic m_axi_rready;
  logic [BUS_WIDTH-1:0] m_axi_rdata;
  logic [1:0] m_axi_rresp;
  logic m_axi_rlast;
  logic m_axi_awvalid;
  logic m_axi_awready;
  logic [REG_WIDTH-1:0] m_axi_awaddr;
  logic [7:0] m_axi_awlen;
  logic [2:0] m_axi_awsize;
  logic [1:0] m_axi_awburst;
  logic m_axi_wvalid;
  logic m_axi_wready;
  logic [BUS_WIDTH-1:0] m_axi_wdata;
  logic [BUS_WIDTH/8-1:0] m_axi_wstrb;
  logic m_axi_wlast;
  logic m_axi_bvalid;
  logic m_axi_bready;
  logic [1:0] m_axi_bresp;

  logic [$clog2(CACHE_BLOCKS)-1:0] rd_wr_slot;
  logic [$clog2(SIZE)-1:0] rd_wr_row;
  logic [$clog2(SIZE)-1:0] rd_wr_col_base;
  logic signed [DATA_WIDTH-1:0] rd_wr_data [BUS_WIDTH/8];
  logic rd_wr_valid [BUS_WIDTH/8];
  logic rd_wr_use_16bits;
  logic [BUS_WIDTH-1:0] rd_raw_data;
  logic rd_raw_valid;
  logic [$clog2(SIZE)-1:0] rd_raw_row;
  logic [$clog2(SIZE)-1:0] rd_raw_col_base;
  logic rd_error;
  logic wr_error;

  logic [BUS_WIDTH-1:0] mem [0:MEM_DEPTH-1];

  axi_dual_block_dma #(
    .DATA_WIDTH(DATA_WIDTH),
    .SIZE(SIZE),
    .BUS_WIDTH(BUS_WIDTH),
    .REG_WIDTH(REG_WIDTH),
    .CACHE_BLOCKS(CACHE_BLOCKS)
  ) u_dma (
    .clk(clk),
    .rst_n(rst_n),
    .rd_start(rd_start),
    .rd_linear_read_mode(rd_linear_read_mode),
    .rd_base_addr(rd_base_addr),
    .rd_row_stride(rd_row_stride),
    .rd_rows_to_read(rd_rows_to_read),
    .rd_valid_cols(rd_valid_cols),
    .rd_burst_len_m1(rd_burst_len_m1),
    .rd_slot_id(rd_slot_id),
    .rd_use_16bits(rd_use_16bits),
    .rd_lhs_zp(rd_lhs_zp),
    .rd_busy(rd_busy),
    .rd_done(rd_done),
    .wr_start(wr_start),
    .wr_base_addr(wr_base_addr),
    .wr_row_stride(wr_row_stride),
    .wr_rows_to_write(wr_rows_to_write),
    .wr_burst_len_m1(wr_burst_len_m1),
    .wr_busy(wr_busy),
    .wr_done(wr_done),
    .src_wdata(src_wdata),
    .src_wmask(src_wmask),
    .src_wvalid(src_wvalid),
    .src_wready(src_wready),
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
    .m_axi_bresp(m_axi_bresp),
    .wr_slot(rd_wr_slot),
    .wr_row(rd_wr_row),
    .wr_col_base(rd_wr_col_base),
    .wr_data(rd_wr_data),
    .wr_valid(rd_wr_valid),
    .wr_use_16bits(rd_wr_use_16bits),
    .rd_raw_data(rd_raw_data),
    .rd_raw_valid(rd_raw_valid),
    .rd_raw_row(rd_raw_row),
    .rd_raw_col_base(rd_raw_col_base),
    .rd_error(rd_error),
    .wr_error(wr_error)
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
        if ((wr_mem_addr >> 2) < REG_WIDTH'(MEM_DEPTH)) begin
          for (int b = 0; b < BUS_WIDTH / 8; b++) begin
            if (m_axi_wstrb[b]) begin
              mem[wr_mem_addr >> 2][b*8 +: 8] <= m_axi_wdata[b*8 +: 8];
            end
          end
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

      if (b_hs) begin
        m_axi_bvalid <= 1'b0;
      end
    end
  end

  task automatic pulse_start();
    begin
      @(posedge clk);
      rd_start <= 1'b1;
      wr_start <= 1'b1;
      @(posedge clk);
      rd_start <= 1'b0;
      wr_start <= 1'b0;
    end
  endtask

  task automatic send_write_beat(input logic [31:0] data);
    begin
      while (!src_wready) @(posedge clk);
      src_wdata <= data;
      src_wmask <= 4'hF;
      src_wvalid <= 1'b1;
      @(posedge clk);
      src_wvalid <= 1'b0;
      src_wdata <= '0;
      src_wmask <= '0;
    end
  endtask

  int rd_cnt;
  logic signed [DATA_WIDTH-1:0] rd_cap [0:3];
  int rd_rows [0:1];
  logic rd_done_seen;
  logic wr_done_seen;

  always_ff @(posedge clk) begin
    int idx;
    idx = rd_cnt;
    if (!rst_n) begin
      rd_done_seen <= 1'b0;
      wr_done_seen <= 1'b0;
    end else begin
      if (rd_done) rd_done_seen <= 1'b1;
      if (wr_done) wr_done_seen <= 1'b1;
    end
    if (rd_wr_valid[0]) begin
      rd_cap[idx] <= rd_wr_data[0];
      idx = idx + 1;
    end
    if (rd_wr_valid[1]) begin
      rd_cap[idx] <= rd_wr_data[1];
      idx = idx + 1;
    end
    rd_cnt <= idx;
    if (rd_wr_valid[0] && rd_wr_col_base == '0) begin
      rd_rows[rd_wr_row] <= rd_wr_row;
    end
  end

  initial begin
    rd_start = 1'b0;
    rd_linear_read_mode = 1'b0;
    rd_base_addr = 32'h0;
    rd_row_stride = 32'd4;
    rd_rows_to_read = 32'd2;
    rd_valid_cols = 32'd2;
    rd_burst_len_m1 = 4'd0;
    rd_slot_id = '0;
    rd_use_16bits = 1'b1;
    rd_lhs_zp = '0;

    wr_start = 1'b0;
    wr_base_addr = 32'h40;
    wr_row_stride = 32'd8;
    wr_rows_to_write = 32'd2;
    wr_burst_len_m1 = 4'd1;
    src_wdata = '0;
    src_wmask = '0;
    src_wvalid = 1'b0;
    rd_cnt = 0;
    rd_done_seen = 1'b0;
    wr_done_seen = 1'b0;
    foreach (rd_cap[i]) rd_cap[i] = '0;
    foreach (rd_rows[i]) rd_rows[i] = -1;
    for (int i = 0; i < MEM_DEPTH; i++) mem[i] = '0;
    mem[0] = 32'h0002_0001;
    mem[1] = 32'h0004_0003;

    rst_n = 1'b0;
    repeat (5) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    pulse_start();

    fork
      begin
        send_write_beat(32'h1122_3344);
        send_write_beat(32'h5566_7788);
        send_write_beat(32'h99aa_bbcc);
        send_write_beat(32'hddee_ff00);
      end
    join_none

    wait (rd_done_seen && wr_done_seen);
    repeat (2) @(posedge clk);

    if (rd_error || wr_error) begin
      $display("[AXI_DUAL_DMA] FAIL err rd=%0b wr=%0b", rd_error, wr_error);
      $finish;
    end
    if (rd_cnt != 4 || rd_cap[0] != 32'sd1 || rd_cap[1] != 32'sd2 ||
        rd_cap[2] != 32'sd3 || rd_cap[3] != 32'sd4) begin
      $display("[AXI_DUAL_DMA][READ] FAIL cnt=%0d cap=%0d,%0d,%0d,%0d",
               rd_cnt, rd_cap[0], rd_cap[1], rd_cap[2], rd_cap[3]);
      $finish;
    end
    if (mem[16] != 32'h1122_3344 || mem[17] != 32'h5566_7788 ||
        mem[18] != 32'h99aa_bbcc || mem[19] != 32'hddee_ff00) begin
      $display("[AXI_DUAL_DMA][WRITE] FAIL mem=%08x,%08x,%08x,%08x",
               mem[16], mem[17], mem[18], mem[19]);
      $finish;
    end

    $display("[AXI_DUAL_DMA] ALL PASS");
    repeat (5) @(posedge clk);
    $finish;
  end

  initial begin
    #2000000;
    $display("[AXI_DUAL_DMA] TIMEOUT");
    $finish;
  end
endmodule
