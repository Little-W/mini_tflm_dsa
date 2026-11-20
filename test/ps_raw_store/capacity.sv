module ps_frame_capacity_reference #(
    parameter int INITIAL_W = 14,
    parameter int WORDS_W = 10,
    parameter int BANKS_W = 4
) (
    input logic [INITIAL_W-1:0] initial_row,
    input logic [31:0] frame_rows, reserve_rows,
    input logic [WORDS_W-1:0] bank_words,
    input logic [BANKS_W-1:0] bank_count,
    output logic fits
);
    logic [63:0] reserve;
    assign reserve = reserve_rows > frame_rows ? 64'(reserve_rows) : 64'(frame_rows);
    assign fits = (64'(initial_row) << 2) + (reserve << 2) <=
                  64'(bank_words) * 64'(bank_count);
endmodule

module ps_frame_capacity_formal #(
    parameter int INITIAL_W = 14,
    parameter int WORDS_W = 10,
    parameter int BANKS_W = 4
) (
    input logic [INITIAL_W-1:0] initial_row,
    input logic [31:0] frame_rows, reserve_rows,
    input logic [WORDS_W-1:0] bank_words,
    input logic [BANKS_W-1:0] bank_count,
    output logic equivalent
);
    logic reference_fits, actual_fits;
    ps_frame_capacity_reference #(
        .INITIAL_W(INITIAL_W), .WORDS_W(WORDS_W), .BANKS_W(BANKS_W)
    ) reference (
        .initial_row(initial_row), .frame_rows(frame_rows), .reserve_rows(reserve_rows),
        .bank_words(bank_words), .bank_count(bank_count), .fits(reference_fits)
    );
    ps_frame_store_capacity #(
        .p_initial_row_width(INITIAL_W), .p_bank_words_width(WORDS_W), .p_bank_count_width(BANKS_W)
    ) actual (
        .i_initial_row(initial_row), .i_frame_rows(frame_rows), .i_reserve_rows(reserve_rows),
        .i_bank_words(bank_words), .i_bank_count(bank_count), .o_rows_fit(actual_fits)
    );
    assign equivalent = reference_fits == actual_fits;
endmodule

module ps_frame_capacity_measure #(
    parameter int REFERENCE = 0,
    parameter int INITIAL_W = 14,
    parameter int WORDS_W = 10,
    parameter int BANKS_W = 4
) (
    input logic clk,
    input logic [INITIAL_W-1:0] initial_row,
    input logic [31:0] frame_rows, reserve_rows,
    input logic [WORDS_W-1:0] bank_words,
    input logic [BANKS_W-1:0] bank_count,
    output logic fits
);
    logic [INITIAL_W-1:0] initial_row_q;
    logic [31:0] frame_rows_q, reserve_rows_q;
    logic [WORDS_W-1:0] bank_words_q;
    logic [BANKS_W-1:0] bank_count_q;
    logic result;
    always_ff @(posedge clk) begin
        initial_row_q <= initial_row;
        frame_rows_q <= frame_rows;
        reserve_rows_q <= reserve_rows;
        bank_words_q <= bank_words;
        bank_count_q <= bank_count;
        fits <= result;
    end
    if (REFERENCE) begin : g_reference
        ps_frame_capacity_reference #(
            .INITIAL_W(INITIAL_W), .WORDS_W(WORDS_W), .BANKS_W(BANKS_W)
        ) dut (
            .initial_row(initial_row_q), .frame_rows(frame_rows_q), .reserve_rows(reserve_rows_q),
            .bank_words(bank_words_q), .bank_count(bank_count_q), .fits(result)
        );
    end else begin : g_current
        ps_frame_store_capacity #(
            .p_initial_row_width(INITIAL_W), .p_bank_words_width(WORDS_W), .p_bank_count_width(BANKS_W)
        ) dut (
            .i_initial_row(initial_row_q), .i_frame_rows(frame_rows_q), .i_reserve_rows(reserve_rows_q),
            .i_bank_words(bank_words_q), .i_bank_count(bank_count_q), .o_rows_fit(result)
        );
    end
endmodule
