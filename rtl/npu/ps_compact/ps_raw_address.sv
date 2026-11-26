// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 常量除法通过倒数乘法估计商，再修正商与余数，输出线性位置的存储映射。
module ps_raw_address #(
    parameter integer WIDTH=13,
    parameter integer DIVISOR=5
) (
    input wire [WIDTH-1:0] linear /* 部分和原始数据的线性存储字位置 */,
    output wire [WIDTH-1:0] quotient /* 线性位置除以物理存储块数得到的块内地址 */,
    output wire [2:0] remainder /* 线性位置对应的物理存储块编号 */
);
    // 向上取整的定点倒数生成商估计，高位截取保留所需的整数部分。
    localparam [WIDTH:0] RECIPROCAL = (WIDTH+1)'(
        ((64'd1 << WIDTH) + 64'($unsigned(DIVISOR)) - 64'd1) / 64'($unsigned(DIVISOR)));
    wire [2*WIDTH:0] product=linear*RECIPROCAL;
    wire [WIDTH:0] estimate=product[2*WIDTH:WIDTH];
    wire [WIDTH+3:0] scaled_estimate=estimate*(WIDTH+4)'(DIVISOR);
    // 商估计对应的乘积越过输入时，商减一，余数补回一个除数。
    wire overshot=scaled_estimate>(WIDTH+4)'(linear);
    wire [WIDTH+3:0] residual=(WIDTH+4)'(linear)-scaled_estimate+
        (overshot ? (WIDTH+4)'(DIVISOR) : (WIDTH+4)'(0));
    assign quotient=WIDTH'(estimate-overshot);
    assign remainder=3'(residual);
endmodule

`default_nettype wire
