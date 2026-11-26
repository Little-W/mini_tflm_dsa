// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据参数写入索引、并行存储组数量和装载上限确定最后一次写入。
(* keep_hierarchy = "yes" *)
module requant_parameter_last #(
    parameter int unsigned p_index_width = 9,
    parameter int unsigned p_banks = 2,
    parameter int unsigned p_word = 0
) (
    input wire logic [p_index_width-1:0] i_index, // 当前参数写入索引
    input wire logic [31:0] i_limit, // 完整参数装载数量上限
    output logic o_last // 本次写入完成全部参数装载
);
    wire [p_index_width-1:0] word_index = i_index + p_index_width'(p_word);
    localparam int p_last_step = (p_banks == 2 && p_word == 1) ? 3 : p_banks;
    localparam int p_compare_index_width = p_index_width < 32 ? p_index_width : 32;
    localparam int p_step_width = p_last_step <= 1 ? 1 : $clog2(p_last_step+1);
    localparam int p_last_compare_width =
        (p_compare_index_width > p_step_width ? p_compare_index_width : p_step_width) + 1;
    logic [p_last_compare_width-1:0] parameter_index_extended, parameter_limit_inverse;
    logic [p_last_compare_width-1:0] parameter_compare_sum, parameter_compare_carry;
    logic [p_last_compare_width-1:0] unused_parameter_difference;
    logic parameter_compare_reached, parameter_limit_in_range;
    if (p_banks == 2 && p_word == 1) begin : g_next_word
      // 加一回绕单独判断，正常写入的末次资格直接使用加一前的索引。
      assign parameter_index_extended = p_last_compare_width'(32'(i_index));
    end else begin : g_current_word
      assign parameter_index_extended = p_last_compare_width'(32'(word_index));
    end
    // 索引和步长的静态位宽决定可达范围，上限的其余高位独立参与判断。
    if (p_last_compare_width < 32) begin : g_limit_high
      assign parameter_limit_in_range = !(|i_limit[31:p_last_compare_width]);
    end else begin : g_limit_full
      assign parameter_limit_in_range = 1'b1;
    end
    assign parameter_limit_inverse = ~p_last_compare_width'(i_limit);
    // 三操作数先保存各位进位，最高进位直接表示末次写入资格。
    assign parameter_compare_sum = parameter_index_extended ^ parameter_limit_inverse ^
        p_last_compare_width'(p_last_step);
    assign parameter_compare_carry = ((parameter_index_extended & parameter_limit_inverse) |
        ((parameter_index_extended | parameter_limit_inverse) &
        p_last_compare_width'(p_last_step))) << 1;
    parallel_prefix_add #(
        .p_width(p_last_compare_width), .p_group_width(4), .p_preserve_groups(1'b1)
    ) u_parameter_reached (
        .i_a(parameter_compare_sum), .i_b(parameter_compare_carry), .i_carry(1'b1),
        .o_sum(unused_parameter_difference), .o_carry(parameter_compare_reached)
    );
    always_comb begin
      o_last = parameter_limit_in_range && parameter_compare_reached;
      if (p_banks == 2 && p_word == 1) begin
        if (&i_index[p_compare_index_width-1:0])
          o_last = i_limit <= 32'(p_banks);
      end
`ifndef SYNTHESIS
      case (^{i_index, word_index, i_limit})
        1'b0, 1'b1: begin end
        default: o_last =
            ({1'b0, 32'(word_index)} + 33'(p_banks)) >=
            {1'b0, i_limit};
      endcase
`endif
    end
endmodule

`default_nettype wire
