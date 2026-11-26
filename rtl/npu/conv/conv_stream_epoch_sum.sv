// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 共享当前通道与配置偏移的分段和值，按传输步长选择完整十八位通道索引。
module conv_stream_epoch_sum #(
  parameter int p_lanes = 8,
  localparam int p_low_width = p_lanes > 1 ? $clog2(p_lanes+1) : 1,
  localparam int p_high_width = 18-p_low_width
) (
  input wire logic [15:0] i_offset, // 配置中保存的通道组起始偏移
  input wire logic [17:0] i_channel, // 当前完整通道坐标的低十八位
  input wire logic [p_lanes:0] i_selected, // 各传输步长的选择位
  output logic [17:0] o_sum // 已选择的通道组偏移与步长和值
);
  logic [p_low_width:0] base_low;
  logic [p_high_width-1:0] base_high;
  logic [17:0] offset;
  logic [2:0][p_high_width-1:0] high_candidate;
  logic [2:0] high_selected;
  logic [p_lanes:0][p_low_width+2:0] step_candidate;
  logic [p_low_width-1:0] selected_low;
  logic [17:0] prepared_sum, reference_sum;
  logic [p_lanes:0][17:0] reference_step;
  assign offset = {2'b0, i_offset};

  logic [p_high_width:0] high_a, high_b, high_zero, high_one_encoded;
  assign high_a = {1'b0, offset[17:p_low_width]};
  assign high_b = {1'b0, i_channel[17:p_low_width]};
  // 高段的零进位和一进位由两路普通加法并行计算，反码编码保留模加法结果。
  parallel_prefix_native_sums #(
    .p_low_width(p_high_width+1), .p_high_width(p_high_width+1)
  ) u_base (
    .i_low_a(high_a), .i_low_b(high_b),
    .i_high_a(~high_a), .i_high_b(~high_b),
    .o_low_sum(high_zero), .o_high_sum(high_one_encoded)
  );
  assign base_high = high_zero[p_high_width-1:0];
  assign base_low[p_low_width-1:0] = offset[p_low_width-1:0]+i_channel[p_low_width-1:0];
  conv_stream_epoch_low_carry #(.p_width(p_low_width)) u_low_carry (
    .i_a(offset[p_low_width-1:0]), .i_b(i_channel[p_low_width-1:0]),
    .o_carry(base_low[p_low_width])
  );
  assign high_candidate[0] = base_high;
  assign high_candidate[1] = ~high_one_encoded[p_high_width-1:0];
  conv_stream_epoch_increment #(.p_width(p_high_width), .p_increment(2)) u_two (
    .i_value(base_high), .o_value(high_candidate[2])
  );
  for (genvar step = 0; step <= p_lanes; step++) begin : g_step
    logic [p_low_width+1:0] low_sum;
    logic [17:0] sum_bits, carry_bits;
    assign low_sum = {1'b0, base_low} + (p_low_width+2)'(step);
    assign step_candidate[step][p_low_width-1:0] = low_sum[p_low_width-1:0];
    for (genvar carry_class = 0; carry_class < 3; carry_class++) begin : g_carry
      conv_stream_epoch_carry_bit #(
        .p_width(p_low_width+1), .p_step(step), .p_carry(carry_class)
      ) u_carry (
        .i_low(base_low), .o_selected(step_candidate[step][p_low_width+carry_class])
      );
    end
    // 四态参照保留完整的逐位压缩与定宽加法表达式。
    assign sum_bits = offset ^ i_channel ^ 18'(step);
    assign carry_bits = ((offset & i_channel) | ((offset | i_channel) & 18'(step))) << 1;
    assign reference_step[step] = sum_bits + carry_bits;
  end
  // 同一高段进位的所有步长先归并，完整高段只保留三个共享候选。
  conv_group_range_select #(.p_choices(p_lanes+1), .p_width(p_low_width+3)) u_step (
    .i_select(i_selected), .i_data(step_candidate), .o_data({high_selected, selected_low})
  );
  assign prepared_sum[p_low_width-1:0] = selected_low;
  (* keep_hierarchy = "yes" *)
  onehot_mux #(.p_choices(3), .p_width(p_high_width)) u_high (
    .i_select(high_selected), .i_data(high_candidate), .o_data(prepared_sum[17:p_low_width])
  );
  always_comb begin
    reference_sum = '0;
    for (int step = 0; step <= p_lanes; step++)
      reference_sum |= {18{i_selected[step]}} & reference_step[step];
    o_sum = reference_sum;
    case (^{i_offset, i_channel})
      1'b0, 1'b1: o_sum = prepared_sum;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
