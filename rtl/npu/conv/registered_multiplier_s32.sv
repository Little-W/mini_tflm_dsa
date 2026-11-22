// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两个输入寄存阶段分别可选，全部流水阶段共用使能。
module registered_multiplier_s32 #(
    parameter bit p_input_register = 1'b0,
    parameter bit p_b_input_register = p_input_register
) (
    input  wire logic clk,
    input  wire logic i_en,
    input  wire logic signed [31:0] i_a,
    input  wire logic signed [31:0] i_b,
    output logic signed [63:0] o_product
);
    //! 0. 运算数据与进位
    //! -----------------

    logic signed [31:0] operand_a, operand_b;
    logic [31:0] low_product;
    logic signed [32:0] low_high_product;
    logic signed [32:0] high_low_product;
    logic signed [31:0] high_product;
    logic [47:0] diagonal;
    logic [47:0] low_high_extended, high_low_extended;
    logic [47:0] upper_sum, compressed_sum, compressed_carry;
    logic unused_upper_add_carry;

    //! 1. 选择输入寄存阶段
    //! -------------------

    generate
        if (!p_input_register) begin : g_direct_a
            assign operand_a = i_a;
        end else begin : g_registered_a
            always_ff @(posedge clk) begin
                if (i_en) begin
                    operand_a <= i_a;
                end
            end
        end
        if (!p_b_input_register) begin : g_direct_b
            assign operand_b = i_b;
        end else begin : g_registered_b
            always_ff @(posedge clk) begin
                if (i_en) begin
                    operand_b <= i_b;
                end
            end
        end
    endgenerate

    //! 2. 保存有符号部分积
    //! -------------------

    // 低半字按无符号数扩展，高半字保留符号，四个部分积使用同一使能。
    always_ff @(posedge clk) begin
        if (i_en) begin
            low_product      <= operand_a[15:0] * operand_b[15:0];
            low_high_product <= $signed({1'b0, operand_a[15:0]}) * $signed(operand_b[31:16]);
            high_low_product <= $signed(operand_a[31:16]) * $signed({1'b0, operand_b[15:0]});
            high_product     <= $signed(operand_a[31:16]) * $signed(operand_b[31:16]);
        end
    end

    //! 3. 组合并保存完整乘积
    //! ---------------------

    assign diagonal = {high_product, low_product[31:16]};
    assign low_high_extended = {{15{low_high_product[32]}}, low_high_product};
    assign high_low_extended = {{15{high_low_product[32]}}, high_low_product};
    // 三项先按位压缩为和与进位，再完成四十八位模加法。
    assign compressed_sum = diagonal ^ low_high_extended ^ high_low_extended;
    assign compressed_carry = ((diagonal & low_high_extended) |
                               (diagonal & high_low_extended) |
                               (low_high_extended & high_low_extended)) << 1;
    parallel_prefix_add #(
        .p_width(48), .p_group_width(8), .p_preserve_groups(1'b1)
    ) u_upper_add (
        .i_a(compressed_sum),
        .i_b(compressed_carry),
        .i_carry(1'b0),
        .o_sum(upper_sum),
        .o_carry(unused_upper_add_carry)
    );

    always_ff @(posedge clk) begin
        if (i_en) begin
            o_product <= {upper_sum, low_product[15:0]};
        end
    end
endmodule

`default_nettype wire
