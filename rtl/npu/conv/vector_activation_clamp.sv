// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 向量结果限幅：并行处理本地量化、量化加法及两种平均池化结果。
// 量化上下限减去输出偏移后在时钟边沿保存，其他结果保持组合输出。
// 输出数组依次为量化、量化加法、二次幂平均池化和通用平均池化结果。
module vector_activation_clamp (
    input  logic clk,                                // 限幅上下限预处理寄存器的时钟
    input  logic signed [31:0] cfg_output_offset,      // 输出零点偏移，量化路径使用有效低八位
    input  logic signed [31:0] cfg_minimum,            // 完整有符号激活下限
    input  logic signed [31:0] cfg_maximum,            // 完整有符号激活上限
    input  logic signed [63:0] i_quantized_value,      // 本地量化流水已经舍入的结果
    input  logic signed [63:0] i_add_rounded_value,     // 量化加法已经舍入的结果
    input  logic signed [7:0] i_average_floor,         // 二次幂平均池化向下取整的低八位结果
    input  logic signed [7:0] i_average_rounded,       // 二次幂平均池化最近偶数舍入的低八位结果
    input  logic signed [8:0] i_average_divided,       // 通用平均池化完成符号恢复的九位结果
    output logic [3:0][31:0] o_result                 // 四类完整限幅结果，数组下标含义见模块说明
);

    //! 0. 常量与内部信号
    //! --------------------

    localparam int p_quantized = 0;
    localparam int p_add = 1;
    localparam int p_average_power = 2;
    localparam int p_average_divide = 3;

    (* use_dsp = "simd" *) logic [8:0] quantized_offset_low;
    logic signed [8:0] minimum_before_offset;
    logic signed [8:0] maximum_before_offset;
    logic quantized_fits_nine_bits;
    logic quantized_before_offset_below;
    logic quantized_before_offset_above;
    logic quantized_offset_increment;
    logic quantized_offset_decrement;
    logic quantized_positive_overflow;
    logic quantized_negative_overflow;
    logic quantized_below_minimum;
    logic quantized_above_maximum;
    (* use_dsp = "simd" *) logic signed [9:0] add_adjusted;
    logic add_below_minimum;
    logic add_above_maximum;
    logic [1:0] bound_high_zero;
    logic [1:0] bound_high_ones;
    logic signed [8:0] average_minimum;
    logic signed [8:0] average_maximum;

    (* use_dsp = "simd" *) wire [9:0] quantized_low_difference, quantized_high_difference;
    (* use_dsp = "simd" *) wire [10:0] add_low_difference, add_high_difference;
    (* use_dsp = "simd" *) wire [8:0] floor_low_difference, floor_high_difference;
    (* use_dsp = "simd" *) wire [9:0] divided_low_difference, divided_high_difference;
    (* use_dsp = "simd" *) wire [8:0] minimum_offset_difference, maximum_offset_difference;

    //! 1. 数值范围与偏移计算
    //! ------------------------

    // 各比较输入扩展一个符号位，差值最高位表示完整有效范围内的严格小于关系。
    // 独立的窄位算术保留普通加减表达式，由综合工具合并并行算术资源。
    assign quantized_low_difference = {i_quantized_value[8],i_quantized_value[8:0]} -
        {minimum_before_offset[8],minimum_before_offset};
    assign quantized_high_difference = {maximum_before_offset[8],maximum_before_offset} -
        {i_quantized_value[8],i_quantized_value[8:0]};
    assign add_low_difference = {add_adjusted[9],add_adjusted} - {cfg_minimum[9],cfg_minimum[9:0]};
    assign add_high_difference = {cfg_maximum[9],cfg_maximum[9:0]} - {add_adjusted[9],add_adjusted};
    assign floor_low_difference = {i_average_floor[7],i_average_floor} - {cfg_minimum[7],cfg_minimum[7:0]};
    assign floor_high_difference = {i_average_floor[7],i_average_floor} - {cfg_maximum[7],cfg_maximum[7:0]};
    assign divided_low_difference = {i_average_divided[8],i_average_divided} - {average_minimum[8],average_minimum};
    assign divided_high_difference = {average_maximum[8],average_maximum} - {i_average_divided[8],i_average_divided};
    assign minimum_offset_difference = {cfg_minimum[7],cfg_minimum[7:0]} -
        {cfg_output_offset[7],cfg_output_offset[7:0]};
    assign maximum_offset_difference = {cfg_maximum[7],cfg_maximum[7:0]} -
        {cfg_output_offset[7],cfg_output_offset[7:0]};

    // 低八位加法与高位符号检查并行，完整保留六十四位补码加法的回绕结果。
    assign quantized_offset_low = {1'b0, i_quantized_value[7:0]} + {1'b0, cfg_output_offset[7:0]};
    assign quantized_offset_increment = quantized_offset_low[8] && !cfg_output_offset[7];
    assign quantized_offset_decrement = !quantized_offset_low[8] && cfg_output_offset[7];
    assign quantized_fits_nine_bits = i_quantized_value[63:9] == {55{i_quantized_value[8]}};
    assign quantized_before_offset_below = quantized_fits_nine_bits ?
        quantized_low_difference[9] : i_quantized_value[63];
    assign quantized_before_offset_above = quantized_fits_nine_bits ?
        quantized_high_difference[9] : !i_quantized_value[63];
    assign quantized_positive_overflow = !i_quantized_value[63] &&
        (&i_quantized_value[62:8]) && quantized_offset_increment;
    assign quantized_negative_overflow = i_quantized_value[63] &&
        !(|i_quantized_value[62:8]) && quantized_offset_decrement;
    assign quantized_below_minimum = !quantized_negative_overflow &&
        (quantized_positive_overflow || quantized_before_offset_below);
    assign quantized_above_maximum = !quantized_positive_overflow &&
        (quantized_negative_overflow || quantized_before_offset_above);

    // 加法结果保留十位有符号偏移，激活范围的高位资格与低位比较独立形成。
    assign add_adjusted = $signed(i_add_rounded_value[9:0]) +
        $signed({{2{cfg_output_offset[7]}}, cfg_output_offset[7:0]});
    assign bound_high_zero[0] = !(|cfg_minimum[30:9]);
    assign bound_high_zero[1] = !(|cfg_maximum[30:9]);
    assign bound_high_ones[0] = &cfg_minimum[30:9];
    assign bound_high_ones[1] = &cfg_maximum[30:9];
    assign add_below_minimum = cfg_minimum[31] ?
        (bound_high_ones[0] && add_low_difference[10]) :
        (!bound_high_zero[0] || add_low_difference[10]);
    assign add_above_maximum = cfg_maximum[31] ?
        (!bound_high_ones[1] || add_high_difference[10]) :
        (bound_high_zero[1] && add_high_difference[10]);
    assign average_minimum = {cfg_minimum[7], cfg_minimum[7:0]};
    assign average_maximum = {cfg_maximum[7], cfg_maximum[7:0]};

    //! 2. 量化上下限保存
    //! --------------------

    // 配置预处理在时钟边沿保存，四类限幅结果保持组合输出。
    always_ff @(posedge clk) begin
        minimum_before_offset <= minimum_offset_difference;
        maximum_before_offset <= maximum_offset_difference;
    end

    //! 3. 各类限幅结果
    //! ------------------

    assign o_result[p_quantized] = quantized_below_minimum ? cfg_minimum :
        quantized_above_maximum ? cfg_maximum : 32'($signed(quantized_offset_low[7:0]));
    assign o_result[p_add] = i_add_rounded_value > 64'sd255 ? cfg_maximum :
        i_add_rounded_value < -64'sd256 ? cfg_minimum :
        add_below_minimum ? cfg_minimum : add_above_maximum ? cfg_maximum : 32'(add_adjusted);
    // 最近偶数舍入只增加零或一，先检查向下取整结果即可保持整数激活范围。
    assign o_result[p_average_power] = floor_low_difference[8] ? cfg_minimum :
        !floor_high_difference[8] ? cfg_maximum : 32'(i_average_rounded);
    assign o_result[p_average_divide] = divided_low_difference[9] ? cfg_minimum :
        divided_high_difference[9] ? cfg_maximum : 32'(i_average_divided);

endmodule

`default_nettype wire
