// SPDX-License-Identifier: Apache-2.0
`default_nettype none

/* 根据行起点、帧行数和物理存储容量计算当前帧是否可以保留。 */ module ps_frame_store_capacity #(
    parameter int p_initial_row_width = 10,
    parameter int p_bank_words_width = 10,
    parameter int p_bank_count_width = 4
) (
    input  wire logic [p_initial_row_width-1:0] i_initial_row /* 当前帧占用空间的起始行位置 */,
    input  wire logic [31:0]                    i_frame_rows /* 当前帧的实际有效行数 */,
    input  wire logic [31:0]                    i_reserve_rows /* 当前帧要求保留的行容量 */,
    input  wire logic [p_bank_words_width-1:0]   i_bank_words /* 每个部分和存储块可使用的128 位字数 */,
    input  wire logic [p_bank_count_width-1:0]   i_bank_count /* 分配给部分和的物理存储块数 */,
    output logic                           o_rows_fit /* 实际行范围及预留行范围均在物理容量内 */
);
    localparam int p_pool_word_width = p_bank_words_width + p_bank_count_width;
    localparam int p_rows_width = (p_initial_row_width > p_pool_word_width-2) ?
        p_initial_row_width : p_pool_word_width-2;

    if (p_rows_width < 32) begin : g_bounded_rows
        logic [p_pool_word_width-1:0] pool_words;
        logic [p_rows_width-1:0] pool_rows;
        logic [1:0] request_fits;
        logic [31:0] requested_rows [2];

        // 每行占四个存储字，实际行数和预留行数分别检查。
        assign pool_words = p_pool_word_width'(i_bank_words) * p_pool_word_width'(i_bank_count);
        assign pool_rows = p_rows_width'((p_rows_width+2)'(pool_words) >> 2);
        assign requested_rows[0] = i_frame_rows;
        assign requested_rows[1] = i_reserve_rows;
        for (genvar request = 0; request < 2; request++) begin : g_request
            logic [p_rows_width:0] initial_row, row_count, inverted_capacity;
            logic [p_rows_width:0] sum_bits, carry_bits, shifted_carry;
            logic [p_rows_width:0] unused_row_sum;
            logic unused_high_carry, exceeds_capacity;

            assign initial_row = (p_rows_width+1)'(i_initial_row);
            assign row_count = {1'b0, requested_rows[request][p_rows_width-1:0]};
            assign inverted_capacity = ~{1'b0, pool_rows};
            assign sum_bits = initial_row ^ row_count ^ inverted_capacity;
            assign carry_bits = (initial_row & row_count) |
                ((initial_row | row_count) & inverted_capacity);
            assign {unused_high_carry, shifted_carry} = {carry_bits, 1'b0};
            // 和值与进位并行形成，最终加法给出超过容量的进位。
            parallel_prefix_add #(
                .p_width(p_rows_width+1), .p_group_width(4), .p_preserve_groups(1'b1)
            ) u_end_compare (
                .i_a(sum_bits), .i_b(shifted_carry), .i_carry(1'b0),
                .o_sum(unused_row_sum), .o_carry(exceeds_capacity)
            );
            assign request_fits[request] = !(|requested_rows[request][31:p_rows_width]) &&
                !exceeds_capacity;
        end
        assign o_rows_fit = &request_fits;
    end else begin : g_wide_rows
        logic [63:0] reserve_rows;
        logic [63:0] initial_words, pool_words;

        // 宽参数配置保留 64 位无符号容量运算。
        assign reserve_rows = (i_reserve_rows > i_frame_rows) ? 64'(i_reserve_rows) : 64'(i_frame_rows);
        assign initial_words = 64'(i_initial_row) << 2;
        assign pool_words = 64'(i_bank_words) * 64'(i_bank_count);
        assign o_rows_fit = initial_words + (reserve_rows << 2) <= pool_words;
    end
endmodule

`default_nettype wire
