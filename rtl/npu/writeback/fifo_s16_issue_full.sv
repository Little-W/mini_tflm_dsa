// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行准备十六位输出容量和发射条件，在末级直接选择需要阻止的新输入分组。
(* keep_hierarchy = "yes" *)
module fifo_s16_issue_full #(
    parameter int unsigned p_count_width = 3
) (
    input wire logic [p_count_width-1:0] i_ready, // 当前已完成写入的银行数量。
    input wire logic [p_count_width-1:0] i_threshold, // 下一计算组允许使用的已完成银行数量。
    input wire logic i_partial, // 当前写入银行已有部分结果行。
    input wire logic i_write_blocked, // 当前写入银行仍有待输出结果。
    input wire logic i_next_blocked, // 下一写入银行仍有待输出结果。
    input wire logic i_selected, // 当前计算任务采用十六位输出格式。
    input wire logic i_output_pending, // 当前输入分组需要生成最终输出。
    input wire logic i_other_full, // 八位输出缓冲的容量阻塞状态。
    output logic o_full // 当前分组需要输出且所选缓冲容量不足。
);
    (* keep = 1 *) logic ready_above, ready_equal, ready_all_ones;
    (* keep = 1 *) logic allow_empty, allow_partial, selected_blocked;
    logic qualified_full, reference_full;

    // 完整计数比较与格式、部分写入条件独立准备，保留计数溢出的模回绕语义。
    assign ready_above = i_ready > i_threshold;
    assign ready_equal = i_ready == i_threshold;
    assign ready_all_ones = &i_ready;
    assign allow_empty = i_selected && i_output_pending && !i_partial;
    assign allow_partial = i_selected && i_output_pending && i_partial;
    assign selected_blocked = i_output_pending &&
        ((i_selected && (i_write_blocked || i_next_blocked)) ||
         (!i_selected && i_other_full));
    assign qualified_full = selected_blocked || (allow_empty && ready_above) ||
        (allow_partial && !ready_all_ones && (ready_above || ready_equal));

    // 未知控制按完整条件选择表达式传播，公共接口保留四态结果。
    assign reference_full = i_write_blocked || i_next_blocked ||
        (!(i_partial && (&i_ready)) &&
         ((i_ready > i_threshold) || (i_partial && i_ready == i_threshold)));
    always_comb begin
        case (^{i_ready, i_threshold, i_partial, i_write_blocked, i_next_blocked,
                i_selected, i_output_pending, i_other_full})
            1'b0, 1'b1: o_full = qualified_full;
            default: o_full = (i_selected ? reference_full : i_other_full) && i_output_pending;
        endcase
    end
endmodule

`default_nettype wire
