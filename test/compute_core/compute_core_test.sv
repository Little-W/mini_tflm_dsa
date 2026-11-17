`timescale 1ns / 1ps
module compute_core_test #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned DATA_WIDTH = 16,
    parameter int unsigned WEIGHT_WIDTH = 16,
    parameter int unsigned PS_FRAME_COUNT = SIZE,
    parameter int unsigned MAX_IA_REUSE = 2
) (
    input logic clk, rst_n,
    input logic weight_commit, store_weight_req,
    input logic signed [WEIGHT_WIDTH-1:0] weight_in [SIZE],
    input logic signed [DATA_WIDTH-1:0] ia_vec_in [SIZE],
    input logic ia_row_valid, ia_tile_start, ia_calc_done, ia_is_init_data,
    input logic ia_l1_switch, ia_sending_done, send_ia_trigger,
    input logic ps_store_cfg_valid, ps_frame_request, ps_frame_init,
    input logic ps_frame_final, ps_force_raw,
    input logic bias_sleep,
    input logic signed [31:0] bias_in [SIZE],
    output wire signed [31:0] acc_data_out [SIZE],
    output wire acc_data_valid, partial_sum_calc_over, tile_calc_over,
    output wire ps_frame_ready, ps_frame_complete, ps_capacity_fault
);
    compute_core #(
        .SIZE(SIZE), .DATA_WIDTH(DATA_WIDTH), .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .PS_FRAME_COUNT(PS_FRAME_COUNT), .MAX_IA_REUSE(MAX_IA_REUSE)
    ) u_core (
        .clk, .rst_n, .weight_commit, .store_weight_req, .weight_in,
        .ia_vec_in, .ia_row_valid, .ia_tile_start, .ia_calc_done,
        .ia_is_init_data, .ia_l1_switch, .ia_sending_done, .send_ia_trigger,
        .ps_store_cfg_valid, .ps_frame_request, .ps_frame_id('0),
        .ps_frame_rows(32'(SIZE)), .ps_frame_reserve_rows(32'(SIZE)),
        .ps_frame_word_cap(3'd4), .ps_frame_init, .ps_frame_final, .ps_force_raw,
        .ps_frame_ready, .ps_frame_complete, .ps_capacity_fault,
        .ps_frame_pressure(), .partial_sum_advance_ready(),
        .ps_ram_read_en(), .ps_ram_read_addr(),
        .ps_ram_write_en(), .ps_ram_write_addr(), .ps_ram_write_data(),
        .bias_sleep, .bias_in, .acc_data_out, .acc_data_valid,
        .partial_sum_calc_over, .tile_calc_over
    );
endmodule
