// SPDX-License-Identifier: Apache-2.0
// 实例化完整仲裁器与线性 DMA，检查错误、中止和总线排空。
module dma_abort_top #(
  parameter int BUS_WIDTH = 32,
  parameter int SIZE = 8,
  parameter int DMA_SIZE = 8,
  parameter int CACHE_BLOCKS = 4,
  parameter int DATA_WIDTH = 8,
  parameter int OUTSTANDING = 1
) (
  input logic clk, rst_n, i_abort, owner_dw,
  input logic read_req, read_start, write_req, write_start,
  output logic read_granted, write_granted, write_done, write_done_raw, write_error_raw, idle, bus_error,
  input logic [BUS_WIDTH-1:0] source_data,
  input logic source_valid,
  output logic source_ready,
  output logic arvalid, awvalid, wvalid, rready, bready,
  input logic arready, awready, wready, rvalid, bvalid,
  input logic [1:0] rresp, bresp,
  output logic [7:0] arlen, awlen,
  output logic [BUS_WIDTH-1:0] wdata,
  output logic [BUS_WIDTH/8-1:0] wstrb,
  output logic wlast
);
  logic oa_granted, dw_granted, oa_done, dw_done, dw_error;
  logic oa_source_ready, dw_source_ready;
  assign write_granted = owner_dw ? dw_granted : oa_granted;
  assign source_ready = owner_dw ? dw_source_ready : oa_source_ready;
  assign write_done = owner_dw ? dw_done && !dw_error : oa_done;
  assign write_done_raw = owner_dw ? dw_done : oa_done;
  assign write_error_raw = owner_dw && dw_error;
  axi_block_dma_arbiter #(
    .DATA_WIDTH(DATA_WIDTH), .KERNEL_WIDTH(8), .SIZE(SIZE), .DMA_SIZE(DMA_SIZE),
    .CACHE_BLOCKS(CACHE_BLOCKS),
    .BUS_WIDTH(BUS_WIDTH), .READ_OUTSTANDING(OUTSTANDING), .WRITE_OUTSTANDING(OUTSTANDING),
    .p_register_bus_error(1'b1)
  ) dut (
    .clk, .rst_n, .abort(i_abort), .idle, .bus_error,
    .ia_req(read_req), .ia_start(read_start), .ia_granted(read_granted),
    .ia_linear_read_mode(1'b0), .ia_base_addr(32'h2000), .ia_row_stride(32'd4),
    .ia_rows_to_read(32'd1), .ia_burst_len_m1(8'd0), .ia_slot_id('0),
    .ia_use_16bits(1'b0), .ia_lhs_zp(32'sd0),
    .kernel_req(1'b0), .kernel_start(1'b0), .kernel_linear_read_mode(1'b0),
    .kernel_base_addr(32'd0), .kernel_row_stride(32'd0), .kernel_rows_to_read(32'd0),
    .kernel_burst_len_m1(8'd0), .kernel_slot_id(1'b0), .kernel_use_16bits(1'b0), .kernel_lhs_zp(32'sd0),
    .bias_req(1'b0), .bias_start(1'b0), .bias_linear_read_mode(1'b0),
    .bias_base_addr(32'd0), .bias_row_stride(32'd0), .bias_rows_to_read(32'd0),
    .bias_burst_len_m1(8'd0), .bias_slot_id(1'b0), .bias_use_16bits(1'b0), .bias_lhs_zp(32'sd0),
    .quant_req(1'b0), .quant_start(1'b0), .quant_linear_read_mode(1'b0),
    .quant_base_addr(32'd0), .quant_row_stride(32'd0), .quant_rows_to_read(32'd0),
    .quant_burst_len_m1(8'd0), .quant_slot_id(1'b0), .quant_use_16bits(1'b0), .quant_lhs_zp(32'sd0),
    .oa_req(write_req && !owner_dw), .oa_start(write_start && !owner_dw), .oa_granted,
    .oa_base_addr(32'h1000), .oa_row_stride(32'd16), .oa_rows_to_read(32'd1), .oa_burst_len_m1(8'd3),
    .oa_src_wdata(source_data), .oa_src_wmask({BUS_WIDTH/8{1'b1}}), .oa_src_wvalid(source_valid),
    .oa_src_wready(oa_source_ready), .oa_done,
    .dw_req(1'b0), .dw_start(1'b0),
    .dw_wr_req(write_req && owner_dw), .dw_wr_start(write_start && owner_dw),
    .dw_wr_granted(dw_granted), .dw_wr_base_addr(32'h1000), .dw_wr_row_stride(32'd16),
    .dw_wr_rows_to_write(32'd1), .dw_wr_burst_len_m1(8'd3),
    .dw_src_wdata(source_data), .dw_src_wmask({BUS_WIDTH/8{1'b1}}), .dw_src_wvalid(source_valid),
    .dw_src_wready(dw_source_ready), .dw_wr_done(dw_done), .dw_wr_error(dw_error),
    .m_axi_arvalid(arvalid), .m_axi_arready(arready), .m_axi_arlen(arlen),
    .m_axi_rvalid(rvalid), .m_axi_rready(rready), .m_axi_rdata(BUS_WIDTH'(64'h1029384712345678)),
    .m_axi_rresp(rresp), .m_axi_rlast(1'b1),
    .m_axi_awvalid(awvalid), .m_axi_awready(awready), .m_axi_awlen(awlen),
    .m_axi_wvalid(wvalid), .m_axi_wready(wready), .m_axi_wdata(wdata),
    .m_axi_wstrb(wstrb), .m_axi_wlast(wlast),
    .m_axi_bvalid(bvalid), .m_axi_bready(bready), .m_axi_bresp(bresp)
  );
endmodule
