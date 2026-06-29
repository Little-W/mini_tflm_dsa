module tb_kernel_loader;

  localparam int SIZE       = 4;
  localparam int DATA_WIDTH = 8;
  localparam int BUS_WIDTH  = 32;
  localparam int REG_WIDTH  = 32;

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

  kernel_loader #(
    .DATA_WIDTH   (DATA_WIDTH),
    .SIZE         (SIZE),
    .BUS_WIDTH    (BUS_WIDTH),
    .REG_WIDTH    (REG_WIDTH),
    .CACHE_BLOCKS (1)
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
    .weight_sending_done(tb_if.weight_sending_done),
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
