/*
 * tb_bias_loader — bias_loader 参数化验证顶层
 */

`include "e203_defines.v"
`include "icb_types.svh"

module tb_bias_loader;

  localparam int SIZE       = 8;
  localparam int DATA_WIDTH = 32;
  localparam int BUS_WIDTH  = 32;
  localparam int REG_WIDTH  = 32;

  `include "test_params.svh"

  logic clk   = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  logic init_cfg;
  logic [REG_WIDTH-1:0] bias_base;
  logic [REG_WIDTH-1:0] k_in;
  logic [REG_WIDTH-1:0] m_in;
  logic bias_switch;
  logic bias_sleep;
  logic bias_last_loop;
  logic load_bias_req;
  logic load_bias_granted;
  logic bias_valid;
  logic next_bias_valid;
  logic bias_group_valid;
  logic load_bias_done;

  logic signed [DATA_WIDTH-1:0] data_out [SIZE];
  logic signed [DATA_WIDTH-1:0] next_data_out [SIZE];
  logic signed [DATA_WIDTH-1:0] group_data_out [SIZE];
  logic signed [7:0]            ext_dma_wr_data [BUS_WIDTH/8];
  logic                         ext_dma_wr_valid[BUS_WIDTH/8];

  logic                        dut_cmd_valid, dut_cmd_ready, dut_cmd_read;
  logic [REG_WIDTH-1:0]        dut_cmd_addr;
  logic [3:0]                  dut_cmd_len;
  logic                        dut_rsp_valid, dut_rsp_ready;
  logic [BUS_WIDTH-1:0]        dut_rsp_rdata;
  logic                        dut_rsp_err;

  logic                        brg_cmd_valid, brg_cmd_ready, brg_cmd_read;
  logic [REG_WIDTH-1:0]        brg_cmd_addr;
  logic [BUS_WIDTH-1:0]        brg_cmd_wdata;
  logic [BUS_WIDTH/8-1:0]      brg_cmd_wmask;
  logic                        brg_rsp_valid, brg_rsp_ready;
  logic [BUS_WIDTH-1:0]        brg_rsp_rdata;
  logic                        brg_rsp_err;

  bias_loader #(
    .SIZE       (SIZE),
    .DATA_WIDTH (DATA_WIDTH),
    .BUS_WIDTH  (BUS_WIDTH),
    .REG_WIDTH  (REG_WIDTH)
  ) u_dut (
    .clk               (clk),
    .rst_n             (rst_n),
    .init_cfg          (init_cfg),
    .bias_base         (bias_base),
    .k                 (k_in),
    .m                 (m_in),
    .bias_step_blocks  (REG_WIDTH'(1)),
    .bias_switch       (bias_switch),
    .bias_sleep        (bias_sleep),
    .bias_last_loop    (bias_last_loop),
    .load_bias_req     (load_bias_req),
    .load_bias_granted (load_bias_granted),
    .bias_valid        (bias_valid),
    .next_bias_valid   (next_bias_valid),
    .bias_group_valid  (bias_group_valid),
    .load_bias_done    (load_bias_done),
    .data_out          (data_out),
    .next_data_out     (next_data_out),
    .group_data_out    (group_data_out),
    .icb_cmd_valid     (dut_cmd_valid),
    .icb_cmd_ready     (dut_cmd_ready),
    .icb_cmd_read      (dut_cmd_read),
    .icb_cmd_addr      (dut_cmd_addr),
    .icb_cmd_len       (dut_cmd_len),
    .icb_rsp_valid     (dut_rsp_valid),
    .icb_rsp_ready     (dut_rsp_ready),
    .icb_rsp_rdata     (dut_rsp_rdata),
    .icb_rsp_err       (dut_rsp_err),
    .ext_dma_start     (),
    .ext_dma_is_write  (),
    .ext_dma_linear_read_mode(),
    .ext_dma_base_addr (),
    .ext_dma_row_stride(),
    .ext_dma_rows_to_read(),
    .ext_dma_burst_len_m1(),
    .ext_dma_slot_id   (),
    .ext_dma_use_16bits(),
    .ext_dma_lhs_zp    (),
    .ext_dma_busy      (1'b0),
    .ext_dma_done      (1'b0),
    .ext_dma_wr_slot   (1'b0),
    .ext_dma_wr_row    ('0),
    .ext_dma_wr_col_base('0),
    .ext_dma_wr_data   (ext_dma_wr_data),
    .ext_dma_wr_valid  (ext_dma_wr_valid),
    .ext_dma_wr_use_16bits(1'b0)
  );

  initial begin
    for (int ext_i = 0; ext_i < BUS_WIDTH/8; ext_i++) begin
      ext_dma_wr_data[ext_i]  = '0;
      ext_dma_wr_valid[ext_i] = 1'b0;
    end
  end

  icb_unalign_bridge #(
    .WIDTH     (BUS_WIDTH),
    .ADDR_W    (REG_WIDTH),
    .OUTS_DEPTH(16),
    .ICB_LEN_W (4)
  ) u_bridge (
    .clk               (clk),
    .rst_n             (rst_n),
    .sa_icb_cmd_valid  (dut_cmd_valid),
    .sa_icb_cmd_ready  (dut_cmd_ready),
    .sa_icb_cmd_addr   (dut_cmd_addr),
    .sa_icb_cmd_read   (dut_cmd_read),
    .sa_icb_cmd_len    (dut_cmd_len),
    .sa_icb_cmd_wdata  ({BUS_WIDTH{1'b0}}),
    .sa_icb_cmd_wmask  ({(BUS_WIDTH/8){1'b0}}),
    .sa_icb_w_valid    (1'b0),
    .sa_icb_w_ready    (),
    .sa_icb_rsp_valid  (dut_rsp_valid),
    .sa_icb_rsp_ready  (dut_rsp_ready),
    .sa_icb_rsp_rdata  (dut_rsp_rdata),
    .sa_icb_rsp_err    (dut_rsp_err),
    .m_icb_cmd_valid   (brg_cmd_valid),
    .m_icb_cmd_ready   (brg_cmd_ready),
    .m_icb_cmd_addr    (brg_cmd_addr),
    .m_icb_cmd_read    (brg_cmd_read),
    .m_icb_cmd_wdata   (brg_cmd_wdata),
    .m_icb_cmd_wmask   (brg_cmd_wmask),
    .m_icb_rsp_valid   (brg_rsp_valid),
    .m_icb_rsp_ready   (brg_rsp_ready),
    .m_icb_rsp_rdata   (brg_rsp_rdata),
    .m_icb_rsp_err     (brg_rsp_err)
  );

  tb_sram_model #(
    .DEPTH     (TC_SRAM_DEPTH),
    .DATA_W    (BUS_WIDTH),
    .ADDR_W    (REG_WIDTH),
    .INIT_FILE ("out/init.mem")
  ) u_sram (
    .clk       (clk),
    .rst_n     (rst_n),
    .cmd_valid (brg_cmd_valid),
    .cmd_ready (brg_cmd_ready),
    .cmd_addr  (brg_cmd_addr),
    .cmd_read  (brg_cmd_read),
    .cmd_wdata (brg_cmd_wdata),
    .cmd_wmask (brg_cmd_wmask),
    .rsp_valid (brg_rsp_valid),
    .rsp_ready (brg_rsp_ready),
    .rsp_rdata (brg_rsp_rdata),
    .rsp_err   (brg_rsp_err)
  );

  `include "tb_scoreboard.sv"
  `include "tb_test_seq.sv"

endmodule
