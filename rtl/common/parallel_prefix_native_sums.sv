// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行计算低位段与高位段的普通加法，各段位宽包含最高进位。
(* keep_hierarchy = "yes" *)
module parallel_prefix_native_sums #(
    parameter int unsigned p_low_width = 17,
    parameter int unsigned p_high_width = 17
) (
    input wire logic [p_low_width-1:0] i_low_a, // 低位段第一个操作数
    input wire logic [p_low_width-1:0] i_low_b, // 低位段第二个操作数
    input wire logic [p_high_width-1:0] i_high_a, // 高位段第一个操作数
    input wire logic [p_high_width-1:0] i_high_b, // 高位段第二个操作数
    (* use_dsp = "simd" *) output logic [p_low_width-1:0] o_low_sum, // 低位段和值及最高进位
    (* use_dsp = "simd" *) output logic [p_high_width-1:0] o_high_sum // 高位段和值及最高进位
);
    assign o_low_sum = i_low_a + i_low_b;
    assign o_high_sum = i_high_a + i_high_b;
endmodule

`default_nettype wire
