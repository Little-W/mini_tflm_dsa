module compute_core_test #(
    parameter int unsigned SIZE       = 4,
    parameter int unsigned DATA_WIDTH = 16
) (
    input  logic                         clk,
    input  logic                         rst_n,

    input  logic                         store_weight_req,
    input  logic signed [7:0]            weight_in   [SIZE],

    // ia_vec_in must be driven in diagonalized / stair-stepped order by the
    // upstream data setup stage or by the testbench.
    input  logic signed [DATA_WIDTH-1:0] ia_vec_in   [SIZE],

    // External control timing contract:
    // 1. ia_row_valid follows the last row of the diagonalized IA input.
    //    For a SIZE x SIZE tile, it stays high for SIZE cycles.
    // 2. ia_is_init_data is asserted with ia_row_valid only for the first tile.
    // 3. ia_calc_done is asserted with ia_row_valid only for the final tile.
    // 4. ia_l1_switch pulses once after each tile input completes.
    // 5. send_ia_trigger is asserted one cycle before the next stair-stepped IA input.
    input  logic                         ia_row_valid,
    input  logic                         ia_calc_done,
    input  logic                         ia_is_init_data,
    input  logic                         ia_l1_switch,
    input  logic                         send_ia_trigger,

    // bias_sleep = 0: select bias_in as initial sum.
    // bias_sleep = 1: select ps_buffer replay output as previous partial sum.
    input  logic                         bias_sleep,
    input  logic signed [31:0]           bias_in     [SIZE],

    output logic signed [31:0]           acc_data_out[SIZE],
    output logic                         acc_data_valid,
    output logic                         tile_calc_over
);
    logic signed [31:0] bias_or_ps_sum [0:SIZE-1];
    logic signed [31:0] systolic_sum   [0:SIZE-1];
    logic signed [31:0] ps_data_out    [0:SIZE-1];
    logic               ps_acc_data_valid;
    logic               ps_tile_calc_over;

    localparam int unsigned PS_BURST_CYCLES = (2 * SIZE) - 1;
    localparam int unsigned PS_CNT_W        = (PS_BURST_CYCLES < 2) ? 1 :
                                               $clog2(PS_BURST_CYCLES + 1);

    logic [PS_CNT_W-1:0] ps_burst_cnt;
    logic                ia_row_valid_d;
    logic                ps_burst_is_final;
    logic                ps_burst_is_init;

    logic                ps_burst_start;
    logic                ps_stream_valid;
    logic                ps_calc_done;
    logic                ps_is_init_data;
    logic                ps_l1_switch;

    assign ps_burst_start = ia_row_valid & ~ia_row_valid_d;

    // Convert the external SIZE-cycle row-valid window into the internal
    // full diagonal partial-sum window required by ps_buffer:
    //     2*SIZE-1 cycles: step0 ... step(2*SIZE-2)
    // The external ia_l1_switch is accepted as a tile-level marker, but the
    // ps_buffer write pointer is reset by ps_l1_switch on the final internal
    // partial-sum write cycle, so that the RAM frame length includes the
    // complete diagonal stream.
    assign ps_stream_valid = ps_burst_start | (ps_burst_cnt != '0);
    assign ps_calc_done    = ps_stream_valid & (ps_burst_start ? ia_calc_done    : ps_burst_is_final);
    assign ps_is_init_data = ps_stream_valid & (ps_burst_start ? ia_is_init_data : ps_burst_is_init);
    assign ps_l1_switch    = ps_stream_valid & ~ps_burst_start & (ps_burst_cnt == PS_CNT_W'(1));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ia_row_valid_d   <= 1'b0;
            ps_burst_cnt     <= '0;
            ps_burst_is_final<= 1'b0;
            ps_burst_is_init <= 1'b0;
        end else begin
            ia_row_valid_d <= ia_row_valid;

            if (ps_burst_start) begin
                ps_burst_cnt      <= PS_CNT_W'(PS_BURST_CYCLES - 1);
                ps_burst_is_final <= ia_calc_done;
                ps_burst_is_init  <= ia_is_init_data;
            end else if (ps_burst_cnt != '0) begin
                ps_burst_cnt <= ps_burst_cnt - 1'b1;
            end else begin
                ps_burst_is_final <= 1'b0;
                ps_burst_is_init  <= 1'b0;
            end
        end
    end

    genvar idx;
    generate
        for (idx = 0; idx < SIZE; idx++) begin : gen_acc_data_out
            assign acc_data_out[idx] = ps_data_out[idx];
        end
    endgenerate

    bias_mux #(
        .SIZE      (SIZE),
        .DATA_WIDTH(32)
    ) u_bias_mux (
        .bias_sleep(bias_sleep),
        .bias_in   (bias_in),
        .ps_in     (ps_data_out),
        .sum_in    (bias_or_ps_sum)
    );

    ws_systolic_array #(
        .SIZE(SIZE)
    ) u_systolic_array (
        .clk             (clk),
        .store_weight_req(store_weight_req),
        .weight_in       (weight_in),
        .data_in         (ia_vec_in),
        .sum_in          (bias_or_ps_sum),
        .sum_out         (systolic_sum)
    );

    ps_buffer #(
        .SIZE      (SIZE),
        .DATA_WIDTH(32)
    ) u_ps_buffer (
        .clk            (clk),
        .rst_n          (rst_n),
        .data_in        (systolic_sum),
        .ia_row_valid   (ps_stream_valid),
        .ia_calc_done   (ps_calc_done),
        .ia_l1_switch   (ps_l1_switch),
        .send_ia_trigger(send_ia_trigger),
        .ia_is_init_data(ps_is_init_data),
        .data_out       (ps_data_out),
        .acc_data_valid (ps_acc_data_valid),
        .tile_calc_over (ps_tile_calc_over)
    );

    assign acc_data_valid = ps_acc_data_valid;
    assign tile_calc_over = ps_tile_calc_over;
endmodule
