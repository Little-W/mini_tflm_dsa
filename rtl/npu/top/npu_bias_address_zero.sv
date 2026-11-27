// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查两种数据流的偏置地址，并在比较归并时形成输入发送候选。
// 地址按四字节元素计算，保留控制器可见位宽的完整模加与四态选择语义。
module npu_bias_address_zero #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_base, // 控制器可见的偏置字节基址
    input wire logic [31:0] i_ws_channel, // 权重驻留模式的输出列序号
    input wire logic [31:0] i_is_channel, // 输入驻留模式的输出行序号
    input wire logic i_is_mode, // 选择输入驻留模式对应的通道序号
    input wire logic i_issue_eligible = 1'b0, // 输入数据、部分和、控制状态和输出容量允许发送
    input wire logic i_frame_mode = 1'b0, // 当前任务采用帧执行模式
    input wire logic i_base_nonzero = 1'b0, // 原始偏置基址在完整配置位宽内非零
    input wire logic i_frame_phase = 1'b0, // 当前帧位置要求读取偏置
    input wire logic i_visible_base_nonzero = 1'b0, // 直接执行偏置基址在控制器位宽内非零
    input wire logic i_bias_available = 1'b0, // 偏置数据有效或当前计算通过部分和回放继续
    input wire logic i_frame_incomplete = 1'b1, // 帧执行的计算、存储或输出尚未全部完成
    input wire logic i_output_complete = 1'b0, // 直接执行模式的输出已经完成
    output logic o_zero, // 基址加通道字节偏移后的地址为零
    output logic o_issue // 本周期满足全部输入发送条件
);
    logic [31:0] selected_offset;
    logic reference_zero, binary_zero;
    logic reference_issue, binary_issue;
    logic [2:0] issue_candidates;
    (* keep = 1 *) logic issue_without_address;
    npu_bias_issue_optional u_optional (
        .i_eligible(i_issue_eligible), .i_frame_mode(i_frame_mode),
        .i_base_nonzero(i_base_nonzero), .i_frame_phase(i_frame_phase),
        .i_visible_base_nonzero(i_visible_base_nonzero), .i_bias_available(i_bias_available),
        .o_qualified(issue_without_address)
    );
    assign reference_issue = i_issue_eligible &&
        (i_bias_available || !(i_frame_mode ?
            (i_base_nonzero && i_frame_phase && !reference_zero) : i_visible_base_nonzero)) &&
        (i_frame_mode ? i_frame_incomplete : !i_output_complete);
    assign selected_offset = (i_is_mode ? i_is_channel : i_ws_channel) << 2;
    add_equal #(.p_width(p_width), .p_preserve_bits(1'b1), .p_keep_bits(1'b0)) u_reference (
        .i_a(i_base), .i_b(p_width'(selected_offset)), .i_target(p_width'(0)),
        .i_carry_in(1'b0), .o_equal(reference_zero)
    );

    if (p_width > 2 && p_width <= 32) begin : g_channel
        localparam int unsigned p_channel_width = p_width-2;
        (* keep = 1 *) logic ws_equal, is_equal;
        (* keep = 1 *) logic ws_eligible, is_eligible;
        (* keep = 1 *) logic ws_qualified, is_qualified;
        // 数据流和发送条件先独立完成，通道比较的末级归并仅增加一个资格输入。
        assign ws_eligible = i_frame_mode && !i_is_mode && i_base[1:0] == 2'b0;
        assign is_eligible = i_frame_mode && i_is_mode && i_base[1:0] == 2'b0;
        // 地址低两位必须为零，其余位检查通道序号是否等于基址字序号的补码。
        npu_bias_channel_match #(.p_width(p_channel_width)) u_ws (
            .i_a(~i_base[p_width-1:2]), .i_target(i_ws_channel[p_channel_width-1:0]),
            .i_eligible(i_issue_eligible), .i_mode_eligible(ws_eligible),
            .o_equal(ws_equal), .o_qualified(ws_qualified)
        );
        npu_bias_channel_match #(.p_width(p_channel_width)) u_is (
            .i_a(~i_base[p_width-1:2]), .i_target(i_is_channel[p_channel_width-1:0]),
            .i_eligible(i_issue_eligible), .i_mode_eligible(is_eligible),
            .o_equal(is_equal), .o_qualified(is_qualified)
        );
        assign binary_zero = (i_base[1:0] == 2'b0) && (i_is_mode ? is_equal : ws_equal);
        assign issue_candidates = {issue_without_address, ws_qualified, is_qualified};
    end else if (p_width <= 2) begin : g_low_address
        assign binary_zero = i_base == '0;
        assign issue_candidates = {issue_without_address,
            (i_issue_eligible && i_frame_mode && binary_zero), 1'b0};
    end else begin : g_wide_address
        assign binary_zero = reference_zero;
        assign issue_candidates = {reference_issue, 2'b0};
    end
    npu_bias_issue_select u_issue_select (
        .i_candidates(issue_candidates), .i_frame_mode(i_frame_mode),
        .i_frame_incomplete(i_frame_incomplete), .i_output_complete(i_output_complete),
        .o_issue(binary_issue)
    );

    // 未知输入沿逐位进位比较传播，已知输入采用并行的通道检查结果。
    always_comb begin
        case (^{i_base, i_ws_channel, i_is_channel, i_is_mode})
            1'b0, 1'b1: o_zero = binary_zero;
            default: o_zero = reference_zero;
        endcase
        case (^{i_base, i_ws_channel, i_is_channel, i_is_mode, i_issue_eligible,
                i_frame_mode, i_base_nonzero, i_frame_phase, i_visible_base_nonzero, i_bias_available,
                i_frame_incomplete, i_output_complete})
            1'b0, 1'b1: o_issue = binary_issue;
            default: o_issue = reference_issue;
        endcase
    end
endmodule

`default_nettype wire
