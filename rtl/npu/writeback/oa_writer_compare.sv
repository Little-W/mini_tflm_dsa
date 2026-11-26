// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较输出写回的索引与上界，分段完成大小关系并保留减法借位的四态含义。
module oa_writer_compare #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_value, // 待检查的索引或字节偏移。
    input wire logic [p_width-1:0] i_limit, // 当前范围的排他上界。
    output logic o_less // 输入值严格小于上界。
);
    logic less, unused_equal;
    logic [p_width:0] difference;
    unsigned_compare #(.p_width(p_width)) u_compare (
        .i_a(i_value), .i_b(i_limit), .o_less(less), .o_equal(unused_equal)
    );
    assign difference = {1'b0, i_value} - {1'b0, i_limit};
    always_comb begin
        case (^{i_value, i_limit})
            1'b0, 1'b1: o_less = less;
            default: o_less = difference[p_width];
        endcase
    end
endmodule

`default_nettype wire
