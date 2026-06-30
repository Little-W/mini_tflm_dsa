module tb_kernel_loader;

  localparam int SIZE       = 4;
  localparam int DATA_WIDTH = 8;
  localparam int BUS_WIDTH  = 32;
  localparam int REG_WIDTH  = 32;
  localparam int BYTE_PER_BEAT = BUS_WIDTH / 8;
  localparam int SIZE_W     = $clog2(SIZE);

  `include "test_params.svh"

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  kernel_loader_tb_if #(
    .SIZE       (SIZE),
    .DATA_WIDTH (DATA_WIDTH),
    .BUS_WIDTH  (BUS_WIDTH),
    .REG_WIDTH  (REG_WIDTH)
  ) tb_if (
    .clk   (clk),
    .rst_n (rst_n)
  );

  icb_bus_if #(
    .ADDR_W (REG_WIDTH),
    .DATA_W (BUS_WIDTH)
  ) sa_icb_if (
    .clk   (clk),
    .rst_n (rst_n)
  );

  icb_bus_if #(
    .ADDR_W (REG_WIDTH),
    .DATA_W (BUS_WIDTH)
  ) mem_icb_if (
    .clk   (clk),
    .rst_n (rst_n)
  );

  logic load_weight_done;
  logic dummy_ext_dma_start;
  logic dummy_ext_dma_is_write;
  logic dummy_ext_dma_linear_read_mode;
  logic [REG_WIDTH-1:0] dummy_ext_dma_base_addr;
  logic [REG_WIDTH-1:0] dummy_ext_dma_row_stride;
  logic [REG_WIDTH-1:0] dummy_ext_dma_rows_to_read;
  logic [3:0] dummy_ext_dma_burst_len_m1;
  logic dummy_ext_dma_slot_id;
  logic dummy_ext_dma_use_16bits;
  logic signed [REG_WIDTH-1:0] dummy_ext_dma_lhs_zp;
  logic [SIZE_W-1:0] dummy_ext_dma_wr_row;
  logic [SIZE_W-1:0] dummy_ext_dma_wr_col_base;
  logic signed [DATA_WIDTH-1:0] dummy_ext_dma_wr_data [BYTE_PER_BEAT];
  logic dummy_ext_dma_wr_valid[BYTE_PER_BEAT];

  always_comb begin
    dummy_ext_dma_wr_row      = '0;
    dummy_ext_dma_wr_col_base = '0;
    for (int i = 0; i < BYTE_PER_BEAT; i++) begin
      dummy_ext_dma_wr_data[i]  = '0;
      dummy_ext_dma_wr_valid[i] = 1'b0;
    end
  end

  kernel_loader #(
    .DATA_WIDTH   (DATA_WIDTH),
    .SIZE         (SIZE),
    .BUS_WIDTH    (BUS_WIDTH),
    .REG_WIDTH    (REG_WIDTH),
    .CACHE_BLOCKS (1),
    .EXTERNAL_DMA (1'b0)
  ) u_dut (
    .clk               (clk),
    .rst_n             (rst_n),
    .init_cfg           (tb_if.init_cfg),
    .load_weight_req    (tb_if.load_weight_req),
    .load_weight_granted(tb_if.load_weight_granted),
    .send_weight_trigger(tb_if.send_weight_trigger),
    .k                  (tb_if.k),
    .n                  (tb_if.n),
    .m                  (tb_if.m),
    .rhs_base           (tb_if.rhs_base),
    .rhs_row_stride_b   (tb_if.rhs_row_stride_b),
    .rhs_zp             (tb_if.rhs_zp),
    .use_16bits         (1'b0),
    .ia_reuse_num       (tb_if.ia_reuse_num),
    .w_reuse_num        (tb_if.w_reuse_num),
    .icb_cmd_valid      (sa_icb_if.cmd_valid),
    .icb_cmd_ready      (sa_icb_if.cmd_ready),
    .icb_cmd_read       (sa_icb_if.cmd_read),
    .icb_cmd_addr       (sa_icb_if.cmd_addr),
    .icb_cmd_len        (sa_icb_if.cmd_len),
    .icb_rsp_valid      (sa_icb_if.rsp_valid),
    .icb_rsp_ready      (sa_icb_if.rsp_ready),
    .icb_rsp_rdata      (sa_icb_if.rsp_rdata),
    .icb_rsp_err        (sa_icb_if.rsp_err),
    .ext_dma_start            (dummy_ext_dma_start),
    .ext_dma_is_write         (dummy_ext_dma_is_write),
    .ext_dma_linear_read_mode (dummy_ext_dma_linear_read_mode),
    .ext_dma_base_addr        (dummy_ext_dma_base_addr),
    .ext_dma_row_stride       (dummy_ext_dma_row_stride),
    .ext_dma_rows_to_read     (dummy_ext_dma_rows_to_read),
    .ext_dma_burst_len_m1     (dummy_ext_dma_burst_len_m1),
    .ext_dma_slot_id          (dummy_ext_dma_slot_id),
    .ext_dma_use_16bits       (dummy_ext_dma_use_16bits),
    .ext_dma_lhs_zp           (dummy_ext_dma_lhs_zp),
    .ext_dma_busy             (1'b0),
    .ext_dma_done             (1'b0),
    .ext_dma_wr_row           (dummy_ext_dma_wr_row),
    .ext_dma_wr_col_base      (dummy_ext_dma_wr_col_base),
    .ext_dma_wr_data          (dummy_ext_dma_wr_data),
    .ext_dma_wr_valid         (dummy_ext_dma_wr_valid),
    .weight_sending_done(tb_if.weight_sending_done),
    .load_weight_done   (load_weight_done),
    .store_weight_req   (tb_if.store_weight_req),
    .weight_out         (tb_if.weight_out),
    .weight_data_valid  (tb_if.weight_data_valid)
  );

  icb_unalign_bridge #(
    .WIDTH      (BUS_WIDTH),
    .ADDR_W     (REG_WIDTH),
    .OUTS_DEPTH (16),
    .ICB_LEN_W  (4)
  ) u_bridge (
    .clk               (clk),
    .rst_n             (rst_n),
    .sa_icb_cmd_valid  (sa_icb_if.cmd_valid),
    .sa_icb_cmd_ready  (sa_icb_if.cmd_ready),
    .sa_icb_cmd_addr   (sa_icb_if.cmd_addr),
    .sa_icb_cmd_read   (sa_icb_if.cmd_read),
    .sa_icb_cmd_len    (sa_icb_if.cmd_len),
    .sa_icb_cmd_wdata  (sa_icb_if.cmd_wdata),
    .sa_icb_cmd_wmask  (sa_icb_if.cmd_wmask),
    .sa_icb_w_valid    (1'b0),
    .sa_icb_w_ready    (),
    .sa_icb_rsp_valid  (sa_icb_if.rsp_valid),
    .sa_icb_rsp_ready  (sa_icb_if.rsp_ready),
    .sa_icb_rsp_rdata  (sa_icb_if.rsp_rdata),
    .sa_icb_rsp_err    (sa_icb_if.rsp_err),
    .m_icb_cmd_valid   (mem_icb_if.cmd_valid),
    .m_icb_cmd_ready   (mem_icb_if.cmd_ready),
    .m_icb_cmd_addr    (mem_icb_if.cmd_addr),
    .m_icb_cmd_read    (mem_icb_if.cmd_read),
    .m_icb_cmd_wdata   (mem_icb_if.cmd_wdata),
    .m_icb_cmd_wmask   (mem_icb_if.cmd_wmask),
    .m_icb_rsp_valid   (mem_icb_if.rsp_valid),
    .m_icb_rsp_ready   (mem_icb_if.rsp_ready),
    .m_icb_rsp_rdata   (mem_icb_if.rsp_rdata),
    .m_icb_rsp_err     (mem_icb_if.rsp_err)
  );

  tb_sram_model #(
    .DEPTH     (TC_SRAM_DEPTH),
    .DATA_W    (BUS_WIDTH),
    .ADDR_W    (REG_WIDTH),
    .INIT_FILE ("out/init.mem")
  ) u_sram (
    .bus       (mem_icb_if)
  );

  `include "tb_scoreboard.sv"
  `include "tb_test_seq.sv"

  initial begin
    string wave_file;
    if (!$value$plusargs("WAVE_FILE=%s", wave_file)) begin
      wave_file = "wave.vcd";
    end
    $dumpfile(wave_file);
    $dumpvars(0, tb_kernel_loader);
  end

endmodule
