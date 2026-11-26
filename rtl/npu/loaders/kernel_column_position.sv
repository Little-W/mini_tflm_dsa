// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按列组大小、组内偏移及起始列计算当前权重列位置。
`default_nettype wire
module kernel_column_position #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_count_width = 16,
    parameter int unsigned p_shift = 4
) (
    input wire logic [p_width-1:0] i_group, // 当前列组索引
    input wire logic [p_width-1:0] i_offset, // 当前组内或装载偏移
    input wire logic [p_width-1:0] i_base, // 计算起始位置
    output logic [p_width-1:0] o_position // 完整权重列位置
);
    localparam int unsigned p_high_width = p_width - p_count_width - p_shift;
    logic [p_count_width:0] a_ext, b_ext, c_ext;
    logic [p_count_width:0] compressed_sum, compressed_carry, total_sum;
    logic [p_count_width-1:0] unused_column_sum;
    logic group_carry;
    logic high_carry;
    logic [p_high_width-1:0] high_value, high_increment;
    assign a_ext = {1'b0, i_group[p_shift+:p_count_width]};
    assign b_ext = {1'b0, i_offset[p_shift+:p_count_width]};
    assign c_ext = {1'b0, i_base[p_shift+:p_count_width]};
    assign compressed_sum = a_ext ^ b_ext ^ c_ext;
    assign compressed_carry = ((a_ext & b_ext) | (a_ext & c_ext) | (b_ext & c_ext)) << 1;
    assign total_sum = compressed_sum + compressed_carry;
    assign {group_carry, unused_column_sum} = a_ext + b_ext;
    // 完整三项和的进位去除列号模宽溢出，得到配置坐标需要的进位。
    assign high_carry = total_sum[p_count_width] ^ group_carry;
    assign high_value = i_base[p_width-1 -: p_high_width];
    assign high_increment = high_value + p_high_width'(1);
    assign o_position[p_width-1 -: p_high_width] = high_carry ? high_increment : high_value;
    assign o_position[p_shift+:p_count_width] = total_sum[p_count_width-1:0];
    if (p_shift > 0) begin : g_low_bits
      assign o_position[p_shift-1:0] = i_base[p_shift-1:0];
    end
endmodule

`default_nettype wire
