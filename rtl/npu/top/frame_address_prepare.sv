// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保存一帧的三个地址表达式，依次复用一个乘加器，结果保持至接收。
module frame_address_prepare #(
    parameter int p_size = 16,
    parameter bit p_ready_mask_abort = 1'b1,
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
    input  wire logic rst_n,
    input  wire logic i_start,
    input  wire logic i_abort,
    output logic o_start_rdy,
    input  wire logic i_result_rdy,
    output logic o_result_vld,
    input  wire logic [31:0] i_p0,
    input  wire logic [31:0] i_q0,
    input  wire logic [31:0] i_column,
    input  wire logic [31:0] i_total_depth,
    input  wire logic [31:0] i_ia_base,
    input  wire logic [31:0] i_ia_stride,
    input  wire logic i_ia_packed,
    input  wire logic i_ia_s16,
    input  wire logic [31:0] i_weight_base,
    input  wire logic [31:0] i_weight_stride,
    input  wire logic i_weight_packed,
    input  wire logic i_weight_s16,
    input  wire logic [31:0] i_dst_base,
    input  wire logic [31:0] i_dst_stride,
    input  wire logic i_is_mode,
    input  wire logic i_output_s16,
    output logic [31:0] o_ia_base,
    output logic [31:0] o_weight_base,
    output logic [31:0] o_dst_base
);
    //! 0. 地址上下文与运算状态
    //! -----------------------

    localparam int p_size_shift = $clog2(p_size);
    typedef enum logic [1:0] {IDLE, PRODUCT, FINISH, RESULT} state_t;
    state_t c_st, n_st;
    logic [1:0] operation, phase;
    logic start_fire, multiply_en;
    logic [31:0] depth_rounded, depth_tiles;
    logic unused_depth_carry;
    logic [31:0] ia_factor, weight_factor;
    logic [31:0] packed_depth_offset, ia_packed_offset, weight_packed_offset;
    logic [31:0] factor_a [0:2];
    logic [31:0] factor_b [0:2];
    logic [31:0] base [0:2];
    logic [31:0] offset [0:2];
    logic [31:0] selected_a, selected_b, selected_base, selected_offset;
    logic [31:0] addend;
    logic unused_addend_carry;
    logic signed [17:0] multiply_a, multiply_b;
    logic [47:0] accumulated;
    logic [16:0] result_low;

    //! 1. 接收帧地址上下文
    //! -------------------

    assign start_fire = i_start && o_start_rdy && !i_abort;
    assign multiply_en = (c_st == PRODUCT) && !i_abort;

    // 分块计数保留三十二位回绕；两个偏移位段互不重叠，可直接组合。
    assign {unused_depth_carry, depth_rounded} = {1'b0, i_total_depth} + 33'(p_size-1);
    assign depth_tiles = depth_rounded >> p_size_shift;
    assign ia_factor = (i_p0 >> p_size_shift) << (2*p_size_shift + int'(i_ia_s16));
    assign weight_factor = (i_column >> p_size_shift) << (2*p_size_shift + int'(i_weight_s16));
    assign packed_depth_offset = (i_q0 >> p_size_shift) << (2*p_size_shift);
    assign ia_packed_offset = (packed_depth_offset | ((i_p0 & 32'(p_size-1)) << p_size_shift)) << i_ia_s16;
    assign weight_packed_offset = (packed_depth_offset | ((i_column & 32'(p_size-1)) << p_size_shift)) << i_weight_s16;

    // 输入接收后全部运算只访问这三个记录，随后变化的配置不影响当前结果。
    always_ff @(posedge clk) begin
        if (start_fire) begin
            factor_a[0] <= i_ia_packed ? ia_factor : i_p0;
            factor_b[0] <= i_ia_packed ? depth_tiles : i_ia_stride;
            base[0] <= i_ia_base;
            offset[0] <= i_ia_packed ? ia_packed_offset : (i_q0 << i_ia_s16);
            factor_a[1] <= i_weight_packed ? weight_factor : i_column;
            factor_b[1] <= i_weight_packed ? depth_tiles : i_weight_stride;
            base[1] <= i_weight_base;
            offset[1] <= i_weight_packed ? weight_packed_offset : (i_q0 << i_weight_s16);
            factor_a[2] <= i_is_mode ? i_column : i_p0;
            factor_b[2] <= i_dst_stride;
            base[2] <= i_dst_base;
            offset[2] <= (i_is_mode ? i_p0 : i_column) << i_output_s16;
        end
    end

    // 每个地址共用一次基址加法；乘法的高位乘高位项从第三十四位开始，无需进入地址低三十二位。
    always_comb begin
        selected_a = factor_a[0];
        selected_b = factor_b[0];
        selected_base = base[0];
        selected_offset = offset[0];
        case (operation)
            2'd1: begin
                selected_a = factor_a[1];
                selected_b = factor_b[1];
                selected_base = base[1];
                selected_offset = offset[1];
            end
            2'd2: begin
                selected_a = factor_a[2];
                selected_b = factor_b[2];
                selected_base = base[2];
                selected_offset = offset[2];
            end
        endcase
    end
    assign {unused_addend_carry, addend} = {1'b0, selected_base} + {1'b0, selected_offset};
    assign multiply_a = (phase == 2'd2) ? $signed({{3{selected_a[31]}}, selected_a[31:17]}) : $signed({1'b0, selected_a[16:0]});
    assign multiply_b = (phase == 2'd1) ? $signed({{3{selected_b[31]}}, selected_b[31:17]}) : $signed({1'b0, selected_b[16:0]});

    //! 2. 依次计算并保存地址
    //! ---------------------

    // 状态机：接收后执行九次乘加，第十个边沿保存最后结果，随后等待接收。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            c_st <= IDLE;
        end else if (i_abort) begin
            c_st <= IDLE;
        end else begin
            c_st <= n_st;
        end
    end
    always_comb begin
        n_st = c_st;
        case (c_st)
            IDLE: begin
                if (start_fire) begin
                    n_st = PRODUCT;
                end
            end
            PRODUCT: begin
                if ((operation == 2'd2) && (phase == 2'd2)) begin
                    n_st = FINISH;
                end
            end
            FINISH: begin
                n_st = RESULT;
            end
            RESULT: begin
                if (i_result_rdy) begin
                    n_st = IDLE;
                end
            end
        endcase
    end

    // 相位零计算低段并加入基址，相位一加入首个交叉项，相位二加入另一个交叉项。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            operation <= 2'd0;
            phase <= 2'd0;
        end else if (i_abort || start_fire) begin
            operation <= 2'd0;
            phase <= 2'd0;
        end else if (multiply_en) begin
            if (phase == 2'd2) begin
                phase <= 2'd0;
                if (operation != 2'd2) begin
                    operation <= operation + 2'd1;
                end
            end else begin
                phase <= phase + 2'd1;
            end
        end
    end

    generate
        if (p_use_dsp) begin : g_dsp
            logic [29:0] dsp_i_a, dsp_i_acin;
            logic [17:0] dsp_i_b, dsp_i_bcin;
            logic [47:0] dsp_i_c, dsp_i_pcin;
            logic [24:0] dsp_i_d;
            logic [6:0] dsp_i_opmode;
            logic [4:0] dsp_i_inmode;
            logic [3:0] dsp_i_alumode;
            logic [2:0] dsp_i_carry_select;
            logic dsp_i_zero, dsp_i_en;
            logic [47:0] dsp_o_p, unused_pcout;
            logic [29:0] unused_acout;
            logic [17:0] unused_bcout;
            logic [3:0] unused_carryout;
            logic unused_carrycascout, unused_multsignout;
            logic unused_overflow, unused_underflow;
            logic unused_patterndetect, unused_patternbdetect;

            assign dsp_i_a = {{12{multiply_a[17]}}, multiply_a};
            assign dsp_i_b = multiply_b;
            assign dsp_i_c = {16'd0, addend};
            assign dsp_i_acin = '0;
            assign dsp_i_bcin = '0;
            assign dsp_i_pcin = '0;
            assign dsp_i_d = '0;
            assign dsp_i_opmode = (phase == 2'd0) ? 7'b0110101 : ((phase == 2'd1) ? 7'b1100101 : 7'b0100101);
            assign dsp_i_inmode = '0;
            assign dsp_i_alumode = '0;
            assign dsp_i_carry_select = '0;
            assign dsp_i_zero = 1'b0;
            assign dsp_i_en = multiply_en;
            assign accumulated = dsp_o_p;

            // PREG 每周期保存乘加结果，反馈可直接取完整 P 或算术右移十七位的 P。
            DSP48E1 #(
                .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .ADREG(0),
                .CREG(0), .DREG(0), .MREG(0), .PREG(1), .CARRYINREG(0),
                .CARRYINSELREG(0), .INMODEREG(0), .OPMODEREG(0), .ALUMODEREG(0),
                .USE_DPORT("FALSE"), .USE_MULT("MULTIPLY"), .USE_SIMD("ONE48")
            ) u_dsp (
                .CLK(clk), .A(dsp_i_a), .ACIN(dsp_i_acin), .B(dsp_i_b), .BCIN(dsp_i_bcin),
                .C(dsp_i_c), .D(dsp_i_d), .PCIN(dsp_i_pcin),
                .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode), .ALUMODE(dsp_i_alumode),
                .CARRYIN(dsp_i_zero), .CARRYINSEL(dsp_i_carry_select),
                .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero),
                .CEA1(dsp_i_zero), .CEA2(dsp_i_zero), .CEAD(dsp_i_zero),
                .CEB1(dsp_i_zero), .CEB2(dsp_i_zero), .CEC(dsp_i_zero),
                .CECARRYIN(dsp_i_zero), .CED(dsp_i_zero), .CEM(dsp_i_zero), .CEP(dsp_i_en),
                .CECTRL(dsp_i_zero), .CEINMODE(dsp_i_zero), .CEALUMODE(dsp_i_zero),
                .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
                .RSTM(dsp_i_zero), .RSTP(dsp_i_zero), .RSTALLCARRYIN(dsp_i_zero),
                .RSTCTRL(dsp_i_zero), .RSTINMODE(dsp_i_zero), .RSTALUMODE(dsp_i_zero),
                .P(dsp_o_p), .ACOUT(unused_acout), .BCOUT(unused_bcout),
                .PCOUT(unused_pcout), .CARRYOUT(unused_carryout),
                .CARRYCASCOUT(unused_carrycascout), .MULTSIGNOUT(unused_multsignout),
                .OVERFLOW(unused_overflow), .UNDERFLOW(unused_underflow),
                .PATTERNDETECT(unused_patterndetect), .PATTERNBDETECT(unused_patternbdetect)
            );
        end else begin : g_generic
            logic signed [35:0] partial_product;
            logic signed [47:0] feedback;
            assign partial_product = multiply_a * multiply_b;
            assign feedback = (phase == 2'd0) ? $signed({16'd0, addend}) :
                ((phase == 2'd1) ? ($signed(accumulated) >>> 17) : $signed(accumulated));
            always_ff @(posedge clk) begin
                if (multiply_en) begin
                    accumulated <= 48'(partial_product) + feedback;
                end
            end
        end
    endgenerate

    // 低十七位在第二次乘加前保存；下一地址开始时收集上一地址的完整三十二位。
    always_ff @(posedge clk) begin
        if (!i_abort) begin
            if (multiply_en && (phase == 2'd1)) begin
                result_low <= accumulated[16:0];
            end
            if ((c_st == PRODUCT) && (phase == 2'd0)) begin
                if (operation == 2'd1) begin
                    o_ia_base <= {accumulated[14:0], result_low};
                end
                if (operation == 2'd2) begin
                    o_weight_base <= {accumulated[14:0], result_low};
                end
            end
            if (c_st == FINISH) begin
                o_dst_base <= {accumulated[14:0], result_low};
            end
        end
    end

    //! 3. 输出结果与接收状态
    //! ---------------------

    // 上层已检查中止条件时可直接读取空闲状态，内部接收始终检查中止信号。
    assign o_start_rdy = (c_st == IDLE) && (!p_ready_mask_abort || !i_abort);
    assign o_result_vld = (c_st == RESULT) && !i_abort;
endmodule

`default_nettype wire
