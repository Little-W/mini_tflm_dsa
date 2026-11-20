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

    // p_use_dsp 保留接口兼容，所有配置均使用普通 RTL。
    begin : g_generic
        assign selected_rhs = i_rhs_select ? i_rhs1 : i_rhs0;
        if ((p_width == 48) && p_split_12bit) begin : g_parallel
            for (genvar lane = 0; lane < 4; lane++) begin : g_lane
                assign o_sum[lane*12 +: 12] = i_add_enable ?
                    i_lhs[lane*12 +: 12] + selected_rhs[lane*12 +: 12] :
                    i_lhs[lane*12 +: 12];
            end
        end else begin : g_single
            assign o_sum = i_add_enable ? i_lhs + selected_rhs : i_lhs;
        end
    end
endmodule
`default_nettype wire
