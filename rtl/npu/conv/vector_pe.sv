// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 操作数与操作码在同一使能边沿保存，各模式共用乘加和极值比较。
module vector_pe #(
  parameter bit ENABLE_EXTENDED_MULTIPLY=1'b1,
  parameter bit p_accumulator_preselected=1'b0
) (
  input wire logic clk,
  input wire logic i_en,
  input wire logic [2:0] i_op,
  input wire logic signed [15:0] i_a, i_b,
  input wire logic signed [31:0] i_acc,
  output logic signed [31:0] o_result
);
  logic [2:0] op;
  logic signed [15:0] a, b;
  logic signed [31:0] acc;
  logic [31:0] product_uu, product_su;
  logic signed [31:0] product_ss, extended_a;
  logic signed [32:0] mac_value;
  logic acc_high_equal, acc_less_than_a;
  logic signed [31:0] extremum;
  logic result_multiply, result_zero, result_compare;
  logic compare_select;

  // 乘法和求和所需的常量在寄存前选择，暂停时全部操作数共同保持。
  always_ff @(posedge clk) begin
    if (i_en) begin
      op <= i_op;
      // 输出来源与操作数共同保存，后级数据选择直接使用寄存资格。
      result_multiply <= 1'b0;
      result_zero <= 1'b0;
      result_compare <= 1'b0;
      case (i_op)
        3'd0, 3'd1, 3'd4: result_multiply <= 1'b1;
        3'd2, 3'd3: result_compare <= 1'b1;
        3'd5, 3'd6: result_zero <= 1'b1;
        default: begin end
      endcase
      a <= i_a;
      b <= i_op == 3'd1 ? 16'sd1 : i_b;
      if (p_accumulator_preselected) acc <= i_acc;
      else case (i_op)
        3'd4, 3'd5, 3'd6: acc <= 32'sd0;
        default: acc <= i_acc;
      endcase
    end
  end
  assign mac_value = $signed(a) * $signed(b) + $signed({acc[31], acc});
  assign product_ss = mac_value[31:0];
  generate
    if (ENABLE_EXTENDED_MULTIPLY) begin : g_extended_multiply
      assign product_su=$unsigned(product_ss)+(b[15] ? {a,16'b0} : 32'd0);
      assign product_uu=product_su+(a[15] ? {b,16'b0} : 32'd0);
    end else begin : g_signed_multiply
      assign product_su=32'd0;
      assign product_uu=32'd0;
    end
  endgenerate
  assign extended_a = {{16{a[15]}},a};
  // 高半字相等时比较低半字；高半字不等时，完整累加值的符号决定次序。
  assign acc_high_equal = acc[31:16] == {16{a[15]}};
  assign acc_less_than_a = acc_high_equal ? (acc[15:0] < a[15:0]) : acc[31];
  assign extremum = (acc_less_than_a ^ op[0]) ? extended_a : acc;
  assign compare_select = result_compare && (acc_less_than_a ^ op[0]);
  generate
    if (ENABLE_EXTENDED_MULTIPLY) begin : g_extended_result
      always_comb begin
        case (op)
          3'd0, 3'd1, 3'd4: o_result = product_ss;
          3'd2, 3'd3: o_result = extremum;
          3'd5: o_result = $signed(product_uu);
          3'd6: o_result = $signed(product_su);
          default: o_result = acc;
        endcase
      end
    end else begin : g_signed_result
      assign o_result = result_multiply ? product_ss : result_zero ? 32'sd0 :
          compare_select ? extended_a : acc;
    end
  endgenerate
endmodule

`default_nettype wire
