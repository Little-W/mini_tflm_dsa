// SPDX-License-Identifier: Apache-2.0
// 量化参数按 DMA 数据字分组存储，异步读结果由调用方原有寄存器接收。
`default_nettype none
module vector_quant_params #(
    parameter int p_entries = 16,
    parameter int p_bus_width = 64,
    parameter int p_dma_index_width = $clog2(4*p_entries),
    parameter int p_read_index_width = $clog2(p_entries+1),
    parameter int p_active_width = $clog2(p_entries+1)
) (
    input  logic clk,
    input  logic i_wr_en,
    input  logic i_wr_multiplier,
    input  logic i_wr_shift,
    input  logic [p_dma_index_width-1:0] i_wr_byte_index,
    input  logic [p_bus_width-1:0] i_wr_data,
    input  logic [p_active_width-1:0] i_active,
    input  logic [p_read_index_width-1:0] i_rd_index,
    output logic signed [31:0] o_multiplier,
    output logic [5:0] o_right_shift
);
    //! 0. 分组尺寸与写入地址
    //! ---------------------

    localparam int p_banks = p_bus_width / 32;
    localparam int p_rows = (p_entries + p_banks - 1) / p_banks;
    localparam int p_row_width = (p_rows <= 1) ? 1 : $clog2(p_rows);
    localparam int p_word_index_width = p_dma_index_width + 1;
    logic [p_word_index_width-1:0] write_index [0:p_banks-1];
    logic [37:0] write_data [0:p_banks-1];
    logic [37:0] bank_read_data [0:p_banks-1];
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
        logic [0:0] regfile_i_rd_en;
        logic [0:0][p_row_width-1:0] regfile_i_rd_addr;
        logic [0:0][37:0] regfile_o_rd_data;

        always_comb begin
            regfile_i_wr_en = 1'b0;
            regfile_i_wr_addr = '0;
            regfile_i_wr_data = '0;
            for (int word_index = 0; word_index < p_banks; word_index++) begin
                if ((write_index[word_index] % p_banks) == p_word_index_width'(bank_index)) begin
                    regfile_i_wr_en = i_wr_en && (i_wr_multiplier || i_wr_shift) &&
                        write_index[word_index] < p_word_index_width'(p_entries) &&
                        write_index[word_index] < p_word_index_width'(i_active);
                    regfile_i_wr_addr = p_row_width'(write_index[word_index] / p_banks);
                    regfile_i_wr_data = write_data[word_index];
                end
            end
        end
        assign regfile_i_wr_mask = {{6{i_wr_shift}}, {32{i_wr_multiplier}}};
        assign regfile_i_rd_en = 1'b1;
        assign regfile_i_rd_addr[0] = p_row_width'(i_rd_index / p_banks);
        regfile #(
            .p_data_width(38),
            .p_depth(p_rows),
            .p_addr_width(p_row_width),
            .p_write_unit(1),
            .p_read_ports(1),
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
        assign bank_read_data[bank_index] = regfile_o_rd_data[0];
    end

    //! 2. 当前量化通道的异步读取
    //! -------------------------

    always_comb begin
        read_data = '0;
        for (int bank_index = 0; bank_index < p_banks; bank_index++) begin
            if ((i_rd_index % p_banks) == p_read_index_width'(bank_index) &&
                i_rd_index < p_read_index_width'(p_entries))
                read_data = bank_read_data[bank_index];
        end
    end
    assign o_multiplier = $signed(read_data[31:0]);
    assign o_right_shift = read_data[37:32];
endmodule
`default_nettype wire
