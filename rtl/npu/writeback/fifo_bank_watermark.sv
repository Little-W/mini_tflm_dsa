// SPDX-License-Identifier: Apache-2.0
`default_nettype none

/* 根据结果存储体占用和预留数量计算是否可以接收下一计算组。 */ module fifo_bank_watermark #(
    parameter int p_banks = 16,
    parameter int p_count_width = (p_banks <= 1) ? 1 : $clog2(p_banks + 1),
    parameter bit p_precomputed_threshold = 1'b0
) (
    input  wire logic [31:0] i_reserve /* 下一计算组需要预留的结果存储体数 */,
    input  wire logic [p_count_width-1:0] i_ready_banks /* 当前已完成写入的结果存储体数 */,
    input  wire logic i_partial_write /* 当前另有一个未完成写入的结果存储体 */,
    input  wire logic [p_count_width-1:0] i_ready_threshold /* 预先计算的已完成存储体数量限制 */,
    output logic o_full /* 当前结果存储余量不足以满足预留需求 */
);
    if (p_precomputed_threshold) begin : g_precomputed_threshold
        // 配置阶段保存容量阈值，运行期间并行比较计数片段并归并部分写入条件。
        fifo_ready_threshold #(.p_width(p_count_width)) u_threshold (
            .i_ready(i_ready_banks), .i_threshold(i_ready_threshold),
            .i_partial(i_partial_write), .o_full(o_full)
        );
    end else if (p_banks > 0 && p_count_width >= $clog2(p_banks+1)) begin : g_parallel_compare
        localparam int p_sum_width = p_count_width + 1;
        localparam logic [p_sum_width-1:0] p_negative_capacity = ~p_sum_width'(p_banks);
        logic [p_sum_width-1:0] ready_count, reserve_count;
        logic [p_sum_width-1:0] sum_bits, carry_bits, shifted_carry, unused_sum;
        logic unused_high_carry, normal_full, zero_full, saturated_full;
        logic count_overflow, reserve_zero, reserve_saturated;

        assign ready_count = {1'b0, i_ready_banks};
        assign reserve_count = p_sum_width'(p_count_width'(i_reserve));
        assign sum_bits = ready_count ^ reserve_count ^ p_negative_capacity;
        assign carry_bits = (ready_count & reserve_count) |
            ((ready_count | reserve_count) & p_negative_capacity);
        assign {unused_high_carry, shifted_carry} = {carry_bits, 1'b0};
        parallel_prefix_add #(
            .p_width(p_sum_width), .p_group_width(4), .p_preserve_groups(1'b1)
        ) u_capacity_compare (
            .i_a(sum_bits), .i_b(shifted_carry), .i_carry(i_partial_write),
            .o_sum(unused_sum), .o_carry(normal_full)
        );
        assign zero_full = (i_ready_banks > p_count_width'(p_banks-1)) ||
            (i_partial_write && i_ready_banks == p_count_width'(p_banks-1));
        assign saturated_full = (|i_ready_banks) || i_partial_write;
        assign reserve_zero = i_reserve == 32'd0;
        localparam int p_capacity_bits = $clog2(p_banks+1);
        localparam int p_capacity_low_bit = $clog2(p_banks & -p_banks);
        localparam int p_capacity_prefix = p_banks >> p_capacity_low_bit;
        if ((p_capacity_prefix & (p_capacity_prefix+1)) == 0 && p_capacity_bits <= 32) begin : g_prefix_capacity
            // 容量为连续高位一和低位零时，比较仅需高位非零与有效位归约。
            assign reserve_saturated = (|(i_reserve >> p_capacity_bits)) ||
                (&i_reserve[p_capacity_bits-1:p_capacity_low_bit]);
        end else begin : g_arbitrary_capacity
            assign reserve_saturated = i_reserve >= 32'(p_banks);
        end
        // 部分写入使计数回绕时，保持有限位宽占用计数的结果。
        assign count_overflow = i_partial_write && (&i_ready_banks);
        assign o_full = !count_overflow && ((reserve_zero && zero_full) ||
            (!reserve_zero && reserve_saturated && saturated_full) ||
            (!reserve_zero && !reserve_saturated && normal_full));
    end else begin : g_narrow_count
        logic [p_count_width-1:0] reserve_count, ready_threshold;
        logic ready_above, ready_at, count_overflow;

        assign reserve_count = (i_reserve == 32'd0) ? p_count_width'(1) :
            ((i_reserve >= 32'(p_banks)) ? p_count_width'(p_banks) : p_count_width'(i_reserve));
        assign ready_threshold = p_count_width'(p_banks) - reserve_count;
        assign ready_above = i_ready_banks > ready_threshold;
        assign ready_at = i_ready_banks == ready_threshold;
        assign count_overflow = i_partial_write && (&i_ready_banks);
        assign o_full = !count_overflow && (ready_above || (i_partial_write && ready_at));
    end
endmodule

`default_nettype wire
