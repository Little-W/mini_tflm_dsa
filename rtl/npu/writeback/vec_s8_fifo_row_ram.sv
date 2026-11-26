// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 输出 FIFO 的行存储接口，写入更新完整数据行，读使能控制同步读取。
module vec_s8_fifo_row_ram #(
    parameter int unsigned DATA_WIDTH = 128,
    parameter int unsigned DEPTH = 16,
    parameter int unsigned ADDR_WIDTH = 4,
    parameter [8*16-1:0] p_ram_style = "auto"
) (
    input  wire logic                  clk /* 工作时钟 */,
    input  wire logic                  wr_en /* 使能当前结果行存储字写入 */,
    input  wire logic [ADDR_WIDTH-1:0] wr_addr /* 当前写入结果行的存储地址 */,
    input  wire logic [DATA_WIDTH-1:0] wr_data /* 当前写入的结果行数据字 */,
    input  wire logic                  rd_en /* 使能结果行同步读取 */,
    input  wire logic [ADDR_WIDTH-1:0] rd_addr /* 当前读取结果行的存储地址 */,
    output logic [DATA_WIDTH-1:0] rd_data /* 同步返回的结果行数据字 */
);

    // 两种存储实现共用读写地址、数据和使能，整行写掩码始终有效。
    logic storage_i_wr_en, storage_i_rd_en;
    logic [ADDR_WIDTH-1:0] storage_i_wr_addr, storage_i_rd_addr;
    logic [DATA_WIDTH-1:0] storage_i_wr_data, storage_o_rd_data;
    assign storage_i_wr_en = wr_en;
    assign storage_i_wr_addr = wr_addr;
    assign storage_i_wr_data = wr_data;
    assign storage_i_rd_en = rd_en;
    assign storage_i_rd_addr = rd_addr;
    assign rd_data = storage_o_rd_data;
`ifdef ASIC_SRAM
    logic [DATA_WIDTH-1:0] storage_i_wr_mask;
    assign storage_i_wr_mask = '1;
    smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)) u_storage (
        .clk(clk), .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
        .write_data(storage_i_wr_data), .write_mask(storage_i_wr_mask),
        .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr), .read_data(storage_o_rd_data)
    );
`else
    logic storage_i_wr_mask;
    assign storage_i_wr_mask = 1'b1;
    regfile #(
        .p_data_width(DATA_WIDTH), .p_depth(DEPTH), .p_addr_width(ADDR_WIDTH),
        .p_write_unit(DATA_WIDTH), .p_ram_style(p_ram_style)
    ) u_storage (
        .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
        .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
        .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
    );
`endif

endmodule

`default_nettype wire
