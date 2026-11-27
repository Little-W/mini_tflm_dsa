// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 各描述符来源先计算保存字和返回字的复用资格，再用完整来源选择位归并命中结果。
(* keep_hierarchy = "yes" *)
module conv_incoming_word_hit (
  input wire logic [9:0] i_select, // 当前描述符的十个互斥来源选择位
  input wire logic [9:0][1:0] i_candidate, // 每个来源与保存字及运行字的匹配结果
  input wire logic i_response_forward, // 当前操作直接采用缓存返回数据
  input wire logic i_saved_valid, // 保存的数据字有效且字节地址满足数据字边界
  input wire logic i_reference, // 完整条件表达式对应的四态命中结果
  output logic o_hit // 描述符首数据字可以直接复用
);
  (* keep = "true" *) logic [9:0] candidate_hit;
  logic selected_hit;
  for (genvar candidate = 0; candidate < 10; candidate++) begin : g_candidate
    assign candidate_hit[candidate] = i_response_forward ? i_candidate[candidate][1] :
        i_saved_valid && i_candidate[candidate][0];
  end
  onehot_mux #(.p_choices(10), .p_width(1), .p_preserve_groups(1'b1)) u_select (
    .i_select(i_select), .i_data(candidate_hit), .o_data(selected_hit)
  );
  // 未知字段沿用完整条件表达式，已知字段只经过分组来源选择。
  always_comb begin
    o_hit = i_reference;
    case (^{i_select, i_candidate, i_response_forward, i_saved_valid, i_reference})
      1'b0, 1'b1: o_hit = selected_hit;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
