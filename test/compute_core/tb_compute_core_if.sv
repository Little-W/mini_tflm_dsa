interface tb_compute_core_if(input logic clk);
    import test_params_pkg::*;
    localparam int unsigned DATA_WIDTH = 16;
    localparam int unsigned WEIGHT_WIDTH = 16;

    logic weight_commit, store_weight_req;
    logic signed [WEIGHT_WIDTH-1:0] weight_in [SIZE];
    logic signed [DATA_WIDTH-1:0] ia_vec_in [SIZE];
    logic ia_row_valid, ia_tile_start, ia_calc_done, ia_is_init_data;
    logic ia_l1_switch, ia_sending_done, send_ia_trigger;
    logic ps_store_cfg_valid, ps_frame_request, ps_frame_init;
    logic ps_frame_final, ps_force_raw, bias_sleep;
    logic signed [31:0] bias_in [SIZE];
    wire signed [31:0] acc_data_out [SIZE];
    wire acc_data_valid, tile_calc_over, partial_sum_calc_over;
    wire ps_frame_ready, ps_frame_complete, ps_capacity_fault;
endinterface
