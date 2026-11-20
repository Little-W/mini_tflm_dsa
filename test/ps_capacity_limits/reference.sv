// SPDX-License-Identifier: Apache-2.0
module ps_capacity_reference #(
    parameter int p_max_rows = 1024,
    parameter int p_rows_width = $clog2(p_max_rows + 1),
    parameter int p_frames_width = 5,
    parameter int p_total_banks = 7,
    parameter int p_bank_bytes = 2048,
    parameter int p_tile_shift = 4
) (
    input logic [p_rows_width-1:0] i_frame_rows,
    input logic [p_frames_width-1:0] i_frames,
    input logic [31:0] i_bank_count,
    input logic [31:0] i_frame_slice_tiles,
    input logic i_use_frame_commands,
    output logic o_frames_fit,
    output logic o_admission_fit
);
    localparam int WORD_CAP = 4;
    localparam int CAP_WORDS_W = $clog2(4*p_max_rows+1);
    localparam int RESERVATION_WORDS_MAX = 4*p_max_rows;
    localparam int RESERVATION_BITS = $clog2(RESERVATION_WORDS_MAX+p_total_banks);
    wire [63:0] ps_max_frame_rows = 64'(i_frame_rows);
    wire [63:0] ps_admission_rows = i_use_frame_commands ?
        ((ps_max_frame_rows < (64'(i_frame_slice_tiles) << p_tile_shift)) ?
         ps_max_frame_rows : (64'(i_frame_slice_tiles) << p_tile_shift)) : ps_max_frame_rows;
    wire [63:0] ps_admission_words = ps_admission_rows << 2;
    wire [63:0] raw_bank_words [0:p_total_banks-1];
    wire [63:0] admission_bank_words [0:p_total_banks-1];
    assign raw_bank_words[0] = '0;
    assign admission_bank_words[0] = '0;
    for (genvar count=1;count<p_total_banks;count++) begin : g_count
        if (count==p_total_banks-1 || count==p_total_banks-2 || count==p_total_banks-4) begin : g_legal
            wire [RESERVATION_BITS-1:0] raw_words=RESERVATION_BITS'(ps_max_frame_rows<<2);
            wire [RESERVATION_BITS-1:0] admission_words=RESERVATION_BITS'(ps_admission_words);
            wire [RESERVATION_BITS-1:0] raw_rounded=raw_words+RESERVATION_BITS'(count-1);
            wire [RESERVATION_BITS-1:0] admission_rounded=admission_words+RESERVATION_BITS'(count-1);
            wire [RESERVATION_BITS-1:0] raw_bank_word_count=raw_rounded/RESERVATION_BITS'(count);
            wire [RESERVATION_BITS-1:0] admission_bank_word_count=admission_rounded/RESERVATION_BITS'(count);
            assign raw_bank_words[count]=ps_max_frame_rows>64'(p_max_rows) ?
                {64{1'b1}} : 64'(raw_bank_word_count);
            assign admission_bank_words[count]=ps_admission_words>64'(RESERVATION_WORDS_MAX) ?
                {64{1'b1}} : 64'(admission_bank_word_count);
        end else begin : g_unused
            assign raw_bank_words[count]={64{1'b1}};
            assign admission_bank_words[count]={64{1'b1}};
        end
    end
    wire [63:0] ps_raw_frame_bank_words=raw_bank_words[i_bank_count];
    wire [63:0] ps_admission_bank_words=admission_bank_words[i_bank_count];
    wire [CAP_WORDS_W+p_frames_width-1:0] ps_raw_bank_total=
        CAP_WORDS_W'(ps_raw_frame_bank_words)*i_frames;
    assign o_frames_fit=(i_frames=='0 ||
        (ps_raw_frame_bank_words<=64'(4*p_max_rows) &&
         64'(ps_raw_bank_total)<=64'(p_bank_bytes/16)));
    assign o_admission_fit=(ps_admission_bank_words<=64'(p_bank_bytes/16));
endmodule

module ps_capacity_formal #(
    parameter int p_max_rows = 1024,
    parameter int p_rows_width = $clog2(p_max_rows + 1),
    parameter int p_frames_width = 5,
    parameter int p_total_banks = 7,
    parameter int p_bank_bytes = 2048,
    parameter int p_tile_shift = 4
) (
    input logic [p_rows_width-1:0] i_frame_rows,
    input logic [p_frames_width-1:0] i_frames,
    input logic [31:0] i_bank_count,
    input logic [31:0] i_frame_slice_tiles,
    input logic i_use_frame_commands
);
    logic candidate_frames_fit, candidate_admission_fit;
    logic reference_frames_fit, reference_admission_fit;
    ps_capacity_limits #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),
        .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),
        .p_bank_bytes(p_bank_bytes), .p_tile_shift(p_tile_shift)) u_candidate (
        .i_frame_rows(i_frame_rows), .i_frames(i_frames), .i_bank_count(i_bank_count),
        .i_frame_slice_tiles(i_frame_slice_tiles), .i_use_frame_commands(i_use_frame_commands),
        .o_frames_fit(candidate_frames_fit), .o_admission_fit(candidate_admission_fit)
    );
    ps_capacity_reference #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),
        .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),
        .p_bank_bytes(p_bank_bytes), .p_tile_shift(p_tile_shift)) u_reference (
        .i_frame_rows(i_frame_rows), .i_frames(i_frames), .i_bank_count(i_bank_count),
        .i_frame_slice_tiles(i_frame_slice_tiles), .i_use_frame_commands(i_use_frame_commands),
        .o_frames_fit(reference_frames_fit), .o_admission_fit(reference_admission_fit)
    );
    always_comb begin
        // 原始数组在物理索引范围内定义，包括索引零和预留项。
        if (i_bank_count < 32'(p_total_banks)) begin
            assert(candidate_frames_fit == reference_frames_fit);
            assert(candidate_admission_fit == reference_admission_fit);
        end
        if (i_frames == '0) assert(candidate_frames_fit);
    end
endmodule
