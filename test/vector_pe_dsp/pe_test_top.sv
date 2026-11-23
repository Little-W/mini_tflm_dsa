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
        .clk(clk), .i_en(i_en), .i_op(i_op), .i_a(i_a), .i_b(i_b), .i_acc(i_acc),
        .o_result(o_extended)
    );
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_candidate (
        .clk(clk), .i_en(i_en), .i_op(i_op), .i_a(i_a), .i_b(i_b), .i_acc(i_acc),
        .o_result(o_result)
    );
    logic signed [31:0] reference_next;
    logic signed [63:0] product;
    assign product = 64'(i_a) * 64'(i_b);
    always_comb begin
        case (i_op)
            3'd0: reference_next = 32'(product + 64'(i_acc));
            3'd1: reference_next = i_acc + 32'(i_a);
            3'd2: reference_next = i_acc > 32'(i_a) ? i_acc : 32'(i_a);
            3'd3: reference_next = i_acc < 32'(i_a) ? i_acc : 32'(i_a);
            3'd4: reference_next = 32'(product);
            3'd5, 3'd6: reference_next = 32'sd0;
            default: reference_next = i_acc;
        endcase
    end
    always_ff @(posedge clk) begin
        if (i_en) o_reference <= reference_next;
    end
endmodule
