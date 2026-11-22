module pe_test_top (
    input logic clk,
    input logic i_en,
    input logic [2:0] i_op,
    input logic signed [15:0] i_a,
    input logic signed [15:0] i_b,
    input logic signed [31:0] i_acc,
    output logic signed [31:0] o_result,
    output logic signed [31:0] o_reference,
    output logic signed [31:0] o_extended
);
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b1)) u_extended (
        .op(i_op), .a(i_a), .b(i_b), .acc(i_acc), .result(o_extended)
    );
    registered_vector_pe u_candidate (
        .clk(clk), .i_en(i_en), .i_op(i_op), .i_a(i_a), .i_b(i_b), .i_acc(i_acc),
        .o_result(o_result)
    );
    logic signed [15:0] saved_a,saved_b;
    logic signed [31:0] saved_acc;
    always_ff @(posedge clk)begin
        if(i_en)begin saved_a<=i_a;saved_b<=i_b;saved_acc<=i_acc;end
    end
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_reference(
        .op(i_op),.a(saved_a),.b(saved_b),.acc(saved_acc),.result(o_reference));
endmodule
