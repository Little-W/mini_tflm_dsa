// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 读取保护器的地址范围比较：各三位分组独立判断，按平衡结构归并完整次序。
// 含未知位的地址使用字节分组关系，保持区间判断的四态传播规则。
(* keep_hierarchy = "yes" *)
module conv_guard_range_compare #(
    parameter int unsigned p_width = 33
) (
    input wire logic [p_width-1:0] i_a, // 待检查的请求地址或页号
    input wire logic [p_width-1:0] i_b, // 对应区间的边界地址或页号
    output logic o_less, // 请求操作数小于边界操作数
    output logic o_equal // 两个地址操作数完全相等
);
    logic parallel_o_less, parallel_o_equal;
    logic reference_o_less, reference_o_equal;

    parallel_unsigned_compare #(
        .p_width(p_width), .p_preserve_groups(1'b1), .p_infer_arithmetic(1'b0)
    ) u_parallel (
        .i_a(i_a), .i_b(i_b),
        .o_less(parallel_o_less), .o_equal(parallel_o_equal)
    );
    unsigned_compare #(.p_width(p_width)) u_reference (
        .i_a(i_a), .i_b(i_b),
        .o_less(reference_o_less), .o_equal(reference_o_equal)
    );

    always_comb begin
        {o_less, o_equal} = {reference_o_less, reference_o_equal};
        case (^{i_a, i_b})
            1'b0, 1'b1: {o_less, o_equal} = {parallel_o_less, parallel_o_equal};
            default: begin end
        endcase
    end
endmodule

`default_nettype wire
