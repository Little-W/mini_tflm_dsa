// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 独立比较一个固定步长对应的进位区间，使选择结果只依赖完整低段和值。
(* keep_hierarchy = "yes" *)
module conv_stream_epoch_carry_bit #(
  parameter int p_width = 5,
  parameter int p_step = 0,
  parameter int p_carry = 0
) (
  input wire logic [p_width-1:0] i_low, // 两个低段操作数相加后的完整结果
  output logic o_selected // 当前和值加入步长后产生指定进位
);
  localparam int p_first_limit = (1 << (p_width-1))-p_step;
  localparam int p_second_limit = (1 << p_width)-p_step;
  if (p_carry == 0) begin : g_zero
    assign o_selected = i_low < p_width'(p_first_limit);
  end else if (p_carry == 1) begin : g_one
    if (p_step == 0) begin : g_full_range
      assign o_selected = i_low >= p_width'(p_first_limit);
    end else begin : g_bounded_range
      assign o_selected = (i_low >= p_width'(p_first_limit)) &&
          (i_low < p_width'(p_second_limit));
    end
  end else begin : g_two
    if (p_step == 0) begin : g_no_second
      assign o_selected = 1'b0;
    end else begin : g_second
      assign o_selected = i_low >= p_width'(p_second_limit);
    end
  end
endmodule

`default_nettype wire
