// SPDX-License-Identifier: Apache-2.0
// Shared input cache. Policy 3 uses convolution-window lifetime and geometric
// lookahead; policies 0-2 provide fixed-capacity replacement comparisons.
`default_nettype none

module conv_read_cache #(
  parameter int SETS=128,
  parameter int WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int READ_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=3,
  parameter int DEMAND_DEPTH=4,
  parameter int SI=$clog2(SETS),
  parameter int LB=$clog2(LINE_BYTES),
  parameter int WB=$clog2(LINE_BYTES/4),
  parameter int WI=(WAYS==1 ? 1 : $clog2(WAYS)),
  parameter int DEPTH=WAYS*SETS*(LINE_BYTES/4),
  parameter int DA=$clog2(DEPTH),
  parameter int TAGW=32-LB-SI,
  parameter bit p_defer_retire_shift=1'b0
) (
  input wire logic clk, rst_n,
  input wire logic cfg_valid,
  output logic cfg_ready,
  input wire logic [31:0] cfg_base, cfg_bytes,
  input wire logic cfg_bypass,
  input wire logic cfg_geometry = 1'b0,
  input wire logic req_valid,
  output logic req_ready,
  input wire logic [31:0] req_addr,
  input wire logic req_geometry = 1'b0,
  input wire logic req_event_first = 1'b0,
  input wire logic hint_valid = 1'b0,
  input wire logic [31:0] hint_next = 32'hffff_ffff,
  output logic hint_pending,
  output logic rsp_valid,
  input wire logic rsp_ready,
  output logic [READ_WIDTH-1:0] rsp_data,
  output logic rsp_error,
  output logic arvalid,
  input wire logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input wire logic rvalid,
  output logic rready,
  input wire logic [BUS_WIDTH-1:0] rdata,
  input wire logic [1:0] rresp,
  input wire logic rlast,
  input wire logic cfg_windowed = 1'b0,
  input wire logic cfg_prefetch_enable = 1'b0,
  input wire logic req_window_index_valid = 1'b0,
  input wire logic [31:0] req_window_index = 32'd0,
  input wire logic [31:0] req_window_epoch = 32'd0,
  input wire logic [31:0] req_window_retire = 32'hffff_ffff,
  input wire logic [31:0] req_window_progress = 32'd0,
  input wire logic prefetch_valid = 1'b0,
  output logic prefetch_ready,
  input wire logic [31:0] prefetch_addr = 32'd0,
  input wire logic prefetch_window_index_valid = 1'b0,
  input wire logic [31:0] prefetch_window_index = 32'd0,
  input wire logic [31:0] prefetch_window_epoch = 32'd0,
  input wire logic [31:0] prefetch_window_retire = 32'hffff_ffff,
  input wire logic prefetch_next_fragment = 1'b0,
  input wire logic prefetch_ref_valid = 1'b0,
  input wire logic [31:0] prefetch_ref_addr = 32'd0,
  input wire logic prefetch_ref_index_valid = 1'b0,
  input wire logic [31:0] prefetch_ref_index = 32'd0,
  input wire logic [31:0] prefetch_ref_epoch = 32'd0);
  generate if (CACHE_POLICY==3) begin : g_window
    conv_windowed_cache #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .DEMAND_DEPTH(DEMAND_DEPTH),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES),
      .p_defer_retire_shift(p_defer_retire_shift)) u_window (.*);
  end else begin : g_reference
    conv_read_cache_reference #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_reference (.*);
    assign prefetch_ready=1'b0;
  end endgenerate
endmodule

`default_nettype wire
