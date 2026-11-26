// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两级有符号右移保留三十四位商、保护位和舍弃位，支持最近偶数舍入。
module requant_shift_pipeline (
    input  wire logic clk /* 工作时钟 */,
    input  wire logic i_en /* 推进两级乘积右移流水 */,
    input  wire logic signed [63:0] i_product /* 待舍入的64 位有符号乘积 */,
    input  wire logic [6:0] i_amount /* 乘积的总算术右移位数 */,
    output logic signed [33:0] o_quotient /* 右移后保留的34 位有符号商 */,
    output logic o_increment /* 按最近偶数舍入规则需要加一 */
);
    //! 0. 移位与舍入信号
    //! ------------------

    logic signed [65:0] coarse_value [0:3];
    logic signed [42:0] coarse_q;
    logic [2:0] fine_amount_q;
    logic coarse_overflow_q, sign_q, zero_q;
    logic signed [42:0] fine_value [0:3];
    logic fine_overflow;
    logic coarse_overflow;
    logic coarse_overflow_fast;
    logic fine_overflow_fast;
    logic [6:0] fine_difference;
    logic [6:0] fine_overflow_terms;
    logic signed [33:0] bounded_quotient;

    //! 1. 保存粗移位结果
    //! ------------------

    // 低两位依次保存保护位与全部已舍弃位的或值。
    assign coarse_value[0] = {i_product, 2'b00};
    for (genvar stage = 0; stage < 3; stage++) begin : g_coarse
        localparam int p_distance = 32 >> stage;
        assign coarse_value[stage+1] = i_amount[5-stage] ?
            {{p_distance{coarse_value[stage][65]}}, coarse_value[stage][65:p_distance+1],
             (|coarse_value[stage][p_distance:0])} : coarse_value[stage];
    end
    // 粗移位的溢出只检查仍可能超出保留范围的三个原始高段。
    always_comb begin
        coarse_overflow_fast = 1'b0;
        case (i_amount[5:3])
            3'd0: coarse_overflow_fast = i_product[63:40] != {24{i_product[40]}};
            3'd1: coarse_overflow_fast = i_product[63:48] != {16{i_product[48]}};
            3'd2: coarse_overflow_fast = i_product[63:56] != {8{i_product[56]}};
            default: begin end
        endcase
        coarse_overflow = coarse_value[3][65:42] != {24{coarse_value[3][42]}};
        case (^{i_product, i_amount[5:3]})
            1'b0, 1'b1: coarse_overflow = coarse_overflow_fast;
            default: begin end
        endcase
    end
    always_ff @(posedge clk) begin
        if (i_en) begin
            coarse_q <= coarse_value[3][42:0];
            coarse_overflow_q <= coarse_overflow;
            fine_amount_q <= i_amount[2:0];
            sign_q <= i_product[63];
            zero_q <= i_amount[6];
        end
    end

    //! 2. 保存细移位与舍入结果
    //! ------------------------

    // 剩余移位最多七位，四十三位中间值保留最终商的全部有效位。
    assign fine_value[0] = coarse_q;
    for (genvar stage = 0; stage < 3; stage++) begin : g_fine
        localparam int p_distance = 4 >> stage;
        assign fine_value[stage+1] = fine_amount_q[2-stage] ?
            {{p_distance{fine_value[stage][42]}}, fine_value[stage][42:p_distance+1],
             (|fine_value[stage][p_distance:0])} : fine_value[stage];
    end
    // 符号扩展检查直接读取已寄存高位，各位是否保留由细移位量并行决定。
    assign fine_difference = coarse_q[41:35] ^ {7{coarse_q[42]}};
    for (genvar bit_index = 0; bit_index < 7; bit_index++) begin : g_fine_overflow
        assign fine_overflow_terms[bit_index] = fine_difference[bit_index] &&
            fine_amount_q <= 3'(bit_index);
    end
    assign fine_overflow_fast = |fine_overflow_terms;
    always_comb begin
        fine_overflow = coarse_overflow_q ||
            fine_value[3][42:35] != {8{fine_value[3][35]}};
        case (^{coarse_q, fine_amount_q})
            1'b0, 1'b1: fine_overflow = coarse_overflow_q || fine_overflow_fast;
            default: begin end
        endcase
    end
    always_comb begin
        bounded_quotient = $signed(fine_value[3][35:2]);
        if (zero_q) bounded_quotient = '0;
        else if (fine_overflow)
            bounded_quotient = sign_q ? 34'sh200000000 : 34'sh1ffffffff;
    end
    always_ff @(posedge clk) begin
        if (i_en) begin
            o_quotient <= bounded_quotient;
            o_increment <= !zero_q && fine_value[3][1] &&
                (fine_value[3][0] || fine_value[3][2]);
        end
    end
endmodule

`default_nettype wire
