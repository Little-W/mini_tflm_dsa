// SPDX-License-Identifier: Apache-2.0
// 并行检查各位进位是否一致，比较保留 p_width 位的加法结果。
`default_nettype none
module add_equal #(
    parameter int unsigned p_width = 32,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_lut = 1'b0
`elsif XILINX_FPGA
    parameter bit p_use_lut = 1'b1
`else
    parameter bit p_use_lut = 1'b0
`endif
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    input  wire logic [p_width-1:0] i_target,
    input  wire logic               i_carry_in,
    output logic                   o_equal
);
    //! 0. 各位进位的一致性
    //! ------------

    // 每个结果位只依赖本位与相邻低位的输入，FPGA 综合时保留该计算边界。
    (* keep = p_use_lut *) logic [p_width-1:0] bit_equal;

    //! 1. 计算各位进位条件
    //! --------------------

    assign bit_equal[0] = ~(i_a[0] ^ i_b[0] ^ i_target[0] ^ i_carry_in);
    for (genvar bit_index = 1; bit_index < p_width; bit_index++) begin : g_bit
        // 目标和值确定相邻低位产生的进位，与本位所需进位同时比较。
        assign bit_equal[bit_index] = ~((i_a[bit_index] ^ i_b[bit_index] ^ i_target[bit_index]) ^
            ((i_a[bit_index-1] & i_b[bit_index-1]) |
             ((i_a[bit_index-1] | i_b[bit_index-1]) & ~i_target[bit_index-1])));
    end

    //! 2. 合并逐位比较
    //! ----------------

    // 最高位只检查输入进位，全部条件成立即满足保留 p_width 位的模加法等式。
    assign o_equal = &bit_equal;

endmodule
`default_nettype wire
