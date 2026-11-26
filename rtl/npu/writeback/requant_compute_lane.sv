// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// INT8 与 INT16 共用乘积、舍入和裁剪，七个使能边沿后输出。
module requant_compute_lane #(
    // 同步参数存储在数据接收后的下一个边沿提供乘数和移位量。
    parameter bit p_delayed_parameters = 1'b0
) (
    input  wire logic clk /* 工作时钟 */,
    input  wire logic rst_n /* 低有效复位 */,
    input  wire logic i_en /* 推进本通道的量化流水寄存器 */,
    input  wire logic i_clear /* 清除当前量化流水的有效状态 */,
    input  wire logic i_valid /* 当前待量化累加结果有效 */,
    input  wire logic i_lane_enable /* 当前通道参与本次量化运算 */,
    input  wire logic signed [31:0] i_value /* 待重新量化的有符号32 位累加值 */,
    input  wire logic signed [31:0] i_multiplier /* 本次量化使用的有符号乘数 */,
    input  wire logic [6:0] i_amount /* 乘积的总算术右移位数 */,
    input  wire logic i_s16 /* 当前结果选择16 位输出格式 */,
    input  wire logic signed [31:0] i_dst_offset /* 舍入后加入的输出零点偏移 */,
    input  wire logic signed [31:0] i_activation_min /* 当前输出激活的最小允许值 */,
    input  wire logic signed [31:0] i_activation_max /* 当前输出激活的最大允许值 */,
    output logic o_valid /* 当前量化流水输出有效 */,
    output logic signed [7:0] o_s8 /* 裁剪后的8 位有符号量化结果 */,
    output logic signed [15:0] o_s16 /* 裁剪后的16 位有符号量化结果 */
);
    //! 0. 算术与流水信号
    //! ------------------

    localparam int p_stages = requant_pkg::REQUANT_LATENCY;
    localparam int p_amount_stages = p_delayed_parameters ? 2 : 3;
    logic arithmetic_en;
    logic [p_stages-1:0] valid_q;
    logic [p_stages-2:0] lane_enable_q;
    logic [6:0] amount_q [p_amount_stages];
    logic product_i_en;
    logic signed [31:0] product_i_a, product_i_b;
    logic signed [63:0] product_o_product;
    logic shift_i_en;
    logic signed [63:0] shift_i_product;
    logic [6:0] shift_i_amount;
    logic signed [33:0] shift_o_quotient;
    logic shift_o_increment;
    logic unused_round_carry;
    logic signed [34:0] rounded_q, round_value, offset_value;
    logic [1:0] bound_less;

    //! 1. 接收数据与参数
    //! ------------------

    assign arithmetic_en = rst_n && i_en && !i_clear;
    assign o_valid = valid_q[p_stages-1];
    assign product_i_en = arithmetic_en;
    assign product_i_a = i_value;
    assign product_i_b = i_multiplier;
    assign shift_i_en = arithmetic_en;
    assign shift_i_product = product_o_product;
    assign shift_i_amount = amount_q[p_amount_stages-1];
    registered_multiplier_s32 #(
        .p_input_register(1'b1), .p_b_input_register(!p_delayed_parameters)
    ) u_product (
        .clk(clk), .i_en(product_i_en), .i_a(product_i_a), .i_b(product_i_b), .o_product(product_o_product)
    );
    always_ff @(posedge clk) begin
        if (arithmetic_en) begin
            amount_q[0] <= i_amount;
            for (int stage = 1; stage < p_amount_stages; stage++) amount_q[stage] <= amount_q[stage-1];
        end
    end
    requant_shift_pipeline u_shift (
        .clk(clk), .i_en(shift_i_en), .i_product(shift_i_product),
        .i_amount(shift_i_amount), .o_quotient(shift_o_quotient), .o_increment(shift_o_increment)
    );

    //! 2. 舍入并保存偏移结果
    //! ----------------------

    // 34 位商、32 位偏移和舍入增量的完整和使用 35 位有符号数保存。
    // INT16 的输出零点为零；任务配置保持稳定，同一个加法加入偏移与舍入增量。
    assign offset_value = i_s16 ? 35'sd0 : {{3{i_dst_offset[31]}}, i_dst_offset};
`ifdef SYNTHESIS
    requant_round_add u_round_offset (
        .i_a({shift_o_quotient[33], shift_o_quotient}), .i_b(offset_value),
        .i_increment(shift_o_increment), .o_sum(round_value)
    );
    assign unused_round_carry = 1'b0;
`else
    assign {unused_round_carry, round_value} = {1'b0, shift_o_quotient[33], shift_o_quotient} +
        {1'b0, offset_value} + 36'(shift_o_increment);
`endif
    always_ff @(posedge clk) begin
        if (arithmetic_en) rounded_q <= round_value;
    end

    //! 3. 裁剪输出并传递有效位
    //! ------------------------

    // 已知输入按符号翻转后的无符号次序比较；未知输入按字节关系传播。
    for (genvar bound = 0; bound < 2; bound++) begin : g_bound
        logic [34:0] lhs, rhs;
        logic [4:0] equal_group, greater_group, greater_selected;
        if (bound == 0) begin : g_minimum
            assign lhs = rounded_q;
            assign rhs = {{3{i_activation_min[31]}}, i_activation_min};
        end else begin : g_maximum
            assign lhs = {{3{i_activation_max[31]}}, i_activation_max};
            assign rhs = rounded_q;
        end
        for (genvar group = 0; group < 5; group++) begin : g_group
            localparam int p_bits = group == 4 ? 3 : 8;
            assign equal_group[group] = lhs[8*group +: p_bits] == rhs[8*group +: p_bits];
            if (group == 4) begin : g_sign
                assign greater_group[group] = $signed(lhs[34:32]) > $signed(rhs[34:32]);
                assign greater_selected[group] = greater_group[group];
            end else begin : g_unsigned
                assign greater_group[group] = lhs[8*group +: 8] > rhs[8*group +: 8];
                assign greater_selected[group] = greater_group[group] && (&equal_group[4:group+1]);
            end
        end
        logic reference_less, inferred_less, unused_equal;
        assign reference_less = !((|greater_selected) || (&equal_group));
        // 翻转最高符号位后保持完整三十五位次序，FPGA 可推断两段减法。
        unsigned_compare #(.p_width(35)) u_signed_compare (
            .i_a({~lhs[34], lhs[33:0]}), .i_b({~rhs[34], rhs[33:0]}),
            .o_less(inferred_less), .o_equal(unused_equal)
        );
        always_comb begin
            case (^{lhs, rhs})
                1'b0, 1'b1: bound_less[bound] = inferred_less;
                default: bound_less[bound] = reference_less;
            endcase
        end
    end

    // 有效位与尾列掩码随算术共同暂停，初始化清空整条流水。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_q <= '0;
            lane_enable_q <= '0;
            o_s8 <= '0;
            o_s16 <= '0;
        end else if (i_clear) begin
            valid_q <= '0;
            lane_enable_q <= '0;
            o_s8 <= '0;
            o_s16 <= '0;
        end else if (i_en) begin
            valid_q <= {valid_q[p_stages-2:0], i_valid};
            lane_enable_q <= {lane_enable_q[p_stages-3:0], i_valid && i_lane_enable};
            if (!lane_enable_q[p_stages-2]) begin
                o_s8 <= '0;
                o_s16 <= '0;
            end else begin
                if (bound_less[0]) o_s16 <= i_activation_min[15:0];
                else if (bound_less[1]) o_s16 <= i_activation_max[15:0];
                else if (rounded_q < -35'sd32768) o_s16 <= -16'sd32768;
                else if (rounded_q > 35'sd32767) o_s16 <= 16'sd32767;
                else o_s16 <= rounded_q[15:0];
                if (bound_less[0]) o_s8 <= i_activation_min[7:0];
                else if (bound_less[1]) o_s8 <= i_activation_max[7:0];
                else if (rounded_q > 35'sd127) o_s8 <= 8'sd127;
                else if (rounded_q < -35'sd128) o_s8 <= -8'sd128;
                else o_s8 <= rounded_q[7:0];
            end
        end
    end
endmodule

`default_nettype wire
