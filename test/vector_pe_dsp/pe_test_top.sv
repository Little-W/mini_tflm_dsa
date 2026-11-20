module pe_test_top (
    input logic clk,
    input logic i_en,
    input logic [2:0] i_op,
    input logic signed [15:0] i_a,
    input logic signed [15:0] i_b,
    input logic signed [31:0] i_acc,
    output logic signed [31:0] o_result,
    output logic signed [31:0] o_reference
);
    registered_vector_pe #(.p_use_dsp(1'b1)) u_candidate (
        .clk(clk), .i_en(i_en), .i_op(i_op), .i_a(i_a), .i_b(i_b), .i_acc(i_acc),
        .o_result(o_result)
    );
    registered_vector_pe #(.p_use_dsp(1'b0)) u_reference (
        .clk(clk), .i_en(i_en), .i_op(i_op), .i_a(i_a), .i_b(i_b), .i_acc(i_acc),
        .o_result(o_reference)
    );
endmodule
