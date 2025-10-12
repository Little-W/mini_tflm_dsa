interface tb_compute_core_if(input logic clk);
    localparam int unsigned SIZE = 4;
    localparam int unsigned DATA_WIDTH = 16;

    // DUT inputs
    logic                         store_weight_req;
    logic signed [           7:0] weight_in             [     SIZE];
    logic signed [DATA_WIDTH-1:0] ia_vec_in             [     SIZE];
    logic                         ia_row_valid;
    logic                         ia_calc_done;
    logic                         ia_is_init_data;
    logic signed [          31:0] bias_in               [     SIZE];

    // DUT outputs
    wire signed  [          31:0] acc_data_out          [     SIZE];
    wire                          acc_data_valid;
    wire                          tile_calc_over;
    wire                          partial_sum_calc_over;

    // Clocking block for testbench to prevent race conditions
    clocking cb @(posedge clk);
        output store_weight_req, weight_in, ia_vec_in, ia_row_valid, ia_calc_done, ia_is_init_data, bias_in;
        input acc_data_out, acc_data_valid, tile_calc_over, partial_sum_calc_over;
    endclocking
endinterface
