// SPDX-License-Identifier: Apache-2.0
// 选择一个有符号操作数，并按使能执行定宽模加；输出在当前周期组合产生。
`default_nettype none
module select_add #(
    parameter int p_width = 32,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0,
`elsif XILINX_FPGA
    parameter bit p_use_dsp = 1'b1,
`elsif SYNTHESIS
    parameter bit p_use_dsp = 1'b1,
`else
    parameter bit p_use_dsp = 1'b0,
`endif
    // 48 位端口可分为四个独立的 12 位模加通道。
    parameter bit p_split_12bit = 1'b0
) (
    input  wire logic signed [p_width-1:0] i_lhs,
    input  wire logic signed [p_width-1:0] i_rhs0,
    input  wire logic signed [p_width-1:0] i_rhs1,
    input  wire logic                      i_rhs_select,
    input  wire logic                      i_add_enable,
    output logic signed [p_width-1:0] o_sum
);
    //! 0. 辅助定义
    //! -----------

    logic signed [p_width-1:0] selected_rhs;

    //! 1. 选择输入并生成组合结果
    //! -------------------------

    // 四路 12 位组合加法按 p_use_dsp 选择 SIMD 推断。
    begin : g_generic
        assign selected_rhs = i_rhs_select ? i_rhs1 : i_rhs0;
        if ((p_width == 48) && p_split_12bit) begin : g_parallel
            for (genvar lane = 0; lane < 4; lane++) begin : g_lane
                (* use_dsp = p_use_dsp ? "simd" : "no" *) logic [11:0] lane_sum;
                assign lane_sum = i_lhs[lane*12 +: 12] + selected_rhs[lane*12 +: 12];
                assign o_sum[lane*12 +: 12] = i_add_enable ? lane_sum : i_lhs[lane*12 +: 12];
            end
        end else if (p_use_dsp && p_width >= 17 && p_width <= 48) begin : g_inferred_sum
            (* use_dsp = "yes" *) logic signed [p_width-1:0] arithmetic_sum;
            logic signed [p_width-1:0] enabled_rhs;

            // 关闭加法时选择零操作数，共用一次完整模加和输入选择逻辑。
            assign enabled_rhs = i_add_enable ? selected_rhs : '0;
            assign arithmetic_sum = i_lhs + enabled_rhs;
`ifdef SYNTHESIS
            assign o_sum = arithmetic_sum;
`else
            // 四态仿真保留直通数据中的已知位以及未知使能的条件合并行为。
            always_comb begin
                o_sum = arithmetic_sum;
                if (i_add_enable !== 1'b1)
                    o_sum = i_add_enable ? i_lhs + selected_rhs : i_lhs;
            end
`endif
        end else begin : g_single
            localparam int p_low_width = (p_width <= 16) ? p_width :
                ((p_width <= 32) ? 16 : (p_width+1)/2);
            if (p_width == p_low_width) begin : g_short
                assign o_sum = i_add_enable ? i_lhs + selected_rhs : i_lhs;
            end else begin : g_partition
                logic [p_low_width:0] low_sum;
                logic [p_width-p_low_width-1:0] high_sum, high_sum_with_carry;
                logic [p_width-1:0] sum;

                // 高半字同时准备两种进位结果，低半字的进位只选择最终结果。
                assign low_sum = {1'b0, i_lhs[p_low_width-1:0]} +
                    {1'b0, selected_rhs[p_low_width-1:0]};
                assign high_sum = i_lhs[p_width-1:p_low_width] + selected_rhs[p_width-1:p_low_width];
                assign high_sum_with_carry = i_lhs[p_width-1:p_low_width] +
                    selected_rhs[p_width-1:p_low_width] + (p_width-p_low_width)'(1);
                assign sum = {low_sum[p_low_width] ? high_sum_with_carry : high_sum, low_sum[p_low_width-1:0]};
                assign o_sum = i_add_enable ? sum : i_lhs;
            end
        end
    end
endmodule
`default_nettype wire
