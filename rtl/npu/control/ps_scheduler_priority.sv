// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 四帧组内编码与组间选择并行计算，保留实际的分组归并节点。
module ps_scheduler_priority #(
    parameter int p_frames = 16,
    parameter int p_id_width = (p_frames <= 1) ? 1 : $clog2(p_frames)
) (
    input wire [p_frames-1:0] i_eligible /* 各候选帧的可调度标记 */,
    output logic [p_id_width-1:0] o_id /* 按模块优先顺序选中的候选帧编号 */
);
    localparam int p_group_width = 4;
    localparam int p_groups = (p_frames + p_group_width - 1) / p_group_width;
    logic [p_groups-1:0] group_any, group_first;
    logic [p_id_width-1:0] group_id [p_groups];
    logic [p_id_width-1:0] grouped_id, flat_id;
    logic [p_frames-1:0] flat_first;

    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int p_first = group * p_group_width;
        localparam int p_bits = (p_frames - p_first < p_group_width) ?
            p_frames - p_first : p_group_width;
        logic [p_bits-1:0] local_first;
        if (p_bits == 1) begin : g_single
            assign group_any[group] = i_eligible[p_first];
        end else begin : g_many
            (* keep = "true" *) logic found;
            assign found = |i_eligible[p_first +: p_bits];
            assign group_any[group] = found;
        end
        if (group == 0) begin : g_first_group
            assign group_first[group] = group_any[group];
        end else begin : g_later_group
            (* keep = "true" *) logic selected;
            assign selected = group_any[group] && !(|group_any[group-1:0]);
            assign group_first[group] = selected;
        end
        for (genvar frame = 0; frame < p_bits; frame++) begin : g_frame
            if (frame == 0) begin : g_first
                assign local_first[frame] = i_eligible[p_first];
            end else begin : g_later
                assign local_first[frame] = i_eligible[p_first+frame] &&
                    !(|i_eligible[p_first +: frame]);
            end
        end
        always_comb begin
            group_id[group] = '0;
            for (int frame = 0; frame < p_bits; frame++) begin
                group_id[group] |= p_id_width'(p_first+frame) & {p_id_width{local_first[frame]}};
            end
        end
    end
    for (genvar frame = 0; frame < p_frames; frame++) begin : g_flat
        if (frame == 0) begin : g_first
            assign flat_first[frame] = i_eligible[frame];
        end else begin : g_later
            assign flat_first[frame] = i_eligible[frame] && !(|i_eligible[frame-1:0]);
        end
    end
    always_comb begin
        grouped_id = '0;
        for (int group = 0; group < p_groups; group++) begin
            grouped_id |= group_id[group] & {p_id_width{group_first[group]}};
        end
        flat_id = '0;
        for (int frame = 0; frame < p_frames; frame++) begin
            flat_id |= p_id_width'(frame) & {p_id_width{flat_first[frame]}};
        end
        case (^i_eligible)
            1'b0, 1'b1: o_id = grouped_id;
            default: o_id = flat_id;
        endcase
    end
endmodule

`default_nettype wire
