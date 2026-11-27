// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行准备帧模式和直接执行模式的偏置需求，地址零值结果在末级参与选择。
// 所有条件均为组合逻辑，保留模式未知时的条件选择语义。
module npu_bias_presence (
    input wire logic i_frame_mode, // 当前任务采用帧执行模式
    input wire logic i_base_nonzero, // 完整偏置基址非零
    input wire logic i_is_mode, // 当前任务采用输入驻留数据流
    input wire logic i_ws_final_bias, // 权重驻留模式在末帧应用偏置
    input wire logic i_frame_final, // 当前帧为归约维度的最后一帧
    input wire logic i_frame_init, // 当前帧为归约维度的第一帧
    input wire logic i_address_zero, // 当前通道偏置地址按控制器位宽回绕为零
    input wire logic i_visible_base_nonzero, // 控制器可见位宽内的直接执行偏置基址非零
    output logic o_present, // 当前执行步骤需要等待偏置数据
    output logic o_frame_phase // 当前数据流与帧位置要求读取偏置
);
    (* keep = 1 *) logic frame_eligible, direct_required;
    assign o_frame_phase = (i_is_mode || i_ws_final_bias) ? i_frame_final : i_frame_init;
    assign frame_eligible = i_frame_mode && i_base_nonzero && o_frame_phase;
    assign direct_required = !i_frame_mode && i_visible_base_nonzero;
    always_comb begin
        case (^{i_frame_mode, i_base_nonzero, i_is_mode, i_ws_final_bias,
                i_frame_final, i_frame_init, i_address_zero, i_visible_base_nonzero})
            1'b0, 1'b1: o_present = (frame_eligible && !i_address_zero) || direct_required;
            default: o_present = i_frame_mode ?
                (i_base_nonzero &&
                 ((i_is_mode || i_ws_final_bias) ? i_frame_final : i_frame_init) &&
                 !i_address_zero) : i_visible_base_nonzero;
        endcase
    end
endmodule

`default_nettype wire
