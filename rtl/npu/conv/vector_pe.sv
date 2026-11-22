// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 十六位乘法器同时承担乘加、加法及完整乘积组合。
module vector_pe #(
  parameter bit ENABLE_EXTENDED_MULTIPLY=1'b1,
  parameter bit p_accumulator_preselected=1'b0
) (
  input wire logic [2:0] op,
  input wire logic signed [15:0] a, b,
  input wire logic signed [31:0] acc,
  output logic signed [31:0] result
);
  logic [31:0] product_uu, product_su;
  logic signed [31:0] product_ss, extended_a;
  logic signed [15:0] mac_rhs;
  logic signed [31:0] mac_acc;
  logic signed [32:0] mac_value;
  logic acc_high_equal, acc_less_than_a;
  logic signed [31:0] extremum;

  // 求和操作把第二乘数设为一，与乘加操作共用同一个算术单元。
  assign mac_rhs = op == 3'd1 ? 16'sd1 : b;
  // 预选模式由调用方在纯乘法输入周期提供零累加值，乘加直接使用已保存操作数。
  assign mac_acc = p_accumulator_preselected ? acc :
      ((op == 3'd0 || op == 3'd1) ? acc : 32'sd0);
  assign mac_value = $signed(a) * $signed(mac_rhs) + $signed({mac_acc[31], mac_acc});
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
  always_comb begin
    case (op)
      3'd0: result = product_ss;
      3'd1: result = product_ss;
      3'd2, 3'd3: result = extremum;
      3'd4: result = product_ss;
      3'd5: result = $signed(product_uu);
      3'd6: result = $signed(product_su);
      default: result = acc;
    endcase
  end
endmodule

`default_nettype wire
