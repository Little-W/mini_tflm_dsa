// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查本周期有无加载完成两种情况下的发送完成资格。
// 有界差值保留完整计数回绕关系，晚到的加载完成信号只选择最终结果。
(* keep_hierarchy = "yes" *)
module kernel_completion_check (
    input wire logic [1:0] i_pending_loads, // 已发出而尚未完成加载的分块数量
    input wire logic [1:0] i_pending_sends, // 已发出而尚未完成发送的分块数量
    input wire logic i_issued_zero, // 完整发出计数为零
    input wire logic i_issued_one, // 完整发出计数为一
    input wire logic i_all_loads_done, // 先前周期已经完成全部加载
    input wire logic i_all_loads_issued, // 全部加载请求已经发出
    input wire logic i_load_done, // 本周期完成一个分块加载
    output logic o_complete // 本周期发送结束后已经覆盖全部加载结果
);
    logic [1:0] remaining_sends, reference_loads;
    logic sends_wrap, reference_wrap, load_count_reached;
    logic reference_covers, reference_complete;
    (* keep = 1 *) logic [1:0] complete_candidate;
    assign remaining_sends = i_pending_sends-2'd1;
    assign sends_wrap = (remaining_sends != 0 && i_issued_zero) ||
        (remaining_sends == 2 && i_issued_one);
    assign load_count_reached = i_pending_loads == 1 || (i_pending_loads == 2 && i_issued_zero);
    for (genvar step = 0; step < 2; step++) begin : g_candidate
        logic [1:0] remaining_loads;
        logic loads_wrap, covers;
        assign remaining_loads = i_pending_loads-2'(step);
        assign loads_wrap = (remaining_loads != 0 && i_issued_zero) ||
            (remaining_loads == 2 && i_issued_one);
        assign covers = (sends_wrap != loads_wrap) ? sends_wrap : remaining_sends <= remaining_loads;
        assign complete_candidate[step] =
            (i_all_loads_done || (1'(step) && i_all_loads_issued && load_count_reached)) && covers;
    end
    // 未知输入使用完整差值与条件表达式，保持公开控制的四态传播。
    assign reference_loads = i_pending_loads-2'(i_load_done);
    assign reference_wrap = (reference_loads != 0 && i_issued_zero) ||
        (reference_loads == 2 && i_issued_one);
    assign reference_covers = (sends_wrap != reference_wrap) ? sends_wrap : remaining_sends <= reference_loads;
    assign reference_complete =
        (i_all_loads_done || (i_load_done && i_all_loads_issued && load_count_reached)) && reference_covers;
    always_comb begin
        case (^{i_pending_loads, i_pending_sends, i_issued_zero, i_issued_one,
                i_all_loads_done, i_all_loads_issued, i_load_done})
            1'b0, 1'b1: o_complete = complete_candidate[i_load_done];
            default: o_complete = reference_complete;
        endcase
    end
endmodule

`default_nettype wire
