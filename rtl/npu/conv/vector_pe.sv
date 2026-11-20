// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// One 16-bit multiplier supports signed MAC and full-width product assembly.
module vector_pe #(
  parameter bit ENABLE_EXTENDED_MULTIPLY=1'b1
) (
  input logic [2:0] op,
  input logic signed [15:0] a, b,
  input logic signed [31:0] acc,
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
  always_comb begin
    case (op)
      3'd0: result = product_ss;
      3'd1: result = acc + extended_a;
      3'd2: result = (acc > extended_a) ? acc : extended_a;
      3'd3: result = (acc < extended_a) ? acc : extended_a;
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
  input logic clk,
  input logic i_en,
  input logic [2:0] i_op,
  input logic signed [15:0] i_a,
  input logic signed [15:0] i_b,
  input logic signed [31:0] i_acc,
  output logic signed [31:0] o_result
);
  //! 0. 操作数寄存
  //! -------------

  logic signed [15:0] operand_a_q;
  logic signed [31:0] operand_acc_q;

  // 极值选择保留原始输入与累加值；关闭使能时所有操作数同时保持。
  always_ff @(posedge clk) begin
    if (i_en) begin
      operand_a_q <= i_a;
      operand_acc_q <= i_acc;
    end
  end

  //! 1. 算术与极值选择
  //! -----------------

  if (p_use_dsp) begin : g_dsp
    logic multiply_operation;
    logic compare_operation;
    logic [29:0] dsp_i_a;
    logic [29:0] dsp_i_acin;
    logic [17:0] dsp_i_b;
    logic [17:0] dsp_i_bcin;
    logic [47:0] dsp_i_c;
    logic [24:0] dsp_i_d;
    logic [47:0] dsp_i_pcin;
    logic [6:0] dsp_i_opmode;
    logic [4:0] dsp_i_inmode;
    logic [3:0] dsp_i_alumode;
    logic [2:0] dsp_i_carry_select;
    logic dsp_i_zero;
    logic dsp_i_en;
    logic [47:0] dsp_o_p;
    logic [29:0] unused_acout;
    logic [17:0] unused_bcout;
    logic [47:0] unused_pcout;
    logic [3:0] unused_carryout;
    logic unused_carrycascout;
    logic unused_multsignout;
    logic unused_overflow;
    logic unused_underflow;
    logic unused_patterndetect;
    logic unused_patternbdetect;
    logic signed [31:0] extended_a;
    logic signed [31:0] extrema_result;

    assign multiply_operation = (i_op == 3'd0) || (i_op == 3'd4);
    assign compare_operation = (i_op == 3'd2) || (i_op == 3'd3);
    assign dsp_i_a = 30'($signed(i_b));
    assign dsp_i_acin = '0;
    assign dsp_i_b = 18'($signed(i_a));
    assign dsp_i_bcin = '0;
    assign dsp_i_c = 48'($signed(operand_acc_q));
    assign dsp_i_d = 25'd1;
    assign dsp_i_pcin = '0;
    assign dsp_i_opmode = (i_op == 3'd4) ? 7'b0000101 : 7'b0110101;
    assign dsp_i_inmode = multiply_operation ? 5'b00000 : 5'b00110;
    assign dsp_i_alumode = compare_operation ? 4'b0011 : 4'b0000;
    assign dsp_i_carry_select = '0;
    assign dsp_i_zero = 1'b0;
    assign dsp_i_en = i_en;
    assign extended_a = 32'($signed(operand_a_q));

    // AREG/BREG 同拍保存 b/a；预加法选择 b 或常数一，共用乘法和加减法。
    // 比较采用四十八位 acc-a，符号位覆盖全部 INT32/INT16 输入范围。
    DSP48E1 #(
      .AREG(1), .ACASCREG(1), .BREG(1), .BCASCREG(1), .ADREG(0),
      .CREG(0), .DREG(0), .MREG(0), .PREG(0), .CARRYINREG(0),
      .CARRYINSELREG(0), .INMODEREG(0), .OPMODEREG(0), .ALUMODEREG(0),
      .USE_DPORT("TRUE"), .USE_MULT("MULTIPLY"), .USE_SIMD("ONE48")
    ) u_dsp (
      .CLK(clk), .A(dsp_i_a), .ACIN(dsp_i_acin), .B(dsp_i_b), .BCIN(dsp_i_bcin),
      .C(dsp_i_c), .D(dsp_i_d), .PCIN(dsp_i_pcin),
      .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode), .ALUMODE(dsp_i_alumode),
      .CARRYIN(dsp_i_zero), .CARRYINSEL(dsp_i_carry_select),
      .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero),
      .CEA1(dsp_i_zero), .CEA2(dsp_i_en), .CEAD(dsp_i_zero),
      .CEB1(dsp_i_zero), .CEB2(dsp_i_en), .CEC(dsp_i_zero),
      .CECARRYIN(dsp_i_zero), .CED(dsp_i_zero), .CEM(dsp_i_zero), .CEP(dsp_i_zero),
      .CECTRL(dsp_i_zero), .CEINMODE(dsp_i_zero), .CEALUMODE(dsp_i_zero),
      .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
      .RSTM(dsp_i_zero), .RSTP(dsp_i_zero), .RSTALLCARRYIN(dsp_i_zero),
      .RSTCTRL(dsp_i_zero), .RSTINMODE(dsp_i_zero), .RSTALUMODE(dsp_i_zero),
      .P(dsp_o_p), .ACOUT(unused_acout), .BCOUT(unused_bcout), .PCOUT(unused_pcout),
      .CARRYOUT(unused_carryout), .CARRYCASCOUT(unused_carrycascout),
      .MULTSIGNOUT(unused_multsignout), .OVERFLOW(unused_overflow),
      .UNDERFLOW(unused_underflow), .PATTERNDETECT(unused_patterndetect),
      .PATTERNBDETECT(unused_patternbdetect)
    );

    assign extrema_result = ((i_op == 3'd2) ? !dsp_o_p[47] : dsp_o_p[47]) ?
        operand_acc_q : extended_a;
    always_comb begin
      o_result = operand_acc_q;
      case (i_op)
        3'd0, 3'd1, 3'd4: o_result = $signed(dsp_o_p[31:0]);
        3'd2, 3'd3: o_result = extrema_result;
        3'd5, 3'd6: o_result = 32'sd0;
      endcase
    end
  end else begin : g_generic
    logic signed [15:0] operand_b_q;
    logic [2:0] pe_i_op;
    logic signed [15:0] pe_i_a;
    logic signed [15:0] pe_i_b;
    logic signed [31:0] pe_i_acc;
    logic signed [31:0] pe_o_result;

    always_ff @(posedge clk) begin
      if (i_en) begin
        operand_b_q <= i_b;
      end
    end
    assign pe_i_op = i_op;
    assign pe_i_a = operand_a_q;
    assign pe_i_b = operand_b_q;
    assign pe_i_acc = operand_acc_q;
    assign o_result = pe_o_result;
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_pe (
      .op(pe_i_op), .a(pe_i_a), .b(pe_i_b), .acc(pe_i_acc), .result(pe_o_result)
    );
  end
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
  input logic clk,
  input logic signed [31:0] i_lhs,
  input logic signed [31:0] i_rhs,
  input logic i_max,
  input logic i_min,
  output logic signed [31:0] o_result
);
  if (p_use_dsp) begin : g_dsp
    logic [47:0] extended_rhs;
    logic compare_operation;
    logic [29:0] dsp_i_a, dsp_i_acin;
    logic [17:0] dsp_i_b, dsp_i_bcin;
    logic [47:0] dsp_i_c, dsp_i_pcin;
    logic [24:0] dsp_i_d;
    logic [6:0] dsp_i_opmode;
    logic [4:0] dsp_i_inmode;
    logic [3:0] dsp_i_alumode;
    logic [2:0] dsp_i_carry_select;
    logic dsp_i_zero;
    logic [47:0] dsp_o_p;
    logic [29:0] unused_acout;
    logic [17:0] unused_bcout;
    logic [47:0] unused_pcout;
    logic [3:0] unused_carryout;
    logic unused_carrycascout, unused_multsignout;
    logic unused_overflow, unused_underflow;
    logic unused_patterndetect, unused_patternbdetect;
    logic signed [31:0] extrema_result;

    assign extended_rhs = 48'($signed(i_rhs));
    assign compare_operation = i_max || i_min;
    assign dsp_i_a = extended_rhs[47:18];
    assign dsp_i_b = extended_rhs[17:0];
    assign dsp_i_c = 48'($signed(i_lhs));
    assign dsp_i_acin = '0;
    assign dsp_i_bcin = '0;
    assign dsp_i_pcin = '0;
    assign dsp_i_d = '0;
    assign dsp_i_opmode = 7'b0110011;
    assign dsp_i_inmode = '0;
    assign dsp_i_alumode = compare_operation ? 4'b0011 : 4'b0000;
    assign dsp_i_carry_select = '0;
    assign dsp_i_zero = 1'b0;

    // 四十八位 lhs-rhs 的符号覆盖两个 INT32 输入的完整差值范围。
    // 所有内部寄存器均旁路，外部归约寄存器保持原有更新边沿。
    DSP48E1 #(
      .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .ADREG(0),
      .CREG(0), .DREG(0), .MREG(0), .PREG(0), .CARRYINREG(0),
      .CARRYINSELREG(0), .INMODEREG(0), .OPMODEREG(0), .ALUMODEREG(0),
      .USE_DPORT("FALSE"), .USE_MULT("NONE"), .USE_SIMD("ONE48")
    ) u_dsp (
      .CLK(clk), .A(dsp_i_a), .ACIN(dsp_i_acin), .B(dsp_i_b), .BCIN(dsp_i_bcin),
      .C(dsp_i_c), .D(dsp_i_d), .PCIN(dsp_i_pcin),
      .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode), .ALUMODE(dsp_i_alumode),
      .CARRYIN(dsp_i_zero), .CARRYINSEL(dsp_i_carry_select),
      .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero),
      .CEA1(dsp_i_zero), .CEA2(dsp_i_zero), .CEAD(dsp_i_zero),
      .CEB1(dsp_i_zero), .CEB2(dsp_i_zero), .CEC(dsp_i_zero),
      .CECARRYIN(dsp_i_zero), .CED(dsp_i_zero), .CEM(dsp_i_zero), .CEP(dsp_i_zero),
      .CECTRL(dsp_i_zero), .CEINMODE(dsp_i_zero), .CEALUMODE(dsp_i_zero),
      .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
      .RSTM(dsp_i_zero), .RSTP(dsp_i_zero), .RSTALLCARRYIN(dsp_i_zero),
      .RSTCTRL(dsp_i_zero), .RSTINMODE(dsp_i_zero), .RSTALUMODE(dsp_i_zero),
      .P(dsp_o_p), .ACOUT(unused_acout), .BCOUT(unused_bcout), .PCOUT(unused_pcout),
      .CARRYOUT(unused_carryout), .CARRYCASCOUT(unused_carrycascout),
      .MULTSIGNOUT(unused_multsignout), .OVERFLOW(unused_overflow),
      .UNDERFLOW(unused_underflow), .PATTERNDETECT(unused_patterndetect),
      .PATTERNBDETECT(unused_patternbdetect)
    );

    assign extrema_result = (i_min ? dsp_o_p[47] : !dsp_o_p[47]) ? i_lhs : i_rhs;
    assign o_result = compare_operation ? extrema_result : $signed(dsp_o_p[31:0]);
  end else begin : g_generic
    always_comb begin
      o_result = i_lhs + i_rhs;
      if (i_max) o_result = i_lhs > i_rhs ? i_lhs : i_rhs;
      if (i_min) o_result = i_lhs < i_rhs ? i_lhs : i_rhs;
    end
  end
endmodule

`default_nettype wire
