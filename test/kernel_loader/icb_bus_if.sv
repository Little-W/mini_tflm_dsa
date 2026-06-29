interface icb_bus_if #(
    parameter int unsigned ADDR_W = 32,
    parameter int unsigned DATA_W = 32
) (
    input logic clk,
    input logic rst_n
);

  logic                      cmd_valid;
  logic                      cmd_ready;
  logic                      cmd_read;
  logic [ADDR_W-1:0]         cmd_addr;
    logic [3:0]                cmd_len;
  logic [DATA_W-1:0]         cmd_wdata;
  logic [DATA_W/8-1:0]       cmd_wmask;
  logic                      rsp_valid;
  logic                      rsp_ready;
  logic [DATA_W-1:0]         rsp_rdata;
  logic                      rsp_err;

  modport master (
      input  clk, rst_n,
      output cmd_valid, cmd_read, cmd_addr, cmd_len, cmd_wdata, cmd_wmask, rsp_ready,
      input  cmd_ready, rsp_valid, rsp_rdata, rsp_err
  );

  modport slave (
      input  clk, rst_n,
      input  cmd_valid, cmd_read, cmd_addr, cmd_len, cmd_wdata, cmd_wmask, rsp_ready,
      output cmd_ready, rsp_valid, rsp_rdata, rsp_err
  );

endinterface