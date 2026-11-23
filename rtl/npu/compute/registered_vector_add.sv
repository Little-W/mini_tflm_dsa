`default_nettype none

// 字节部分和寄存后归并进位，数据与有效、行结束标志共同前进一拍。
module registered_vector_add #(
    parameter int unsigned p_lanes = 16
) (
    input  wire logic clk,
    input  wire logic rst_n,
    input  wire logic i_clear,
    input  wire logic i_valid,
    input  wire logic i_tile_done,
    input  wire logic signed [31:0] i_lhs [p_lanes],
    input  wire logic signed [31:0] i_rhs [p_lanes],
    output wire logic o_valid,
    output wire logic o_tile_done,
    output wire logic signed [31:0] o_sum [p_lanes]
);
    logic valid_q, tile_done_q;
    logic [3:0][7:0] partial_sum_q [p_lanes];
    logic [2:0] partial_carry_q [p_lanes];

    assign o_valid = valid_q && !i_clear;
    assign o_tile_done = tile_done_q && o_valid;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_q <= 1'b0;
            tile_done_q <= 1'b0;
        end else if (i_clear) begin
            valid_q <= 1'b0;
            tile_done_q <= 1'b0;
        end else begin
            valid_q <= i_valid;
            tile_done_q <= i_valid && i_tile_done;
        end
    end

    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
        logic [3:0] increment;
        assign increment[0] = 1'b0;
        assign increment[1] = partial_carry_q[lane][0];
        assign increment[2] = partial_carry_q[lane][1] |
            ((&partial_sum_q[lane][1]) && partial_carry_q[lane][0]);
        assign increment[3] = partial_carry_q[lane][2] |
            ((&partial_sum_q[lane][2]) && partial_carry_q[lane][1]) |
            ((&partial_sum_q[lane][2]) && (&partial_sum_q[lane][1]) && partial_carry_q[lane][0]);

        for (genvar part = 0; part < 4; part++) begin : g_byte
            if (part < 3) begin : g_carry
                always_ff @(posedge clk) begin
                    if (i_valid && !i_clear) begin
                        {partial_carry_q[lane][part], partial_sum_q[lane][part]} <=
                            {1'b0, i_lhs[lane][8*part +: 8]} +
                            {1'b0, i_rhs[lane][8*part +: 8]};
                    end
                end
            end else begin : g_most_significant
                // INT32 加法保留低三十二位，最高字节的溢出不进入结果。
                always_ff @(posedge clk) begin
                    if (i_valid && !i_clear) begin
                        partial_sum_q[lane][part] <=
                            i_lhs[lane][8*part +: 8] + i_rhs[lane][8*part +: 8];
                    end
                end
            end
            assign o_sum[lane][8*part +: 8] = partial_sum_q[lane][part] + 8'(increment[part]);
        end
    end
endmodule

`default_nettype wire
