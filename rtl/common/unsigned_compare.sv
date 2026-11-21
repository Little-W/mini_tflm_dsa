// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 无符号比较保留完整减法扩展位，组合输出小于和相等结果。
module unsigned_compare #(
    parameter int unsigned p_width = 32,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
    parameter bit p_use_dsp = 1'b1
`else
    parameter bit p_use_dsp = 1'b0
`endif
) (
    input  logic [p_width-1:0] i_a,
    input  logic [p_width-1:0] i_b,
    output logic o_less,
    output logic o_equal
);
    if (p_use_dsp && p_width >= 17 && p_width <= 47) begin : g_inferred_difference
        (* use_dsp = "yes" *) logic [p_width:0] difference;

        // 两个操作数先扩展为非负数，最高结果位表示无符号借位。
        assign difference = {1'b0, i_a} - {1'b0, i_b};
        assign o_less = difference[p_width];
    end else begin : g_logic_compare
        assign o_less = i_a < i_b;
    end
    assign o_equal = i_a == i_b;
endmodule

`default_nettype wire
