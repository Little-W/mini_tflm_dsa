module tb_block_dma;
  localparam int SIZE         = 8;
  localparam int DATA_WIDTH   = 32;
  localparam int BUS_WIDTH    = 32;
  localparam int REG_WIDTH    = 32;
  localparam int CACHE_BLOCKS = 4;

  logic clk = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic start;
  logic is_write;
  logic linear_read_mode;
  logic [REG_WIDTH-1:0] tile_base_addr;
  logic [REG_WIDTH-1:0] row_stride;
  logic [REG_WIDTH-1:0] rows_to_read;
  logic [3:0] burst_len_m1;
  logic [$clog2(CACHE_BLOCKS)-1:0] slot_id;
  logic use_16bits;
  logic signed [REG_WIDTH-1:0] lhs_zp;
  logic busy;
  logic tile_done;

  logic [BUS_WIDTH-1:0] src_wdata;
  logic [BUS_WIDTH/8-1:0] src_wmask;
  logic src_wvalid;
  logic src_wready;

  logic icb_cmd_valid;
  logic icb_cmd_ready;
  logic icb_cmd_read;
  logic [REG_WIDTH-1:0] icb_cmd_addr;
  logic [3:0] icb_cmd_len;
	  logic [BUS_WIDTH-1:0] icb_cmd_wdata;
	  logic [BUS_WIDTH/8-1:0] icb_cmd_wmask;
	  logic icb_w_valid;
	  logic icb_w_ready = 1'b1;
	  logic icb_rsp_valid;
  logic icb_rsp_ready;
  logic [BUS_WIDTH-1:0] icb_rsp_rdata;
  logic icb_rsp_err;

  logic [$clog2(CACHE_BLOCKS)-1:0] wr_slot;
  logic [$clog2(SIZE)-1:0] wr_row;
  logic [$clog2(SIZE)-1:0] wr_col_base;
  logic signed [DATA_WIDTH-1:0] wr_data [BUS_WIDTH/8];
	  logic wr_valid [BUS_WIDTH/8];
	  logic wr_use_16bits;
	  logic [BUS_WIDTH-1:0] rd_raw_data;
	  logic rd_raw_valid;
	  logic [$clog2(SIZE)-1:0] rd_raw_row;
	  logic [$clog2(SIZE)-1:0] rd_raw_col_base;

  block_dma #(
    .DATA_WIDTH(DATA_WIDTH),
    .SIZE(SIZE),
    .BUS_WIDTH(BUS_WIDTH),
    .REG_WIDTH(REG_WIDTH),
    .CACHE_BLOCKS(CACHE_BLOCKS)
  ) u_dma (
    .clk(clk),
    .rst_n(rst_n),
    .start(start),
    .is_write(is_write),
    .linear_read_mode(linear_read_mode),
    .tile_base_addr(tile_base_addr),
    .row_stride(row_stride),
    .rows_to_read(rows_to_read),
    .burst_len_m1(burst_len_m1),
    .slot_id(slot_id),
    .use_16bits(use_16bits),
    .lhs_zp(lhs_zp),
    .busy(busy),
    .tile_done(tile_done),
    .src_wdata(src_wdata),
    .src_wmask(src_wmask),
    .src_wvalid(src_wvalid),
    .src_wready(src_wready),
    .icb_cmd_valid(icb_cmd_valid),
    .icb_cmd_ready(icb_cmd_ready),
    .icb_cmd_read(icb_cmd_read),
    .icb_cmd_addr(icb_cmd_addr),
	    .icb_cmd_len(icb_cmd_len),
	    .icb_cmd_wdata(icb_cmd_wdata),
	    .icb_cmd_wmask(icb_cmd_wmask),
	    .icb_w_valid(icb_w_valid),
	    .icb_w_ready(icb_w_ready),
	    .icb_rsp_valid(icb_rsp_valid),
    .icb_rsp_ready(icb_rsp_ready),
    .icb_rsp_rdata(icb_rsp_rdata),
    .icb_rsp_err(icb_rsp_err),
    .wr_slot(wr_slot),
    .wr_row(wr_row),
    .wr_col_base(wr_col_base),
	    .wr_data(wr_data),
	    .wr_valid(wr_valid),
	    .wr_use_16bits(wr_use_16bits),
	    .rd_raw_data(rd_raw_data),
	    .rd_raw_valid(rd_raw_valid),
	    .rd_raw_row(rd_raw_row),
	    .rd_raw_col_base(rd_raw_col_base)
	  );

  tb_sram_model #(
    .DEPTH(256),
    .DATA_W(BUS_WIDTH),
    .ADDR_W(REG_WIDTH),
    .INIT_FILE("init.mem")
  ) u_sram (
    .clk(clk),
    .rst_n(rst_n),
    .cmd_valid(icb_cmd_valid),
    .cmd_ready(icb_cmd_ready),
    .cmd_addr(icb_cmd_addr),
    .cmd_read(icb_cmd_read),
	    .cmd_wdata(icb_cmd_wdata),
	    .cmd_wmask(icb_cmd_wmask),
	    .rsp_valid(icb_rsp_valid),
    .rsp_ready(icb_rsp_ready),
    .rsp_rdata(icb_rsp_rdata),
    .rsp_err(icb_rsp_err)
  );

  task automatic pulse_start();
    @(posedge clk);
    start <= 1'b1;
    @(posedge clk);
    start <= 1'b0;
  endtask

  task automatic send_write_beat(input logic [31:0] data);
    begin
      while (!src_wready) @(posedge clk);
      src_wdata  <= data;
      src_wmask  <= 4'hF;
      src_wvalid <= 1'b1;
      @(posedge clk);
      src_wvalid <= 1'b0;
      src_wdata  <= '0;
      src_wmask  <= '0;
    end
  endtask

  int rd_cnt;
  int rd_beat_cnt;
  logic signed [DATA_WIDTH-1:0] rd_cap[0:3];
  int rd_beat_row[0:3];
  int rd_beat_col[0:3];

  task automatic clear_capture();
    begin
      rd_cnt = 0;
      rd_beat_cnt = 0;
      foreach (rd_cap[i]) begin
        rd_cap[i] = '0;
        rd_beat_row[i] = 0;
        rd_beat_col[i] = 0;
      end
    end
  endtask

  always @(posedge clk) begin
    int next_idx;
    next_idx = rd_cnt;
    if (wr_valid[0]) begin
      rd_beat_row[rd_beat_cnt] <= wr_row;
      rd_beat_col[rd_beat_cnt] <= wr_col_base;
      rd_beat_cnt <= rd_beat_cnt + 1;
      rd_cap[next_idx] <= wr_data[0];
      next_idx = next_idx + 1;
    end
    if (wr_valid[1]) begin
      rd_cap[next_idx] <= wr_data[1];
      next_idx = next_idx + 1;
    end
    rd_cnt <= next_idx;
  end

  initial begin
    start = 0;
    is_write = 0;
    linear_read_mode = 1'b0;
    tile_base_addr = '0;
    row_stride = '0;
    rows_to_read = '0;
    burst_len_m1 = '0;
    slot_id = '0;
    use_16bits = 1'b1;
    lhs_zp = '0;
    src_wdata = '0;
    src_wmask = '0;
    src_wvalid = 1'b0;
    clear_capture();

    rst_n = 0;
    repeat (5) @(posedge clk);

    // 预置读测试数据：2行，每行1个beat，16bitx2；
    // DUT 输出宽度提升到 32 位后，这里验证的是 sign-extend 后的 32-bit 结果。
    u_sram.mem[0] = 32'h0002_0001;
    u_sram.mem[1] = 32'h0004_0003;

    rst_n = 1;
    repeat (2) @(posedge clk);

    // ---------------- read block case ----------------
    is_write      = 1'b0;
    linear_read_mode = 1'b0;
    tile_base_addr= 32'h0000_0000;
    row_stride    = 32'd4;
    rows_to_read  = 32'd2;
    burst_len_m1  = 4'd0;
    slot_id       = '0;
    use_16bits    = 1'b1;
    lhs_zp        = 32'sd0;
    pulse_start();

    wait (tile_done);
    repeat (2) @(posedge clk);

    if (rd_cnt != 4 || rd_beat_cnt != 2 || rd_cap[0] != 32'sd1 || rd_cap[1] != 32'sd2 || rd_cap[2] != 32'sd3 || rd_cap[3] != 32'sd4 || rd_beat_row[0] != 0 || rd_beat_row[1] != 1 || rd_beat_col[0] != 0 || rd_beat_col[1] != 0) begin
      $display("[BLOCK_DMA][READ] FAIL rd_cnt=%0d beat_cnt=%0d cap=%0d,%0d,%0d,%0d row=%0d,%0d col=%0d,%0d", rd_cnt, rd_beat_cnt, rd_cap[0], rd_cap[1], rd_cap[2], rd_cap[3], rd_beat_row[0], rd_beat_row[1], rd_beat_col[0], rd_beat_col[1]);
      $finish;
    end else begin
      $display("[BLOCK_DMA][READ] PASS");
    end

    clear_capture();

    // ---------------- linear 1D read case ----------------
    u_sram.mem[8] = 32'h0006_0005;
    u_sram.mem[9] = 32'h0008_0007;

    is_write         = 1'b0;
    linear_read_mode = 1'b1;
    tile_base_addr   = 32'h0000_0020; // word index 8
    row_stride       = 32'd4;
    rows_to_read     = 32'd2;
    burst_len_m1     = 4'd0;
    use_16bits       = 1'b1;
    lhs_zp           = 32'sd0;
    pulse_start();

    wait (tile_done);
    repeat (2) @(posedge clk);

    if (rd_cnt != 4 || rd_beat_cnt != 2 || rd_cap[0] != 32'sd5 || rd_cap[1] != 32'sd6 || rd_cap[2] != 32'sd7 || rd_cap[3] != 32'sd8 || rd_beat_row[0] != 0 || rd_beat_row[1] != 0 || rd_beat_col[0] != 0 || rd_beat_col[1] != 2) begin
      $display("[BLOCK_DMA][READ1D] FAIL rd_cnt=%0d beat_cnt=%0d cap=%0d,%0d,%0d,%0d row=%0d,%0d col=%0d,%0d", rd_cnt, rd_beat_cnt, rd_cap[0], rd_cap[1], rd_cap[2], rd_cap[3], rd_beat_row[0], rd_beat_row[1], rd_beat_col[0], rd_beat_col[1]);
      $finish;
    end else begin
      $display("[BLOCK_DMA][READ1D] PASS");
    end

    // ---------------- write block case ----------------
    is_write      = 1'b1;
    linear_read_mode = 1'b0;
    tile_base_addr= 32'h0000_0040; // word index 16
    row_stride    = 32'd4;
    rows_to_read  = 32'd2;
    burst_len_m1  = 4'd0;
    use_16bits    = 1'b1;
    pulse_start();

    send_write_beat(32'h1122_3344);
    send_write_beat(32'h5566_7788);

    wait (tile_done);
    @(posedge clk);

    if (u_sram.mem[16] != 32'h1122_3344 || u_sram.mem[17] != 32'h5566_7788) begin
      $display("[BLOCK_DMA][WRITE] FAIL mem16=%08x mem17=%08x", u_sram.mem[16], u_sram.mem[17]);
      $finish;
    end else begin
      $display("[BLOCK_DMA][WRITE] PASS");
    end

    $display("[BLOCK_DMA] ALL PASS");
    repeat (10) @(posedge clk);
    $finish;
  end

  initial begin
    #2000000;
    $display("[BLOCK_DMA] TIMEOUT");
    $finish;
  end

endmodule
