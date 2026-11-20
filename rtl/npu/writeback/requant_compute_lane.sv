`default_nettype none

// 量化算术通道：数据和预处理参数同时采样，十二个使能边沿后输出。
module requant_compute_lane (
    input  wire logic               clk,
    input  wire logic               rst_n,
    input  wire logic               i_en,
    input  wire logic               i_clear,
    input  wire logic               i_valid,
    input  wire logic               i_lane_enable,
    input  wire logic signed [31:0] i_value,
    input  wire logic signed [31:0] i_multiplier,
    input  wire logic        [6:0]  i_amount,
    input  wire logic               i_s16,
    input  wire logic signed [31:0] i_dst_offset,
    input  wire logic signed [31:0] i_activation_min,
    input  wire logic signed [31:0] i_activation_max,
    output logic               o_valid,
    output logic signed [7:0]  o_s8,
    output logic signed [15:0] o_s16
);
    localparam int p_stages = 12;

    logic arithmetic_en;
    logic [p_stages-1:0] valid_q;
    logic [p_stages-2:0] lane_enable_q;
    logic [6:0] amount_q [0:2];
    logic signed [31:0] product_i_a, product_i_b;
    logic signed [63:0] product_o_value;
    logic signed [63:0] shift_i_product;
    logic [6:0] shift_i_amount;
    logic signed [33:0] shift_o_quotient;
    logic shift_o_increment;
    logic signed [35:0] sum_i_lhs, sum_i_rhs;
    logic sum_i_carry;
    logic signed [35:0] sum_o_value;
    logic signed [35:0] compare_i_value;
    logic signed [31:0] compare_i_minimum, compare_i_maximum;
    logic compare_o_below, compare_o_above;

    assign arithmetic_en = rst_n && i_en && !i_clear;
    assign product_i_a = i_value;
    assign product_i_b = i_multiplier;
    assign shift_i_product = product_o_value;
    assign shift_i_amount = amount_q[2];
    assign sum_i_lhs = {{2{shift_o_quotient[33]}}, shift_o_quotient};
    assign sum_i_rhs = i_s16 ? 36'sd0 : {{4{i_dst_offset[31]}}, i_dst_offset};
    assign sum_i_carry = shift_o_increment;
    assign compare_i_value = sum_o_value;
    assign compare_i_minimum = i_activation_min;
    assign compare_i_maximum = i_activation_max;
    assign o_valid = valid_q[p_stages-1];

    // 左右操作数使用相同的输入寄存阶段，随后保存部分积与完整乘积。
    registered_multiplier_s32 #(
        .p_input_register(1'b1),
        .p_b_input_register(1'b1)
    ) u_product (
        .clk(clk),
        .i_en(arithmetic_en),
        .i_a(product_i_a),
        .i_b(product_i_b),
        .o_product(product_o_value)
    );

    // 七级移位保存溢出方向和最近偶数舍入信息。
    requant_shift_pipeline u_shift (
        .clk(clk),
        .i_en(arithmetic_en),
        .i_product(shift_i_product),
        .i_amount(shift_i_amount),
        .o_quotient(shift_o_quotient),
        .o_increment(shift_o_increment)
    );

    // 偏移与舍入增量在同一个 DSP 输出寄存阶段完成。
    requant_registered_sum #(.p_width(36)) u_sum (
        .clk(clk),
        .i_en(arithmetic_en),
        .i_lhs(sum_i_lhs),
        .i_rhs(sum_i_rhs),
        .i_carry(sum_i_carry),
        .o_sum(sum_o_value)
    );

    requant_activation_compare u_compare (
        .i_value(compare_i_value),
        .i_minimum(compare_i_minimum),
        .i_maximum(compare_i_maximum),
        .o_below_minimum(compare_o_below),
        .o_above_maximum(compare_o_above)
    );

    // 移位量与乘积经过相同的三个使能边沿；无效阶段的数据不参与输出。
    always_ff @(posedge clk) begin
        if (arithmetic_en) begin
            amount_q[0] <= i_amount;
            amount_q[1] <= amount_q[0];
            amount_q[2] <= amount_q[1];
        end
    end

    // 有效位、尾列屏蔽与数值结果共同暂停，清空优先于时钟使能。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_q <= '0;
            lane_enable_q <= '0;
            o_s8 <= 8'sd0;
            o_s16 <= 16'sd0;
        end else if (i_clear) begin
            valid_q <= '0;
            lane_enable_q <= '0;
            o_s8 <= 8'sd0;
            o_s16 <= 16'sd0;
        end else if (i_en) begin
            valid_q <= {valid_q[p_stages-2:0], i_valid};
            lane_enable_q <= {lane_enable_q[p_stages-3:0], i_valid && i_lane_enable};

            if (!lane_enable_q[p_stages-2]) begin
                o_s8 <= 8'sd0;
                o_s16 <= 16'sd0;
            end else begin
                if (compare_o_below) o_s16 <= i_activation_min[15:0];
                else if (compare_o_above) o_s16 <= i_activation_max[15:0];
                else if (sum_o_value < -36'sd32768) o_s16 <= -16'sd32768;
                else if (sum_o_value > 36'sd32767) o_s16 <= 16'sd32767;
                else o_s16 <= sum_o_value[15:0];

                if (compare_o_below) o_s8 <= i_activation_min[7:0];
                else if (compare_o_above) o_s8 <= i_activation_max[7:0];
                else if (sum_o_value > 36'sd127) o_s8 <= 8'sd127;
                else if (sum_o_value < -36'sd128) o_s8 <= -8'sd128;
                else o_s8 <= sum_o_value[7:0];
            end
        end
    end
endmodule

`default_nettype wire
