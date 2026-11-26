// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 串行归约在同一周期完成 INT32 加法或极值选择。
module vector_reduce_alu (
  input wire logic clk, // 保留的时钟接口。
  input wire logic signed [31:0] i_lhs, // 当前已累计的三十二位有符号归约值。
  input wire logic signed [31:0] i_rhs, // 本周期加入归约的三十二位有符号操作数。
  input wire logic i_max, // 选择较大值归约。
  input wire logic i_min, // 选择较小值归约，同时有效时优先于较大值选择。
  output logic signed [31:0] o_result // 按当前模式求和或选择极值得到的归约结果。
);
  logic [31:0] sum_i_a, sum_i_b;
  logic sum_i_carry;
  logic [31:0] sum_o_sum;
  logic unused_sum_carry;
  logic [3:0] byte_equal, byte_less, byte_greater;
  logic [3:0] less_terms, greater_terms;
  logic lhs_less, lhs_greater;

  assign sum_i_a = $unsigned(i_lhs);
  assign sum_i_b = $unsigned(i_rhs);
  assign sum_i_carry = 1'b0;

  // 各字节独立比较，只有更高字节全部相等时才采用当前字节的比较结果。
  for (genvar part = 0; part < 4; part++) begin : g_compare_byte
    assign byte_equal[part] = i_lhs[part*8+:8] == i_rhs[part*8+:8];
    assign byte_less[part] = i_lhs[part*8+:8] < i_rhs[part*8+:8];
    assign byte_greater[part] = !(byte_less[part] || byte_equal[part]);
    if (part == 3) begin : g_highest
      assign less_terms[part] = byte_less[part];
      assign greater_terms[part] = byte_greater[part];
    end else begin : g_lower
      assign less_terms[part] = byte_less[part] && (&byte_equal[3:part+1]);
      assign greater_terms[part] = byte_greater[part] && (&byte_equal[3:part+1]);
    end
  end
  assign lhs_less = (i_lhs[31] ^ i_rhs[31]) ? i_lhs[31] : (|less_terms);
  assign lhs_greater = (i_lhs[31] ^ i_rhs[31]) ? i_rhs[31] : (|greater_terms);

  parallel_prefix_add #(
      .p_width(32), .p_group_width(8), .p_preserve_groups(1'b1),
      .p_dsp_split_width(16), .p_parallel_high_prefix(1'b1),
      .p_keep_carry(1'b0), .p_preserve_grouped_unknowns(1'b1)
  ) u_sum (
    .i_a(sum_i_a),
    .i_b(sum_i_b),
    .i_carry(sum_i_carry),
    .o_sum(sum_o_sum),
    .o_carry(unused_sum_carry)
  );

  // 同时请求极大值与极小值时，极小值操作优先；加法按 INT32 保留低 32 位。
  always_comb begin
    o_result = sum_o_sum;
    if (i_max) begin
      o_result = lhs_greater ? i_lhs : i_rhs;
    end
    if (i_min) begin
      o_result = lhs_less ? i_lhs : i_rhs;
    end
  end
endmodule

`default_nettype wire
