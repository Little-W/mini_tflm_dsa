// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两项寄存队列，输出数据与上下游容量信号均由寄存器直接提供。
// 连续发送时每拍可接收下一项；下游暂停后可额外保存一项完整数据。
module dma_register_buffer #(
    parameter int unsigned p_width = 1
) (
    input wire logic clk,
    input wire logic rst_n,
    input wire logic i_valid,
    output logic o_ready,
    input wire logic [p_width-1:0] i_data,
    output logic o_valid,
    input wire logic i_ready,
    output logic [p_width-1:0] o_data
);
    logic head_valid, tail_valid;
    logic [p_width-1:0] head_data, tail_data;
    logic accept_input, accept_output;

    assign o_ready = !tail_valid;
    assign o_valid = head_valid;
    assign o_data = head_data;
    assign accept_input = i_valid && o_ready;
    assign accept_output = o_valid && i_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            head_valid <= 1'b0;
            tail_valid <= 1'b0;
        end else if (accept_output) begin
            head_valid <= tail_valid || accept_input;
            tail_valid <= 1'b0;
        end else if (accept_input) begin
            head_valid <= 1'b1;
            tail_valid <= head_valid;
        end
    end

    // 数据寄存器随接收事件更新，有效标志控制复位后的可见内容。
    always_ff @(posedge clk) begin
        if (accept_output && tail_valid) begin
            head_data <= tail_data;
        end else if (accept_input && (!head_valid || accept_output)) begin
            head_data <= i_data;
        end
        if (accept_input && head_valid && !accept_output) begin
            tail_data <= i_data;
        end
    end
endmodule

`default_nettype wire
