// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分组计算定宽加法的和值与最高进位，支持完整前缀、分段加法和分段减法。
module parallel_prefix_add #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_group_width = 8,
    parameter bit p_preserve_groups = 1'b0,
    parameter int unsigned p_carry_select_width = 0,
    parameter int unsigned p_dsp_split_width = 0,
    parameter bit p_parallel_high_prefix = 1'b0,
    parameter bit p_keep_carry = 1'b1, // 是否保留只用于最高输出进位的末组传播节点。
    parameter bit p_preserve_grouped_unknowns = 1'b0, // 分段算术在未知输入时使用原分组加法的传播结果。
    parameter bit p_direct_subtract = 1'b0 // 输入进位为一时使用两段直接减法，其余输入保留分组加法。
) (
    input  wire logic [p_width-1:0] i_a, // 第一个定宽操作数
    input  wire logic [p_width-1:0] i_b, // 第二个定宽操作数
    input  wire logic               i_carry, // 低位段传入的进位
    output logic [p_width-1:0] o_sum, // 本级加法结果
    output logic               o_carry // 最高位输出进位
);
    logic [p_width-1:0] prefix_sum;
    logic prefix_carry;
`ifdef SYNTHESIS
    if (p_preserve_grouped_unknowns && p_dsp_split_width > 0 &&
        p_dsp_split_width < p_width && p_dsp_split_width <= 23 &&
        p_width-p_dsp_split_width <= 23) begin : g_grouped_unknowns
        logic [p_width-1:0] reference_sum;
        logic reference_carry;
        // 分组产生及传播表达式只含与、或归并，紧凑形式保留相同四态结果。
        // 参照计算无需保留组合节点，二态综合删除未知输入使用的计算分支。
        parallel_prefix_add #(.p_width(p_width), .p_group_width(p_group_width)) u_reference (
            .i_a(i_a), .i_b(i_b), .i_carry(i_carry),
            .o_sum(reference_sum), .o_carry(reference_carry)
        );
        always_comb begin
            case (^{i_a, i_b, i_carry})
                1'b0, 1'b1: {o_carry, o_sum} = {prefix_carry, prefix_sum};
                default: {o_carry, o_sum} = {reference_carry, reference_sum};
            endcase
        end
    end else
`endif
    assign {o_carry, o_sum} = {prefix_carry, prefix_sum};
`ifdef SYNTHESIS
    if (p_direct_subtract && p_dsp_split_width > 0 && p_dsp_split_width < p_width &&
        p_dsp_split_width <= 23 && p_width-p_dsp_split_width <= 23) begin : g_inferred_subtract
        localparam int unsigned p_low_width = p_dsp_split_width;
        localparam int unsigned p_high_width = p_width - p_low_width;
        localparam int unsigned p_high_groups = (p_high_width+3)/4;
        logic [p_low_width:0] low_difference;
        logic [p_high_width:0] high_difference, corrected_difference;
        logic [p_high_groups-1:0] high_zero;
        logic [p_width-1:0] reference_sum;
        logic reference_carry;
        parallel_prefix_add #(.p_width(p_width), .p_group_width(p_group_width)) u_reference (
            .i_a(i_a), .i_b(i_b), .i_carry(i_carry),
            .o_sum(reference_sum), .o_carry(reference_carry)
        );
        // 输入反码恢复为减数，两段完整差值分别包含最高借位。
        parallel_prefix_native_differences #(
            .p_low_width(p_low_width+1), .p_high_width(p_high_width+1)
        ) u_differences (
            .i_low_a({1'b0, i_a[p_low_width-1:0]}),
            .i_low_b({1'b0, ~i_b[p_low_width-1:0]}),
            .i_high_a({1'b0, i_a[p_width-1:p_low_width]}),
            .i_high_b({1'b0, ~i_b[p_width-1:p_low_width]}),
            .o_low_difference(low_difference), .o_high_difference(high_difference)
        );
        for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_zero
            localparam int unsigned p_first = 4*group_index;
            localparam int unsigned p_bits = p_high_width-p_first < 4 ? p_high_width-p_first : 4;
            (* keep = p_preserve_groups && (p_bits == 4) &&
                (p_keep_carry || group_index < p_high_groups-1) *) logic group_zero;
            assign group_zero = !(|high_difference[p_first+:p_bits]);
            assign high_zero[group_index] = group_zero;
        end
        // 高段减去低段借位，结果最高位的反相仍为加法器的输出进位。
        for (genvar group_index = 0; group_index < (p_high_width+4)/4; group_index++) begin : g_correct
            localparam int unsigned p_first = 4*group_index;
            localparam int unsigned p_bits = p_high_width+1-p_first < 4 ? p_high_width+1-p_first : 4;
            localparam int unsigned p_inputs = group_index > 0 ? group_index : 1;
            logic [p_inputs-1:0] groups;
            if (group_index == 0) begin : g_first
                assign groups = 1'b1;
            end else begin : g_later
                assign groups = high_zero[group_index-1:0];
            end
            parallel_prefix_high_group #(.p_bits(p_bits), .p_groups(p_inputs),
                .p_borrow_mode(1'b1)) u_group (
                .i_groups(groups), .i_sum(high_difference[p_first+:p_bits]),
                .i_carry(low_difference[p_low_width]), .i_invert(1'b0),
                .o_sum(corrected_difference[p_first+:p_bits])
            );
        end
        // 进位为零及含未知位的输入沿用分组计算，保持完整加法接口含义。
        always_comb begin
            case ({i_carry, ^{i_a, i_b}})
                2'b10, 2'b11: begin
                    prefix_sum = {corrected_difference[p_high_width-1:0], low_difference[p_low_width-1:0]};
                    prefix_carry = ~corrected_difference[p_high_width];
                end
                default: begin
                    prefix_sum = reference_sum;
                    prefix_carry = reference_carry;
                end
            endcase
        end
    end else if (p_dsp_split_width > 0 && p_dsp_split_width < p_width &&
        p_dsp_split_width <= 23 && p_width-p_dsp_split_width <= 23) begin : g_inferred_add
        localparam int unsigned p_low_width = p_dsp_split_width;
        localparam int unsigned p_high_width = p_width - p_low_width;
        localparam int unsigned p_high_groups = (p_high_width+3)/4;
        logic [p_low_width:0] low_a, low_b;
        logic [p_low_width:0] low_encoded, low_sum;
        logic [p_high_width:0] high_sum;
        logic [p_high_groups-1:0] high_group_all;
        logic [p_high_groups:0] high_group_prefix;

        // 输入进位控制低段操作数和结果的逐位取反，使加一仍由两操作数加法表示。
        // 两段保留各自最高进位，普通加法表达式由综合工具推断为并行算术资源。
        assign low_a = {1'b0, i_a[p_low_width-1:0]} ^ {(p_low_width+1){i_carry}};
        assign low_b = {1'b0, i_b[p_low_width-1:0]} ^ {(p_low_width+1){i_carry}};
        // 两段原生加法共用完整组合边界，外部常量进位可继续简化取反编码。
        parallel_prefix_native_sums #(
            .p_low_width(p_low_width+1), .p_high_width(p_high_width+1)
        ) u_native_sums (
            .i_low_a(low_a), .i_low_b(low_b),
            .i_high_a({1'b0, i_a[p_width-1:p_low_width]}),
            .i_high_b({1'b0, i_b[p_width-1:p_low_width]}),
            .o_low_sum(low_encoded), .o_high_sum(high_sum)
        );
        assign low_sum = low_encoded ^ {(p_low_width+1){i_carry}};
        assign prefix_sum[p_low_width-1:0] = low_sum[p_low_width-1:0];

        // 高段按四位形成传播条件，完整组前缀与组内剩余位并行参与最终修正。
        assign high_group_prefix[0] = 1'b1;
        for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high_group
            localparam int unsigned p_first = group_index*4;
            localparam int unsigned p_bits = p_high_width-p_first < 4 ? p_high_width-p_first : 4;
            // 末组传播条件只影响输出进位，使用方可单独关闭该结果的保留。
            (* keep = p_preserve_groups && (p_bits == 4) && (p_keep_carry || group_index < p_high_groups-1) *) logic group_all;
            (* keep = p_preserve_groups && !p_parallel_high_prefix && (p_bits == 4) && (p_keep_carry || group_index < p_high_groups-1) *) logic prefix_all;
            assign group_all = &high_sum[p_first+:p_bits];
            assign high_group_all[group_index] = group_all;
            assign prefix_all = &high_group_all[group_index:0];
            assign high_group_prefix[group_index+1] = prefix_all;
        end
        if (p_parallel_high_prefix && p_preserve_groups) begin : g_parallel_high
            logic [p_high_width:0] corrected_high;

            // 每组同时计算本组全部结果位，低位组传播条件直接参与最终异或修正。
            for (genvar group_index = 0; group_index < (p_high_width+4)/4; group_index++) begin : g_group
                localparam int unsigned p_first = group_index*4;
                localparam int unsigned p_bits = p_high_width+1-p_first < 4 ? p_high_width+1-p_first : 4;
                localparam int unsigned p_inputs = group_index > 0 ? group_index : 1;
                logic [p_inputs-1:0] correction_i_groups;
                logic [p_bits-1:0] correction_i_sum, correction_o_sum;
                logic correction_i_carry, correction_i_invert;

                if (group_index == 0) begin : g_first
                    assign correction_i_groups = 1'b1;
                end else begin : g_following
                    assign correction_i_groups = high_group_all[group_index-1:0];
                end
                assign correction_i_sum = high_sum[p_first+:p_bits];
                assign correction_i_carry = low_encoded[p_low_width];
                assign correction_i_invert = i_carry;
                parallel_prefix_high_group #(.p_bits(p_bits), .p_groups(p_inputs)) u_correction (
                    .i_groups(correction_i_groups), .i_sum(correction_i_sum),
                    .i_carry(correction_i_carry), .i_invert(correction_i_invert), .o_sum(correction_o_sum)
                );
                assign corrected_high[p_first+:p_bits] = correction_o_sum;
            end
            assign {prefix_carry, prefix_sum[p_width-1:p_low_width]} = corrected_high;
        end
        for (genvar bit_index = 0; bit_index <= p_high_width; bit_index++) begin : g_high
            localparam int unsigned p_full_groups = bit_index/4;
            localparam int unsigned p_local_bits = bit_index%4;
            logic carry_into_bit, result_bit;
            if (bit_index == 0) begin : g_first
                assign carry_into_bit = low_sum[p_low_width];
            end else if (!p_preserve_groups) begin : g_compact
                assign carry_into_bit = low_sum[p_low_width] & (&high_sum[bit_index-1:0]);
            end else if (p_local_bits == 0) begin : g_boundary
                assign carry_into_bit = low_sum[p_low_width] & high_group_prefix[p_full_groups];
            end else begin : g_local
                assign carry_into_bit = low_sum[p_low_width] & high_group_prefix[p_full_groups] &
                    (&high_sum[p_full_groups*4+:p_local_bits]);
            end
            assign result_bit = high_sum[bit_index] ^ carry_into_bit;
            if (!(p_parallel_high_prefix && p_preserve_groups)) begin : g_inline_result
                if (bit_index == p_high_width) begin : g_carry
                    assign prefix_carry = result_bit;
                end else begin : g_sum
                    assign prefix_sum[p_low_width+bit_index] = result_bit;
                end
            end
        end
    end else if (p_carry_select_width > 0 && p_carry_select_width < p_width) begin : g_carry_select
        localparam int unsigned p_low_width = p_carry_select_width;
        localparam int unsigned p_high_width = p_width - p_low_width;
        logic [p_low_width:0] low_sum;
        logic [p_high_width:0] high_zero, high_one;
        // 低段进位只选择两种预先完成的高段和值。
        // 低段末位直接形成和值与进位，进位条件参与高段结果选择。
        if (p_low_width == 1) begin : g_single_low
            assign low_sum[0] = i_a[0] ^ i_b[0] ^ i_carry;
            assign low_sum[1] = (i_a[0] & i_b[0]) | ((i_a[0] | i_b[0]) & i_carry);
        end else begin : g_multiple_low
            logic [p_low_width-1:0] lower_sum;
            assign lower_sum = {1'b0, i_a[p_low_width-2:0]} +
                {1'b0, i_b[p_low_width-2:0]} + p_low_width'(i_carry);
            assign low_sum = {
                (i_a[p_low_width-1] & i_b[p_low_width-1]) |
                    ((i_a[p_low_width-1] | i_b[p_low_width-1]) & lower_sum[p_low_width-1]),
                i_a[p_low_width-1] ^ i_b[p_low_width-1] ^ lower_sum[p_low_width-1],
                lower_sum[p_low_width-2:0]};
        end
        assign high_zero = {1'b0, i_a[p_width-1:p_low_width]} +
            {1'b0, i_b[p_width-1:p_low_width]};
        assign high_one = ~(~{1'b0, i_a[p_width-1:p_low_width]} +
            ~{1'b0, i_b[p_width-1:p_low_width]});
        assign {prefix_carry, prefix_sum} = {
            low_sum[p_low_width] ? high_one : high_zero, low_sum[p_low_width-1:0]};
    end else
`endif
    if (1) begin : g_grouped
        localparam int unsigned p_groups = (p_width + p_group_width - 1) / p_group_width;
        logic [p_width-1:0] bit_generate, bit_propagate;
        // 各组分别保存产生和传播条件，并行推导各组输入进位。
        logic [p_groups-1:0] group_generate;
        logic [p_groups-1:0] group_propagate;
        logic [p_groups:0] group_carry;

        assign bit_generate = i_a & i_b;
        assign bit_propagate = i_a | i_b;
        assign group_carry[0] = i_carry;
        assign prefix_carry = group_carry[p_groups];

        for (genvar group = 0; group < p_groups; group++) begin : g_group
            localparam int unsigned p_first = p_group_width * group;
            localparam int unsigned p_bits = (p_width - p_first < p_group_width) ? p_width - p_first : p_group_width;
            logic [p_bits-1:0] generate_terms;
            logic unused_local_carry;
            // 最高组只形成输出进位，其余组保留供更高位使用的产生和传播条件。
            (* keep = p_preserve_groups && (group < p_groups - 1) *) logic local_generate;
            // 最低组传播条件只连接外部输入进位，允许常量进位消除该部分逻辑。
            (* keep = p_preserve_groups && (group > 0) && (group < p_groups - 1) *) logic local_propagate;

            // 组内各进位产生条件并行计算，最高组允许少于配置的组宽。
            for (genvar bit_idx = 0; bit_idx < p_bits; bit_idx++) begin : g_generate
                if (bit_idx == p_bits - 1) begin : g_last
                    assign generate_terms[bit_idx] = bit_generate[p_first+bit_idx];
                end else begin : g_lower
                    assign generate_terms[bit_idx] = bit_generate[p_first+bit_idx] &
                        (&bit_propagate[p_first+bit_idx+1 +: p_bits-bit_idx-1]);
                end
            end
            assign local_generate = |generate_terms;
            assign local_propagate = &bit_propagate[p_first +: p_bits];
            assign group_generate[group] = local_generate;
            assign group_propagate[group] = local_propagate;
            assign {unused_local_carry, prefix_sum[p_first +: p_bits]} =
                {1'b0, i_a[p_first +: p_bits]} + {1'b0, i_b[p_first +: p_bits]} +
                (p_bits+1)'(group_carry[group]);
        end

        if (p_preserve_groups) begin : g_balanced_prefix
            localparam int unsigned p_levels = $clog2(p_groups);
            // 每层共用左半组的末端前缀，右半组分别合并各自的局部进位。
            logic [p_groups-1:0] prefix_generate [p_levels+1];
            logic [p_groups-1:0] prefix_propagate [p_levels+1];
            assign prefix_generate[0] = group_generate;
            assign prefix_propagate[0] = group_propagate;
            for (genvar level = 0; level < p_levels; level++) begin : g_level
                for (genvar group = 0; group < p_groups; group++) begin : g_node
                    if ((group % (2 << level)) >= (1 << level)) begin : g_merge
                        localparam int unsigned p_prefix_end =
                            (group / (2 << level)) * (2 << level) + (1 << level) - 1;
                        // 保留实际归并节点，避免组间前缀被重新串接为长组合路径。
                        (* keep = (group < p_groups - 1) *) logic merged_generate;
                        assign merged_generate = prefix_generate[level][group] |
                            (prefix_propagate[level][group] & prefix_generate[level][p_prefix_end]);
                        assign prefix_generate[level+1][group] = merged_generate;
                        assign prefix_propagate[level+1][group] = prefix_propagate[level][group] &
                            prefix_propagate[level][p_prefix_end];
                    end else begin : g_pass
                        assign prefix_generate[level+1][group] = prefix_generate[level][group];
                        assign prefix_propagate[level+1][group] = prefix_propagate[level][group];
                    end
                end
            end
            for (genvar group = 0; group < p_groups; group++) begin : g_carry
                assign group_carry[group+1] = prefix_generate[p_levels][group] |
                    (i_carry & prefix_propagate[p_levels][group]);
            end
        end else begin : g_compact_prefix
            // 每个边界独立归并低位各组的产生条件，输入进位通过整段传播条件进入。
            for (genvar boundary = 0; boundary < p_groups; boundary++) begin : g_prefix
                logic [boundary:0] generate_terms;
                for (genvar term = 0; term <= boundary; term++) begin : g_term
                    if (term == boundary) begin : g_last
                        assign generate_terms[term] = group_generate[term];
                    end else begin : g_lower
                        assign generate_terms[term] = group_generate[term] &
                            (&group_propagate[term+1 +: boundary-term]);
                    end
                end
                assign group_carry[boundary+1] = (|generate_terms) |
                    (i_carry & (&group_propagate[0 +: boundary+1]));
            end
        end
    end
endmodule

`default_nettype wire
