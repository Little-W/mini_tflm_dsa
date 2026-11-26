// SPDX-License-Identifier: Apache-2.0
// 暴露线性DMA读取接口，供独立驱动检查数据、顺序、突发长度和4 KiB边界。
module linear_dma_4k_top #(
    parameter int READ_OUTSTANDING = 4,
    parameter int BUS_WIDTH = 32,
    parameter int DMA_MAX_BYTES = 256 * (BUS_WIDTH / 8)
) (
    input logic clk, // 工作时钟。
    input logic rst_n, // 低有效复位。
    input logic rd_start, // 读命令有效。
    input logic rd_linear_read_mode, // 按行单拍读取模式。
    output logic rd_start_ready, // 允许接收读命令。
    input logic [31:0] rd_base_addr, // 首行字节地址。
    input logic [31:0] rd_row_stride, // 相邻行字节步长。
    input logic [31:0] rd_rows_to_read, // 本次读取行数。
    input logic [31:0] rd_valid_cols, // 每行有效元素数量。
    input logic [7:0] rd_burst_len_m1, // 每行读取拍数减一。
    input logic [1:0] rd_slot_id, // 输出缓存槽编号。
    input logic rd_use_16bits, // 输入元素为16位。
    input logic signed [31:0] rd_lhs_zp, // 输入零点偏移。
    output logic rd_busy, // 存在未完成读命令。
    output logic rd_done, // 读命令完成脉冲。
    output logic rd_finish_beat, // 当前拍完成读命令。
    output logic rd_error, // 已完成命令的错误标志。
    output logic m_axi_arvalid, // AXI读地址有效。
    input logic m_axi_arready, // AXI接收读地址。
    output logic [31:0] m_axi_araddr, // AXI读突发首地址。
    output logic [7:0] m_axi_arlen, // AXI读突发拍数减一。
    output logic [2:0] m_axi_arsize, // 每拍字节数的二进制对数。
    output logic [1:0] m_axi_arburst, // AXI突发地址模式。
    input logic m_axi_rvalid, // AXI返回数据有效。
    output logic m_axi_rready, // 允许接收AXI返回数据。
    input logic [BUS_WIDTH-1:0] m_axi_rdata, // AXI返回数据。
    input logic [1:0] m_axi_rresp, // AXI返回响应码。
    input logic m_axi_rlast, // AXI突发末拍。
    output logic [1:0] wr_slot, // 当前输出所属缓存槽。
    output logic [3:0] wr_row, // 当前输出行号。
    output logic [3:0] wr_col_base, // 当前输出首列号。
    output logic signed [15:0] wr_data [BUS_WIDTH/8], // 解包后的有符号元素。
    output logic wr_valid [BUS_WIDTH/8], // 各输出元素有效标志。
    output logic wr_use_16bits, // 输出数据按16位元素使用。
    output logic [BUS_WIDTH-1:0] rd_raw_data, // 未解包的总线数据。
    output logic rd_raw_valid, // 未解包数据有效。
    output logic [3:0] rd_raw_row, // 未解包数据对应行号。
    output logic [3:0] rd_raw_col_base // 未解包数据对应首列号。
);
    axi_linear_block_dma #(
        .DMA_MAX_BYTES(DMA_MAX_BYTES),
        .DATA_WIDTH(16), .SIZE(16), .BUS_WIDTH(BUS_WIDTH), .REG_WIDTH(32),
        .CACHE_BLOCKS(4), .READ_OUTSTANDING(READ_OUTSTANDING)
    ) dut (
        .clk, .rst_n, .rd_start, .rd_start_ready, .rd_tag(3'd0),
        .rd_response_tag(), .rd_finish_tag(), .rd_linear_read_mode, .rd_base_addr, .rd_row_stride,
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
