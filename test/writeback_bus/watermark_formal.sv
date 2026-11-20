module fifo_watermark_formal #(
    parameter int p_banks = 16,
    parameter int p_count_width = (p_banks <= 1) ? 1 : $clog2(p_banks + 1)
) (
    input logic [31:0] reserve_banks,
    input logic [p_count_width-1:0] ready_banks,
    input logic partial_write,
    output logic equivalent
);
    logic actual, expected;
    logic [p_count_width-1:0] reserve_count, used_count, free_count;
    fifo_bank_watermark #(.p_banks(p_banks), .p_count_width(p_count_width)) dut (
        .i_reserve(reserve_banks), .i_ready_banks(ready_banks),
        .i_partial_write(partial_write), .o_full(actual)
    );
    assign reserve_count = reserve_banks == 0 ? p_count_width'(1) :
        (reserve_banks >= 32'(p_banks) ? p_count_width'(p_banks) : p_count_width'(reserve_banks));
    assign used_count = ready_banks + (partial_write ? p_count_width'(1) : p_count_width'(0));
    assign free_count = used_count >= p_count_width'(p_banks) ? '0 : (p_count_width'(p_banks) - used_count);
    assign expected = free_count < reserve_count;
    assign equivalent = actual == expected;
endmodule
