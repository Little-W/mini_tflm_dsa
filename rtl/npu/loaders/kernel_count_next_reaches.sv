// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 完整模宽的加一边界比较，包含最大计数回绕至零的情况。
module kernel_count_next_reaches #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_value /* 递增前的当前计数 */,
    input wire logic [p_width-1:0] i_limit /* 需要检测的完成边界 */,
    output logic o_reaches /* 递增后的计数达到或超过边界 */
);
    logic value_less, unused_value_equal, next_equal, reaches_binary;

    unsigned_compare #(.p_width(p_width)) u_current_compare (
        .i_a(i_value), .i_b(i_limit),
        .o_less(value_less), .o_equal(unused_value_equal)
    );
    (* keep_hierarchy = "yes" *) increment_equal #(.p_width(p_width), .p_preserve_pairs(1'b1), .p_reduce_group_width(6)) u_next_equal (
        .i_a(i_value), .i_target(i_limit), .o_equal(next_equal)
    );
    assign reaches_binary = (i_limit == '0) ||
        ((!(&i_value)) && (!value_less || next_equal));
    always_comb begin
        case (^{i_value, i_limit})
            1'b0, 1'b1: o_reaches = reaches_binary;
            default: o_reaches = (i_value + p_width'(1)) >= i_limit;
        endcase
    end
endmodule

`default_nettype wire
