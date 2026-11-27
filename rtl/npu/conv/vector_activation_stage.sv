// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 为向量引擎提供量化、量化加法及两种平均池化的激活限幅结果。
// 量化与池化保持组合输出；量化加法在舍入保存边沿捕获偏移候选和配置，下一周期完成限幅。
// 加法阶段对应控制器 ADD_ROUND_WAIT 到 ADD_CLAMP 的现有边沿，任务的公开完成周期保持不变。
module vector_activation_stage (
    input wire logic clk, // 保存偏移候选和限幅配置的工作时钟
    input wire logic signed [63:0] i_quantized_value, // 当前本地量化已经完成舍入的结果
    input wire logic signed [63:0] i_add_rounding_value, // 当前舍入输出，在边沿后进入量化加法限幅阶段
    input wire logic signed [7:0] i_average_floor, // 二次幂平均池化向下取整的低八位值
    input wire logic signed [7:0] i_average_rounded, // 二次幂平均池化最近偶数舍入的低八位值
    input wire logic signed [8:0] i_average_divided, // 通用平均池化完成符号恢复的九位值
    input wire logic signed [31:0] cfg_output_offset, // 输出零点偏移，使用低八位有符号值
    input wire logic signed [31:0] cfg_minimum, // 当前结果对应的完整激活下限
    input wire logic signed [31:0] cfg_maximum, // 当前结果对应的完整激活上限
    output logic [3:0][31:0] o_result // 量化、量化加法、二次幂平均池化与通用平均池化的完整结果
);
    //! 0. 内部数值与范围条件
    //! ------------------------

    (* use_dsp = "simd" *) logic signed [9:0] adjusted_candidate;
    logic signed [9:0] adjusted_value;
    logic signed [31:0] minimum_value;
    logic signed [31:0] maximum_value;
    logic above_range;
    logic below_range;
    logic minimum_high_zero;
    logic maximum_high_zero;
    logic minimum_high_ones;
    logic maximum_high_ones;
    (* use_dsp = "simd" *) logic [10:0] minimum_difference;
    (* use_dsp = "simd" *) logic [10:0] maximum_difference;
    logic below_minimum;
    logic above_maximum;
    logic signed [31:0] base_cfg_output_offset;
    logic signed [31:0] base_cfg_minimum;
    logic signed [31:0] base_cfg_maximum;
    logic signed [63:0] base_i_quantized_value;
    logic signed [63:0] base_i_add_rounded_value;
    logic signed [7:0] base_i_average_floor;
    logic signed [7:0] base_i_average_rounded;
    logic signed [8:0] base_i_average_divided;
    logic [3:0][31:0] base_o_result;

    //! 1. 形成偏移候选与组合结果
    //! ----------------------------

    assign adjusted_candidate = $signed(i_add_rounding_value[9:0]) +
        $signed({{2{cfg_output_offset[7]}}, cfg_output_offset[7:0]});

    // 其余三种运算沿用组合限幅与本地量化阈值寄存器，公共配置保持同周期含义。
    assign base_cfg_output_offset = cfg_output_offset;
    assign base_cfg_minimum = cfg_minimum;
    assign base_cfg_maximum = cfg_maximum;
    assign base_i_quantized_value = i_quantized_value;
    assign base_i_add_rounded_value = 64'sd0;
    assign base_i_average_floor = i_average_floor;
    assign base_i_average_rounded = i_average_rounded;
    assign base_i_average_divided = i_average_divided;
    vector_activation_clamp u_base (
        .clk(clk),
        .cfg_output_offset(base_cfg_output_offset),
        .cfg_minimum(base_cfg_minimum),
        .cfg_maximum(base_cfg_maximum),
        .i_quantized_value(base_i_quantized_value),
        .i_add_rounded_value(base_i_add_rounded_value),
        .i_average_floor(base_i_average_floor),
        .i_average_rounded(base_i_average_rounded),
        .i_average_divided(base_i_average_divided),
        .o_result(base_o_result)
    );

    //! 2. 保存数值与限幅配置
    //! ------------------------

    // 向量控制器的舍入保存边沿同时保存候选和全部资格条件，后续比较只读取同拍数据。
    always_ff @(posedge clk) begin
        adjusted_value <= adjusted_candidate;
        minimum_value <= cfg_minimum;
        maximum_value <= cfg_maximum;
        above_range <= i_add_rounding_value > 64'sd255;
        below_range <= i_add_rounding_value < -64'sd256;
        minimum_high_zero <= !(|cfg_minimum[30:9]);
        maximum_high_zero <= !(|cfg_maximum[30:9]);
        minimum_high_ones <= &cfg_minimum[30:9];
        maximum_high_ones <= &cfg_maximum[30:9];
    end

    //! 3. 比较边界与输出结果
    //! ------------------------

    assign minimum_difference = {adjusted_value[9], adjusted_value} -
        {minimum_value[9], minimum_value[9:0]};
    assign maximum_difference = {maximum_value[9], maximum_value[9:0]} -
        {adjusted_value[9], adjusted_value};
    assign below_minimum = minimum_value[31] ?
        (minimum_high_ones && minimum_difference[10]) :
        (!minimum_high_zero || minimum_difference[10]);
    assign above_maximum = maximum_value[31] ?
        (!maximum_high_ones || maximum_difference[10]) :
        (maximum_high_zero && maximum_difference[10]);
    assign o_result[0] = base_o_result[0];
    assign o_result[2] = base_o_result[2];
    assign o_result[3] = base_o_result[3];
    assign o_result[1] = above_range ? maximum_value : below_range ? minimum_value :
        below_minimum ? minimum_value : above_maximum ? maximum_value : 32'(adjusted_value);
endmodule

`default_nettype wire
