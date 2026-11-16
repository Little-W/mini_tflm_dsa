// SPDX-License-Identifier: Apache-2.0
module linear_dma_4k_top #(
    parameter int READ_OUTSTANDING = 4,
    parameter int RD_CONTEXT_DEPTH = 4,
    parameter int BUS_WIDTH = 32,
    parameter int DMA_MAX_BYTES = 256 * (BUS_WIDTH / 8)
) (
    input logic clk, rst_n,
    input logic rd_start, rd_linear_read_mode,
    output logic rd_start_ready,
    input logic [2:0] rd_tag,
    output logic [2:0] rd_response_tag, rd_finish_tag,
    input logic [31:0] rd_base_addr, rd_row_stride, rd_rows_to_read, rd_valid_cols,
    input logic [7:0] rd_burst_len_m1,
    input logic [1:0] rd_slot_id,
    input logic rd_use_16bits,
    input logic signed [31:0] rd_lhs_zp,
    output logic rd_busy, rd_done, rd_finish_beat, rd_error,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    output logic [31:0] m_axi_araddr,
    output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,
    output logic [1:0] m_axi_arburst,
    input logic m_axi_rvalid,
    output logic m_axi_rready,
    input logic [BUS_WIDTH-1:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast,
    output logic [1:0] wr_slot,
    output logic [3:0] wr_row, wr_col_base,
    output logic signed [15:0] wr_data [BUS_WIDTH/8],
    output logic wr_valid [BUS_WIDTH/8],
    output logic wr_use_16bits,
    output logic [BUS_WIDTH-1:0] rd_raw_data,
    output logic rd_raw_valid,
    output logic [3:0] rd_raw_row, rd_raw_col_base
);
    axi_linear_block_dma #(
        .DMA_MAX_BYTES(DMA_MAX_BYTES),
        .DATA_WIDTH(16), .SIZE(16), .BUS_WIDTH(BUS_WIDTH), .REG_WIDTH(32),
        .CACHE_BLOCKS(4), .READ_OUTSTANDING(READ_OUTSTANDING),
        .RD_CONTEXT_DEPTH(RD_CONTEXT_DEPTH), .RD_TAG_WIDTH(3)
    ) dut (
        .clk, .rst_n, .rd_start, .rd_start_ready, .rd_tag, .rd_response_tag, .rd_finish_tag, .rd_linear_read_mode, .rd_base_addr, .rd_row_stride,
        .rd_rows_to_read, .rd_valid_cols, .rd_burst_len_m1, .rd_slot_id,
        .rd_use_16bits, .rd_lhs_zp, .rd_busy, .rd_done, .rd_finish_beat,
        .wr_start(1'b0), .wr_base_addr(32'd0), .wr_row_stride(32'd0),
        .wr_rows_to_write(32'd0), .wr_burst_len_m1(8'd0), .wr_busy(), .wr_done(),
        .src_wdata('0), .src_wmask('0), .src_wvalid(1'b0), .src_wready(),
        .m_axi_arvalid, .m_axi_arready, .m_axi_araddr, .m_axi_arlen,
        .m_axi_arsize, .m_axi_arburst, .m_axi_rvalid, .m_axi_rready,
        .m_axi_rdata, .m_axi_rresp, .m_axi_rlast,
        .m_axi_awvalid(), .m_axi_awready(1'b0), .m_axi_awaddr(), .m_axi_awlen(),
        .m_axi_awsize(), .m_axi_awburst(), .m_axi_wvalid(), .m_axi_wready(1'b0),
        .m_axi_wdata(), .m_axi_wstrb(), .m_axi_wlast(), .m_axi_bvalid(1'b0),
        .m_axi_bready(), .m_axi_bresp(2'b00),
        .wr_slot, .wr_row, .wr_col_base, .wr_data, .wr_valid, .wr_use_16bits,
        .rd_raw_data, .rd_raw_valid, .rd_raw_row, .rd_raw_col_base,
        .rd_error, .wr_error()
    );
endmodule
