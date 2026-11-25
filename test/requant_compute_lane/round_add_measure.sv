`default_nettype none
module requant_round_add_measure (
    input wire logic clk,
    input wire logic [34:0] i_a, i_b,
    input wire logic i_increment,
    output logic [34:0] o_sum
);
    logic [34:0] a_q, b_q, sum;
    logic increment_q;
    requant_round_add u_add (
        .i_a(a_q), .i_b(b_q), .i_increment(increment_q), .o_sum(sum)
    );
    always_ff @(posedge clk) begin
        a_q <= i_a;
        b_q <= i_b;
        increment_q <= i_increment;
        o_sum <= sum;
    end
endmodule
`default_nettype wire
