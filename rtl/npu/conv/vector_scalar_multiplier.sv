// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module vector_scalar_multiplier #(
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
    input  wire logic clk,
    input  wire logic signed [31:0] a,
    input  wire logic signed [31:0] b,
    output logic signed [63:0] product
);
    logic multiplier_i_en;
    logic signed [31:0] multiplier_i_a, multiplier_i_b;
    logic signed [63:0] multiplier_o_product;

    assign multiplier_i_en = 1'b1;
    assign multiplier_i_a = a;
    assign multiplier_i_b = b;
    assign product = multiplier_o_product;

    registered_multiplier_s32 #(.p_use_dsp(p_use_dsp)) u_multiplier (
        .clk(clk),
        .i_en(multiplier_i_en),
        .i_a(multiplier_i_a),
        .i_b(multiplier_i_b),
        .o_product(multiplier_o_product)
    );
endmodule

// 有符号乘法器可在输入边界增加寄存一级，暂停时保持所有输入、部分积和输出。
module registered_multiplier_s32 #(
    parameter bit p_input_register = 1'b0,
    parameter bit p_b_input_register = p_input_register,
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
    input  wire logic clk,
    input  wire logic i_en,
    input  wire logic signed [31:0] i_a,
    input  wire logic signed [31:0] i_b,
    output logic signed [63:0] o_product
);
    //! 0. 部分积与组合中间结果
    //! -----------------------

    logic signed [31:0] operand_a, operand_b;

    //! 1. 两级有符号乘法流水
    //! ---------------------

    generate
        if (p_use_dsp || !p_input_register) begin : g_direct_a
            assign operand_a = i_a;
        end else begin : g_registered_a
            // 通用实现与 DSP AREG 在同一个使能边沿接收左操作数。
            always_ff @(posedge clk) begin
                if (i_en) begin
                    operand_a <= i_a;
                end
            end
        end
        if (p_use_dsp || !p_b_input_register) begin : g_direct_b
            assign operand_b = i_b;
        end else begin : g_registered_b
            // 右操作数可由上游同步存储器提供；寄存选择与左操作数独立。
            always_ff @(posedge clk) begin
                if (i_en) begin
                    operand_b <= i_b;
                end
            end
        end
        if (p_use_dsp) begin : g_dsp
            logic [29:0] multiply_i_a [0:3];
            logic [17:0] multiply_i_b [0:3];
            logic multiply_i_en;
            logic [47:0] multiply_i_zero;
            logic [47:0] multiply_i_pcin [0:3];
            logic [47:0] multiply_o_p [0:3];
            logic [47:0] multiply_o_pcout [0:3];
            logic [16:0] low_result_q;
            logic [16:0] middle_result_q;

            // 低段保存十七位无符号数，高段保存十五位有符号数。
            assign multiply_i_a[0] = {13'd0, operand_a[16:0]};
            assign multiply_i_b[0] = {1'b0, operand_b[16:0]};
            assign multiply_i_a[1] = {13'd0, operand_a[16:0]};
            assign multiply_i_b[1] = {{3{operand_b[31]}}, operand_b[31:17]};
            assign multiply_i_a[2] = {{15{operand_a[31]}}, operand_a[31:17]};
            assign multiply_i_b[2] = {1'b0, operand_b[16:0]};
            assign multiply_i_a[3] = {{15{operand_a[31]}}, operand_a[31:17]};
            assign multiply_i_b[3] = {{3{operand_b[31]}}, operand_b[31:17]};
            assign multiply_i_en = i_en;
            assign multiply_i_zero = '0;
            assign multiply_i_pcin[0] = '0;
            for (genvar partial_index = 1; partial_index < 4; partial_index++) begin : g_cascade
                assign multiply_i_pcin[partial_index] = multiply_o_pcout[partial_index-1];
            end

            // 首个 DSP 用 PREG、其余 DSP 用 MREG 保存部分积，末级 PREG 保存高三十位。
            for (genvar partial_index = 0; partial_index < 4; partial_index++) begin : g_partial
                localparam int p_cascade = (partial_index == 0) ? 0 : ((partial_index == 2) ? 1 : 2);
                registered_multiplier_dsp #(
                    .p_multiply(1'b1), .p_input_register(p_input_register),
                    .p_b_input_register(p_b_input_register), .p_m_register(partial_index != 0),
                    .p_output_register((partial_index == 0) || (partial_index == 3)), .p_cascade_mode(p_cascade)
                ) u_multiply (
                    .clk(clk), .i_en(multiply_i_en),
                    .i_a(multiply_i_a[partial_index]), .i_b(multiply_i_b[partial_index]),
                    .i_c(multiply_i_zero), .i_pcin(multiply_i_pcin[partial_index]),
                    .o_p(multiply_o_p[partial_index]), .o_pcout(multiply_o_pcout[partial_index])
                );
            end
            // 低段和中段在相同使能边沿保存，与末级 PREG 的高段同时输出。
            for (genvar result_bit = 0; result_bit < 17; result_bit++) begin : g_result
                logic register_i_low, register_i_middle, register_i_zero;
                logic register_o_low, register_o_middle;
                assign register_i_low = multiply_o_p[0][result_bit];
                assign register_i_middle = multiply_o_p[2][result_bit];
                assign register_i_zero = 1'b0;
                assign low_result_q[result_bit] = register_o_low;
                assign middle_result_q[result_bit] = register_o_middle;
                FDRE #(.INIT(1'bx)) u_low (
                    .C(clk), .CE(i_en), .D(register_i_low), .R(register_i_zero), .Q(register_o_low)
                );
                FDRE #(.INIT(1'bx)) u_middle (
                    .C(clk), .CE(i_en), .D(register_i_middle), .R(register_i_zero), .Q(register_o_middle)
                );
            end
            assign o_product = $signed({multiply_o_p[3][29:0], middle_result_q, low_result_q});
        end else begin : g_generic
            (* keep, use_dsp = "yes" *) logic [31:0] low_product;
            (* keep, use_dsp = "yes" *) logic signed [32:0] low_high_product;
            (* keep, use_dsp = "yes" *) logic signed [32:0] high_low_product;
            (* keep, use_dsp = "yes" *) logic signed [31:0] high_product;
            logic [47:0] diagonal;
            logic [47:0] low_high_extended, high_low_extended;
            logic [47:0] compressed_sum, compressed_carry;
            (* use_dsp = "no" *) logic [47:0] upper_sum;

            assign diagonal = {high_product, low_product[31:16]};

            // 第一个使能边沿保存四个部分积，低半字无符号，高半字保留 INT32 符号。
            always_ff @(posedge clk) begin
                if (i_en) begin
                    low_product      <= operand_a[15:0] * operand_b[15:0];
                    low_high_product <= $signed({1'b0, operand_a[15:0]}) * $signed(operand_b[31:16]);
                    high_low_product <= $signed(operand_a[31:16]) * $signed({1'b0, operand_b[15:0]});
                    high_product     <= $signed(operand_a[31:16]) * $signed(operand_b[31:16]);
                end
            end

            // 对角项占用互不重叠的位段，三个高位操作数先形成保留进位的求和。
            assign low_high_extended = {{15{low_high_product[32]}}, low_high_product};
            assign high_low_extended = {{15{high_low_product[32]}}, high_low_product};
            assign compressed_sum    = diagonal ^ low_high_extended ^ high_low_extended;
            assign compressed_carry  = ((diagonal & low_high_extended) |
                                       (diagonal & high_low_extended) |
                                       (low_high_extended & high_low_extended)) << 1;
            assign upper_sum         = compressed_sum + compressed_carry;

            // 两个使能边沿后形成完整乘积；暂停时两个寄存阶段同时保持。
            always_ff @(posedge clk) begin
                if (i_en) begin
                    o_product <= {upper_sum, low_product[15:0]};
                end
            end
        end
    endgenerate
endmodule

module registered_multiplier_dsp #(
    parameter bit p_multiply = 1'b0,
    parameter bit p_input_register = 1'b0,
    parameter bit p_b_input_register = p_input_register,
    parameter bit p_m_register = 1'b0,
    parameter bit p_output_register = 1'b1,
    parameter int p_cascade_mode = 0
) (
    input  wire logic clk,
    input  wire logic i_en,
    input  wire logic [29:0] i_a,
    input  wire logic [17:0] i_b,
    input  wire logic [47:0] i_c,
    input  wire logic [47:0] i_pcin,
    output logic [47:0] o_p,
    output logic [47:0] o_pcout
);
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
    logic dsp_i_input_en;
    logic dsp_i_b_input_en;
    logic [47:0] dsp_o_p;
    logic [47:0] dsp_o_pcout;
    logic [29:0] unused_acout;
    logic [17:0] unused_bcout;
    logic [3:0] unused_carryout;
    logic unused_carrycascout;
    logic unused_multsignout;
    logic unused_overflow;
    logic unused_underflow;
    logic unused_patterndetect;
    logic unused_patternbdetect;

    assign dsp_i_a = i_a;
    assign dsp_i_acin = '0;
    assign dsp_i_b = i_b;
    assign dsp_i_bcin = '0;
    assign dsp_i_c = i_c;
    assign dsp_i_d = '0;
    assign dsp_i_pcin = i_pcin;
    assign dsp_i_opmode = !p_multiply ? 7'b0011111 :
        (p_cascade_mode == 0) ? 7'b0000101 :
        (p_cascade_mode == 1) ? 7'b0010101 : 7'b1010101;
    assign dsp_i_inmode = '0;
    assign dsp_i_alumode = '0;
    assign dsp_i_carry_select = '0;
    assign dsp_i_zero = 1'b0;
    assign dsp_i_en = i_en;
    assign dsp_i_input_en = p_input_register ? i_en : 1'b0;
    assign dsp_i_b_input_en = p_b_input_register ? i_en : 1'b0;
    assign o_p = dsp_o_p;
    assign o_pcout = dsp_o_pcout;

    // MREG 和 PREG 分别选择乘积及算术结果寄存，输入寄存独立选择，各级共用流水使能。
    DSP48E1 #(
        .AREG(p_input_register ? 1 : 0), .ACASCREG(p_input_register ? 1 : 0),
        .BREG(p_b_input_register ? 1 : 0), .BCASCREG(p_b_input_register ? 1 : 0), .ADREG(0),
        .CREG(0), .DREG(0), .MREG(p_m_register ? 1 : 0), .PREG(p_output_register ? 1 : 0), .CARRYINREG(0),
        .CARRYINSELREG(0), .INMODEREG(0), .OPMODEREG(0), .ALUMODEREG(0),
        .USE_DPORT("FALSE"), .USE_MULT(p_multiply ? "MULTIPLY" : "NONE"), .USE_SIMD("ONE48")
    ) u_dsp (
        .CLK(clk), .A(dsp_i_a), .ACIN(dsp_i_acin), .B(dsp_i_b), .BCIN(dsp_i_bcin),
        .C(dsp_i_c), .D(dsp_i_d), .PCIN(dsp_i_pcin),
        .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode), .ALUMODE(dsp_i_alumode),
        .CARRYIN(dsp_i_zero), .CARRYINSEL(dsp_i_carry_select),
        .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero),
        .CEA1(dsp_i_zero), .CEA2(dsp_i_input_en), .CEAD(dsp_i_zero),
        .CEB1(dsp_i_zero), .CEB2(dsp_i_b_input_en), .CEC(dsp_i_zero),
        .CECARRYIN(dsp_i_zero), .CED(dsp_i_zero), .CEM(dsp_i_en), .CEP(dsp_i_en),
        .CECTRL(dsp_i_zero), .CEINMODE(dsp_i_zero), .CEALUMODE(dsp_i_zero),
        .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
        .RSTM(dsp_i_zero), .RSTP(dsp_i_zero), .RSTALLCARRYIN(dsp_i_zero),
        .RSTCTRL(dsp_i_zero), .RSTINMODE(dsp_i_zero), .RSTALUMODE(dsp_i_zero),
        .P(dsp_o_p), .ACOUT(unused_acout), .BCOUT(unused_bcout),
        .PCOUT(dsp_o_pcout), .CARRYOUT(unused_carryout),
        .CARRYCASCOUT(unused_carrycascout), .MULTSIGNOUT(unused_multsignout),
        .OVERFLOW(unused_overflow), .UNDERFLOW(unused_underflow),
        .PATTERNDETECT(unused_patterndetect), .PATTERNBDETECT(unused_patternbdetect)
    );
endmodule
`default_nettype wire
