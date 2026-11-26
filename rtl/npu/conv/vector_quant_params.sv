// SPDX-License-Identifier: Apache-2.0
// 量化参数按 DMA 数据字分组存储，异步读结果由调用方原有寄存器接收。
`default_nettype none
module vector_quant_params #(
    parameter int p_entries = 16,
    parameter int p_bus_width = 64,
    parameter int p_dma_index_width = $clog2(4*p_entries),
    parameter int p_read_index_width = $clog2(p_entries+1),
    parameter int p_active_width = $clog2(p_entries+1),
    parameter bit p_parallel_output = 1'b0
) (
    input  wire logic clk, // 模块工作时钟。
    input  wire logic i_wr_en, // 允许接收本周期的参数总线数据。
    input  wire logic i_wr_multiplier, // 本次写入更新量化乘数。
    input  wire logic i_wr_shift, // 本次写入更新量化移位参数。
    input  wire logic [p_dma_index_width-1:0] i_wr_byte_index, // 参数数据在对应数组中的起始字节索引。
    input  wire logic [p_bus_width-1:0] i_wr_data, // 包含连续量化参数的数据总线。
    input  wire logic [p_active_width-1:0] i_active, // 当前分块实际使用的量化参数项数。
    input  wire logic [p_read_index_width-1:0] i_rd_index, // 串行量化读取的通道索引。
    output logic signed [31:0] o_multiplier, // 当前读取通道的三十二位有符号量化乘数。
    output logic [5:0] o_right_shift, // 当前读取通道计算所用的右移位数。
    output logic signed [31:0] o_multiplier_vec[p_entries], // 并行读取的各通道有符号量化乘数。
    output logic [5:0] o_right_shift_vec[p_entries] // 并行读取的各通道右移位数。
);
    //! 0. 分组尺寸与写入地址
    //! ---------------------

    localparam int p_banks = p_bus_width / 32;
    localparam int p_rows = (p_entries + p_banks - 1) / p_banks;
    localparam int p_row_width = (p_rows <= 1) ? 1 : $clog2(p_rows);
    localparam int p_word_index_width = p_dma_index_width + 1;
    localparam int p_read_ports = p_parallel_output ? p_rows : 1;
    logic [p_word_index_width-1:0] write_index [0:p_banks-1];
    logic [37:0] write_data [0:p_banks-1];
    logic [37:0] bank_read_data [0:p_banks-1];
    logic [37:0] bank_parallel_data [p_banks][p_rows];
    logic [37:0] read_data;

    // 每拍各数据字具有连续的逻辑地址，取余分组保证每个 regfile 至多写入一次。
    for (genvar word_index = 0; word_index < p_banks; word_index++) begin : g_write_word
        logic [5:0] right_shift;
        assign write_index[word_index] = (p_word_index_width'(i_wr_byte_index) >> 2) +
            p_word_index_width'(word_index);
        assign right_shift = 6'd31 - i_wr_data[32*word_index +: 6];
        assign write_data[word_index] = {right_shift, i_wr_data[32*word_index +: 32]};
    end

    //! 1. 参数存储分组
    //! ---------------

    for (genvar bank_index = 0; bank_index < p_banks; bank_index++) begin : g_bank
        logic regfile_i_wr_en;
        logic [p_row_width-1:0] regfile_i_wr_addr;
        logic [37:0] regfile_i_wr_data;
        logic [37:0] regfile_i_wr_mask;
        logic [p_read_ports-1:0] regfile_i_rd_en;
        logic [p_read_ports-1:0][p_row_width-1:0] regfile_i_rd_addr;
        logic [p_read_ports-1:0][37:0] regfile_o_rd_data;

        always_comb begin
            regfile_i_wr_en = 1'b0;
            regfile_i_wr_addr = '0;
            regfile_i_wr_data = '0;
            for (int word_index = 0; word_index < p_banks; word_index++) begin
                if ((write_index[word_index] % p_word_index_width'(p_banks)) == p_word_index_width'(bank_index)) begin
                    regfile_i_wr_en = i_wr_en && (i_wr_multiplier || i_wr_shift) &&
                        write_index[word_index] < p_word_index_width'(p_entries) &&
                        write_index[word_index] < p_word_index_width'(i_active);
                    regfile_i_wr_addr = p_row_width'(write_index[word_index] / p_banks);
                    regfile_i_wr_data = write_data[word_index];
                end
            end
        end
        assign regfile_i_wr_mask = {{6{i_wr_shift}}, {32{i_wr_multiplier}}};
        assign regfile_i_rd_en = '1;
        if (p_parallel_output) begin : g_parallel_read
            // 固定地址读取直接连接原存储项，全部通道共用同一份参数状态。
            for (genvar row = 0; row < p_rows; row++) begin : g_row
                assign regfile_i_rd_addr[row] = p_row_width'(row);
                assign bank_parallel_data[bank_index][row] = regfile_o_rd_data[row];
            end
            assign bank_read_data[bank_index] = regfile_o_rd_data[p_row_width'(i_rd_index / p_banks)];
        end else begin : g_single_read
            assign regfile_i_rd_addr[0] = p_row_width'(i_rd_index / p_banks);
            assign bank_read_data[bank_index] = regfile_o_rd_data[0];
            for (genvar row = 0; row < p_rows; row++) begin : g_row
                assign bank_parallel_data[bank_index][row] = '0;
            end
        end
        regfile #(
            .p_data_width(38),
            .p_depth(p_rows),
            .p_addr_width(p_row_width),
            .p_write_unit(1),
            .p_read_ports(p_read_ports),
            .p_sync_read(1'b0)
        ) u_regfile (
            .clk(clk),
            .i_wr_en(regfile_i_wr_en),
            .i_wr_addr(regfile_i_wr_addr),
            .i_wr_data(regfile_i_wr_data),
            .i_wr_mask(regfile_i_wr_mask),
            .i_rd_en(regfile_i_rd_en),
            .i_rd_addr(regfile_i_rd_addr),
            .o_rd_data(regfile_o_rd_data)
        );
    end

    //! 2. 当前量化通道的异步读取
    //! -------------------------

    always_comb begin
        read_data = '0;
        for (int bank_index = 0; bank_index < p_banks; bank_index++) begin
            if ((i_rd_index % p_read_index_width'(p_banks)) == p_read_index_width'(bank_index) &&
                i_rd_index < p_read_index_width'(p_entries))
                read_data = bank_read_data[bank_index];
        end
    end
    assign o_multiplier = $signed(read_data[31:0]);
    assign o_right_shift = read_data[37:32];
    for (genvar lane = 0; lane < p_entries; lane++) begin : g_parallel_output
        assign o_multiplier_vec[lane] = $signed(bank_parallel_data[lane%p_banks][lane/p_banks][31:0]);
        assign o_right_shift_vec[lane] = bank_parallel_data[lane%p_banks][lane/p_banks][37:32];
    end
endmodule
`default_nettype wire
