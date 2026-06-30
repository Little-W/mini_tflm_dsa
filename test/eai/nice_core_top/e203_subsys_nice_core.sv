/* verilator lint_off TIMESCALEMOD */
// //`include "define.svh"
`include "e203_defines.v"
`include "icb_types.svh"
/* verilator lint_on TIMESCALEMOD */

// `ifdef E203_HAS_NICE  //{
module e203_subsys_nice_core (
    // System
    input  nice_clk,        // NICE 核心时钟
    input  nice_rst_n,      // NICE 核心异步复位，低有效
    output nice_active,     // NICE 核心活动指示（有计算时拉高）
    output nice_mem_holdup, // 内存暂停信号（指令未退休时拉高）

    // Control cmd_req - 指令请求接口
    input                   nice_req_valid,  // 指令请求有效信号
    output                  nice_req_ready,  // 指令请求就绪信号
    input  [`E203_XLEN-1:0] nice_req_inst,   // 指令数据
    input  [`E203_XLEN-1:0] nice_req_rs1,    // rs1 寄存器值
    input  [`E203_XLEN-1:0] nice_req_rs2,    // rs2 寄存器值

    // Control cmd_rsp - 指令响应接口
    output                  nice_rsp_valid,  // 响应有效信号
    input                   nice_rsp_ready,  // 响应就绪信号
    output [`E203_XLEN-1:0] nice_rsp_rdat,   // 响应数据
    output                  nice_rsp_err,    // 响应错误标志

    // Memory lsu_req - 内存访问请求接口
    output                       nice_icb_cmd_valid,  // ICB 命令有效
    input                        nice_icb_cmd_ready,  // ICB 命令就绪
    output [`E203_ADDR_SIZE-1:0] nice_icb_cmd_addr,   // ICB 命令地址
    output                       nice_icb_cmd_read,   // ICB 读命令标志
    output [     `E203_XLEN-1:0] nice_icb_cmd_wdata,  // ICB 写数据
    output [  `E203_XLEN_MW-1:0] nice_icb_cmd_wmask,  // ICB 写掩码
    output [                1:0] nice_icb_cmd_size,   // ICB 访问大小

    // Memory lsu_rsp - 内存访问响应接口
    input                   nice_icb_rsp_valid,  // ICB 响应有效
    output                  nice_icb_rsp_ready,  // ICB 响应就绪
    input  [`E203_XLEN-1:0] nice_icb_rsp_rdata,  // ICB 响应数据
    input                   nice_icb_rsp_err,    // ICB 响应错误

    output                  m_axi_arvalid,
    input                   m_axi_arready,
    output [`E203_XLEN-1:0] m_axi_araddr,
    output [           7:0] m_axi_arlen,
    output [           2:0] m_axi_arsize,
    output [           1:0] m_axi_arburst,
    input                   m_axi_rvalid,
    output                  m_axi_rready,
    input  [`E203_XLEN-1:0] m_axi_rdata,
    input  [           1:0] m_axi_rresp,
    input                   m_axi_rlast,
    output                  m_axi_awvalid,
    input                   m_axi_awready,
    output [`E203_XLEN-1:0] m_axi_awaddr,
    output [           7:0] m_axi_awlen,
    output [           2:0] m_axi_awsize,
    output [           1:0] m_axi_awburst,
    output                  m_axi_wvalid,
    input                   m_axi_wready,
    output [`E203_XLEN-1:0] m_axi_wdata,
    output [`E203_XLEN_MW-1:0] m_axi_wstrb,
    output                  m_axi_wlast,
    input                   m_axi_bvalid,
    output                  m_axi_bready,
    input  [           1:0] m_axi_bresp
);

  // ========================================================================
  // 内部信号定义
  // ========================================================================
  wire calc_start;  // MMA 计算开始信号
  wire cfg_16bits_ia;  // 使用16位IA数据配置
  wire use_per_channel;  // 使用per-channel量化
  wire [`E203_XLEN-1:0] dst_base;  // 输出地址基址
  wire sa_ready;  // 执行单元就绪信号（反压）

  // CSR 相关信号
  wire [`E203_XLEN-1:0] csr_wdata;  // CSR 写数据
  wire csr_req;  // CSR 请求信号
  wire is_csr_read;  // CSR 读操作标志
  wire [11:0] csr_addr;  // CSR 地址
  wire csr_ready;  // CSR 就绪信号
  wire [`E203_XLEN-1:0] csr_rdata;  // CSR 读数据

  // CSR 输出值（配置参数）
  wire [`E203_XLEN-1:0] lhs_base;  // A矩阵基址 (0x7C0)
  wire [`E203_XLEN-1:0] rhs_base;  // B矩阵基址 (0x7C1)
  wire [`E203_XLEN-1:0] dst_base_csr;  // 输出矩阵基址 (0x7C2)
  wire [`E203_XLEN-1:0] bias_base;  // bias数组基址 (0x7C3)
  wire signed [`E203_XLEN-1:0] lhs_zp;  // A矩阵零点 (0x7CA)
  wire signed [`E203_XLEN-1:0] rhs_zp;  // B矩阵零点 (0x7CB)
  wire signed [`E203_XLEN-1:0] dst_zp;  // 输出矩阵零点 (0x7CC)
  wire signed [`E203_XLEN-1:0] q_mult_pt;  // per-tensor量化乘数或指针 (0x7CD)
  wire signed [`E203_XLEN-1:0] q_shift_pt;  // per-tensor量化移位或指针 (0x7CE)
  wire [`E203_XLEN-1:0] k;  // K: A的行数 (0x7C4)
  wire [`E203_XLEN-1:0] n;  // N: B的行数/内积长度 (0x7C5)
  wire [`E203_XLEN-1:0] m;  // M: B的列数/输出通道数 (0x7C6)
  wire [`E203_XLEN-1:0] lhs_row_stride_b;  // A矩阵行步距 (0x7C8)
  wire [`E203_XLEN-1:0] dst_row_stride_b;  // 输出矩阵行步距 (0x7C7)
  wire [`E203_XLEN-1:0] rhs_col_stride_b;  // B矩阵行步距 (0x7C9)
  wire signed [`E203_XLEN-1:0] act_min;  // 激活下限 (0x7CF)
  wire signed [`E203_XLEN-1:0] act_max;  // 激活上限 (0x7D0)
  wire [`E203_XLEN-1:0] cfg_ia_reuse_num;  // IA reuse depth (0x7D1)
  wire [`E203_XLEN-1:0] cfg_w_reuse_num;   // W reuse window (0x7D2)
  wire cfg_dataflow_mode;                  // 0=WS, 1=IS (0x7D3)

  // WBU 相关信号
  wire mma_wb_valid;  // MMA写回有效
  wire mma_wb_ready;  // MMA写回就绪
  wire [`E203_XLEN-1:0] mma_wb_data;  // MMA写回数据

  // CSR 写回信号
  wire csr_wb_valid;  // CSR写回有效
  wire csr_wb_ready;  // CSR写回就绪
  wire [`E203_XLEN-1:0] csr_wb_data;  // CSR写回数据

  // MMA 错误码信号
  wire [1:0] mma_err_code;  // MMA执行错误码

  // 指令退休跟踪信号
  wire retire_mem_holdup;  // 退休跟踪器输出的内存暂停信号

  // ========================================================================
  // Decoder & Dispatcher 模块实例化
  // ========================================================================
  decode_dispatch #(
      .REG_WIDTH(`E203_XLEN)
  ) u_decode_dispatch (
      .clk  (nice_clk),
      .rst_n(nice_rst_n),

      // 指令输入
      .decode_inst_valid(nice_req_valid),
      .decode_inst_ready(nice_req_ready),
      .instruction      (nice_req_inst),
      .rs1_val          (nice_req_rs1),
      .rs2_val          (nice_req_rs2),

      .id_stall(1'b0),  // 当前不考虑全局 stall

      // 执行单元反压
      .sa_ready(sa_ready),

      // CSR 单元反压
      .csr_ready(csr_ready),

      // 控制信号输出
      .calc_start     (calc_start),
      .cfg_16bits_ia  (cfg_16bits_ia),
      .use_per_channel(use_per_channel),
      .dst_base       (dst_base),

      // CSR 接口
      .csr_wdata  (csr_wdata),
      .csr_req    (csr_req),
      .is_csr_read(is_csr_read),
      .csr_addr   (csr_addr)
  );

  // ========================================================================
  // 连接执行单元
  // ========================================================================
  mma_top #(
      .WEIGHT_WIDTH(16),
      .DATA_WIDTH  (16),
      .SIZE        (16),
      .BUS_WIDTH   (`E203_XLEN),
      .REG_WIDTH   (`E203_XLEN),
      .ADDR_WIDTH  (`E203_ADDR_SIZE),
      .ICB_LEN_W   (`ICB_LEN_W)
  ) u_mma_top (
      .clk             (nice_clk),
      .rst_n           (nice_rst_n),
      .calc_start      (calc_start),
      .cfg_16bits_ia   (cfg_16bits_ia),
      .cfg_dataflow_mode(cfg_dataflow_mode),
      .cfg_ia_reuse_num(cfg_ia_reuse_num),
      .cfg_w_reuse_num (cfg_w_reuse_num),
      .sa_ready        (sa_ready),
      .wb_valid        (mma_wb_valid),
      .wb_ready        (mma_wb_ready),
      .err_code        (mma_err_code),
      .lhs_base        (lhs_base),
      .rhs_base        (rhs_base),
      .dst_base        (dst_base),
      .bias_base       (bias_base),
      .lhs_zp          (lhs_zp),
      .rhs_zp          (rhs_zp),
      .dst_zp          (dst_zp),
      .q_mult_pt       (q_mult_pt),
      .q_shift_pt      (q_shift_pt),
      .use_per_channel (use_per_channel),
      .k               (k),
      .n               (n),
      .m               (m),
      .lhs_row_stride_b(lhs_row_stride_b),
      .dst_row_stride_b(dst_row_stride_b),
      .rhs_col_stride_b(rhs_col_stride_b),
      .act_min         (act_min),
      .act_max         (act_max),
      .m_axi_arvalid   (m_axi_arvalid),
      .m_axi_arready   (m_axi_arready),
      .m_axi_araddr    (m_axi_araddr),
      .m_axi_arlen     (m_axi_arlen),
      .m_axi_arsize    (m_axi_arsize),
      .m_axi_arburst   (m_axi_arburst),
      .m_axi_rvalid    (m_axi_rvalid),
      .m_axi_rready    (m_axi_rready),
      .m_axi_rdata     (m_axi_rdata),
      .m_axi_rresp     (m_axi_rresp),
      .m_axi_rlast     (m_axi_rlast),
      .m_axi_awvalid   (m_axi_awvalid),
      .m_axi_awready   (m_axi_awready),
      .m_axi_awaddr    (m_axi_awaddr),
      .m_axi_awlen     (m_axi_awlen),
      .m_axi_awsize    (m_axi_awsize),
      .m_axi_awburst   (m_axi_awburst),
      .m_axi_wvalid    (m_axi_wvalid),
      .m_axi_wready    (m_axi_wready),
      .m_axi_wdata     (m_axi_wdata),
      .m_axi_wstrb     (m_axi_wstrb),
      .m_axi_wlast     (m_axi_wlast),
      .m_axi_bvalid    (m_axi_bvalid),
      .m_axi_bready    (m_axi_bready),
      .m_axi_bresp     (m_axi_bresp)
  );

  // ========================================================================
  // CSR 单元实例化
  // ========================================================================
  csr_unit #(
      .REG_WIDTH(`E203_XLEN)
  ) u_csr_unit (
      .clk  (nice_clk),
      .rst_n(nice_rst_n),

      // CSR 读写接口
      .csr_req    (csr_req),
      .csr_addr   (csr_addr),
      .csr_wdata  (csr_wdata),
      .is_csr_read(is_csr_read),
      .csr_ready  (csr_ready),
      .csr_rdata  (csr_rdata),

      // CSR 写回接口
      .csr_wb_valid(csr_wb_valid),
      .csr_wb_ready(csr_wb_ready),
      .csr_wb_data (csr_wb_data),

      // CSR 输出值
      .lhs_base        (lhs_base),
      .rhs_base        (rhs_base),
      .dst_base        (dst_base_csr),
      .bias_base       (bias_base),
      .lhs_zp          (lhs_zp),
      .rhs_zp          (rhs_zp),
      .dst_zp          (dst_zp),
      .q_mult_pt       (q_mult_pt),
      .q_shift_pt      (q_shift_pt),
      .m               (m),
      .k               (k),
      .n               (n),
      .lhs_row_stride_b(lhs_row_stride_b),
      .dst_row_stride_b(dst_row_stride_b),
      .rhs_col_stride_b(rhs_col_stride_b),
      .act_min         (act_min),
      .act_max         (act_max),
      .cfg_ia_reuse_num(cfg_ia_reuse_num),
      .cfg_w_reuse_num (cfg_w_reuse_num),
      .cfg_dataflow_mode(cfg_dataflow_mode)
  );

  // ========================================================================
  // Write-Back Unit (WBU) 实例化
  // ========================================================================
  wbu #(
      .DW(`E203_XLEN)
  ) u_wbu (
      .clk  (nice_clk),
      .rst_n(nice_rst_n),

      // 来自 CSR 单元的写回数据
      .csr_wb_valid(csr_wb_valid),
      .csr_wb_ready(csr_wb_ready),
      .csr_wb_data (csr_wb_data),

      // 来自 MMA 执行单元的写回数据
      .mma_wb_valid(mma_wb_valid),
      .mma_wb_ready(mma_wb_ready),
      .mma_wb_data (mma_wb_data),

      // NICE 响应接口
      .nice_rsp_valid(nice_rsp_valid),
      .nice_rsp_ready(nice_rsp_ready),
      .nice_rsp_rdat (nice_rsp_rdat),
      .nice_rsp_err  (nice_rsp_err)
  );

  assign mma_wb_data = {30'b0, mma_err_code};

  // ========================================================================
  // 内存访问接口（nice_icb_*）
  // ========================================================================
  assign nice_icb_cmd_valid = 1'b0;
  assign nice_icb_cmd_addr  = '0;
  assign nice_icb_cmd_read  = 1'b0;
  assign nice_icb_cmd_wdata = '0;
  assign nice_icb_cmd_wmask = '0;
  assign nice_icb_rsp_ready = 1'b1;
  assign nice_icb_cmd_size = 2'b10;  // 固定字（4字节）访问

  // ========================================================================
  // 指令退休跟踪模块实例化
  // ========================================================================
  inst_tracker u_inst_tracker (
      .clk  (nice_clk),
      .rst_n(nice_rst_n),

      // MMA 指令启动
      .calc_start(calc_start),

      // MMA 写回握手
      .mma_wb_valid(mma_wb_valid),
      .mma_wb_ready(mma_wb_ready),

      // 输出控制信号
      .nice_mem_holdup(retire_mem_holdup)
  );

  // ========================================================================
  // Active 信号（当有计算进行时拉高）
  // ========================================================================
  assign nice_active     = calc_start;  // 简化实现，实际需根据执行状态
  assign nice_mem_holdup = retire_mem_holdup;  // 使用退休跟踪器的输出

endmodule
// `endif  //
