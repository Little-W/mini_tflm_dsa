`default_nettype none

// 两个半字分别计算并寄存，低半字进位在输出端加入高半字。
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
    logic [16:0] low_sum_q [p_lanes];
    logic [15:0] high_sum_q [p_lanes];

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

`ifndef SYNTHESIS
    // 四态仿真按字节传播未知值，已确定的低位字节仍保持可见。
    function automatic logic [31:0] byte_sum_four_state(
        input logic [31:0] lhs,
        input logic [31:0] rhs
    );
        logic [8:0] part [4];
        logic [3:0] increment;
        for (int index = 0; index < 4; index++) begin
            part[index] = {1'b0, lhs[8*index +: 8]} + {1'b0, rhs[8*index +: 8]};
        end
        increment[0] = 1'b0;
        increment[1] = part[0][8];
        increment[2] = part[1][8] | ((&part[1][7:0]) && part[0][8]);
        increment[3] = part[2][8] | ((&part[2][7:0]) && part[1][8]) |
            ((&part[2][7:0]) && (&part[1][7:0]) && part[0][8]);
        for (int index = 0; index < 4; index++) begin
            byte_sum_four_state[8*index +: 8] = part[index][7:0] + 8'(increment[index]);
        end
    endfunction
`endif

    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
        logic [31:0] lane_sum;
        // 独立半字算术允许综合工具将两组结果放入同一 DSP。
        (* use_dsp = "simd" *) logic [16:0] low_sum;
        (* use_dsp = "simd" *) logic [15:0] high_sum;
        assign low_sum = {1'b0, i_lhs[lane][15:0]} + {1'b0, i_rhs[lane][15:0]};
        assign high_sum = i_lhs[lane][31:16] + i_rhs[lane][31:16];
        // 两个十六位加法器共用输入使能，结果及进位共同保持。
        always_ff @(posedge clk) begin
            if (i_valid && !i_clear) begin
                low_sum_q[lane] <= low_sum;
                high_sum_q[lane] <= high_sum;
            end
        end

`ifndef SYNTHESIS
        logic four_state_q;
        logic [31:0] four_state_sum_q;
        always_ff @(posedge clk) begin
            if (i_valid && !i_clear) begin
                four_state_q <= (^{i_lhs[lane], i_rhs[lane]}) === 1'bx;
                four_state_sum_q <= byte_sum_four_state(i_lhs[lane], i_rhs[lane]);
            end
        end
`endif
        always_comb begin
            lane_sum = {high_sum_q[lane] + 16'(low_sum_q[lane][16]), low_sum_q[lane][15:0]};
`ifndef SYNTHESIS
            if (four_state_q) begin
                lane_sum = four_state_sum_q;
            end
`endif
        end
        assign o_sum[lane] = lane_sum;
    end

endmodule

`default_nettype wire
