// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两个位段并行执行普通无符号减法，各段扩展的最高位保存借位。
(* keep_hierarchy = "yes" *)
module parallel_prefix_native_differences #(
    parameter int unsigned p_low_width = 17,
    parameter int unsigned p_high_width = 17
) (
    input wire logic [p_low_width-1:0] i_low_a, // 低位段被减数
    input wire logic [p_low_width-1:0] i_low_b, // 低位段减数
    input wire logic [p_high_width-1:0] i_high_a, // 高位段被减数
    input wire logic [p_high_width-1:0] i_high_b, // 高位段减数
    (* use_dsp = "simd" *) output logic [p_low_width-1:0] o_low_difference, // 低位段差值与借位
    (* use_dsp = "simd" *) output logic [p_high_width-1:0] o_high_difference // 高位段差值与借位
);
    assign o_low_difference = i_low_a - i_low_b;
    assign o_high_difference = i_high_a - i_high_b;
endmodule

`default_nettype wire
