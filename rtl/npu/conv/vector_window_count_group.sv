// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 使用预先形成的完整组传播条件，按四位一组修正窗口计数的高位结果。
// 当前组的各结果位并行计算，低段进位只参与最后一级与或及异或运算。
(* keep_hierarchy = "yes" *)
module vector_window_count_group #(
    parameter int unsigned p_bits = 4
) (
    input wire logic i_prefix, // 所有较低高位组均可传播进位。
    input wire logic [p_bits-1:0] i_sum, // 当前组的原计数值。
    input wire logic i_carry, // 低段加法产生的进位。
    output logic [p_bits-1:0] o_sum // 当前组更新后的计数值。
);
    for (genvar bit_index=0; bit_index<p_bits; bit_index++) begin : g_bit
        if (bit_index == 0) begin : g_first
            assign o_sum[bit_index] = i_sum[bit_index] ^ (i_carry & i_prefix);
        end else begin : g_later
            assign o_sum[bit_index] = i_sum[bit_index] ^
                (i_carry & i_prefix & (&i_sum[bit_index-1:0]));
        end
    end
endmodule

`default_nettype wire
