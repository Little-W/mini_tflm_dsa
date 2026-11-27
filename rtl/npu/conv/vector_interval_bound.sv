// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 将有符号坐标转换为保持次序的无符号编码，并行检查左闭右开的有效区间。
// 两个端点采用三位分组比较，分组结果按固定层次归并后形成完整范围条件。
(* keep_hierarchy = "yes" *)
module vector_interval_bound (
  input wire logic signed [16:0] i_coordinate, // 待检查的有符号坐标
  input wire logic signed [16:0] i_minimum, // 有效坐标区间的左端点，包含该端点
  input wire logic signed [16:0] i_maximum, // 有效坐标区间的右端点，不包含该端点
    output logic o_inside // 当前坐标处于给定的左闭右开区间
);
    //! 0. 比较接口信号
    //! ------------------

    logic [16:0] lower_i_a;
    logic [16:0] lower_i_b;
    logic [16:0] upper_i_a;
    logic [16:0] upper_i_b;
    logic lower_o_less;
    logic lower_o_equal;
    logic upper_o_less;
    logic upper_o_equal;

    //! 1. 并行比较两个端点
    //! ----------------------

    assign lower_i_a = {~i_coordinate[16], i_coordinate[15:0]};
    assign lower_i_b = {~i_minimum[16], i_minimum[15:0]};
    assign upper_i_a = {~i_coordinate[16], i_coordinate[15:0]};
    assign upper_i_b = {~i_maximum[16], i_maximum[15:0]};
    parallel_unsigned_compare #(.p_width(17), .p_preserve_groups(1'b1)) u_lower (
        .i_a(lower_i_a), .i_b(lower_i_b), .o_less(lower_o_less), .o_equal(lower_o_equal)
    );
    parallel_unsigned_compare #(.p_width(17), .p_preserve_groups(1'b1)) u_upper (
        .i_a(upper_i_a), .i_b(upper_i_b), .o_less(upper_o_less), .o_equal(upper_o_equal)
    );

    //! 2. 形成范围结果
    //! ------------------

    assign o_inside = !lower_o_less && upper_o_less;
endmodule

`default_nettype wire
