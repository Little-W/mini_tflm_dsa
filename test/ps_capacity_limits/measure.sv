// SPDX-License-Identifier: Apache-2.0
module ps_capacity_measure #(
    parameter bit p_reference = 1'b0,
    parameter int p_max_rows = 1024,
    parameter int p_rows_width = $clog2(p_max_rows + 1),
    parameter int p_frames_width = 5,
    parameter int p_total_banks = 7,
    parameter int p_bank_bytes = 2048,
    parameter int p_tile_shift = 4
) (
    input logic clk,
    input logic [p_rows_width-1:0] i_frame_rows,
    input logic [p_frames_width-1:0] i_frames,
    input logic [31:0] i_bank_count,
    input logic [31:0] i_frame_slice_tiles,
    input logic i_use_frame_commands,
    output logic o_frames_fit,
    output logic o_admission_fit
);
    logic [p_rows_width-1:0] frame_rows_q;
    logic [p_frames_width-1:0] frames_q;
    logic [31:0] bank_count_q, frame_slice_tiles_q;
    logic use_frame_commands_q;
    logic frames_fit, admission_fit;
    always_ff @(posedge clk) begin
        frame_rows_q <= i_frame_rows;
        frames_q <= i_frames;
        bank_count_q <= i_bank_count;
        frame_slice_tiles_q <= i_frame_slice_tiles;
        use_frame_commands_q <= i_use_frame_commands;
        o_frames_fit <= frames_fit;
        o_admission_fit <= admission_fit;
    end
    if (p_reference) begin : g_reference
        ps_capacity_reference #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),
            .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),
            .p_bank_bytes(p_bank_bytes), .p_tile_shift(p_tile_shift)) u_limits (
            .i_frame_rows(frame_rows_q), .i_frames(frames_q), .i_bank_count(bank_count_q),
            .i_frame_slice_tiles(frame_slice_tiles_q), .i_use_frame_commands(use_frame_commands_q),
            .o_frames_fit(frames_fit), .o_admission_fit(admission_fit)
        );
    end else begin : g_candidate
        ps_capacity_limits #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),
            .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),
            .p_bank_bytes(p_bank_bytes), .p_tile_shift(p_tile_shift)) u_limits (
            .i_frame_rows(frame_rows_q), .i_frames(frames_q), .i_bank_count(bank_count_q),
            .i_frame_slice_tiles(frame_slice_tiles_q), .i_use_frame_commands(use_frame_commands_q),
            .o_frames_fit(frames_fit), .o_admission_fit(admission_fit)
        );
    end
endmodule
