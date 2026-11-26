// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分别寻找队首以后和整个队列的首个匹配项，再选择循环次序中的第一项。
(* keep_hierarchy = "yes" *)
module conv_cache_prefetch_priority #(
  parameter int p_depth = 8,
  parameter int p_address_width = p_depth <= 1 ? 1 : $clog2(p_depth)
) (
  input wire logic [p_depth-1:0] i_match, // 各逻辑位置的代次匹配结果
  input wire logic [p_address_width-1:0] i_head, // 循环队列的起始位置
  output logic [p_depth-1:0] o_select // 按循环次序选中的独热位置
);
  //! 0. Helper
  //! ---------

  logic [p_depth-1:0] after_head, head_select;
  // 两个独立优先编码结果形成明确边界，循环选择只接收已完成的独热结果。
  (* keep = 1 *) logic [p_depth-1:0] first_any, first_after;
  logic [p_depth-1:0] selected, reference_select;
  logic any_match, any_after;

  //! 1. Candidate Selection
  //! ----------------------

  assign any_match = |i_match;
  assign any_after = |after_head;
  for (genvar slot = 0; slot < p_depth; slot++) begin : g_slot
    logic [p_depth-1:0] preceding_matches;
    assign after_head[slot] = i_match[slot] && i_head <= p_address_width'(slot);
    assign head_select[slot] = i_head == p_address_width'(slot);
    if (slot == 0) begin : g_first
      assign first_any[slot] = i_match[slot];
      assign first_after[slot] = after_head[slot];
    end else begin : g_later
      assign first_any[slot] = i_match[slot] && !(|i_match[slot-1:0]);
      assign first_after[slot] = after_head[slot] && !(|after_head[slot-1:0]);
    end
    assign selected[slot] = any_after ? first_after[slot] :
        (first_any[slot] || (!any_match && head_select[slot]));
    // 含未知位置或匹配位时，保留各位置独立检查循环优先次序的结果。
    for (genvar other = 0; other < p_depth; other++) begin : g_preceding
      if (other < slot) begin : g_lower
        assign preceding_matches[other] = i_match[other] &&
            ((i_head <= p_address_width'(other)) ||
             ((slot == p_depth-1) ? 1'b0 : i_head > p_address_width'(slot)));
      end else if (other > slot) begin : g_higher
        assign preceding_matches[other] = i_match[other] &&
            ((i_head > p_address_width'(slot)) &&
             ((other == p_depth-1) ? 1'b1 : i_head <= p_address_width'(other)));
      end else begin : g_self
        assign preceding_matches[other] = 1'b0;
      end
    end
    assign reference_select[slot] = (i_match[slot] && !(|preceding_matches)) ||
        (!any_match && head_select[slot]);
  end

  //! 2. Output Generation
  //! --------------------

  always_comb begin
    o_select = selected;
    case (^{i_match, i_head})
      1'b0, 1'b1: begin end
      default: o_select = reference_select;
    endcase
  end
endmodule

`default_nettype wire
