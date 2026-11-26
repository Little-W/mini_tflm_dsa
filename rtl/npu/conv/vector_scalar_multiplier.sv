// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 连续接收两个有符号三十二位乘数，通过寄存乘法流水输出完整六十四位积。
module vector_scalar_multiplier (
    input  wire logic clk, // 模块工作时钟。
    input  wire logic signed [31:0] a, // 第一个三十二位有符号乘数。
    input  wire logic signed [31:0] b, // 第二个三十二位有符号乘数。
    output logic signed [63:0] product // 乘法流水输出的完整六十四位有符号积。
);
    registered_multiplier_s32 u_multiplier (
        .clk(clk), .i_en(1'b1), .i_a(a), .i_b(b), .o_product(product)
    );
endmodule

`default_nettype wire
