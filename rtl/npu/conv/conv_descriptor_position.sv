// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 描述符提交时保存下一空间起点，后续请求只比较完整位置。
module conv_descriptor_position #(
  parameter int unsigned p_count_width = 5
) (
  input  wire logic                         clk,                  // 描述符时钟
  input  wire logic                         rst_n,                // 异步低有效复位
  input  wire logic                         i_configure,          // 当前周期接收新配置
  input  wire logic                         i_commit,             // 当前周期提交描述符
  input  wire logic                         i_invalid,            // 提交描述符未通过范围检查
  input  wire logic [31:0]                  i_commit_position,    // 提交描述符的空间起点
  input  wire logic [p_count_width-1:0]     i_commit_rows,        // 提交描述符的有效行数
  input  wire logic [31:0]                  i_position,           // 当前描述符的空间起点
  input  wire logic [p_count_width-1:0]     i_rows,               // 当前描述符的有效行数
  input  wire logic [31:0]                  i_target,             // 待接收描述符的空间起点
  output logic                         o_equal               // 待接收起点紧随当前分块
);

  //! 0. 辅助信号
  //! -------------

  logic [31:0] position_end;
  logic [31:0] position_sum_i_a;
  logic [31:0] position_sum_i_b;
  logic        position_sum_i_carry;
  logic [31:0] position_sum_o_sum;
  logic        unused_position_sum_o_carry;
  logic [31:0] reference_match_i_a;
  logic [31:0] reference_match_i_b;
  logic [31:0] reference_match_i_target;
  logic        reference_match_i_carry_in;
  logic        reference_match_o_equal;
  logic        saved_equal;
  localparam int p_equal_groups = (32 + 2) / 3;
  (* keep = "true" *) logic [p_equal_groups-1:0] position_group_equal;

  //! 1. 准备空间终点
  //! -----------------

  assign position_sum_i_a = i_commit_position;
  assign position_sum_i_b = 32'(i_commit_rows);
  assign position_sum_i_carry = 1'b0;
  parallel_prefix_add #(
    .p_width(32), .p_group_width(8), .p_preserve_groups(1'b1),
    .p_carry_select_width(16)
  ) u_position_sum (
    .i_a(position_sum_i_a),
    .i_b(position_sum_i_b),
    .i_carry(position_sum_i_carry),
    .o_sum(position_sum_o_sum),
    .o_carry(unused_position_sum_o_carry)
  );

  //! 2. 保存空间终点
  //! -----------------

  // 配置接收优先于描述符提交；无效描述符保持已有位置和行数。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      position_end <= 32'd0;
    end else if (i_configure) begin
    end else if (i_commit) begin
      if (i_invalid) begin
      end else begin
        position_end <= position_sum_o_sum;
      end
    end
  end

  //! 3. 比较后续起点
  //! -----------------

  // 每组三位先比较，完整位置由各组结果并行归并。
  for (genvar group_index = 0; group_index < p_equal_groups; group_index++) begin : g_position_group
    localparam int p_first = group_index * 3;
    localparam int p_width = 32 - p_first < 3 ? 32 - p_first : 3;
    assign position_group_equal[group_index] =
        position_end[p_first +: p_width] == i_target[p_first +: p_width];
  end
  assign saved_equal = &position_group_equal;
  assign reference_match_i_a = i_position;
  assign reference_match_i_b = 32'(i_rows);
  assign reference_match_i_target = i_target;
  assign reference_match_i_carry_in = 1'b0;
  add_equal #(.p_width(32), .p_preserve_bits(1'b1), .p_keep_bits(1'b0)) u_reference_match (
    .i_a(reference_match_i_a),
    .i_b(reference_match_i_b),
    .i_target(reference_match_i_target),
    .i_carry_in(reference_match_i_carry_in),
    .o_equal(reference_match_o_equal)
  );
  // 已知输入使用保存的终点；未知输入保留逐位进位关系的传播范围。
  always_comb begin
    o_equal = reference_match_o_equal;
    case (^{i_position, i_rows, i_target})
      1'b0, 1'b1: o_equal = saved_equal;
      default: begin end
    endcase
  end

endmodule

`default_nettype wire
