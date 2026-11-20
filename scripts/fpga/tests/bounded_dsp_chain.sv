`default_nettype none
module bounded_dsp_chain (
    input logic clk,
    input logic [31:0] i_a, i_b, i_c, i_d,
    output logic [31:0] o_y
);
    logic [31:0] a_q, b_q, c_q, d_q;
    logic [31:0] first_sum, mixed_sum;

    // 两次模加之间保留逐位异或，分别映射两个算术单元。
    assign first_sum = a_q + b_q;
    assign mixed_sum = first_sum ^ c_q;
    always_ff @(posedge clk) begin
        a_q <= i_a;
        b_q <= i_b;
        c_q <= i_c;
        d_q <= i_d;
        o_y <= mixed_sum + d_q;
    end
endmodule
`default_nettype wire
