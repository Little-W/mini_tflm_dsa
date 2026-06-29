interface kernel_loader_tb_if #(
    parameter int unsigned SIZE       = 4,
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned BUS_WIDTH  = 32,
    parameter int unsigned REG_WIDTH  = 32
) (
    input logic clk,
    input logic rst_n
);

  logic                        init_cfg;
  logic                        load_weight_req;
  logic                        load_weight_granted;
  logic                        send_weight_trigger;

  logic [REG_WIDTH-1:0]        k;
  logic [REG_WIDTH-1:0]        n;
  logic [REG_WIDTH-1:0]        m;
  logic [REG_WIDTH-1:0]        rhs_base;
  logic [REG_WIDTH-1:0]        rhs_row_stride_b;
  logic signed [REG_WIDTH-1:0] rhs_zp;
  logic [REG_WIDTH-1:0]        ia_reuse_num;
  logic [REG_WIDTH-1:0]        w_reuse_num;

  logic                        icb_cmd_valid;
  logic                        icb_cmd_ready;
  logic                        icb_cmd_read;
  logic [REG_WIDTH-1:0]        icb_cmd_addr;
  logic [3:0]                  icb_cmd_len;
  logic                        icb_rsp_valid;
  logic                        icb_rsp_ready;
  logic [BUS_WIDTH-1:0]        icb_rsp_rdata;
  logic                        icb_rsp_err;

  logic                        weight_sending_done;
  logic                        store_weight_req;
  logic signed [DATA_WIDTH-1:0] weight_out [SIZE];
  logic                        weight_data_valid;

  logic                        brg_cmd_valid;
  logic                        brg_cmd_ready;
  logic                        brg_cmd_read;
  logic [REG_WIDTH-1:0]        brg_cmd_addr;
  logic [BUS_WIDTH-1:0]        brg_cmd_wdata;
  logic [BUS_WIDTH/8-1:0]      brg_cmd_wmask;
  logic                        brg_rsp_valid;
  logic                        brg_rsp_ready;
  logic [BUS_WIDTH-1:0]        brg_rsp_rdata;
  logic                        brg_rsp_err;

  modport tb (
      input  clk, rst_n,
      output init_cfg, load_weight_granted, send_weight_trigger,
      output k, n, m, rhs_base, rhs_row_stride_b, rhs_zp, ia_reuse_num, w_reuse_num,
      input  load_weight_req, weight_sending_done, store_weight_req, weight_data_valid, weight_out,
      output icb_cmd_ready, icb_rsp_valid, icb_rsp_rdata, icb_rsp_err,
      input  icb_cmd_valid, icb_rsp_ready, icb_cmd_read, icb_cmd_addr, icb_cmd_len,
      output brg_cmd_ready, brg_rsp_valid, brg_rsp_rdata, brg_rsp_err,
      input  brg_cmd_valid, brg_cmd_read, brg_cmd_addr, brg_cmd_wdata, brg_cmd_wmask, brg_rsp_ready
  );

endinterface