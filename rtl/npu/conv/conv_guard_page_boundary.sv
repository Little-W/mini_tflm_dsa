// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 以四个二位字段并行检查完整字突发是否位于当前 4 KiB 页内。
(* keep_hierarchy = "yes" *)
module conv_guard_page_boundary #(parameter int p_width=9)(
    input wire logic [p_width-1:0] i_offset, // 当前页内的起始字索引
    input wire logic [7:0] i_length, // 突发字数减一
    output logic o_fits // 最后一个字仍位于当前页内
);
        // ARLEN 最多为八位。页内高位未全置一时，整个突发都位于当前页。
        // 其余情况并行比较两个四位字段，直接得到跨页条件。
        (* keep *) logic [3:0] page_generate, page_propagate;
        (* keep *) logic lower_carry, upper_generate, upper_propagate;
        logic page_high_full;
        if (p_width > 8) begin : g_page_high
            assign page_high_full = &i_offset[p_width-1:8];
        end else begin : g_page_eight
            assign page_high_full = 1'b1;
        end
        // 每两位独立计算进位和传播条件，最高分组同时检查页内高位。
        for (genvar group_index = 0; group_index < 4; group_index++) begin : g_page_group
            logic [1:0] address_part, length_part;
            logic part_enabled;
            assign address_part = i_offset[2*group_index +: 2];
            assign length_part = i_length[2*group_index +: 2];
            assign part_enabled = group_index == 3 ? page_high_full : 1'b1;
            // 二位加法的进位由生成项和传播项直接组成，组内不串联算术运算。
            assign page_generate[group_index] = part_enabled &&
                ((address_part[1] && length_part[1]) ||
                 ((address_part[1] || length_part[1]) && address_part[0] && length_part[0]));
            assign page_propagate[group_index] = (&(address_part ^ length_part)) && part_enabled;
        end
        // 两对分组独立合并，再组合高、低两部分的进位。
        assign lower_carry = page_generate[1] || (page_propagate[1] && page_generate[0]);
        assign upper_generate = page_generate[3] || (page_propagate[3] && page_generate[2]);
        assign upper_propagate = page_propagate[3] && page_propagate[2];
        assign o_fits = !(upper_generate || (upper_propagate && lower_carry));
endmodule
`default_nettype wire
