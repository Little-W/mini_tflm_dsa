// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 指数累加器先保存数据及舍入进位，再在下一边沿更新三十二位累计结果。
module vector_softmax_accumulator (
    input  wire logic        clk,
    input  wire logic        rst_n,
    input  wire logic        i_clear,
    input  wire logic        i_vld,
    input  wire logic [19:0] i_value,
    input  wire logic        i_increment,
    output logic [31:0] o_sum
);
    //! 0. 辅助定义
    //! -----------

    logic add_pending;
    logic sum_clear;
    logic [19:0] value_stage;
    logic increment_stage;
    logic [31:0] sum;
    logic [31:0] sum_next;
    logic unused_sum_carry;

    //! 1. 输入处理
    //! -----------

    assign sum_clear = !rst_n || i_clear;
    parallel_prefix_add #(
        .p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)
    ) u_accumulate (
        .i_a(sum), .i_b({12'd0, value_stage}), .i_carry(increment_stage),
        .o_sum(sum_next), .o_carry(unused_sum_carry)
    );

    //! 2. 保存输入与累计结果
    //! ---------------------

    // 任务初始化同时清除累计结果和待处理标志，新的有效数据不会跨任务保留。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            add_pending <= 1'b0;
        end else if (i_clear) begin
            add_pending <= 1'b0;
        end else begin
            add_pending <= i_vld;
        end
    end

    always_ff @(posedge clk) begin
        value_stage <= i_value;
        increment_stage <= i_increment;
        if (sum_clear) begin
            sum <= '0;
        end else if (add_pending) begin
            sum <= sum_next;
        end
    end
    //! 3. 输出累计结果
    //! ---------------

    assign o_sum = sum;
endmodule

`default_nettype wire
