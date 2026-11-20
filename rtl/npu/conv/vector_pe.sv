// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// One 16-bit multiplier supports signed MAC and full-width product assembly.
module vector_pe #(
  parameter bit ENABLE_EXTENDED_MULTIPLY=1'b1
) (
  input wire logic [2:0] op,
  input wire logic signed [15:0] a, b,
  input wire logic signed [31:0] acc,
  output logic signed [31:0] result
);
  logic [31:0] product_uu, product_su;
  logic signed [31:0] product_ss, extended_a;
  wire signed [31:0] mac_acc = op==3'd0 ? acc : 32'sd0;
  (* use_dsp = "yes" *) wire signed [32:0] mac_value =
      $signed(a) * $signed(b) + $signed({mac_acc[31],mac_acc});
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
  // Both extrema use the same signed comparison; equality selects equivalent values.
  wire acc_less_than_a = acc < extended_a;
  wire signed [31:0] extremum = (acc_less_than_a ^ op[0]) ? extended_a : acc;
  always_comb begin
    case (op)
      3'd0: result = product_ss;
      3'd1: result = acc + extended_a;
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

  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_pe (
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
  // i_min has priority when both extrema controls are asserted.
  always_comb begin
    o_result = i_lhs + i_rhs;
    if (i_max) o_result = i_lhs > i_rhs ? i_lhs : i_rhs;
    if (i_min) o_result = i_lhs < i_rhs ? i_lhs : i_rhs;
  end
endmodule

`default_nettype wire
