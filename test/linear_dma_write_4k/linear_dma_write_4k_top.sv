// SPDX-License-Identifier: Apache-2.0
module linear_dma_write_4k_top #(
    parameter int WRITE_OUTSTANDING = 4,
    parameter int SIZE = 16,
    parameter int CACHE_BLOCKS = 4,
    parameter int BUS_WIDTH = 32,
    parameter int DMA_MAX_BYTES = 256 * (BUS_WIDTH / 8)
) (
    input logic clk, rst_n,
    input logic wr_start,
    input logic [31:0] wr_base_addr, wr_row_stride, wr_rows_to_write,
    input logic [7:0] wr_burst_len_m1,
    output logic wr_busy, wr_done, wr_error,
    input logic [BUS_WIDTH-1:0] src_wdata,
    input logic [BUS_WIDTH/8-1:0] src_wmask,
    input logic src_wvalid,
    output logic src_wready,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [31:0] m_axi_awaddr,
    output logic [7:0] m_axi_awlen,
    output logic [2:0] m_axi_awsize,
    output logic [1:0] m_axi_awburst,
    output logic m_axi_wvalid,
    input logic m_axi_wready,
    output logic [BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic m_axi_wlast,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    input logic [1:0] m_axi_bresp
);
    axi_linear_block_dma #(
        .DMA_MAX_BYTES(DMA_MAX_BYTES),
        .DATA_WIDTH(16), .SIZE(SIZE), .BUS_WIDTH(BUS_WIDTH), .REG_WIDTH(32),
        .CACHE_BLOCKS(CACHE_BLOCKS), .READ_OUTSTANDING(4),
        .WRITE_OUTSTANDING(WRITE_OUTSTANDING)
    ) dut (
        .clk, .rst_n,
        .rd_start(1'b0), .rd_start_ready(), .rd_tag(3'd0),
        .rd_response_tag(), .rd_finish_tag(), .rd_linear_read_mode(1'b0), .rd_base_addr(32'd0),
        .rd_row_stride(32'd0), .rd_rows_to_read(32'd0), .rd_valid_cols(32'd0),
        .rd_burst_len_m1(8'd0), .rd_slot_id('0), .rd_use_16bits(1'b0),
        .rd_lhs_zp(32'sd0), .rd_busy(), .rd_done(), .rd_finish_beat(),
        .wr_start, .wr_base_addr, .wr_row_stride, .wr_rows_to_write,
        .wr_burst_len_m1, .wr_busy, .wr_done,
        .src_wdata, .src_wmask, .src_wvalid, .src_wready,
        .m_axi_arvalid(), .m_axi_arready(1'b0), .m_axi_araddr(), .m_axi_arlen(),
        .m_axi_arsize(), .m_axi_arburst(), .m_axi_rvalid(1'b0), .m_axi_rready(),
        .m_axi_rdata('0), .m_axi_rresp(2'b00), .m_axi_rlast(1'b0),
        .m_axi_awvalid, .m_axi_awready, .m_axi_awaddr, .m_axi_awlen,
        .m_axi_awsize, .m_axi_awburst, .m_axi_wvalid, .m_axi_wready,
        .m_axi_wdata, .m_axi_wstrb, .m_axi_wlast,
        .m_axi_bvalid, .m_axi_bready, .m_axi_bresp,
        .wr_slot(), .wr_row(), .wr_col_base(), .wr_data(), .wr_valid(),
        .wr_use_16bits(), .rd_raw_data(), .rd_raw_valid(), .rd_raw_row(),
        .rd_raw_col_base(), .rd_error(), .wr_error
    );
endmodule
