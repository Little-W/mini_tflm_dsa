// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
module vector_weight_issue_observer #(
    parameter int p_channels = 16,
    parameter int p_depth = 49
) (
    input logic clk,
    input logic rst_n,
    input logic i_execute,
    input logic i_depthwise,
    input logic [31:0] i_active,
    input logic i_read_en,
    input logic i_wr_en,
    input logic [31:0] i_wr_tap,
    input logic [p_channels-1:0] i_wr_mask,
    input logic [8*p_channels-1:0] i_wr_data,
    input logic [31:0] i_rd_tap,
    input logic [31:0] i_current_tap,
    input logic [8*p_channels-1:0] i_weight_data
);
    logic [7:0] reference_memory [p_channels][p_depth];
    logic [31:0] sampled_read_tap;
    longint unsigned checked_issues;
    longint unsigned checked_weights;

    always @(posedge clk) begin
        if (i_read_en) sampled_read_tap <= i_rd_tap;
        if (!rst_n) begin
            checked_issues <= 0;
            checked_weights <= 0;
        end else if (i_execute && i_depthwise) begin
            assert(sampled_read_tap == i_current_tap);
            for (int channel = 0; channel < p_channels; channel++) begin
                // 未使用的通道不参与本次计算，存储内容由后续任务重新写入。
                if (channel < i_active) begin
                    if (i_current_tap < p_depth) begin
                        assert(i_weight_data[8*channel+:8] === reference_memory[channel][i_current_tap]);
                    end else begin
                        assert(i_weight_data[8*channel+:8] == 8'd0);
                    end
                end
            end
            checked_issues <= checked_issues + 1;
            checked_weights <= checked_weights + 64'(i_active);
        end
        if (i_wr_en && i_wr_tap < p_depth) begin
            for (int channel = 0; channel < p_channels; channel++) begin
                if (i_wr_mask[channel]) begin
                    reference_memory[channel][i_wr_tap] <= i_wr_data[8*channel+:8];
                end
            end
        end
    end
    final begin
        $display("VECTOR_WEIGHT_ROWS_CHECK issues=%0d weights=%0d", checked_issues, checked_weights);
    end
endmodule

bind vector_engine vector_weight_issue_observer #(.p_channels(TILE), .p_depth(MAX_TAPS)) weight_rows_observer (
    .clk(clk), .rst_n(rst_n), .i_execute(dw_issue_fire), .i_depthwise(depthwise),
    .i_active(32'(active)), .i_read_en(u_operand_store.weights_i_rd_en),
    .i_wr_en(u_operand_store.weights_i_wr_en), .i_wr_tap(u_operand_store.weights_i_wr_tap),
    .i_wr_mask(u_operand_store.weights_i_wr_mask), .i_wr_data(u_operand_store.weights_i_wr_data),
    .i_rd_tap(state_weight_zero_address ? 32'd0 :
        u_operand_store.weight_tap_advance ? 32'(weight_tap_nxt) : 32'(tap)),
    .i_current_tap(32'(tap)), .i_weight_data(u_operand_store.weights_o_rd_data)
);
`endif
