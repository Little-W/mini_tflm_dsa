`ifndef GEMMORA_PS_POOL_BYTES
`define GEMMORA_PS_POOL_BYTES 12288
`endif

module ps_buffer #(
    parameter int unsigned SIZE       = 16,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned FRAME_COUNT = SIZE,
    parameter int unsigned MAX_IA_REUSE = 2,
    parameter int unsigned STORAGE_ROWS = 0,
    parameter int unsigned PS_EXTERNAL_RAM = 0,
    parameter int unsigned PS_POOL_BYTES = `GEMMORA_PS_POOL_BYTES,
    parameter int unsigned PS_BANK_BYTES = 2048,
    parameter int unsigned PS_DIRECTORY_ROWS = FRAME_COUNT * MAX_IA_REUSE * SIZE,
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
    input  logic signed [DATA_WIDTH-1:0] data_in       [0:SIZE-1],
    input  logic                         ia_row_valid,
    input  logic                         ia_calc_done,
    input  logic                         ia_tile_start,
    input  logic                         ia_l1_switch,
    input  logic                         send_ia_trigger,
    input  logic                         ia_is_init_data,
    input  logic                         replay_enable,
    input  logic                         frame_request = 1'b0,
    input  logic [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id = '0,
    input  logic                         frame_accept = 1'b0,
    input  logic [31:0]                  frame_rows = 32'd0,
    input  logic [31:0]                  frame_reserve_rows = 32'd0,
    input  logic [2:0]                   frame_word_cap = 3'd4,
    input  logic                         frame_init = 1'b0,
    input  logic                         frame_final = 1'b0,
    input  logic                         force_raw = 1'b0,
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
    localparam int unsigned MAX_FRAME_LEN = ((MAX_IA_REUSE + 1) * SIZE) - 1;
    // Frames occupy their actual stream length in a circular SRAM. The host
    // admits a group only when its retained frames and one replacement frame
    // fit; the physical capacity is independent of the maximum IA reuse.
    localparam int unsigned DEPTH = STORAGE_ROWS != 0 ? STORAGE_ROWS :
                                   MAX_FRAME_LEN * (FRAME_COUNT + 1);
    localparam int unsigned FIFO_VEC_WIDTH = DATA_WIDTH * SIZE;

    logic signed [DATA_WIDTH-1:0] fifo_data_out    [0:SIZE-1];
    logic signed [DATA_WIDTH-1:0] de_diag_data_out [0:SIZE-1];
    logic [FIFO_VEC_WIDTH-1:0]    fifo_data_in_vec;
    logic [FIFO_VEC_WIDTH-1:0]    fifo_data_out_vec;

    logic                         de_diag_data_valid;
    logic                         replay_row_valid;
    logic                         frame_final_q;
    logic [FIFO_VEC_WIDTH-1:0]     matrix_data_vec;
    logic signed [DATA_WIDTH-1:0]  replay_skew [0:SIZE-1];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) frame_final_q <= 1'b0;
        else if (frame_accept) frame_final_q <= frame_final;
    end
    always_comb begin
        for (int lane_idx = 0; lane_idx < SIZE; lane_idx++)
            matrix_data_vec[lane_idx*DATA_WIDTH +: DATA_WIDTH] = de_diag_data_out[lane_idx];
    end
    logic                         de_diag_tile_calc_over;
    logic                         de_diag_stream_calc_over;

    always_comb begin
        fifo_data_in_vec = '0;
        for (int lane_idx = 0; lane_idx < SIZE; lane_idx++) begin
            fifo_data_in_vec[lane_idx*DATA_WIDTH +: DATA_WIDTH] = data_in[lane_idx];
            fifo_data_out[lane_idx] = fifo_data_out_vec[lane_idx*DATA_WIDTH +: DATA_WIDTH];
        end
    end

`ifdef GEMPACT_PS_COMPRESS
    localparam bit COMPRESS_ENABLED = (SIZE == 16) && (DATA_WIDTH == 32);
`else
    localparam bit COMPRESS_ENABLED = 1'b0;
`endif

    generate if (COMPRESS_ENABLED) begin : g_compressed
        assign replay_ready = frame_ready && !frame_init;
        ps_frame_store #(
            .MAX_FRAME_ROWS(MAX_IA_REUSE * SIZE),
            .FRAME_COUNT(FRAME_COUNT),
            .POOL_BYTES(PS_POOL_BYTES),
            .BANK_BYTES(PS_BANK_BYTES),
            .EXTERNAL_RAM(PS_EXTERNAL_RAM),
            .DIRECTORY_ROWS(PS_DIRECTORY_ROWS),
            .RAM_ADDR_BITS(PS_RAM_ADDR_BITS)
        ) u_store (
            .clk(clk), .rst_n(rst_n),
            .cfg_valid(ps_store_cfg_valid), .cfg_pool_bank_words(ps_pool_bank_words),
            .cfg_pool_bank_count(ps_pool_bank_count),
            .cfg_directory_stride(ps_directory_stride),
            .ram_read_en(ps_ram_read_en), .ram_read_addr(ps_ram_read_addr), .ram_read_data(ps_ram_read_data),
            .ram_write_en(ps_ram_write_en), .ram_write_addr(ps_ram_write_addr), .ram_write_data(ps_ram_write_data),
            .frame_request(frame_request), .frame_accept(frame_accept),
            .frame_id(frame_id), .frame_reserve_rows(frame_reserve_rows),
            .frame_word_cap(frame_word_cap),
            .frame_rows(frame_rows - 32'(SIZE - 1)), .frame_init(frame_init), .frame_final(frame_final),
            .force_raw_i(force_raw),
            .frame_ready(frame_ready), .capacity_fault(capacity_fault),
            .frame_pressure(frame_pressure), .frame_complete(frame_complete),
            .write_valid(de_diag_data_valid && !frame_final_q), .write_data(matrix_data_vec),
            .write_frame_end(de_diag_stream_calc_over), .replay_trigger(send_ia_trigger),
            .replay_data(fifo_data_out_vec), .replay_valid(replay_row_valid)
        );
        for (genvar lane = 0; lane < SIZE; lane++) begin : g_replay_skew
            if (lane == 0) begin : g_first
                assign replay_skew[lane] = replay_row_valid ? fifo_data_out[lane] : '0;
            end else begin : g_delay
                logic signed [DATA_WIDTH-1:0] values [0:lane-1];
                always_ff @(posedge clk) begin
                    values[0] <= replay_row_valid ? fifo_data_out[lane] : '0;
                    for (int stage = 1; stage < lane; stage++) values[stage] <= values[stage-1];
                end
                assign replay_skew[lane] = values[lane-1];
            end
        end
    end else begin : g_raw
    assign ps_ram_read_en = '0;
    assign ps_ram_write_en = '0;
    assign ps_ram_read_addr = '{default:'0};
    assign ps_ram_write_addr = '{default:'0};
    assign ps_ram_write_data = '{default:'0};
    assign replay_row_valid = 1'b0;
    assign replay_skew = '{default:'0};
    assign frame_ready = 1'b1;
    assign frame_pressure = 1'b0;
    assign frame_complete = 1'b0;
    ps_buffer_wide_fifo #(
        .DEPTH      (DEPTH),
        .DATA_WIDTH (FIFO_VEC_WIDTH),
        .FRAME_COUNT(FRAME_COUNT),
        .MAX_FRAME_LEN(MAX_FRAME_LEN)
    ) u_ps_buffer_fifo (
        .clk              (clk),
        .rst_n            (rst_n),
        .data_in          (fifo_data_in_vec),
        .input_valid_i    (ia_row_valid & ~ia_calc_done),
        .ia_l1_switch_i   (ia_l1_switch),
        .send_ia_trigger_i(send_ia_trigger),
        .replay_enable_i  (replay_enable),
        .capacity_fault   (capacity_fault),
        .replay_ready     (replay_ready),
        .data_out         (fifo_data_out_vec)
    );
    end endgenerate

    de_diagonalizer #(
        .SIZE      (SIZE),
        .DATA_WIDTH(DATA_WIDTH)
    ) u_de_diagonalizer (
        .clk             (clk),
        .rst_n           (rst_n),
        .data_in         (data_in),
        .input_valid_i   (COMPRESS_ENABLED ? ia_row_valid : ia_calc_done),
        .burst_start_i   (ia_tile_start),
        .burst_last_i    (ia_l1_switch),
        .data_out        (de_diag_data_out),
        .data_valid_o    (de_diag_data_valid),
        .tile_calc_over_o(de_diag_tile_calc_over),
        .stream_calc_over_o(de_diag_stream_calc_over)
    );

    always_comb begin
        for (int lane_idx = 0; lane_idx < SIZE; lane_idx++) begin
            data_out[lane_idx]     = COMPRESS_ENABLED ? replay_skew[lane_idx] : fifo_data_out[lane_idx];
            acc_data_out[lane_idx] = de_diag_data_out[lane_idx];
        end
    end

    // acc_data_valid and tile_calc_over are owned only by de_diagonalizer.
    assign acc_data_valid = de_diag_data_valid && (!COMPRESS_ENABLED || frame_final_q);
    assign tile_calc_over = de_diag_tile_calc_over && (!COMPRESS_ENABLED || frame_final_q);
    assign stream_calc_over = de_diag_stream_calc_over && (!COMPRESS_ENABLED || frame_final_q);
endmodule

module ps_buffer_wide_fifo #(
    parameter int unsigned DEPTH       = 16,
    parameter int unsigned DATA_WIDTH  = 512,
    parameter int unsigned FRAME_COUNT = 1,
    parameter int unsigned MAX_FRAME_LEN = DEPTH
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic [DATA_WIDTH-1:0] data_in,
    input  logic                  input_valid_i,
    input  logic                  ia_l1_switch_i,
    input  logic                  send_ia_trigger_i,
    input  logic                  replay_enable_i,
    output logic [DATA_WIDTH-1:0] data_out,
    output logic capacity_fault,
    output logic replay_ready
);
    localparam int unsigned ADDR_W      = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
    localparam int unsigned CNT_W       = (DEPTH <= 1) ? 1 : $clog2(DEPTH + 1);
    localparam int unsigned FRAME_IDX_W = (FRAME_COUNT <= 1) ? 1 : $clog2(FRAME_COUNT);
    localparam int unsigned FRAME_CNT_W = (FRAME_COUNT < 1) ? 1 : $clog2(FRAME_COUNT + 1);
    localparam int unsigned FRAME_LEN_W = (MAX_FRAME_LEN <= 1) ? 1 : $clog2(MAX_FRAME_LEN + 1);
    localparam int unsigned EXT_W       = CNT_W + 1;

    localparam logic [ADDR_W-1:0]      DEPTH_LAST_ADDR = ADDR_W'(DEPTH - 1);
    localparam logic [CNT_W-1:0]       DEPTH_COUNT     = CNT_W'(DEPTH);
    localparam logic [FRAME_CNT_W-1:0] FRAME_COUNT_C   = FRAME_CNT_W'(FRAME_COUNT);

    logic [ADDR_W-1:0]      write_ptr;
    logic [ADDR_W-1:0]      read_ptr;
    logic [ADDR_W-1:0]      write_base;
    logic [ADDR_W-1:0]      read_base;
    logic [FRAME_LEN_W-1:0] frame_len;
    logic [FRAME_LEN_W-1:0] frame_len_fifo [FRAME_COUNT];
    logic [FRAME_IDX_W-1:0] frame_wr_ptr;
    logic [FRAME_IDX_W-1:0] frame_rd_ptr;
    logic [FRAME_CNT_W-1:0] frame_count;
    logic [FRAME_LEN_W-1:0] replay_count;
    logic                   ia_l1_switch_i_d;
    logic                   send_ia_trigger_i_d;

    logic                   ram_write_en;
    logic                   ram_read_en;
    logic [ADDR_W-1:0]      ram_write_addr;
    logic [ADDR_W-1:0]      ram_read_addr;
    logic [CNT_W-1:0]       write_ptr_ext;
    logic [FRAME_LEN_W-1:0] frame_len_next;
    logic [FRAME_LEN_W-1:0] replay_frame_len;
    logic [DATA_WIDTH-1:0]  ram_read_data;
    logic                   read_forward_valid;
    logic [DATA_WIDTH-1:0]  read_forward_data;
    logic                   ram_write_en_q;
    logic [ADDR_W-1:0]      ram_write_addr_q;
    logic [DATA_WIDTH-1:0]  ram_write_data_q;
    logic                   replay_data_valid;
    logic [CNT_W:0]         ram_write_addr_ext;
    logic [CNT_W:0]         write_base_next_ext;
    logic [CNT_W:0]         read_base_next_ext;
    logic [ADDR_W-1:0]      write_base_next;
    logic [ADDR_W-1:0]      read_base_next;
    logic [ADDR_W-1:0]      read_ptr_inc;
    logic [FRAME_IDX_W-1:0] frame_wr_ptr_inc;
    logic [FRAME_IDX_W-1:0] frame_rd_ptr_inc;

`ifndef SYNTHESIS
    bit ps_trace_en;

    initial begin
        ps_trace_en = 1'b0;
        if ($test$plusargs("NPU_PS_TRACE")) ps_trace_en = 1'b1;
    end
`else
    localparam bit ps_trace_en = 1'b0;
`endif

    assign replay_ready = (frame_count != '0) && (replay_count == '0);
    assign ram_write_en   = input_valid_i;
    assign ram_read_en    = (replay_count != '0);
    assign ram_read_addr  = read_ptr;
    assign write_ptr_ext  = write_ptr;
    assign frame_len_next = input_valid_i
                          ? FRAME_LEN_W'(write_ptr_ext + CNT_W'(1))
                          : FRAME_LEN_W'(write_ptr_ext);
    assign frame_len      = (frame_count != '0) ? frame_len_fifo[frame_rd_ptr] : '0;
    assign replay_frame_len = (frame_count != '0) ? frame_len : frame_len_next;

    assign ram_write_addr_ext = EXT_W'(write_base) + EXT_W'(write_ptr);
    assign write_base_next_ext = EXT_W'(write_base) + EXT_W'(frame_len_next);
    assign read_base_next_ext = EXT_W'(read_base) + EXT_W'(replay_frame_len);
    assign ram_write_addr = (ram_write_addr_ext >= EXT_W'(DEPTH_COUNT)) ?
                            ADDR_W'(ram_write_addr_ext - EXT_W'(DEPTH_COUNT)) :
                            ADDR_W'(ram_write_addr_ext);
    assign write_base_next = (write_base_next_ext >= EXT_W'(DEPTH_COUNT)) ?
                             ADDR_W'(write_base_next_ext - EXT_W'(DEPTH_COUNT)) :
                             ADDR_W'(write_base_next_ext);
    assign read_base_next = (read_base_next_ext >= EXT_W'(DEPTH_COUNT)) ?
                            ADDR_W'(read_base_next_ext - EXT_W'(DEPTH_COUNT)) :
                            ADDR_W'(read_base_next_ext);
    assign read_ptr_inc = (read_ptr == DEPTH_LAST_ADDR) ? '0 : (read_ptr + 1'b1);
    assign frame_wr_ptr_inc = (FRAME_COUNT <= 1) ? '0 :
                              ((frame_wr_ptr == FRAME_IDX_W'(FRAME_COUNT - 1)) ?
                               '0 : (frame_wr_ptr + 1'b1));
    assign frame_rd_ptr_inc = (FRAME_COUNT <= 1) ? '0 :
                              ((frame_rd_ptr == FRAME_IDX_W'(FRAME_COUNT - 1)) ?
                               '0 : (frame_rd_ptr + 1'b1));

    assign data_out = replay_data_valid ?
        (read_forward_valid ? read_forward_data : ram_read_data) : '0;

    // Forward a synchronous read/write collision from the registered write
    // port, independently of the physical SRAM's collision behavior.
    always_ff @(posedge clk) begin
        if (!rst_n) read_forward_valid <= 1'b0;
        else begin
            read_forward_valid <= ram_read_en && ram_write_en_q &&
                                  ram_read_addr == ram_write_addr_q;
            if (ram_read_en && ram_write_en_q && ram_read_addr == ram_write_addr_q)
                read_forward_data <= ram_write_data_q;
        end
    end

    assign capacity_fault=1'b0;
    ps_buffer_exact_ram #(
        .DEPTH(DEPTH),
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH (ADDR_W)
    ) u_ps_fifo_ram (
        .clk   (clk),
        .ena   (1'b1),
        .enb   (ram_read_en),
        .wea   (ram_write_en_q),
        .addra (ram_write_addr_q),
        .dia   (ram_write_data_q),
        .addrb (ram_read_addr),
        .dob   (ram_read_data)
    );

    always_ff @(posedge clk) begin
        ram_write_addr_q <= ram_write_addr;
        ram_write_data_q <= data_in;
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            ram_write_en_q      <= 1'b0;
            write_ptr           <= '0;
            read_ptr            <= '0;
            write_base          <= '0;
            read_base           <= '0;
            frame_wr_ptr        <= '0;
            frame_rd_ptr        <= '0;
            frame_count         <= '0;
            replay_count        <= '0;
            ia_l1_switch_i_d    <= 1'b0;
            send_ia_trigger_i_d <= 1'b0;
            replay_data_valid   <= 1'b0;
            for (int frame_i = 0; frame_i < FRAME_COUNT; frame_i++) begin
                frame_len_fifo[frame_i] <= '0;
            end
        end else begin
            logic push_frame;
            logic pop_frame;

            push_frame = ia_l1_switch_i && !ia_l1_switch_i_d && (frame_len_next != '0);
            pop_frame  = send_ia_trigger_i && !send_ia_trigger_i_d &&
                         replay_enable_i && ((frame_count != '0) || push_frame) &&
                         (replay_count == '0);

            ia_l1_switch_i_d    <= ia_l1_switch_i;
            send_ia_trigger_i_d <= send_ia_trigger_i;
            replay_data_valid   <= ram_read_en;
            ram_write_en_q      <= ram_write_en;

            if (input_valid_i) begin
                write_ptr <= write_ptr + 1'b1;
            end

            if (ia_l1_switch_i && !ia_l1_switch_i_d) begin
                if (frame_len_next != '0) begin
                    frame_len_fifo[frame_wr_ptr] <= frame_len_next;
                    frame_wr_ptr <= frame_wr_ptr_inc;
                    write_base   <= write_base_next;
                    if (ps_trace_en) begin
                        $display("[PS_TRACE] time=%0t push frame_len=%0d frame_count=%0d write_base=%0d",
                                 $time, frame_len_next, frame_count, write_base);
                    end
                end
                write_ptr    <= '0;
            end

            if (send_ia_trigger_i && !send_ia_trigger_i_d) begin
                if (pop_frame) begin
                    read_ptr     <= read_base;
                    read_base    <= read_base_next;
                    replay_count <= replay_frame_len;
                    frame_rd_ptr <= frame_rd_ptr_inc;
                    if (ps_trace_en) begin
                        $display("[PS_TRACE] time=%0t pop frame_len=%0d frame_count=%0d read_base=%0d",
                                 $time, replay_frame_len, frame_count, read_base);
                    end
                end else if (ps_trace_en && (replay_count != '0)) begin
                    $display("[PS_TRACE] time=%0t ignore trigger replay_count=%0d frame_count=%0d",
                             $time, replay_count, frame_count);
                end
            end

            if (!pop_frame && (replay_count != '0)) begin
                if (replay_count == 1) begin
                    replay_count <= '0;
                end else begin
                    replay_count <= replay_count - 1'b1;
                    read_ptr     <= read_ptr_inc;
                end
            end

            if (push_frame && !pop_frame) begin
                if (frame_count < FRAME_COUNT_C) begin
                    frame_count <= frame_count + 1'b1;
                end
            end else if (!push_frame && pop_frame) begin
                frame_count <= frame_count - 1'b1;
            end
        end
    end
endmodule

// Exact-depth synchronous 1R1W SRAM. Ring addresses already wrap at DEPTH.
module ps_buffer_exact_ram #(
    parameter int DEPTH=16, DATA_WIDTH=512, ADDR_WIDTH=$clog2(DEPTH)
)(input logic clk, ena, enb, wea,
  input logic [ADDR_WIDTH-1:0] addra, addrb,
  input logic [DATA_WIDTH-1:0] dia,
  output logic [DATA_WIDTH-1:0] dob);
`ifdef ASIC_SRAM
  smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)) u_sram (
    .clk(clk), .write_enable(ena && wea), .write_address(addra), .write_data(dia),
    .write_mask({DATA_WIDTH{1'b1}}), .read_enable(enb), .read_address(addrb), .read_data(dob));
`else
  (* ram_style="block" *) logic [DATA_WIDTH-1:0] ram [DEPTH];
  always_ff @(posedge clk) begin
    if (ena && wea) ram[addra] <= dia;
    if (enb) dob <= ram[addrb];
  end
`endif

endmodule
