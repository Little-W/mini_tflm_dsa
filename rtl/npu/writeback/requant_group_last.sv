// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据当前行、末行及复用掩码生成最后一块和最后一组标志。
(* keep_hierarchy = "yes" *)
module requant_group_last #(
    parameter int unsigned p_tile_width = 16
) (
    input wire logic [p_tile_width-1:0] i_row, // 当前块的行坐标
    input wire logic [p_tile_width-1:0] i_last_row, // 最后一个块的行坐标
    input wire logic [p_tile_width-1:0] i_mask, // 当前复用组对应的低位掩码
    output logic o_last_tile, // 当前块为完整行范围中的最后一个块
    output logic o_last_group // 当前块位于复用组末端
);
    localparam int unsigned p_groups = (p_tile_width + 2) / 3;
    logic [p_groups-1:0] row_equal, mask_equal;
    logic mask_all;
    // 三位比较只需要六个输入，各组结果随后独立归并。
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_compare
        localparam int unsigned p_first = 3 * group_index;
        localparam int unsigned p_bits = p_tile_width - p_first < 3 ? p_tile_width - p_first : 3;
        (* keep = 1 *) logic rows_match, mask_match;
        assign rows_match = i_row[p_first+:p_bits] == i_last_row[p_first+:p_bits];
        assign mask_match = (i_row[p_first+:p_bits] & i_mask[p_first+:p_bits]) == i_mask[p_first+:p_bits];
        assign row_equal[group_index] = rows_match;
        assign mask_equal[group_index] = mask_match;
    end
    (* keep_hierarchy = "yes" *) add_equal_reduce #(.p_width(p_groups)) u_row_reduce (
        .i_equal(row_equal), .o_equal(o_last_tile)
    );
    (* keep_hierarchy = "yes" *) add_equal_reduce #(.p_width(p_groups)) u_mask_reduce (
        .i_equal(mask_equal), .o_equal(mask_all)
    );
    assign o_last_group = o_last_tile || mask_all;
endmodule

`default_nettype wire
