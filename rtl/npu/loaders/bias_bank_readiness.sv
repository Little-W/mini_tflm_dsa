// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查两个偏置存储体的缓存块，模式与驻留条件提前准备后共同形成读取资格。
(* keep_hierarchy = "yes" *)
module bias_bank_readiness #(
    parameter int unsigned p_block_width = 5
) (
    input wire logic [1:0][p_block_width-1:0] i_bank_block, // 两个偏置存储体的起始块索引。
    input wire logic [p_block_width-1:0] i_current_block, // 当前执行分组的起始块索引。
    input wire logic [p_block_width-1:0] i_cache_block, // 向量缓存内偏置块相对存储体的索引。
    input wire logic [1:0] i_resident, // 两个存储体分别覆盖当前请求范围。
    input wire logic i_cache_valid, // 向量缓存已保存完整偏置数据。
    input wire logic i_cache_bank, // 向量缓存数据所属的存储体。
    input wire logic i_active_bank, // 当前执行选择的偏置存储体。
    input wire logic i_is_mode, // 当前采用输入驻留模式的标量读取。
    output logic o_cache_hit, // 当前执行存储体的向量缓存命中。
    output logic o_bias_valid // 当前执行所需偏置已经准备完成。
);
    (* keep = 1 *) logic [1:0] block_equal;
    (* keep = 1 *) logic [1:0] cache_selected_eligible;
    (* keep = 1 *) logic [1:0] resident_cache_eligible;
    (* keep = 1 *) logic scalar_ready;

    // 各存储体的控制资格独立于块索引计算，比较结果只经过末级归并。
    for (genvar bank = 0; bank < 2; bank++) begin : g_bank
        add_equal #(.p_width(p_block_width), .p_preserve_bits(1'b1)) u_match (
            .i_a(i_cache_block), .i_b(i_bank_block[bank]), .i_target(i_current_block),
            .i_carry_in(1'b0), .o_equal(block_equal[bank])
        );
        assign cache_selected_eligible[bank] = i_cache_valid &&
            i_cache_bank == 1'(bank) && i_active_bank == 1'(bank);
        assign resident_cache_eligible[bank] = cache_selected_eligible[bank] && i_resident[bank];
    end
    assign scalar_ready = i_is_mode && i_resident[i_active_bank];

    // 未知存储体编号保持数组索引和模加比较的四态传播。
    logic selected_block_equal;
    logic selected_cache_hit;
    add_equal #(.p_width(p_block_width), .p_preserve_bits(1'b1)) u_selected_match (
        .i_a(i_cache_block), .i_b(i_bank_block[i_active_bank]), .i_target(i_current_block),
        .i_carry_in(1'b0), .o_equal(selected_block_equal)
    );
    assign selected_cache_hit = i_cache_valid && i_cache_bank == i_active_bank && selected_block_equal;
    always_comb begin
        o_cache_hit = |(block_equal & cache_selected_eligible);
        o_bias_valid = scalar_ready || (|(block_equal & resident_cache_eligible));
        case (i_active_bank)
            1'b0, 1'b1: begin end
            default: begin
                o_cache_hit = selected_cache_hit;
                o_bias_valid = i_resident[i_active_bank] && (i_is_mode || selected_cache_hit);
            end
        endcase
    end
endmodule

`default_nettype wire
