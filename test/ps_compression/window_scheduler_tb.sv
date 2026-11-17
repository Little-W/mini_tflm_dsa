// SPDX-License-Identifier: Apache-2.0
module window_scheduler_tb #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned FRAME_COUNT = 16
) (
    input logic clk, rst_n,
    input logic start,
    input logic [31:0] stream_rows, stationary_rows, reduction,
    input logic [31:0] reuse_rows, window_frames,
    input logic [31:0] slice_tiles = 32'd0,
    input logic [1:0] config_error,
    output logic ready,
    output logic done_valid,
    input logic done_ready,
    output logic [1:0] err_code,
    output logic command_valid,
    input logic command_ready,
    input logic command_pressure,
    input logic command_complete,
    output logic [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id,
    output logic [31:0] p0, q0, column0, rows, cols, count_k, reserve_rows,
    output logic frame_init, frame_final,
    output logic command_active,
    output logic lookahead_valid,
    output logic [31:0] lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k,
    output logic [31:0] stat_commands, stat_pressure_events, stat_early_finish_frames
);

ps_window_scheduler #(.SIZE(SIZE),.FRAME_COUNT(FRAME_COUNT)) u_dut(.*);
assign stat_commands=u_dut.tb_observer.stat_commands;
assign stat_pressure_events=u_dut.tb_observer.stat_pressure_events;
assign stat_early_finish_frames=u_dut.tb_observer.stat_early_finish_frames;
endmodule
