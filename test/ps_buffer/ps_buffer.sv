module ps_buffer #(
    parameter int unsigned SIZE       = 16,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic signed [DATA_WIDTH-1:0] data_in       [0:SIZE-1],
    input  logic                         ia_row_valid,
    input  logic                         ia_calc_done,
    input  logic                         ia_l1_switch,
    input  logic                         send_ia_trigger,
    input  logic                         ia_is_init_data,
    output logic signed [DATA_WIDTH-1:0] data_out      [0:SIZE-1],
    output logic                         acc_data_valid,
    output logic                         tile_calc_over
);
    localparam int unsigned DEPTH = SIZE * 4;

    logic signed [DATA_WIDTH-1:0] fifo_data_out    [0:SIZE-1];
    logic signed [DATA_WIDTH-1:0] de_diag_data_out [0:SIZE-1];

    logic                         input_valid_chain     [0:SIZE];
    logic                         is_init_data_chain    [0:SIZE];
    logic                         ia_l1_switch_chain    [0:SIZE];
    logic                         send_ia_trigger_chain [0:SIZE];

    logic                         de_diag_data_valid;
    logic                         de_diag_tile_calc_over;

    // calc_done is a ps_buffer-level control signal. It is not propagated
    // through the FIFO chain. When ia_calc_done is asserted, the incoming
    // stair-stepped partial sums bypass ps_fifo and enter de_diagonalizer.
    assign input_valid_chain[0]     = ia_row_valid;
    assign is_init_data_chain[0]    = ia_is_init_data;
    assign ia_l1_switch_chain[0]    = ia_l1_switch;
    assign send_ia_trigger_chain[0] = send_ia_trigger;

    genvar lane;
    generate
        for (lane = 0; lane < SIZE; lane++) begin : gen_ps_buffer_fifo
            ps_buffer_fifo #(
                .DEPTH     (DEPTH),
                .DATA_WIDTH(DATA_WIDTH)
            ) u_ps_buffer_fifo (
                .clk              (clk),
                .rst_n            (rst_n),
                .data_in          (data_in[lane]),
                .input_valid_i    (input_valid_chain[lane] & ~ia_calc_done),
                .is_init_data_i   (is_init_data_chain[lane]),
                .ia_l1_switch_i   (ia_l1_switch_chain[lane]),
                .send_ia_trigger_i(send_ia_trigger_chain[lane]),
                .data_out         (fifo_data_out[lane]),
                .input_valid_o    (input_valid_chain[lane + 1]),
                .is_init_data_o   (is_init_data_chain[lane + 1]),
                .ia_l1_switch_o   (ia_l1_switch_chain[lane + 1]),
                .send_ia_trigger_o(send_ia_trigger_chain[lane + 1])
            );
        end
    endgenerate

    de_diagonalizer #(
        .SIZE      (SIZE),
        .DATA_WIDTH(DATA_WIDTH)
    ) u_de_diagonalizer (
        .clk             (clk),
        .rst_n           (rst_n),
        .data_in         (data_in),
        .input_valid_i   (ia_calc_done),
        .data_out        (de_diag_data_out),
        .data_valid_o    (de_diag_data_valid),
        .tile_calc_over_o(de_diag_tile_calc_over)
    );

    always_comb begin
        for (int lane_idx = 0; lane_idx < SIZE; lane_idx++) begin
            if (de_diag_data_valid) begin
                data_out[lane_idx] = de_diag_data_out[lane_idx];
            end else begin
                data_out[lane_idx] = fifo_data_out[lane_idx];
            end
        end
    end

    // acc_data_valid and tile_calc_over are owned only by de_diagonalizer.
    assign acc_data_valid = de_diag_data_valid;
    assign tile_calc_over = de_diag_tile_calc_over;
endmodule
