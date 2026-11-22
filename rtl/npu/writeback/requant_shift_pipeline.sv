// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两级有符号右移保留三十四位商、保护位和舍弃位，支持最近偶数舍入。
module requant_shift_pipeline (
    input  logic clk,
    input  logic i_en,
    input  logic signed [63:0] i_product,
    input  logic [6:0] i_amount,
    output logic signed [33:0] o_quotient,
    output logic o_increment
);
    //! 0. 移位与舍入信号
    //! ------------------

    logic signed [65:0] coarse_value [0:3];
    logic signed [42:0] coarse_q;
    logic [2:0] fine_amount_q;
    logic coarse_overflow_q, sign_q, zero_q;
    logic signed [42:0] fine_value [0:3];
    logic fine_overflow;
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
    always_ff @(posedge clk) begin
        if (i_en) begin
            coarse_q <= coarse_value[3][42:0];
            coarse_overflow_q <= coarse_value[3][65:42] != {24{coarse_value[3][42]}};
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
    assign fine_overflow = coarse_overflow_q ||
        fine_value[3][42:35] != {8{fine_value[3][35]}};
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
