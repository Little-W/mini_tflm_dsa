// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查当前和下一片段的重复标签，并选择本次预取描述的重复结果。
(* keep_hierarchy = "yes" *)
module conv_cache_offer_duplicate #(
  parameter int p_tag_width = 25,
  parameter int p_entries = 10
) (
  input wire logic i_fill_active, // 当前存在尚未完成的填充
  input wire logic [p_tag_width-1:0] i_fill_tag, // 在途填充的完整缓存行标签
  input wire logic [1:0][p_tag_width-1:0] i_offer_tag, // 当前片段和下一片段的标签
  input wire logic [1:0][p_entries-1:0] i_valid, // 两个片段各自可参与比较的条目有效位
  input wire logic [1:0][p_entries-1:0][p_tag_width-1:0] i_tag, // 缓存和预取队列中的条目标签
  input wire logic i_next_fragment, // 下一片段有效
  output logic o_choose_next, // 当前片段重复时选择下一片段
  output logic o_duplicate // 选中片段已经驻留或正在填充
);
  logic [1:0] fill_match, duplicate;
  for (genvar fragment=0; fragment<2; fragment++) begin : g_fragment
    (* keep = 1 *) logic [p_entries-1:0] confirmed_match;
    logic [p_entries-1:0] tag_match;
    conv_cache_snapshot_equal #(.p_width(p_tag_width)) u_fill_equal (
      .i_a(i_offer_tag[fragment]), .i_b(i_fill_tag), .o_equal(fill_match[fragment])
    );
    for (genvar entry=0; entry<p_entries; entry++) begin : g_entry
      conv_cache_snapshot_equal #(.p_width(p_tag_width)) u_equal (
        .i_a(i_offer_tag[fragment]), .i_b(i_tag[fragment][entry]), .o_equal(tag_match[entry])
      );
      // 只有确定有效且标签相等的条目覆盖在途填充判断，保持四态条件语义。
      always_comb begin
        confirmed_match[entry] = 1'b0;
        if (i_valid[fragment][entry] && tag_match[entry]) confirmed_match[entry] = 1'b1;
      end
    end
    assign duplicate[fragment] = (i_fill_active && fill_match[fragment]) || (|confirmed_match);
  end
  assign o_choose_next = duplicate[0] && i_next_fragment;
  always_comb begin
    o_duplicate = duplicate[0] && (!i_next_fragment || duplicate[1]);
    // 未知控制按过程条件的行为保持当前片段结果。
    case (^{duplicate, i_next_fragment})
      1'b0, 1'b1: begin end
      default: begin
        o_duplicate = duplicate[0];
        if (o_choose_next) o_duplicate = duplicate[1];
      end
    endcase
  end
endmodule

`default_nettype wire
