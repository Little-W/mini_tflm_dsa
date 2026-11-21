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
  (* use_dsp = "yes" *) logic signed [32:0] mac_value;
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

// 操作数在使能边沿进入寄存器，操作码由上层独立寄存并持续控制当前结果。
module registered_vector_pe #(
`ifdef ASIC_SYNTHESIS
  parameter bit p_use_dsp = 1'b0,
`elsif XILINX_FPGA
  parameter bit p_use_dsp = 1'b1,
`elsif SYNTHESIS
  parameter bit p_use_dsp = 1'b1,
`else
  parameter bit p_use_dsp = 1'b0,
`endif
  parameter bit p_accumulator_preselected = 1'b0
) (
  input wire logic clk,
  input wire logic i_en,
  input wire logic [2:0] i_op,
  input wire logic signed [15:0] i_a,
  input wire logic signed [15:0] i_b,
  input wire logic signed [31:0] i_acc,
  output logic signed [31:0] o_result
);
  // p_use_dsp is retained for interface compatibility; synthesis can infer DSPs.
  logic signed [15:0] operand_a_q, operand_b_q;
  logic signed [31:0] operand_acc_q;

  always_ff @(posedge clk) begin
    if (i_en) begin
      operand_a_q <= i_a;
      operand_b_q <= i_b;
      operand_acc_q <= i_acc;
    end
  end

  vector_pe #(
      .ENABLE_EXTENDED_MULTIPLY(1'b0), .p_accumulator_preselected(p_accumulator_preselected)
  ) u_pe (
    .op(i_op), .a(operand_a_q), .b(operand_b_q),
    .acc(operand_acc_q), .result(o_result)
  );
endmodule

// 串行归约在同一周期完成 INT32 加法或极值选择。
module vector_reduce_alu #(
`ifdef ASIC_SYNTHESIS
  parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
  parameter bit p_use_dsp = 1'b1
`elsif SYNTHESIS
  parameter bit p_use_dsp = 1'b1
`else
  parameter bit p_use_dsp = 1'b0
`endif
) (
  input wire logic clk,
  input wire logic signed [31:0] i_lhs,
  input wire logic signed [31:0] i_rhs,
  input wire logic i_max,
  input wire logic i_min,
  output logic signed [31:0] o_result
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
    assign byte_greater[part] = i_lhs[part*8+:8] > i_rhs[part*8+:8];
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

  parallel_prefix_add #(.p_width(32), .p_group_width(4)) u_sum (
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
