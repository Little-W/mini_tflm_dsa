// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module vector_scalar_multiplier #(
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
    parameter bit p_use_dsp = 1'b1
`elsif SYNTHESIS
    parameter bit p_use_dsp = 1'b1
`else
    parameter bit p_use_dsp = 1'b0
`endif
) (
    input  wire logic clk,
    input  wire logic signed [31:0] a,
    input  wire logic signed [31:0] b,
    output logic signed [63:0] product
);
    registered_multiplier_s32 #(.p_use_dsp(p_use_dsp)) u_multiplier (
        .clk(clk), .i_en(1'b1), .i_a(a), .i_b(b), .o_product(product)
    );
endmodule

// 两个输入寄存阶段分别可选，全部流水阶段共用使能。
module registered_multiplier_s32 #(
    parameter bit p_input_register = 1'b0,
    parameter bit p_b_input_register = p_input_register,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
    parameter bit p_use_dsp = 1'b1
`elsif SYNTHESIS
    parameter bit p_use_dsp = 1'b1
`else
    parameter bit p_use_dsp = 1'b0
`endif
) (
    input  wire logic clk,
    input  wire logic i_en,
    input  wire logic signed [31:0] i_a,
    input  wire logic signed [31:0] i_b,
    output logic signed [63:0] o_product
);
    logic signed [31:0] operand_a, operand_b;

    generate
        if (!p_input_register) begin : g_direct_a
            assign operand_a = i_a;
        end else begin : g_registered_a
            always_ff @(posedge clk) begin
                if (i_en) operand_a <= i_a;
            end
        end
        if (!p_b_input_register) begin : g_direct_b
            assign operand_b = i_b;
        end else begin : g_registered_b
            always_ff @(posedge clk) begin
                if (i_en) operand_b <= i_b;
            end
        end
    endgenerate

    // 四个完整部分积由行为级乘法推断，各寄存阶段保持相同的使能周期。
    (* keep, use_dsp = "yes" *) logic [31:0] low_product;
    (* keep, use_dsp = "yes" *) logic signed [32:0] low_high_product;
    (* keep, use_dsp = "yes" *) logic signed [32:0] high_low_product;
    (* keep, use_dsp = "yes" *) logic signed [31:0] high_product;
    logic [47:0] diagonal;
    logic [47:0] low_high_extended, high_low_extended;
    logic [47:0] upper_sum;

    assign diagonal = {high_product, low_product[31:16]};

    always_ff @(posedge clk) begin
        if (i_en) begin
            low_product      <= operand_a[15:0] * operand_b[15:0];
            low_high_product <= $signed({1'b0, operand_a[15:0]}) * $signed(operand_b[31:16]);
            high_low_product <= $signed(operand_a[31:16]) * $signed({1'b0, operand_b[15:0]});
            high_product     <= $signed(operand_a[31:16]) * $signed(operand_b[31:16]);
        end
    end

    assign low_high_extended = {{15{low_high_product[32]}}, low_high_product};
    assign high_low_extended = {{15{high_low_product[32]}}, high_low_product};
    // 交叉部分积和高低部分积分别进行模四十八位加法，完整乘积保留全部有效位。
    // FPGA 配置使用普通加法表达式推断 DSP，其余配置使用四位分组并行进位。
    if (p_use_dsp) begin : g_inferred_upper_add
        (* use_dsp = "yes" *) logic [47:0] cross_sum;
        (* use_dsp = "yes" *) logic [47:0] inferred_sum;
        assign cross_sum = low_high_extended + high_low_extended;
        assign inferred_sum = diagonal + cross_sum;
        assign upper_sum = inferred_sum;
    end else begin : g_grouped_upper_add
        logic [47:0] compressed_sum, compressed_carry;
        logic unused_upper_add_carry;
        assign compressed_sum = diagonal ^ low_high_extended ^ high_low_extended;
        assign compressed_carry = ((diagonal & low_high_extended) |
                                   (diagonal & high_low_extended) |
                                   (low_high_extended & high_low_extended)) << 1;
        parallel_prefix_add #(
            .p_width(48), .p_group_width(4), .p_preserve_groups(1'b0)
        ) u_upper_add (
            .i_a(compressed_sum),
            .i_b(compressed_carry),
            .i_carry(1'b0),
            .o_sum(upper_sum),
            .o_carry(unused_upper_add_carry)
        );
    end

    always_ff @(posedge clk) begin
        if (i_en) o_product <= {upper_sum, low_product[15:0]};
    end
endmodule
`default_nettype wire
