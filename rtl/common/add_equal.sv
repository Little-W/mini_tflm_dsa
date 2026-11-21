// SPDX-License-Identifier: Apache-2.0
// 比较定宽模加结果，支持完整算术推断和逐位进位一致性实现。
`default_nettype none
module add_equal #(
    parameter int unsigned p_width = 32,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_lut = 1'b0,
`elsif XILINX_FPGA
    parameter bit p_use_lut = 1'b1,
`else
    parameter bit p_use_lut = 1'b0,
`endif
    parameter bit p_infer_dsp =
`ifdef ASIC_SYNTHESIS
        1'b0
`elsif XILINX_FPGA
        1'b1
`elsif SYNTHESIS
        1'b1
`else
        1'b0
`endif
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    input  wire logic [p_width-1:0] i_target,
    input  wire logic               i_carry_in,
    output logic                   o_equal
);
    //! 0. 资源选择与进位条件
    //! -----------------------

    // 逐位比较只依赖本位与相邻低位的输入，逻辑实现可保留该计算边界。
    localparam bit p_dsp_comparison = p_infer_dsp && p_width >= 24 && p_width <= 47;
    (* keep = p_use_lut && !p_dsp_comparison *) logic [p_width-1:0] bit_equal;

    //! 1. 计算各位进位条件
    //! --------------------

    assign bit_equal[0] = ~(i_a[0] ^ i_b[0] ^ i_target[0] ^ i_carry_in);
    for (genvar bit_index = 1; bit_index < p_width; bit_index++) begin : g_bit
        // 目标和值确定相邻低位产生的进位，与本位所需进位同时比较。
        assign bit_equal[bit_index] = ~((i_a[bit_index] ^ i_b[bit_index] ^ i_target[bit_index]) ^
            ((i_a[bit_index-1] & i_b[bit_index-1]) |
             ((i_a[bit_index-1] | i_b[bit_index-1]) & ~i_target[bit_index-1])));
    end

    //! 2. 生成模加等式结果
    //! -------------------

    // 算术实现比较完整模加结果；逐位实现归并所有进位一致性条件。
    if (p_dsp_comparison) begin : g_inferred_sum
        (* use_dsp = "yes" *) logic [p_width-1:0] arithmetic_sum;
        // 完整模加与目标值比较使用同一组操作数，进位输入保留一位精度。
        assign arithmetic_sum = i_a + i_b + p_width'(i_carry_in);
`ifdef SYNTHESIS
        assign o_equal = arithmetic_sum == i_target;
`else
        // 四态仿真使用逐位进位一致性，保留部分未知输入中的确定比较结果。
        assign o_equal = &bit_equal;
`endif
    end else begin : g_carry_consistency
        assign o_equal = &bit_equal;
    end

endmodule
`default_nettype wire
