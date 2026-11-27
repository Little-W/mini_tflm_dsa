// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行合并控制状态与发送活动，输出当周期可接受分组就绪条件的发送许可。
(* keep_hierarchy = "yes" *)
module ia_data_ready_select (
    input  logic i_eligible, // 下一控制状态允许输入分组发送
    input  logic i_clear_output, // 空闲或初始化状态清除输入发送状态
    input  logic i_output_active, // 当前输入分组正在输出
    input  logic i_send_trigger, // 本周期启动输入分组发送
    input  logic i_current_valid, // 当前保存的输入数据有效标志
    input  logic i_output_done, // 当前输入分组输出完成
    output logic o_data_valid // 下一周期控制状态及输出活动允许提供输入数据
);
    logic output_active_after;

    // 清除、启动、完成按原有优先级更新当周期的输出状态。
    always_comb begin
        output_active_after = i_output_active;
        if (i_clear_output) begin
            output_active_after = 1'b0;
        end else if (i_send_trigger && i_current_valid) begin
            output_active_after = 1'b1;
        end else if (i_output_done) begin
            output_active_after = 1'b0;
        end
    end
    assign o_data_valid = i_eligible && !output_active_after;
endmodule

`default_nettype wire
