`ifndef GEMMORA_PS_POOL_BYTES
`define GEMMORA_PS_POOL_BYTES 12288
`endif

module compute_core #(
    parameter int unsigned SIZE       = 16,
    parameter int unsigned DATA_WIDTH = 16,
    parameter int unsigned WEIGHT_WIDTH = 16,
    parameter int unsigned PS_FRAME_COUNT = SIZE,
    parameter int unsigned MAX_IA_REUSE = 2,
    parameter int unsigned PS_STORAGE_ROWS = 0,
    parameter int unsigned PS_EXTERNAL_RAM = 0,
    parameter int unsigned PS_POOL_BYTES = `GEMMORA_PS_POOL_BYTES,
    parameter int unsigned PS_BANK_BYTES = 2048,
    parameter int unsigned PS_DIRECTORY_ROWS = PS_FRAME_COUNT * MAX_IA_REUSE * SIZE,
    parameter int unsigned PS_RAM_ADDR_BITS = PS_EXTERNAL_RAM!=0 ? $clog2(PS_POOL_BYTES/16) :
        ($clog2(PS_POOL_BYTES/64)>0 ? $clog2(PS_POOL_BYTES/64) : 1)
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         ps_store_cfg_valid = 1'b0,
    input  logic [31:0]                  ps_pool_bank_words = PS_EXTERNAL_RAM!=0 ? PS_BANK_BYTES/16 : PS_POOL_BYTES/64,
    input  logic [31:0]                  ps_pool_bank_count = PS_EXTERNAL_RAM!=0 ? PS_POOL_BYTES/PS_BANK_BYTES : 4,
    input  logic [31:0]                  ps_directory_stride = MAX_IA_REUSE*SIZE,
    output wire [3:0]                    ps_ram_read_en,
    output wire [PS_RAM_ADDR_BITS-1:0]    ps_ram_read_addr [0:3],
    input  wire [127:0]                  ps_ram_read_data [0:3] = '{default:'0},
    output wire [3:0]                    ps_ram_write_en,
    output wire [PS_RAM_ADDR_BITS-1:0]    ps_ram_write_addr [0:3],
    output wire [127:0]                  ps_ram_write_data [0:3],

    input  logic                         weight_commit,
    input  logic                         store_weight_req,
    input  logic signed [WEIGHT_WIDTH-1:0] weight_in [SIZE],
    input  logic signed [DATA_WIDTH-1:0] ia_vec_in   [SIZE],
    input  logic                         ia_row_valid,
    input  logic                         final_output_overlap = 1'b0,
    input  logic [$clog2(SIZE):0]         active_columns = ($clog2(SIZE)+1)'(SIZE),
    input  logic                         ia_tile_start,
    input  logic                         ia_calc_done,
    input  logic                         ia_is_init_data,
    input  logic                         ia_l1_switch,
    input  logic                         ia_sending_done,
    input  logic                         send_ia_trigger,
    input  logic                         ps_frame_request = 1'b0,
    input  logic [((PS_FRAME_COUNT > 1) ? $clog2(PS_FRAME_COUNT) : 1)-1:0] ps_frame_id = '0,
    input  logic [31:0]                  ps_frame_rows = 32'd0,
    input  logic [31:0]                  ps_frame_reserve_rows = 32'd0,
    input  logic [2:0]                   ps_frame_word_cap = 3'd4,
    input  logic                         ps_frame_init = 1'b0,
    input  logic                         ps_frame_final = 1'b0,
    input  logic                         ps_force_raw = 1'b0,
    output logic                         ps_frame_ready,
    output logic                         ps_frame_pressure,
    output logic                         ps_frame_complete,
    input  logic                         bias_sleep,
    input  logic signed [31:0]           bias_in     [SIZE],

    output logic signed [31:0]           acc_data_out[SIZE],
    output logic                         acc_data_valid,
    output logic                         partial_sum_calc_over,
    output logic                         partial_sum_advance_ready,
    output logic                         tile_calc_over,
    output logic                         ps_capacity_fault
);

    logic signed [31:0] bias_or_ps_sum [0:SIZE-1];
    logic signed [31:0] systolic_sum [0:SIZE-1];
    logic signed [31:0] ps_data_out [0:SIZE-1];
    logic signed [31:0] ps_acc_out [0:SIZE-1];
    logic ps_acc_data_valid, ps_tile_calc_over, ps_stream_calc_over;
    logic ps_replay_ready;
    logic [SIZE-1:0] row_valid_pipe, row_final_pipe, row_init_pipe, row_last_pipe;
    logic final_group_complete_q;

    // A PE registers the input and the incoming sum in the same cycle.
    // After SIZE such stages, all output columns belong to one matrix row.
    // Metadata follows the same stages and never creates padding rows.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row_valid_pipe <= '0;
            row_final_pipe <= '0;
            row_init_pipe <= '0;
            row_last_pipe <= '0;
            final_group_complete_q <= 1'b0;
        end else begin
            final_group_complete_q <= row_last_pipe[SIZE-1] &&
                row_final_pipe[SIZE-1] && !final_output_overlap;
            row_valid_pipe[0] <= ia_row_valid;
            row_final_pipe[0] <= ia_row_valid && ia_calc_done;
            row_init_pipe[0] <= ia_row_valid && ia_is_init_data;
            row_last_pipe[0] <= ia_row_valid && ia_sending_done;
            for (int stage=1; stage<SIZE; stage++) begin
                row_valid_pipe[stage] <= row_valid_pipe[stage-1];
                row_final_pipe[stage] <= row_final_pipe[stage-1];
                row_init_pipe[stage] <= row_init_pipe[stage-1];
                row_last_pipe[stage] <= row_last_pipe[stage-1];
            end
        end
    end

    wire ps_stream_valid_d = row_valid_pipe[SIZE-1];
    wire ps_calc_done_d = row_final_pipe[SIZE-1];
    wire ps_is_init_data_d = row_init_pipe[SIZE-1];
    wire ps_group_switch_d = row_last_pipe[SIZE-1];
    localparam int unsigned PS_EFFECTIVE_FRAME_COUNT =
        (PS_FRAME_COUNT < 1) ? MAX_IA_REUSE : PS_FRAME_COUNT;

    bias_mux #(.SIZE(SIZE), .DATA_WIDTH(32)) u_bias_mux (
        .bias_sleep(bias_sleep), .bias_in(bias_in), .ps_in(ps_data_out),
        .sum_in(bias_or_ps_sum)
    );

    ws_systolic_array #(
        .SIZE(SIZE), .DATA_IN_WIDTH(DATA_WIDTH), .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .ACC_WIDTH(32)
    ) u_systolic_array (
        .clk(clk), .store_weight_req(store_weight_req), .weight_commit(weight_commit),
        .weight_in(weight_in), .data_in(ia_vec_in), .sum_in(bias_or_ps_sum),
        .sum_out(systolic_sum)
    );

    ps_buffer #(
        .SIZE      (SIZE),
        .DATA_WIDTH(32),
        .FRAME_COUNT(PS_EFFECTIVE_FRAME_COUNT),
        .MAX_IA_REUSE(MAX_IA_REUSE),
        .STORAGE_ROWS(PS_STORAGE_ROWS),
        .PS_EXTERNAL_RAM(PS_EXTERNAL_RAM),
        .PS_POOL_BYTES(PS_POOL_BYTES),
        .PS_BANK_BYTES(PS_BANK_BYTES),
        .PS_DIRECTORY_ROWS(PS_DIRECTORY_ROWS),
        .PS_RAM_ADDR_BITS(PS_RAM_ADDR_BITS)
    ) u_ps_buffer (
        .clk(clk), .rst_n(rst_n),
        .ps_store_cfg_valid(ps_store_cfg_valid), .ps_pool_bank_words(ps_pool_bank_words),
        .ps_pool_bank_count(ps_pool_bank_count), .ps_directory_stride(ps_directory_stride),
        .ps_ram_read_en(ps_ram_read_en), .ps_ram_read_addr(ps_ram_read_addr),
        .ps_ram_read_data(ps_ram_read_data), .ps_ram_write_en(ps_ram_write_en),
        .ps_ram_write_addr(ps_ram_write_addr), .ps_ram_write_data(ps_ram_write_data),
        .capacity_fault(ps_capacity_fault), .replay_ready(ps_replay_ready),
        .frame_request(ps_frame_request),
        .frame_id(ps_frame_id), .frame_accept(send_ia_trigger),
        .frame_rows(ps_frame_rows), .frame_reserve_rows(ps_frame_reserve_rows),
        .frame_word_cap(ps_frame_word_cap), .frame_init(ps_frame_init),
        .frame_final(ps_frame_final), .force_raw(ps_force_raw),
        .frame_ready(ps_frame_ready), .frame_pressure(ps_frame_pressure),
        .frame_complete(ps_frame_complete),
        .data_in(systolic_sum), .ia_row_valid(ps_stream_valid_d),
        .ia_calc_done(ps_calc_done_d), .ia_tile_start(1'b0),
        .ia_l1_switch(ps_group_switch_d), .send_ia_trigger(ia_tile_start),
        .ia_is_init_data(ps_is_init_data_d), .replay_enable(bias_sleep),
        .data_out(ps_data_out), .acc_data_out(ps_acc_out),
        .acc_data_valid(ps_acc_data_valid), .tile_calc_over(ps_tile_calc_over),
        .stream_calc_over(ps_stream_calc_over)
    );

    assign acc_data_valid = ps_acc_data_valid;
    // Parameter groups advance when their final output row is accepted.
    // The following cycle observes their updated bias and quantization readiness.
    assign partial_sum_calc_over = final_group_complete_q ||
        (ps_group_switch_d && (!ps_calc_done_d || final_output_overlap));
    // Complete-row IA reads start with the registered weight commit, so
    // the first input reaches the PEs after their new weights are active.
    assign partial_sum_advance_ready = 1'b0;
    assign tile_calc_over = ps_tile_calc_over;
    assign acc_data_out = ps_acc_out;

`ifndef SYNTHESIS
    always_ff @(posedge clk) if (rst_n) begin
        assert (!ia_sending_done || ia_row_valid)
            else $fatal(1, "DiP stream completion requires a valid input row");
        assert (!weight_commit || !(|row_valid_pipe))
            else $fatal(1, "DiP weight commit overlaps active computation");
    end
`endif
endmodule
