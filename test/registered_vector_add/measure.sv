`default_nettype none

// 输入与输出各加一组寄存器，以测量实际加法路径的组合单元数量。
module registered_vector_add_measure (
    input wire logic clk,
    input wire logic rst_n,
    input wire logic i_clear,
    input wire logic i_valid,
    input wire logic i_tile_done,
    input wire logic signed [31:0] i_lhs [16],
    input wire logic signed [31:0] i_rhs [16],
    output logic o_valid,
    output logic o_tile_done,
    output logic signed [31:0] o_sum [16]
);
    logic clear_q, valid_q, tail_q;
    logic signed [31:0] lhs_q [16], rhs_q [16];
    logic valid, tail;
    wire logic signed [31:0] sum [16];

    always_ff @(posedge clk) begin
        clear_q <= i_clear;
        valid_q <= i_valid;
        tail_q <= i_tile_done;
        for (int lane = 0; lane < 16; lane++) begin
            lhs_q[lane] <= i_lhs[lane];
            rhs_q[lane] <= i_rhs[lane];
            o_sum[lane] <= sum[lane];
        end
        o_valid <= valid;
        o_tile_done <= tail;
    end

    registered_vector_add #(.p_lanes(16)) u_add (
        .clk(clk), .rst_n(rst_n), .i_clear(clear_q), .i_valid(valid_q), .i_tile_done(tail_q),
        .i_lhs(lhs_q), .i_rhs(rhs_q), .o_valid(valid), .o_tile_done(tail), .o_sum(sum)
    );
endmodule

`default_nettype wire
