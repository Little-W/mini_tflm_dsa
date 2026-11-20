// SPDX-License-Identifier: Apache-2.0
// 并行检查各位进位是否一致，比较保留 p_width 位的加法结果。
`default_nettype none
module add_equal #(
    parameter int unsigned p_width = 32,
    parameter bit p_use_lut = 1'b0
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    input  wire logic [p_width-1:0] i_target,
    input  wire logic               i_carry_in,
    output logic               o_equal
);
    //! 0. 进位信号
    //! ------------

    logic [p_width-1:0] carry_needed;
    logic [p_width-1:0] carry_generated;
    logic [p_width-1:0] carry_expected;
    logic unused_final_carry;

    //! 1. 计算各位进位条件
    //! --------------------

    // 目标和值确定该位所需进位，同时确定传向下一位的进位。
    assign carry_needed = i_a ^ i_b ^ i_target;
    assign carry_generated = (i_a & i_b) | ((i_a | i_b) & ~i_target);
    assign {unused_final_carry, carry_expected} = {carry_generated, i_carry_in};

    //! 2. 合并逐位比较
    //! ----------------

    // 最低位采用输入进位，其余各位采用相邻低位产生的进位。
    if (p_use_lut) begin : g_lut
        localparam int p_groups = (p_width + 5) / 6;
        localparam logic [63:0] p_bit_equal = 64'h9669_6969_9696_9669;
        localparam logic [63:0] p_all_equal = 64'h8000_0000_0000_0000;
        logic [p_width-1:0] bit_equal;
        logic [p_groups-1:0] group_equal;

        // 每一位只依赖本位操作数和相邻低位，六输入表固定比较层数。
        for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
            logic [5:0] equal_i_value;
            logic equal_o_value;

            assign equal_i_value[2:0] = {i_target[bit_index], i_b[bit_index], i_a[bit_index]};
            if (bit_index == 0) begin : g_first
                assign equal_i_value[5:3] = {1'b0, i_carry_in, i_carry_in};
            end else begin : g_following
                assign equal_i_value[5:3] = {
                    i_target[bit_index-1], i_b[bit_index-1], i_a[bit_index-1]};
            end
            LUT6 #(.INIT(p_bit_equal)) u_equal (
                .I0(equal_i_value[0]), .I1(equal_i_value[1]),
                .I2(equal_i_value[2]), .I3(equal_i_value[3]),
                .I4(equal_i_value[4]), .I5(equal_i_value[5]),
                .O(equal_o_value)
            );
            assign bit_equal[bit_index] = equal_o_value;
        end

        // 六位一组归约后再合并，保持宽等式的组合树深度。
        for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
            logic [5:0] group_i_value;
            logic group_o_value;

            for (genvar item = 0; item < 6; item++) begin : g_item
                if (6*group_index+item < p_width) begin : g_present
                    assign group_i_value[item] = bit_equal[6*group_index+item];
                end else begin : g_padding
                    assign group_i_value[item] = 1'b1;
                end
            end
            LUT6 #(.INIT(p_all_equal)) u_group (
                .I0(group_i_value[0]), .I1(group_i_value[1]),
                .I2(group_i_value[2]), .I3(group_i_value[3]),
                .I4(group_i_value[4]), .I5(group_i_value[5]),
                .O(group_o_value)
            );
            assign group_equal[group_index] = group_o_value;
        end
        assign o_equal = &group_equal;
    end else begin : g_logic
        assign o_equal = (carry_needed == carry_expected);
    end
endmodule
`default_nettype wire
