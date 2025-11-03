`timescale 1ns/1ps
`include "icb_types.svh"

interface icb_ext_if #(
  parameter int ADDR_W = 19,
  parameter int WIDTH  = 32,
  parameter int LEN_W  = 3
)(
  input  logic clk,
  input  logic rst_n
);
  // 三通道打包信号
  icb_ext_cmd_m_t cmd_m;    // master -> slave: command
  icb_ext_wr_m_t  wr_m;     // master -> slave: write data
  icb_ext_cmd_s_t cmd_s;    // slave -> master: command ready
  icb_ext_wr_s_t  wr_s;     // slave -> master: write ready
  icb_ext_rsp_s_t rsp_s;    // slave -> master: response
  icb_ext_rsp_m_t rsp_m;    // master -> slave: response ready

  // Master 侧 clocking block（用于 testbench 驱动 DUT）
  clocking cb_master @(posedge clk);
    default input #1step output #1step;
    // master 输出 -> DUT 输入
    output cmd_m, wr_m, rsp_m;
    // slave 输出 -> master 输入
    input  cmd_s, wr_s, rsp_s;
  endclocking

  // Slave 侧 clocking block（用于 memory bridge 驱动）
  clocking cb_slave @(posedge clk);
    default input #1step output #1step;
    // slave 输出 -> master 输入
    output cmd_s, wr_s, rsp_s;
    // master 输出 -> slave 输入
    input  cmd_m, wr_m, rsp_m;
  endclocking

  // Master modport（DUT 使用）
  modport master (
    input  clk, rst_n,
    output cmd_m, wr_m, rsp_m,
    input  cmd_s, wr_s, rsp_s
  );

  // Slave modport（Memory bridge 使用）
  modport slave (
    input  clk, rst_n,
    input  cmd_m, wr_m, rsp_m,
    output cmd_s, wr_s, rsp_s
  );

  // Testbench master modport（带 clocking block）
  modport tb_master (
    input  clk, rst_n,
    clocking cb_master,
    input  cmd_s, wr_s, rsp_s,
    output rsp_m  // 允许直接访问 rsp_ready
  );

  // Monitor modport（仅用于监控）
  modport monitor (
    input clk, rst_n,
    input cmd_m, wr_m, rsp_m,
    input cmd_s, wr_s, rsp_s
  );

endinterface
