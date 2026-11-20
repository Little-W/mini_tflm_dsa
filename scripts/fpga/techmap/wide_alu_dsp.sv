`default_nettype none

// Yosys 算术单元的组合映射，保留 X、Y 和逐位进位输出。
(* techmap_celltype = "$__FPGA_DSP_ALU" *)
module fpga_dsp_alu #(
    parameter integer A_SIGNED = 0,
    parameter integer B_SIGNED = 0,
    parameter integer A_WIDTH  = 1,
    parameter integer B_WIDTH  = 1,
    parameter integer Y_WIDTH  = 1
) (
    input  logic [A_WIDTH-1:0] A,
    input  logic [B_WIDTH-1:0] B,
    input  logic               CI,
    input  logic               BI,
    output logic [Y_WIDTH-1:0] X,
    output logic [Y_WIDTH-1:0] Y,
    output logic [Y_WIDTH-1:0] CO
);

//! 0. 辅助信号
//! ---------------

logic [Y_WIDTH-1:0] a_extended;
logic [Y_WIDTH-1:0] b_extended;
logic [47:0] dsp_operand_b;
logic [29:0] dsp_i_a;
logic [17:0] dsp_i_b;
logic [47:0] dsp_i_c;
logic [3:0] dsp_i_alumode;
logic [6:0] dsp_i_opmode;
logic dsp_i_carryin;
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

//! 1. 输入规格化
//! -----------------

// 零位操作数表示常量零；两个操作数同时有符号时按 $alu 的规则扩展。
generate
    if (A_SIGNED != 0 && B_SIGNED != 0) begin : g_signed
        assign a_extended = (A_WIDTH == 0) ? '0 : Y_WIDTH'($signed(A));
        assign b_extended = (B_WIDTH == 0) ? '0 : Y_WIDTH'($signed(B));
    end else begin : g_unsigned
        assign a_extended = (A_WIDTH == 0) ? '0 : Y_WIDTH'($unsigned(A));
        assign b_extended = (B_WIDTH == 0) ? '0 : Y_WIDTH'($unsigned(B));
    end
endgenerate

assign dsp_operand_b  = 48'(b_extended);
assign dsp_i_a        = dsp_operand_b[47:18];
assign dsp_i_b        = dsp_operand_b[17:0];
assign dsp_i_c        = 48'(a_extended);
assign dsp_i_alumode  = {2'b00, BI, BI};
assign dsp_i_opmode   = 7'b0110011;
assign dsp_i_carryin  = CI ^ BI;
assign dsp_i_zero     = 1'b0;
assign dsp_i_carryinsel = 3'b000;
assign dsp_i_inmode   = 5'b00000;
assign dsp_i_d        = 25'd0;
assign dsp_i_acin     = 30'd0;
assign dsp_i_bcin     = 18'd0;
assign dsp_i_pcin     = 48'd0;

//! 2. DSP 组合计算
//! -------------------

// BI=0 计算 A+B+CI；BI=1 计算 A-B-(1-CI)，保持逐周期组合行为。
DSP48E1 #(
    .A_INPUT("DIRECT"), .B_INPUT("DIRECT"), .USE_DPORT("FALSE"),
    .USE_MULT("NONE"), .USE_SIMD("ONE48"),
    .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .CREG(0), .DREG(0),
    .ADREG(0), .MREG(0), .PREG(0), .INMODEREG(0), .OPMODEREG(0),
    .ALUMODEREG(0), .CARRYINREG(0), .CARRYINSELREG(0)
) u_dsp (
    .A(dsp_i_a), .B(dsp_i_b), .C(dsp_i_c), .D(dsp_i_d),
    .ACIN(dsp_i_acin), .BCIN(dsp_i_bcin), .PCIN(dsp_i_pcin),
    .ALUMODE(dsp_i_alumode), .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode),
    .CARRYIN(dsp_i_carryin), .CARRYINSEL(dsp_i_carryinsel),
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

//! 3. 输出生成
//! ---------------

assign X = a_extended ^ b_extended ^ {Y_WIDTH{BI}};
assign Y = dsp_o_p[Y_WIDTH-1:0];

// 相邻和位恢复内部进位，最高进位按有效宽度处理减法的借位极性。
generate
    if (Y_WIDTH > 1) begin : g_internal_carry
        assign CO[Y_WIDTH-2:0] = X[Y_WIDTH-1:1] ^ Y[Y_WIDTH-1:1];
    end
    if (Y_WIDTH < 48) begin : g_partial_width
        assign CO[Y_WIDTH-1] = dsp_o_p[Y_WIDTH] ^ BI;
    end else begin : g_full_width
        assign CO[Y_WIDTH-1] = dsp_o_carryout[3];
    end
endgenerate

endmodule
