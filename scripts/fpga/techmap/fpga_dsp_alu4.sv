// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 四个十位算术通道共用一个 DSP，各通道分别接收进位并保留完整结果。
(* techmap_celltype = "$__FPGA_DSP_ALU4" *)
module fpga_dsp_alu4 (
    input  wire logic [39:0] A,
    input  wire logic [39:0] B,
    input  wire logic [3:0]  CI,
    input  wire logic        BI,
    output logic [39:0] X,
    output logic [39:0] Y,
    output logic [39:0] CO
);

//! 0. 辅助信号
//! ---------------

logic [47:0] dsp_operand_a;
logic [47:0] dsp_operand_b;
logic [29:0] dsp_i_a;
logic [17:0] dsp_i_b;
logic [47:0] dsp_i_c;
logic [3:0] dsp_i_alumode;
logic [6:0] dsp_i_opmode;
logic dsp_i_zero;
logic [2:0] dsp_i_carryinsel;
logic [4:0] dsp_i_inmode;
logic [24:0] dsp_i_d;
logic [29:0] dsp_i_acin;
logic [17:0] dsp_i_bcin;
logic [47:0] dsp_i_pcin;
logic [47:0] dsp_o_p;
logic [3:0] dsp_o_carryout;
logic [29:0] unused_acout;
logic [17:0] unused_bcout;
logic [47:0] unused_pcout;
logic unused_carrycascout;
logic unused_multsignout;
logic unused_overflow;
logic unused_underflow;
logic unused_patterndetect;
logic unused_patternbdetect;

//! 1. 独立通道的进位编码
//! ---------------------------

// 每个十二位段的中间十位保存操作数，最低位编码本通道的独立进位。
// 段内最高位保存和或差的符号与进位，FOUR12 阻断四个段之间的进位。
for (genvar lane = 0; lane < 4; lane++) begin : g_input_lane
    assign dsp_operand_a[12*lane +: 12] = {1'b0, A[10*lane +: 10], CI[lane] & ~BI};
    assign dsp_operand_b[12*lane +: 12] = {1'b0, B[10*lane +: 10], BI ? ~CI[lane] : CI[lane]};
end

assign dsp_i_a         = dsp_operand_b[47:18];
assign dsp_i_b         = dsp_operand_b[17:0];
assign dsp_i_c         = dsp_operand_a;
assign dsp_i_alumode   = {2'b00, BI, BI};
assign dsp_i_opmode    = 7'b0110011;
assign dsp_i_zero      = 1'b0;
assign dsp_i_carryinsel = 3'b000;
assign dsp_i_inmode    = 5'b00000;
assign dsp_i_d         = 25'd0;
assign dsp_i_acin      = 30'd0;
assign dsp_i_bcin      = 18'd0;
assign dsp_i_pcin      = 48'd0;

//! 2. 四通道组合算术
//! -----------------------

// BI=0 时每段计算 A+B+CI；BI=1 时计算 A-B-(1-CI)。
// 所有内部寄存器旁路，输入和输出维持组合关系。
DSP48E1 #(
    .A_INPUT("DIRECT"), .B_INPUT("DIRECT"), .USE_DPORT("FALSE"),
    .USE_MULT("NONE"), .USE_SIMD("FOUR12"),
    .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .CREG(0), .DREG(0),
    .ADREG(0), .MREG(0), .PREG(0), .INMODEREG(0), .OPMODEREG(0),
    .ALUMODEREG(0), .CARRYINREG(0), .CARRYINSELREG(0)
) u_dsp (
    .A(dsp_i_a), .B(dsp_i_b), .C(dsp_i_c), .D(dsp_i_d),
    .ACIN(dsp_i_acin), .BCIN(dsp_i_bcin), .PCIN(dsp_i_pcin),
    .ALUMODE(dsp_i_alumode), .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode),
    .CARRYIN(dsp_i_zero), .CARRYINSEL(dsp_i_carryinsel),
    .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero), .CLK(dsp_i_zero),
    .CEA1(dsp_i_zero), .CEA2(dsp_i_zero), .CEB1(dsp_i_zero), .CEB2(dsp_i_zero),
    .CEC(dsp_i_zero), .CED(dsp_i_zero), .CEAD(dsp_i_zero), .CEM(dsp_i_zero),
    .CEP(dsp_i_zero), .CEINMODE(dsp_i_zero), .CECTRL(dsp_i_zero),
    .CEALUMODE(dsp_i_zero), .CECARRYIN(dsp_i_zero),
    .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
    .RSTM(dsp_i_zero), .RSTP(dsp_i_zero), .RSTINMODE(dsp_i_zero),
    .RSTCTRL(dsp_i_zero), .RSTALUMODE(dsp_i_zero), .RSTALLCARRYIN(dsp_i_zero),
    .P(dsp_o_p), .CARRYOUT(dsp_o_carryout),
    .ACOUT(unused_acout), .BCOUT(unused_bcout), .PCOUT(unused_pcout),
    .CARRYCASCOUT(unused_carrycascout), .MULTSIGNOUT(unused_multsignout),
    .OVERFLOW(unused_overflow), .UNDERFLOW(unused_underflow),
    .PATTERNDETECT(unused_patterndetect), .PATTERNBDETECT(unused_patternbdetect)
);

//! 3. 全部和位与进位输出
//! ---------------------------

for (genvar lane = 0; lane < 4; lane++) begin : g_output_lane
    assign X[10*lane +: 10] = A[10*lane +: 10] ^ B[10*lane +: 10] ^ {10{BI}};
    assign Y[10*lane +: 10] = dsp_o_p[12*lane+1 +: 10];
    // 相邻和位恢复逐位进位，最高进位同时恢复减法的借位极性。
    assign CO[10*lane +: 9] = X[10*lane+1 +: 9] ^ Y[10*lane+1 +: 9];
    assign CO[10*lane+9] = dsp_o_p[12*lane+11] ^ BI;
end

endmodule
`default_nettype wire
