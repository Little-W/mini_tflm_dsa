/*
 * tb_ia_loader — ia_loader v1.1 参数化验证顶层
 * ============================================================
 * 文件结构：
 *   tb_ia_loader.sv    — 顶层：DUT、ICB bridge、SRAM 实例化
 *   tb_sram_model.sv   — 可复用 ICB SRAM 模型
 *   tb_scoreboard.sv   — golden 矩阵、发送序列、比对 task
 *   tb_test_seq.sv     — 测试序列与辅助 task
 *   额外监视 bias_sleep / bias_switch，用于校验与 bias_loader 的边界语义。
 *
 * 测试参数从 out/test_params.svh 读入，由 gen_test_data.py 生成。
 */

`include "e203_defines.v"
`include "icb_types.svh"

module tb_ia_loader;

  // ================================================================
  // 硬件固定参数
  // ================================================================
  localparam int SIZE         = 8;
  localparam int DATA_WIDTH   = 16;
  localparam int BUS_WIDTH    = 32;
  localparam int REG_WIDTH    = 32;
  localparam int CACHE_BLOCKS = 4;

  // ================================================================
  // 测试参数（由 gen_test_data.py 生成）
  // ================================================================
  `include "test_params.svh"

  // ================================================================
  // 时钟与复位
  // ================================================================
  logic clk   = 0;
  logic rst_n = 0;
  always #5 clk = ~clk;

  // ================================================================
  // DUT 控制信号
  // ================================================================
  logic                        init_cfg;
  logic                        load_ia_req;
  logic                        load_ia_granted;
  logic                        send_ia_trigger;

  logic [REG_WIDTH-1:0]        k_in, n_in, m_in;
  logic [REG_WIDTH-1:0]        lhs_base;
  logic [REG_WIDTH-1:0]        lhs_row_stride_b;
  logic signed [REG_WIDTH-1:0] lhs_zp;
  logic                        use_16bits;
  logic [REG_WIDTH-1:0]        ia_reuse_num_in;
  logic [REG_WIDTH-1:0]        w_reuse_num_in;

  // ================================================================
  // ICB 信号：DUT ↔ Bridge
  // ================================================================
  logic                        dut_cmd_valid, dut_cmd_ready, dut_cmd_read;
  logic [REG_WIDTH-1:0]        dut_cmd_addr;
  logic [3:0]                  dut_cmd_len;
  logic                        dut_rsp_valid, dut_rsp_ready;
  logic [BUS_WIDTH-1:0]        dut_rsp_rdata;
  logic                        dut_rsp_err;

  // ICB 信号：Bridge ↔ SRAM
  logic                        brg_cmd_valid, brg_cmd_ready, brg_cmd_read;
  logic [REG_WIDTH-1:0]        brg_cmd_addr;
  logic [BUS_WIDTH-1:0]        brg_cmd_wdata;
  logic [BUS_WIDTH/8-1:0]      brg_cmd_wmask;
  logic                        brg_rsp_valid, brg_rsp_ready;
  logic [BUS_WIDTH-1:0]        brg_rsp_rdata;
  logic                        brg_rsp_err;

  // ================================================================
  // DUT 输出
  // ================================================================
  logic signed [DATA_WIDTH-1:0] ia_out          [SIZE];
  logic                         ia_row_valid;     // 最大延迟列有效标志
  logic                         ia_is_init_data;
  logic                         ia_calc_done;
  logic                         ia_sending_done;
  logic                         ia_l1_switch;
  logic                         ia_data_valid;
  logic                         bias_sleep;
  logic                         bias_switch;
  logic                         bias_last_loop;

  // ================================================================
  // DUT
  // ================================================================
  ia_loader #(
    .DATA_WIDTH   (DATA_WIDTH),
    .SIZE         (SIZE),
    .BUS_WIDTH    (BUS_WIDTH),
    .REG_WIDTH    (REG_WIDTH),
    .CACHE_BLOCKS (CACHE_BLOCKS)
  ) u_dut (
    .clk              (clk),
    .rst_n            (rst_n),
    .init_cfg         (init_cfg),
    .load_ia_req      (load_ia_req),
    .load_ia_granted  (load_ia_granted),
    .send_ia_trigger  (send_ia_trigger),
    .k                (k_in),
    .n                (n_in),
    .m                (m_in),
    .lhs_base         (lhs_base),
    .lhs_row_stride_b (lhs_row_stride_b),
    .lhs_zp           (lhs_zp),
    .use_16bits       (use_16bits),
    .ia_reuse_num     (ia_reuse_num_in),
    .w_reuse_num      (w_reuse_num_in),
    .icb_cmd_valid    (dut_cmd_valid),
    .icb_cmd_ready    (dut_cmd_ready),
    .icb_cmd_read     (dut_cmd_read),
    .icb_cmd_addr     (dut_cmd_addr),
    .icb_cmd_len      (dut_cmd_len),
    .icb_rsp_valid    (dut_rsp_valid),
    .icb_rsp_ready    (dut_rsp_ready),
    .icb_rsp_rdata    (dut_rsp_rdata),
    .icb_rsp_err      (dut_rsp_err),
    .ia_out           (ia_out),
    .ia_row_valid     (ia_row_valid),
    .ia_is_init_data  (ia_is_init_data),
    .ia_calc_done     (ia_calc_done),
    .ia_sending_done  (ia_sending_done),
    .ia_l1_switch     (ia_l1_switch),
    .ia_data_valid    (ia_data_valid),
    .bias_sleep       (bias_sleep),
    .bias_switch      (bias_switch),
    .bias_last_loop   (bias_last_loop)
  );

  // ================================================================
  // ICB Bridge
  // ================================================================
  icb_unalign_bridge #(
    .WIDTH     (BUS_WIDTH),
    .ADDR_W    (REG_WIDTH),
    .OUTS_DEPTH(16),
    .ICB_LEN_W (4)
  ) u_bridge (
    .clk               (clk),
    .rst_n              (rst_n),
    .sa_icb_cmd_valid   (dut_cmd_valid),
    .sa_icb_cmd_ready   (dut_cmd_ready),
    .sa_icb_cmd_addr    (dut_cmd_addr),
    .sa_icb_cmd_read    (dut_cmd_read),
    .sa_icb_cmd_len     (dut_cmd_len),
    .sa_icb_cmd_wdata   ({BUS_WIDTH{1'b0}}),
    .sa_icb_cmd_wmask   ({(BUS_WIDTH/8){1'b0}}),
    .sa_icb_w_valid     (1'b0),
    .sa_icb_w_ready     (),
    .sa_icb_rsp_valid   (dut_rsp_valid),
    .sa_icb_rsp_ready   (dut_rsp_ready),
    .sa_icb_rsp_rdata   (dut_rsp_rdata),
    .sa_icb_rsp_err     (dut_rsp_err),
    .m_icb_cmd_valid    (brg_cmd_valid),
    .m_icb_cmd_ready    (brg_cmd_ready),
    .m_icb_cmd_addr     (brg_cmd_addr),
    .m_icb_cmd_read     (brg_cmd_read),
    .m_icb_cmd_wdata    (brg_cmd_wdata),
    .m_icb_cmd_wmask    (brg_cmd_wmask),
    .m_icb_rsp_valid    (brg_rsp_valid),
    .m_icb_rsp_ready    (brg_rsp_ready),
    .m_icb_rsp_rdata    (brg_rsp_rdata),
    .m_icb_rsp_err      (brg_rsp_err)
  );

  // ================================================================
  // SRAM Model
  // ================================================================
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

  // ================================================================
  // Scoreboard — golden 矩阵、发送序列、比对
  // ================================================================
  `include "tb_scoreboard.sv"

  // ================================================================
  // Test Sequence — 主测试流程
  // ================================================================
  `include "tb_test_seq.sv"

endmodule
