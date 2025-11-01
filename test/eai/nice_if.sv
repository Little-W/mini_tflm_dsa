/* verilator lint_off TIMESCALEMOD */
`timescale 1ns / 1ps
/* verilator lint_on TIMESCALEMOD */

interface nice_if (
    input logic clk,
    input logic rst_n
);

    // NICE interface signals
    logic        req_valid;
    logic        req_ready;
    logic [31:0] req_inst;
    logic [31:0] req_rs1;
    logic [31:0] req_rs2;

    logic        rsp_valid;
    logic        rsp_ready;
    logic [31:0] rsp_rdat;
    logic        rsp_err;

    // Memory interface
    logic        mem_holdup;
    logic        icb_cmd_valid;
    logic        icb_cmd_ready;
    logic [31:0] icb_cmd_addr;
    logic        icb_cmd_read;
    logic [31:0] icb_cmd_wdata;
    logic [ 3:0] icb_cmd_wmask;

    logic        icb_rsp_valid;
    logic        icb_rsp_ready;
    logic [31:0] icb_rsp_rdata;
    logic        icb_rsp_err;

    // Clocking block for testbench (Verilator compatible)
    clocking cb @(posedge clk);
        // default input #1ns output #1ns;
        output req_valid;
        output req_inst;
        output req_rs1;
        output req_rs2;
        output rsp_ready;
        input req_ready;
        input rsp_valid;
        input rsp_rdat;
        input rsp_err;
        output icb_cmd_valid;
        output icb_cmd_addr;
        output icb_cmd_read;
        output icb_cmd_wdata;
        output icb_cmd_wmask;
        output icb_rsp_ready;
        input icb_cmd_ready;
        input icb_rsp_valid;
        input icb_rsp_rdata;
        input icb_rsp_err;
    endclocking

    // Modport for testbench (without clocking reference for Verilator)
    modport tb (
        input clk, rst_n,
        input req_ready, rsp_valid, rsp_rdat, rsp_err,
        output req_valid, req_inst, req_rs1, req_rs2, rsp_ready,
        // Memory interface access
        input icb_cmd_ready, icb_rsp_valid, icb_rsp_rdata, icb_rsp_err,
        output icb_cmd_valid, icb_cmd_addr, icb_cmd_read, icb_cmd_wdata, icb_cmd_wmask, icb_rsp_ready
    );

    // Modport for DUT
    modport dut (
        input  clk, rst_n,
        input  req_valid, req_inst, req_rs1, req_rs2, rsp_ready,
        output req_ready, rsp_valid, rsp_rdat, rsp_err,
        output mem_holdup,
        output icb_cmd_valid, icb_cmd_addr, icb_cmd_read, icb_cmd_wdata, icb_cmd_wmask,
        input  icb_cmd_ready,
        input  icb_rsp_valid, icb_rsp_rdata, icb_rsp_err,
        output icb_rsp_ready
    );

endinterface
