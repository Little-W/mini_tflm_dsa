// SPDX-License-Identifier: Apache-2.0
// 选择一个有符号操作数，并按使能执行定宽模加；输出在当前周期组合产生。
`default_nettype none
module select_add #(
    parameter int p_width = 32,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0,
`elsif XILINX_FPGA
    parameter bit p_use_dsp = 1'b1,
`elsif SYNTHESIS
    parameter bit p_use_dsp = 1'b1,
`else
    parameter bit p_use_dsp = 1'b0,
`endif
    // 48 位端口可分为四个独立的 12 位模加通道。
    parameter bit p_split_12bit = 1'b0
) (
    input  wire logic signed [p_width-1:0] i_lhs,
    input  wire logic signed [p_width-1:0] i_rhs0,
    input  wire logic signed [p_width-1:0] i_rhs1,
    input  wire logic                      i_rhs_select,
    input  wire logic                      i_add_enable,
    output logic signed [p_width-1:0] o_sum
);
    //! 0. 辅助定义
    //! -----------

    localparam p_simd_mode =
        ((p_width == 48) && p_split_12bit) ? "FOUR12" : "ONE48";
    logic signed [p_width-1:0] selected_rhs;

    //! 1. 选择输入并生成组合结果
    //! -------------------------

    if (p_use_dsp && p_width <= 48) begin : g_fpga
        logic [47:0] extended_lhs;
        logic [29:0] dsp_i_a;
        logic [17:0] dsp_i_b;
        logic [29:0] dsp_i_acin;
        logic [17:0] dsp_i_bcin;
        logic [47:0] dsp_i_c;
        logic [24:0] dsp_i_d;
        logic [47:0] dsp_i_pcin;
        logic [6:0] dsp_i_opmode;
        logic [4:0] dsp_i_inmode;
        logic [3:0] dsp_i_alumode;
        logic [2:0] dsp_i_carry_select;
        logic dsp_i_zero;
        logic [47:0] dsp_o_sum;
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

        // 操作数选择在组合加法之前完成，各数据位并行选择。
        assign selected_rhs = i_rhs_select ? i_rhs1 : i_rhs0;

        assign extended_lhs = {{(48-p_width){i_lhs[p_width-1]}}, i_lhs};
        assign dsp_i_a = extended_lhs[47:18];
        assign dsp_i_b = extended_lhs[17:0];
        assign dsp_i_acin = '0;
        assign dsp_i_bcin = '0;
        assign dsp_i_c = {{(48-p_width){selected_rhs[p_width-1]}}, selected_rhs};
        assign dsp_i_d = '0;
        assign dsp_i_pcin = '0;
        assign dsp_i_opmode = {3'b000, i_add_enable, i_add_enable, 2'b11};
        assign dsp_i_inmode = '0;
        assign dsp_i_alumode = '0;
        assign dsp_i_carry_select = '0;
        assign dsp_i_zero = 1'b0;
        assign o_sum = dsp_o_sum[p_width-1:0];

        // A:B 始终提供左操作数，Y 在零与 C 之间选择。全部内部寄存器旁路，
        // 保留输入到输出的组合时序，各通道按对应位宽保留模加结果。
        DSP48E1 #(
            .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .ADREG(0),
            .CREG(0), .DREG(0), .MREG(0), .PREG(0), .CARRYINREG(0),
            .CARRYINSELREG(0), .INMODEREG(0), .OPMODEREG(0), .ALUMODEREG(0),
            .A_INPUT("DIRECT"), .B_INPUT("DIRECT"),
            .USE_DPORT("FALSE"), .USE_MULT("NONE"), .USE_SIMD(p_simd_mode)
        ) u_dsp (
            // 直接输入模式使用 A、B 端口，专用级联输入固定为零。
            .CLK(dsp_i_zero), .A(dsp_i_a), .ACIN(dsp_i_acin), .B(dsp_i_b), .BCIN(dsp_i_bcin),
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
            .P(dsp_o_sum), .ACOUT(unused_acout), .BCOUT(unused_bcout),
            .PCOUT(unused_pcout), .CARRYOUT(unused_carryout),
            .CARRYCASCOUT(unused_carrycascout), .MULTSIGNOUT(unused_multsignout),
            .OVERFLOW(unused_overflow), .UNDERFLOW(unused_underflow),
            .PATTERNDETECT(unused_patterndetect), .PATTERNBDETECT(unused_patternbdetect)
        );
    end else begin : g_generic
        assign selected_rhs = i_rhs_select ? i_rhs1 : i_rhs0;
        if ((p_width == 48) && p_split_12bit) begin : g_parallel
            for (genvar lane = 0; lane < 4; lane++) begin : g_lane
                assign o_sum[lane*12 +: 12] = i_add_enable ?
                    i_lhs[lane*12 +: 12] + selected_rhs[lane*12 +: 12] :
                    i_lhs[lane*12 +: 12];
            end
        end else begin : g_single
            assign o_sum = i_add_enable ? i_lhs + selected_rhs : i_lhs;
        end
    end
endmodule
`default_nettype wire
