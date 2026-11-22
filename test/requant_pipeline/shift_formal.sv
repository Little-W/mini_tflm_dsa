// SPDX-License-Identifier: Apache-2.0
// 独立整数移位模型检查两级数据路径与任意使能暂停。
module shift_proof (
    input logic clk, rst_n, i_en,
    input logic signed [63:0] i_product,
    input logic [6:0] i_amount
);
    logic signed [63:0] reference_quotient;
    logic signed [33:0] bounded, quotient_q[2], actual_quotient;
    logic [63:0] mask, remainder, half;
    logic reference_increment, increment_q[2], actual_increment;
    logic [1:0] valid_q;
    assign reference_quotient = i_product >>> i_amount[5:0];
    assign mask = 64'hffffffffffffffff >> (7'd64-i_amount);
    assign remainder = $unsigned(i_product) & mask;
    assign half = 64'd1 << (i_amount-1'b1);
    always_comb begin
        bounded = reference_quotient[33:0];
        if (i_amount[6]) bounded = '0;
        else if (reference_quotient > 64'sd8589934591) bounded = 34'sh1ffffffff;
        else if (reference_quotient < -64'sd8589934592) bounded = 34'sh200000000;
    end
    assign reference_increment = i_amount != 0 && !i_amount[6] &&
        ((remainder > half) || (remainder == half && reference_quotient[0]));
    requant_shift_pipeline dut (.clk(clk),.i_en(i_en),.i_product(i_product),.i_amount(i_amount),
        .o_quotient(actual_quotient),.o_increment(actual_increment));
    always_ff @(posedge clk) begin
        if (!rst_n) valid_q <= '0;
        else if (i_en) valid_q <= {valid_q[0],1'b1};
        if (i_en) begin
            quotient_q[0] <= bounded; quotient_q[1] <= quotient_q[0];
            increment_q[0] <= reference_increment; increment_q[1] <= increment_q[0];
        end
    end
    always_comb if (rst_n && valid_q[1]) begin
        assert(actual_quotient == quotient_q[1]);
        assert(actual_increment == increment_q[1]);
    end
endmodule
