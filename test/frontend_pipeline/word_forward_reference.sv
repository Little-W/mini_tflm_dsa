// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 完整字标签已经选择后的地址计算与匹配参考模型。
module reference_word_addresses #(
  parameter int unsigned p_word_shift = 2,
  parameter bit p_register_descriptor = 1'b1,
  parameter bit p_preview_registered = 1'b0
) (
  input logic [31:0] i_word_addr, // 当前保存数据字的地址
  input logic [31:0] i_addr, // 当前运行通道地址
  input logic [31:0] i_row_base_addr, // 当前输出行的字节基址
  input logic [31:0] i_row_group_base, // 当前输出行的通道组基址
  input logic [31:0] i_window_addr, // 已保存窗口的字节基址
  input logic [31:0] i_window_group_base, // 已保存窗口的通道组基址
  input logic [31:0] i_tap_step_bytes, // 相邻核列的字节步长
  input logic [31:0] i_tap_wrap_bytes, // 核列回绕的字节步长
  input logic [31:0] i_tap_pair_bytes, // 相邻核行之间的字节步长
  input logic [31:0] i_row_step_bytes, // 相邻输出列的字节步长
  input logic [31:0] i_row_wrap_bytes, // 输出列回绕的字节步长
  input logic [31:0] i_next_row_addr, // 下一输出行的字节地址
  input logic [15:0] i_kx0_q, // 当前描述符的卷积核列
  input logic i_row_wrap, // 当前输出行在列方向回绕
  input logic i_incoming_tap_wrap, // 待接收描述符在核列方向回绕
  input logic i_q_equal, // 待接收归约位置与当前描述符相同
  input logic i_position_previous_row, // 窗口复用前一卷积核行
  input logic i_position_forward_tap, // 窗口复用后一卷积核列
  input logic i_position_backward_tap, // 窗口复用前一卷积核列
  input logic i_next_position_fast, // 待接收描述符复用下一空间窗口
  input logic i_next_tile_fast, // 待接收描述符紧随当前空间分块
  output logic [6:0][1:0][31:0] o_candidate_address, // 七种候选的字节地址和通道组地址
  output logic o_incoming_word_equal, // 待接收描述符命中保存的数据字
  output logic o_incoming_live_word_equal, // 待接收描述符命中当前运行数据字
  output logic [1:0] o_next_row_word_match, // 下一行与保存字及运行字的匹配结果
  output logic [1:0] o_incoming_advanced_word_match // 窗口分块及跳核候选的数据字匹配结果
);

  //! 0. 辅助信号
  //! -------------

  logic [6:0][1:0][31:0] incoming_address_i_a;
  logic [6:0][1:0][31:0] incoming_address_i_b;
  logic [6:0][1:0] unused_incoming_address_carry;
  logic [6:0][1:0] incoming_candidate_word_match;
  logic [1:0] incoming_window_word_match;
  logic [1:0] incoming_skip_word_match;

  //! 1. 计算地址及字匹配
  //! ---------------------

  // 接收周期的候选地址与数据字匹配支持提前请求，提交后的检查确认运行数据来源。
  if (!p_register_descriptor || p_preview_registered) begin : g_direct_incoming_word
    logic [1:0] base_word_match, selected_word_match;
    for (genvar target = 0; target < 2; target++) begin : g_target
      logic [31-p_word_shift:0] target_word;
      assign target_word = target == 0 ? i_word_addr[31:p_word_shift] : i_addr[31:p_word_shift];
      conv_descriptor_match #(.p_width(32-p_word_shift)) u_base_match (
        .i_a(i_row_base_addr[31:p_word_shift]), .i_b(target_word),
        .o_equal(base_word_match[target])
      );
      // 基址、核步进和核换行分别完成比较，归约位置只选择一位结果。
      assign selected_word_match[target] = i_q_equal ? base_word_match[target] :
          (i_incoming_tap_wrap ? incoming_candidate_word_match[1][target] :
                                incoming_candidate_word_match[0][target]);
    end
`ifdef SYNTHESIS
    assign {o_incoming_live_word_equal, o_incoming_word_equal} = selected_word_match;
`else
    logic [31:0] incoming_delta;
    logic [p_word_shift:0] incoming_step_low_sum, incoming_wrap_low_sum;
    logic [31-p_word_shift:0] incoming_word_i_a, incoming_word_i_b, incoming_word_i_target;
    logic [31-p_word_shift:0] incoming_live_word_i_target;
    logic incoming_word_i_carry_in;
    logic [1:0] reference_word_match;
    assign incoming_delta = i_q_equal ? 32'd0 :
      (i_incoming_tap_wrap ? i_tap_wrap_bytes : i_tap_step_bytes);
    assign incoming_word_i_carry_in = !i_q_equal &&
      (i_incoming_tap_wrap ? incoming_wrap_low_sum[p_word_shift] : incoming_step_low_sum[p_word_shift]);
    // 两种步长的低位进位并行计算，晚到的描述符比较只选择进位结果。
    assign incoming_step_low_sum = {1'b0, i_row_base_addr[p_word_shift-1:0]} + {1'b0, i_tap_step_bytes[p_word_shift-1:0]};
    assign incoming_wrap_low_sum = {1'b0, i_row_base_addr[p_word_shift-1:0]} + {1'b0, i_tap_wrap_bytes[p_word_shift-1:0]};
    assign incoming_word_i_a = i_row_base_addr[31:p_word_shift];
    assign incoming_word_i_b = incoming_delta[31:p_word_shift];
    assign incoming_word_i_target = i_word_addr[31:p_word_shift];
    add_equal #(.p_width(32-p_word_shift)) u_incoming_word (
      .i_a(incoming_word_i_a), .i_b(incoming_word_i_b), .i_target(incoming_word_i_target),
      .i_carry_in(incoming_word_i_carry_in), .o_equal(reference_word_match[0])
    );
    // 两个来源的数据字提前完成比较，当前传输的完成条件只选择一位命中结果。
    assign incoming_live_word_i_target = i_addr[31:p_word_shift];
    add_equal #(.p_width(32-p_word_shift)) u_incoming_live_word (
      .i_a(incoming_word_i_a), .i_b(incoming_word_i_b), .i_target(incoming_live_word_i_target),
      .i_carry_in(incoming_word_i_carry_in), .o_equal(reference_word_match[1])
    );
    always_comb begin
      // 未知位继续使用完整加法等值关系，已知地址采用并行匹配结果。
      case (^{i_row_base_addr, i_tap_step_bytes, i_tap_wrap_bytes,
              i_word_addr, i_addr, i_q_equal, i_incoming_tap_wrap})
        1'b0, 1'b1: {o_incoming_live_word_equal, o_incoming_word_equal} = selected_word_match;
        default: {o_incoming_live_word_equal, o_incoming_word_equal} = reference_word_match;
      endcase
    end
`endif
  end else begin : g_prepared_incoming_word
    assign o_incoming_word_equal = 1'b0;
    assign o_incoming_live_word_equal = 1'b0;
  end

  // 七种地址候选依次为核步进、核换行、跨两个核列、跨核行及列、
  // 已保存窗口的前向、后向、上一核行；两个端口分别计算数据和通道组地址。
  for (genvar candidate = 0; candidate < 7; candidate++) begin : g_incoming_address
    for (genvar base = 0; base < 2; base++) begin : g_base
      assign incoming_address_i_a[candidate][base] = candidate < 4 ?
        (base == 0 ? i_row_base_addr : i_row_group_base) :
        (base == 0 ? i_window_addr : i_window_group_base);
      assign incoming_address_i_b[candidate][base] =
        candidate == 1 ? i_tap_wrap_bytes : candidate == 3 ? i_tap_pair_bytes :
        candidate == 2 ? i_tap_step_bytes << 1 :
        candidate == 5 ? ~i_tap_step_bytes : candidate == 6 ? ~i_tap_pair_bytes : i_tap_step_bytes;
      if (!p_register_descriptor || p_preview_registered) begin : g_direct_sum
      parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1),
          .p_carry_select_width(16), .p_dsp_split_width(16), .p_keep_carry(1'b0)) u_sum (
        .i_a(incoming_address_i_a[candidate][base]), .i_b(incoming_address_i_b[candidate][base]),
        .i_carry((candidate == 5 || candidate == 6)), .o_sum(o_candidate_address[candidate][base]),
        .o_carry(unused_incoming_address_carry[candidate][base])
      );
      end else begin : g_saved_operands
        assign o_candidate_address[candidate][base] = '0;
        assign unused_incoming_address_carry[candidate][base] = 1'b0;
      end
    end
    if (!p_register_descriptor || p_preview_registered) begin : g_direct_word_match
    for (genvar target = 0; target < 2; target++) begin : g_word_match
      logic [p_word_shift:0] low_sum;
      logic [31-p_word_shift:0] high_i_a, high_i_b, high_i_target;
      logic high_i_carry;
      assign low_sum = {1'b0, incoming_address_i_a[candidate][0][p_word_shift-1:0]} +
        {1'b0, incoming_address_i_b[candidate][0][p_word_shift-1:0]} +
        (p_word_shift+1)'((candidate == 5 || candidate == 6));
      assign high_i_a = incoming_address_i_a[candidate][0][31:p_word_shift];
      assign high_i_b = incoming_address_i_b[candidate][0][31:p_word_shift];
      assign high_i_target = target == 0 ? i_word_addr[31:p_word_shift] : i_addr[31:p_word_shift];
      assign high_i_carry = low_sum[p_word_shift];
      add_equal #(.p_width(32-p_word_shift), .p_preserve_bits(1'b1)) u_match (
        .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
        .i_carry_in(high_i_carry), .o_equal(incoming_candidate_word_match[candidate][target])
      );
    end
    end else begin : g_saved_word_match
      assign incoming_candidate_word_match[candidate] = '0;
    end
  end
  for (genvar target = 0; target < 2; target++) begin : g_next_row_match
    logic [31-p_word_shift:0] high_i_target;
    logic [1:0] row_match;
    assign high_i_target = target == 0 ? i_word_addr[31:p_word_shift] : i_addr[31:p_word_shift];
    // 两种行步长先完成字标签比较，行末状态只选择一位匹配结果。
    for (genvar wrap = 0; wrap < 2; wrap++) begin : g_step
      logic [31:0] byte_step;
      logic [p_word_shift:0] low_sum;
      assign byte_step = wrap == 0 ? i_row_step_bytes : i_row_wrap_bytes;
      assign low_sum = {1'b0, i_row_base_addr[p_word_shift-1:0]} +
          {1'b0, byte_step[p_word_shift-1:0]};
      add_equal #(.p_width(32-p_word_shift), .p_preserve_bits(1'b1)) u_match (
        .i_a(i_row_base_addr[31:p_word_shift]), .i_b(byte_step[31:p_word_shift]),
        .i_target(high_i_target), .i_carry_in(low_sum[p_word_shift]), .o_equal(row_match[wrap])
      );
    end
`ifdef SYNTHESIS
    assign o_next_row_word_match[target] = i_row_wrap ? row_match[1] : row_match[0];
`else
    always_comb begin
      case (^{i_row_base_addr, i_row_step_bytes, i_row_wrap_bytes, i_row_wrap, high_i_target})
        1'b0, 1'b1: o_next_row_word_match[target] = i_row_wrap ? row_match[1] : row_match[0];
        default: o_next_row_word_match[target] = i_next_row_addr[31:p_word_shift] == high_i_target;
      endcase
    end
`endif
    assign incoming_window_word_match[target] = i_position_previous_row ? incoming_candidate_word_match[6][target] :
      i_position_forward_tap ? incoming_candidate_word_match[4][target] :
      i_position_backward_tap ? incoming_candidate_word_match[5][target] :
      i_window_addr[31:p_word_shift] == high_i_target;
    assign incoming_skip_word_match[target] = i_kx0_q != 16'd0 ?
      incoming_candidate_word_match[3][target] : incoming_candidate_word_match[2][target];
    assign o_incoming_advanced_word_match[target] = i_next_position_fast ? incoming_window_word_match[target] :
      i_next_tile_fast ? o_next_row_word_match[target] : incoming_skip_word_match[target];
  end

endmodule

`default_nettype wire
