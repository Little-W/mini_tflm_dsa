`default_nettype none

// 地址按定宽模加更新，公共分段加法器保留低段产生的进位。
(* keep_hierarchy = "yes" *)
module ia_address_add #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_base /* 本次地址更新的基地址 */,
    input wire logic [p_width-1:0] i_step /* 本次地址更新的字节步长 */,
    output logic [p_width-1:0] o_address /* 基地址加步长后的定宽模地址 */
);
    if (p_width > 16 && p_width <= 32) begin : g_halves
`ifdef SYNTHESIS
        logic unused_carry;
        // 两个部分和由公共组合子模块保存，常量进位在外围参与化简。
        parallel_prefix_add #(
            .p_width(p_width), .p_preserve_groups(1'b1), .p_dsp_split_width(16), .p_keep_carry(1'b0)
        ) u_address (
            .i_a(i_base), .i_b(i_step), .i_carry(1'b0),
            .o_sum(o_address), .o_carry(unused_carry)
        );
`else
        // 仿真保留完整地址加法对未知输入的传播。
        assign o_address = i_base + i_step;
`endif
    end else begin : g_direct
        assign o_address = i_base + i_step;
    end
endmodule

`default_nettype wire
