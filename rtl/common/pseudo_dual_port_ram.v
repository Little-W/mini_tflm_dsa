// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保留既有双端口接口，读取和写入在同一时钟边沿独立采样。
module pseudo_dual_port_ram #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 6
) (
    input  wire logic clk /* 模块工作时钟。 */,
    input  wire logic ena /* A 端口访问使能。 */,
    input  wire logic enb /* B 端口访问使能。 */,
    input  wire logic wea /* A 端口写入使能。 */,
    input  wire logic [ADDR_WIDTH-1:0] addra /* A 端口写入元素地址。 */,
    input  wire logic [DATA_WIDTH-1:0] dia /* A 端口写入数据。 */,
    input  wire logic [ADDR_WIDTH-1:0] addrb /* B 端口读取元素地址。 */,
    output logic [DATA_WIDTH-1:0] dob /* B 端口同步读取数据。 */
);
    logic storage_i_wr_en;
    logic [ADDR_WIDTH-1:0] storage_i_wr_addr, storage_i_rd_addr;
    logic [DATA_WIDTH-1:0] storage_i_wr_data, storage_o_rd_data;
    logic storage_i_rd_en;

    assign storage_i_wr_en = ena && wea;
    assign storage_i_wr_addr = addra;
    assign storage_i_wr_data = dia;
    assign storage_i_rd_en = enb;
    assign storage_i_rd_addr = addrb;
    assign dob = storage_o_rd_data;

`ifdef ASIC_SRAM
    logic [DATA_WIDTH-1:0] storage_i_wr_mask;
    assign storage_i_wr_mask = '1;
    smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(1 << ADDR_WIDTH), .ADDR_WIDTH(ADDR_WIDTH)) u_storage (
        .clk(clk), .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
        .write_data(storage_i_wr_data), .write_mask(storage_i_wr_mask),
        .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr), .read_data(storage_o_rd_data)
    );
`else
    logic [0:0] storage_i_wr_mask;
    assign storage_i_wr_mask = 1'b1;
    regfile #(
        .p_data_width(DATA_WIDTH), .p_depth(1 << ADDR_WIDTH), .p_addr_width(ADDR_WIDTH),
        .p_write_unit(DATA_WIDTH), .p_read_ports(1), .p_sync_read(1'b1)
    ) u_storage (
        .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
        .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
        .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
    );
`endif
endmodule

`default_nettype wire
