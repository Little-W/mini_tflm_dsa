`default_nettype none

// 组合归约的两端使用普通寄存器，测量完整操作数至结果路径。
module reduce_depth_top (
    input logic clk,
    input logic signed [31:0] i_lhs, i_rhs,
    input logic i_max, i_min,
    output logic signed [31:0] o_result
);
    logic signed [31:0] lhs_q, rhs_q, result;
    logic max_q, min_q;
    always_ff @(posedge clk) begin
        lhs_q <= i_lhs;
        rhs_q <= i_rhs;
        max_q <= i_max;
        min_q <= i_min;
        o_result <= result;
    end
    vector_reduce_alu u_reduce (
        .clk(clk), .i_lhs(lhs_q), .i_rhs(rhs_q), .i_max(max_q), .i_min(min_q), .o_result(result)
    );
endmodule

// 使用生产配置的中间移位寄存器，同时保留舍入与向下取整两个公开输出。
module round_depth_top (
    input logic clk,
    input logic signed [63:0] i_value,
    input logic [5:0] i_amount,
    output logic signed [63:0] o_result,
    output logic signed [63:0] o_floor
);
    logic signed [63:0] value_q, result, floor_value;
    logic [5:0] amount_q;
    always_ff @(posedge clk) begin
        value_q <= i_value;
        amount_q <= i_amount;
        o_result <= result;
        o_floor <= floor_value;
    end
    vector_round_shift #(.REGISTER_MIDDLE(1'b1)) u_round (
        .clk(clk), .value(value_q), .amount(amount_q), .result(result), .floor_value(floor_value)
    );
endmodule

`default_nettype wire
