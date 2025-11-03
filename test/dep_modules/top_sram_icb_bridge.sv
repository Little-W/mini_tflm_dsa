module top_sram_icb_bridge #(
  parameter WIDTH = 32,
  parameter ADDR_W = 19,        // 与 sram_icb 的 AW 对齐
  parameter AW_LSB = 2,
  parameter MW = (WIDTH/8),
  parameter USR_W = 1,
  parameter DP = 131072,
  parameter FORCE_X2ZERO = 0
)(
  input  wire                   clk,
  input  wire                   rst_n,
  // 可选控制信号
  input  wire                   tcm_cgstop,
  input  wire                   test_mode,

  // 上游 sa_icb 接口（暴露给外部）
  input  wire                   sa_icb_cmd_valid,
  output wire                   sa_icb_cmd_ready,
  input  wire [ADDR_W-1:0]      sa_icb_cmd_addr,
  input  wire                   sa_icb_cmd_read,
  input  wire [2:0]             sa_icb_cmd_len, // 保持与 bridge 默认宽度一致（可调整）
  input  wire [WIDTH-1:0]       sa_icb_cmd_wdata,
  input  wire [MW-1:0]          sa_icb_cmd_wmask,
  input  wire                   sa_icb_w_valid,
  output wire                   sa_icb_w_ready,
  output wire                   sa_icb_rsp_valid,
  input  wire                   sa_icb_rsp_ready,
  output wire [WIDTH-1:0]       sa_icb_rsp_rdata,
  output wire                   sa_icb_rsp_err
);

  // 内部连接线：bridge <-> sram_icb
  wire                         m_icb_cmd_valid;
  wire                         m_icb_cmd_ready;
  wire [ADDR_W-1:0]            m_icb_cmd_addr;
  wire                         m_icb_cmd_read;
  wire [WIDTH-1:0]             m_icb_cmd_wdata;
  wire [MW-1:0]                m_icb_cmd_wmask;

  wire                         m_icb_rsp_valid;
  wire                         m_icb_rsp_ready;
  wire [WIDTH-1:0]             m_icb_rsp_rdata;
  wire                         m_icb_rsp_err; // sram_icb 无 err，绑 0

  wire [USR_W-1:0]             sram_rsp_usr;

  // 将下游 err 固定为 0（sram_icb 没有 err 信号）
  assign m_icb_rsp_err = 1'b0;

  // instantiate bridge
  icb_unalign_bridge #(
    .WIDTH(WIDTH),
    .ADDR_W(ADDR_W)
  ) u_icb_unalign_bridge (
    .clk               (clk),
    .rst_n             (rst_n),
    .sa_icb_cmd_valid  (sa_icb_cmd_valid),
    .sa_icb_cmd_ready  (sa_icb_cmd_ready),
    .sa_icb_cmd_addr   (sa_icb_cmd_addr),
    .sa_icb_cmd_read   (sa_icb_cmd_read),
    .sa_icb_cmd_len    (sa_icb_cmd_len),
    .sa_icb_cmd_wdata  (sa_icb_cmd_wdata),
    .sa_icb_cmd_wmask  (sa_icb_cmd_wmask),
    .sa_icb_w_valid    (sa_icb_w_valid),
    .sa_icb_w_ready    (sa_icb_w_ready),
    .sa_icb_rsp_valid  (sa_icb_rsp_valid),
    .sa_icb_rsp_ready  (sa_icb_rsp_ready),
    .sa_icb_rsp_rdata  (sa_icb_rsp_rdata),
    .sa_icb_rsp_err    (sa_icb_rsp_err),

    .m_icb_cmd_valid   (m_icb_cmd_valid),
    .m_icb_cmd_ready   (m_icb_cmd_ready),
    .m_icb_cmd_addr    (m_icb_cmd_addr),
    .m_icb_cmd_read    (m_icb_cmd_read),
    .m_icb_cmd_wdata   (m_icb_cmd_wdata),
    .m_icb_cmd_wmask   (m_icb_cmd_wmask),

    .m_icb_rsp_valid   (m_icb_rsp_valid),
    .m_icb_rsp_ready   (m_icb_rsp_ready),
    .m_icb_rsp_rdata   (m_icb_rsp_rdata),
    .m_icb_rsp_err     (m_icb_rsp_err)
  );

  // instantiate existing sram_icb (作为从设备)
  sram_icb #(
    .DW(WIDTH),
    .MW(MW),
    .AW(ADDR_W),
    .AW_LSB(AW_LSB),
    .USR_W(USR_W),
    .DP(DP),
    .FORCE_X2ZERO(FORCE_X2ZERO)
  ) u_sram_icb (
    .clk                (clk),
    .rst_n              (rst_n),
    // ICB 从接口（sram_icb 的 i_icb_*）
    .i_icb_cmd_valid    (m_icb_cmd_valid),
    .i_icb_cmd_ready    (m_icb_cmd_ready),
    .i_icb_cmd_read     (m_icb_cmd_read),
    .i_icb_cmd_addr     (m_icb_cmd_addr),
    .i_icb_cmd_wdata    (m_icb_cmd_wdata),
    .i_icb_cmd_wmask    (m_icb_cmd_wmask),
    .i_icb_cmd_usr      ({USR_W{1'b0}}),
    .i_icb_rsp_valid    (m_icb_rsp_valid),
    .i_icb_rsp_ready    (m_icb_rsp_ready),
    .i_icb_rsp_rdata    (m_icb_rsp_rdata),
    .i_icb_rsp_usr      (sram_rsp_usr),
    .tcm_cgstop         (tcm_cgstop),
    .test_mode          (test_mode)
  );

endmodule
