`ifndef GEMMORA_PS_POOL_BYTES
`define GEMMORA_PS_POOL_BYTES 12288
`endif
`default_nettype none

module ps_buffer #(
    parameter int unsigned SIZE       = 16,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned FRAME_COUNT = SIZE,
    parameter int unsigned MAX_IA_REUSE = 2,
    parameter int unsigned STORAGE_ROWS = 0,
    parameter int unsigned PS_EXTERNAL_RAM = 0,
    parameter bit p_fixed_ps_channels = 1'b0,
    parameter int unsigned PS_POOL_BYTES = `GEMMORA_PS_POOL_BYTES,
    parameter int unsigned PS_BANK_BYTES = 2048,
    parameter int unsigned PS_DIRECTORY_ROWS = FRAME_COUNT * MAX_IA_REUSE * SIZE,
    parameter int unsigned PS_RAM_ADDR_BITS = PS_EXTERNAL_RAM!=0 ? $clog2(PS_POOL_BYTES/16) :
        ($clog2(PS_POOL_BYTES/64)>0 ? $clog2(PS_POOL_BYTES/64) : 1)
) (
    input  wire logic                         clk,
    input  wire logic                         rst_n,
    input  wire logic                         ps_store_cfg_valid = 1'b0,
    input  wire logic [31:0]                  ps_pool_bank_words = PS_EXTERNAL_RAM!=0 ? PS_BANK_BYTES/16 : PS_POOL_BYTES/64,
    input  wire logic [31:0]                  ps_pool_bank_count = PS_EXTERNAL_RAM!=0 ? PS_POOL_BYTES/PS_BANK_BYTES : 4,
    input  wire logic [31:0]                  ps_directory_stride = MAX_IA_REUSE*SIZE,
    output wire [3:0]                    ps_ram_read_en,
    output wire [PS_RAM_ADDR_BITS-1:0]    ps_ram_read_addr [0:3],
    input  wire [127:0]                  ps_ram_read_data [0:3] = '{default:'0},
    output wire [3:0]                    ps_ram_write_en,
    output wire [PS_RAM_ADDR_BITS-1:0]    ps_ram_write_addr [0:3],
    output wire [127:0]                  ps_ram_write_data [0:3],
    input  wire logic signed [DATA_WIDTH-1:0] data_in       [0:SIZE-1],
    input  wire logic                         ia_row_valid,
    input  wire logic                         ia_calc_done,
    input  wire logic                         ia_tile_start,
    input  wire logic                         ia_l1_switch,
    input  wire logic                         send_ia_trigger,
    input  wire logic                         ia_is_init_data,
    input  wire logic                         replay_enable,
    input  wire logic                         direct_final_stream = 1'b0,
    input  wire logic                         frame_request = 1'b0,
    input  wire logic [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id = '0,
    input  wire logic                         frame_accept = 1'b0,
    input  wire logic [31:0]                  frame_rows = 32'd0,
    input  wire logic [31:0]                  frame_reserve_rows = 32'd0,
    input  wire logic [2:0]                   frame_word_cap = 3'd4,
    input  wire logic                         frame_init = 1'b0,
    input  wire logic                         frame_final = 1'b0,
    input  wire logic                         force_raw = 1'b0,
    output logic                         frame_ready,
    output logic                         frame_pressure,
    output logic                         frame_complete,
    output logic signed [DATA_WIDTH-1:0] data_out      [0:SIZE-1],
    output logic signed [DATA_WIDTH-1:0] acc_data_out  [0:SIZE-1],
    output logic                         acc_data_valid,
    output logic                         tile_calc_over,
    output logic                         stream_calc_over,
    output logic                         capacity_fault,
    output logic                         replay_ready
);
    localparam int unsigned MAX_FRAME_LEN = MAX_IA_REUSE * SIZE;
    localparam int unsigned DEPTH = STORAGE_ROWS != 0 ? STORAGE_ROWS :
                                   MAX_FRAME_LEN * (FRAME_COUNT + 1);
    localparam int unsigned FIFO_VEC_WIDTH = DATA_WIDTH * SIZE;
    localparam int unsigned ROW_COUNT_WIDTH = SIZE > 1 ? $clog2(SIZE) : 1;

    logic [FIFO_VEC_WIDTH-1:0] matrix_data_vec, replay_data_vec;
    logic replay_row_valid, frame_final_q;
    logic [ROW_COUNT_WIDTH-1:0] output_row;
    wire row_tile_end = ia_row_valid &&
        (output_row == ROW_COUNT_WIDTH'(SIZE-1) || ia_l1_switch);

    // DiP outputs one complete matrix row per valid cycle. PS RAM stores
    // that same row representation and supplies it directly to the array.
    always_comb begin
        for (int lane=0; lane<SIZE; lane++) begin
            matrix_data_vec[lane*DATA_WIDTH +: DATA_WIDTH] = data_in[lane];
            acc_data_out[lane] = data_in[lane];
            data_out[lane] = replay_data_vec[lane*DATA_WIDTH +: DATA_WIDTH];
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            frame_final_q <= 1'b0;
            output_row <= '0;
        end else begin
            if (frame_accept) frame_final_q <= frame_final;
            if (ia_row_valid)
                output_row <= row_tile_end ? '0 : output_row + ROW_COUNT_WIDTH'(1);
        end
    end

`ifdef GEMPACT_PS_COMPRESS
    localparam bit COMPRESS_ENABLED = (SIZE == 16) && (DATA_WIDTH == 32);
`else
    localparam bit COMPRESS_ENABLED = 1'b0;
`endif

    generate if (COMPRESS_ENABLED) begin : g_compressed
        wire store_ready, store_complete;
        wire [FIFO_VEC_WIDTH-1:0] store_replay_data;
        assign frame_ready = direct_final_stream || store_ready;
        assign frame_complete = direct_final_stream ? stream_calc_over : store_complete;
        assign replay_ready = !direct_final_stream && store_ready && !frame_init;
        assign replay_data_vec = direct_final_stream ? '0 : store_replay_data;
        ps_frame_store #(
            .MAX_FRAME_ROWS(MAX_IA_REUSE * SIZE),
            .FRAME_COUNT(FRAME_COUNT),
            .POOL_BYTES(PS_POOL_BYTES),
            .BANK_BYTES(PS_BANK_BYTES),
            .EXTERNAL_RAM(PS_EXTERNAL_RAM),
            .p_fixed_ps_channels(p_fixed_ps_channels),
            .DIRECTORY_ROWS(PS_DIRECTORY_ROWS),
            .RAM_ADDR_BITS(PS_RAM_ADDR_BITS)
        ) u_store (
            .clk(clk), .rst_n(rst_n),
            .cfg_valid(ps_store_cfg_valid), .cfg_pool_bank_words(ps_pool_bank_words),
            .cfg_pool_bank_count(ps_pool_bank_count),
            .cfg_directory_stride(ps_directory_stride),
            .ram_read_en(ps_ram_read_en), .ram_read_addr(ps_ram_read_addr),
            .ram_read_data(ps_ram_read_data), .ram_write_en(ps_ram_write_en),
            .ram_write_addr(ps_ram_write_addr), .ram_write_data(ps_ram_write_data),
            .frame_request(frame_request && !direct_final_stream),
            .frame_accept(frame_accept && !direct_final_stream),
            .frame_id(frame_id), .frame_reserve_rows(frame_reserve_rows),
            .frame_word_cap(frame_word_cap), .frame_rows(frame_rows),
            .frame_init(frame_init), .frame_final(frame_final), .force_raw_i(force_raw),
            .frame_ready(store_ready), .capacity_fault(capacity_fault),
            .frame_pressure(frame_pressure), .frame_complete(store_complete),
            .write_valid(ia_row_valid && !frame_final_q && !direct_final_stream), .write_data(matrix_data_vec),
            .write_frame_end(ia_l1_switch && !direct_final_stream),
            .replay_trigger(send_ia_trigger && !direct_final_stream),
            .replay_data(store_replay_data), .replay_valid(replay_row_valid)
        );
    end else begin : g_raw
        assign ps_ram_read_en = '0;
        assign ps_ram_write_en = '0;
        assign ps_ram_read_addr = '{default:'0};
        assign ps_ram_write_addr = '{default:'0};
        assign ps_ram_write_data = '{default:'0};
        assign replay_row_valid = 1'b0;
        assign frame_ready = 1'b1;
        assign frame_pressure = 1'b0;
        assign frame_complete = direct_final_stream && stream_calc_over;
        ps_buffer_wide_fifo #(
            .DEPTH(DEPTH), .DATA_WIDTH(FIFO_VEC_WIDTH),
            .FRAME_COUNT(FRAME_COUNT), .MAX_FRAME_LEN(MAX_FRAME_LEN)
        ) u_ps_buffer_fifo (
            .clk(clk), .rst_n(rst_n), .data_in(matrix_data_vec),
            .input_valid_i(ia_row_valid && !ia_calc_done),
            .ia_l1_switch_i(ia_l1_switch && !direct_final_stream),
            .send_ia_trigger_i(send_ia_trigger && !direct_final_stream),
            .replay_enable_i(replay_enable), .capacity_fault(capacity_fault),
            .replay_ready(replay_ready), .data_out(replay_data_vec)
        );
    end endgenerate

    assign acc_data_valid = ia_row_valid && ia_calc_done;
    assign tile_calc_over = row_tile_end && ia_calc_done;
    assign stream_calc_over = ia_l1_switch && ia_calc_done;
`ifdef NPU_SIM_ASSERT
    initial forever @(posedge clk) if (rst_n && direct_final_stream) begin
        if (frame_accept) assert (frame_init && frame_final)
            else $fatal(1, "Direct output requires a single reduction tile");
        if (ia_row_valid) assert (ia_is_init_data && ia_calc_done)
            else $fatal(1, "Direct output rows must have no partial-sum dependency");
    end
`endif
endmodule

`default_nettype wire
