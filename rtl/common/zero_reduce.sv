// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行归并一组数据的各位，全部为零时输出有效。
(* keep_hierarchy = "yes" *)
module zero_reduce #(
    parameter int unsigned p_width = 6,
    parameter int unsigned p_group_width = 0 // 非零时保留各分组的零值结果。
) (
    input wire logic [p_width-1:0] i_value, // 需要检查的分组数据
    output logic o_zero // 本组全部位均为零
);
    if (p_group_width > 0 && p_width > p_group_width) begin : g_grouped
        localparam int unsigned p_groups = (p_width+p_group_width-1)/p_group_width;
        (* keep = 1 *) logic [p_groups-1:0] group_zero;
        for (genvar group = 0; group < p_groups; group++) begin : g_group
            localparam int unsigned p_first = group*p_group_width;
            localparam int unsigned p_count = p_width-p_first < p_group_width ?
                p_width-p_first : p_group_width;
            assign group_zero[group] = !(|i_value[p_first+:p_count]);
        end
        assign o_zero = &group_zero;
    end else begin : g_direct
        assign o_zero = !(|i_value);
    end
endmodule

`default_nettype wire
