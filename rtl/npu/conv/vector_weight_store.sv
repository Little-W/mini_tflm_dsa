// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 每个卷积核位置保存全部通道，字节写入与整行同步读取共用存储数组。
module vector_weight_store #(
    parameter int p_channels = 16,
    parameter int p_depth = 49,
    parameter int p_address_width = (p_depth < 2) ? 1 : $clog2(p_depth)
) (
    input logic clk,
    input logic i_wr_en,
    input logic [31:0] i_wr_tap,
    input logic [p_channels-1:0] i_wr_mask,
    input logic [8*p_channels-1:0] i_wr_data,
    input logic [31:0] i_rd_tap,
    output logic [8*p_channels-1:0] o_rd_data
);
    //! 0. 存储端口和读取状态
    //! -----------------------

    logic storage_i_wr_en;
    logic [p_address_width-1:0] storage_i_wr_addr;
    logic [8*p_channels-1:0] storage_i_wr_data;
    logic [p_channels-1:0] storage_i_wr_mask;
    logic [0:0] storage_i_rd_en;
    logic [0:0][p_address_width-1:0] storage_i_rd_addr;
    logic [0:0][8*p_channels-1:0] storage_o_rd_data;
    logic read_in_range;

    //! 1. 生成存储地址和字节写入条件
    //! -------------------------------

    assign storage_i_wr_en = i_wr_en && (i_wr_tap < 32'(p_depth));
    assign storage_i_wr_addr = p_address_width'(i_wr_tap);
    assign storage_i_wr_data = i_wr_data;
    assign storage_i_wr_mask = i_wr_mask;
    assign storage_i_rd_en = 1'b1;
    assign storage_i_rd_addr[0] = p_address_width'(i_rd_tap);

    //! 2. 保存读取结果和地址有效状态
    //! -------------------------------

    regfile #(
        .p_data_width(8*p_channels), .p_depth(p_depth), .p_addr_width(p_address_width),
        .p_write_unit(8), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_storage (
        .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
        .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
        .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
    );
    always_ff @(posedge clk) begin
        read_in_range <= i_rd_tap < 32'(p_depth);
    end

    //! 3. 输出读取的权重行
    //! ---------------------

    assign o_rd_data = read_in_range ? storage_o_rd_data[0] : '0;
endmodule

`default_nettype wire
