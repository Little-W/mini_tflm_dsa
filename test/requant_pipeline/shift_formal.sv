module shift_formal (
    input logic clk,
    input logic i_en,
    input logic signed [63:0] i_product,
    input logic [6:0] i_amount
);
    logic signed [33:0] actual_quotient;
    logic actual_increment;
    logic signed [63:0] exact_quotient;
    logic [63:0] mask;
    logic [63:0] remainder;
    logic [63:0] half;
    logic signed [33:0] expected_quotient;
    logic expected_increment;
    logic signed [33:0] quotient_pipe [7];
    logic increment_pipe [7];
    logic [6:0] valid_pipe = 7'd0;

    requant_shift_pipeline u_dut (
        .clk(clk),
        .i_en(i_en),
        .i_product(i_product),
        .i_amount(i_amount),
        .o_quotient(actual_quotient),
        .o_increment(actual_increment)
    );

    // 直接使用完整六十四位除数和余数定义最近偶数舍入。
    always_comb begin
        exact_quotient = i_product >>> i_amount[5:0];
        mask = ~(64'hffffffffffffffff << i_amount[5:0]);
        remainder = $unsigned(i_product) & mask;
        half = 64'd1 << (i_amount[5:0] - 6'd1);
        expected_quotient = exact_quotient[33:0];
        expected_increment = (i_amount != 7'd0) && !i_amount[6] &&
            ((remainder > half) || ((remainder == half) && exact_quotient[0]));
        if (i_amount[6]) begin
            expected_quotient = '0;
        end else if (exact_quotient > 64'sd8589934591) begin
            expected_quotient = 34'sh1ffffffff;
        end else if (exact_quotient < -64'sd8589934592) begin
            expected_quotient = 34'sh200000000;
        end
    end

    always_ff @(posedge clk) begin
        if (i_en) begin
            valid_pipe <= {valid_pipe[5:0], 1'b1};
            quotient_pipe[0] <= expected_quotient;
            increment_pipe[0] <= expected_increment;
            for (int stage = 1; stage < 7; stage++) begin
                quotient_pipe[stage] <= quotient_pipe[stage-1];
                increment_pipe[stage] <= increment_pipe[stage-1];
            end
        end
        if (valid_pipe[6]) begin
            assert(actual_quotient == quotient_pipe[6]);
            assert(actual_increment == increment_pipe[6]);
        end
    end
endmodule
