// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
module vector_engine_control_observer #(
    parameter int p_dw_finish = 0,
    parameter int p_output_next = 0
) (
    input wire logic clk,
    input wire logic rst_n,
    input wire logic [31:0] i_state,
    input wire logic [31:0] i_position_next,
    input wire logic [31:0] i_position_count,
    input wire logic i_position_has_more,
    input wire logic i_position_is_last,
    input wire logic i_snapshot_fire
);
    // 消费边界关系时，提前保存的比较结果必须对应当前像素位置。
    always @(posedge clk) begin
        if (rst_n) begin
            if (i_state == p_dw_finish || i_state == p_output_next) begin
                assert (i_position_has_more === (i_position_next < i_position_count))
                    else $fatal(1, "下一位置的范围比较与当前任务不一致");
            end
            if (i_state == p_dw_finish && i_snapshot_fire) begin
                assert (i_position_is_last === (i_position_next == i_position_count))
                    else $fatal(1, "最后位置标志与当前任务不一致");
            end
        end
    end
endmodule

bind vector_engine_control vector_engine_control_observer #(
    .p_dw_finish(32'(vector_engine_control_pkg::DW_FINISH)),
    .p_output_next(32'(vector_engine_control_pkg::OUTPUT_NEXT))
) u_position_observer (
    .clk(clk), .rst_n(rst_n), .i_state(32'(state)),
    .i_position_next(position_next), .i_position_count(position_count[31:0]),
    .i_position_has_more(position_has_more), .i_position_is_last(o_position_is_last),
    .i_snapshot_fire(dw_snapshot_fire)
);
`endif
