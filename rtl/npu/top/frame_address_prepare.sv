// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保存一帧的三个地址表达式，依次复用一个乘加器，结果保持至接收。
module frame_address_prepare #(
    parameter int p_size = 16,
    parameter bit p_ready_mask_abort = 1'b1,
    parameter bit p_pipeline_products = 1'b1
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
    logic [31:0] depth_round_i_size;
    logic depth_round_i_carry;
    logic [31:0] ia_factor, weight_factor;
    logic [31:0] packed_depth_offset, ia_packed_offset, weight_packed_offset;
    logic [31:0] factor_a [0:2];
    logic [31:0] factor_b [0:2];
    logic [31:0] base [0:2];
    logic [31:0] offset [0:2];
    logic [31:0] selected_a, selected_b, selected_base, selected_offset;
    logic [31:0] addend;
    logic unused_addend_carry;
    logic addend_i_carry;
    logic [16:0] multiply_a, multiply_b;
    logic [31:0] accumulated;
    logic product_valid_q, execute_en, finish_capture;
    logic [1:0] execute_operation, execute_phase;
    logic [31:0] execute_product, execute_addend;
    logic [33:0] partial_product;
    logic [16:0] result_low;

    //! 1. 接收帧地址上下文
    //! -------------------

    assign start_fire = i_start && o_start_rdy && !i_abort;
    assign multiply_en = (c_st == PRODUCT) && !i_abort;

    // 分块计数保留三十二位回绕；两个偏移位段互不重叠，可直接组合。
    assign depth_round_i_size = 32'(p_size-1);
    assign depth_round_i_carry = 1'b0;
    parallel_prefix_add #(.p_width(32)) u_depth_round (
        .i_a(i_total_depth), .i_b(depth_round_i_size), .i_carry(depth_round_i_carry),
        .o_sum(depth_rounded), .o_carry(unused_depth_carry)
    );
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
            default: begin end
        endcase
    end
    // 基址与偏移先相加，在部分积累加阶段加入地址结果。
    assign addend_i_carry = 1'b0;
    parallel_prefix_add #(.p_width(32)) u_addend (
        .i_a(selected_base), .i_b(selected_offset), .i_carry(addend_i_carry),
        .o_sum(addend), .o_carry(unused_addend_carry)
    );
    // 地址按模 2^32 计算，交叉项只贡献低十五位，乘数统一使用十七位无符号数。
    assign multiply_a = (phase == 2'd2) ? {2'b00, selected_a[31:17]} : selected_a[16:0];
    assign multiply_b = (phase == 2'd1) ? {2'b00, selected_b[31:17]} : selected_b[16:0];
    assign partial_product = multiply_a * multiply_b;
    assign finish_capture = (c_st == FINISH) && !product_valid_q;

    // 乘积可单独寄存，操作号、相位及基址加数随数据经过同一边沿。
    if (p_pipeline_products) begin : g_product_stage
        logic [31:0] product_q, addend_q;
        logic [1:0] operation_q, phase_q;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) product_valid_q <= 1'b0;
            else if (i_abort) product_valid_q <= 1'b0;
            else product_valid_q <= multiply_en;
        end
        always_ff @(posedge clk) begin
            if (multiply_en) begin
                product_q <= partial_product[31:0];
                operation_q <= operation;
                phase_q <= phase;
                if (phase == 2'd0) addend_q <= addend;
            end
        end
        assign execute_en = product_valid_q && !i_abort;
        assign execute_operation = operation_q;
        assign execute_phase = phase_q;
        assign execute_product = product_q;
        assign execute_addend = addend_q;
    end else begin : g_direct_product
        assign product_valid_q = 1'b0;
        assign execute_en = multiply_en;
        assign execute_operation = operation;
        assign execute_phase = phase;
        assign execute_product = partial_product[31:0];
        assign execute_addend = addend;
    end

    //! 2. 依次计算并保存地址
    //! ---------------------

    // 九个部分积连续发射；有效流水排空后保存最后地址，再等待结果接收。
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
                if (finish_capture) n_st = RESULT;
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

    // 累加器只保存地址有效位；低段结果单独保留，交叉项使用逻辑右移后的高十五位。
    logic [31:0] feedback;
    logic [31:0] accumulated_next;
    assign feedback = (execute_phase == 2'd0) ? execute_addend :
        ((execute_phase == 2'd1) ? {17'd0, accumulated[31:17]} : accumulated);
    assign accumulated_next = execute_product + feedback;
    always_ff @(posedge clk) begin
        if (execute_en) accumulated <= accumulated_next;
    end

    // 低十七位在第二次乘加前保存；下一地址开始时收集上一地址的完整三十二位。
    always_ff @(posedge clk) begin
        if (!i_abort) begin
            if (execute_en && (execute_phase == 2'd1)) begin
                result_low <= accumulated[16:0];
            end
            if (execute_en && (execute_phase == 2'd0)) begin
                if (execute_operation == 2'd1) begin
                    o_ia_base <= {accumulated[14:0], result_low};
                end
                if (execute_operation == 2'd2) begin
                    o_weight_base <= {accumulated[14:0], result_low};
                end
            end
            if (finish_capture) begin
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
