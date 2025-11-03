`timescale 1ns/1ps

interface mma_top_if #(
  parameter int REG_WIDTH = 32
)(
  input logic clk,
  input logic rst_n
);
  // 控制信号
  logic                       calc_start;
  logic                       cfg_16bits_ia;
  logic                       sa_ready;

  // Base pointers
  logic [REG_WIDTH-1:0]       lhs_base;
  logic [REG_WIDTH-1:0]       rhs_base;
  logic [REG_WIDTH-1:0]       dst_base;
  logic [REG_WIDTH-1:0]       bias_base;

  // Quantization & zero-points
  logic signed [REG_WIDTH-1:0] lhs_zp;
  logic signed [REG_WIDTH-1:0] rhs_zp;
  logic signed [REG_WIDTH-1:0] dst_zp;
  logic signed [REG_WIDTH-1:0] q_mult_pt;
  logic signed [REG_WIDTH-1:0] q_shift_pt;
  logic                        use_per_channel;

  // Dimensions
  logic [REG_WIDTH-1:0]       k;
  logic [REG_WIDTH-1:0]       n;
  logic [REG_WIDTH-1:0]       m;

  // Row strides (bytes)
  logic [REG_WIDTH-1:0]       lhs_row_stride_b;
  logic [REG_WIDTH-1:0]       dst_row_stride_b;
  logic [REG_WIDTH-1:0]       rhs_row_stride_b;

  // Activation clamp
  logic signed [REG_WIDTH-1:0] act_min;
  logic signed [REG_WIDTH-1:0] act_max;

  // Clocking block for testbench (驱动配置)
  clocking cb_cfg @(posedge clk);
    default input #1step output #1step;
    output calc_start, cfg_16bits_ia;
    output lhs_base, rhs_base, dst_base, bias_base;
    output lhs_zp, rhs_zp, dst_zp, q_mult_pt, q_shift_pt, use_per_channel;
    output k, n, m;
    output lhs_row_stride_b, dst_row_stride_b, rhs_row_stride_b;
    output act_min, act_max;
    input  sa_ready;
  endclocking

  // DUT modport
  modport dut (
    input  clk, rst_n,
    input  calc_start, cfg_16bits_ia,
    output sa_ready,
    input  lhs_base, rhs_base, dst_base, bias_base,
    input  lhs_zp, rhs_zp, dst_zp, q_mult_pt, q_shift_pt, use_per_channel,
    input  k, n, m,
    input  lhs_row_stride_b, dst_row_stride_b, rhs_row_stride_b,
    input  act_min, act_max
  );

  // Testbench modport (带 clocking block)
  modport tb (
    input  clk, rst_n,
    clocking cb_cfg,
    input  sa_ready
  );

endinterface
