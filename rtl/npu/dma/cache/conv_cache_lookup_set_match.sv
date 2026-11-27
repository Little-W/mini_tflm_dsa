// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行比较旁路、缺失处理和当前工作请求的缓存组号，末级选择替换快照的冲突结果。
// 已知状态只选择单比特比较结果，未知状态保留完整组号的逐位条件合并语义。
(* keep_hierarchy = "yes" *)
module conv_cache_lookup_set_match #(
  parameter int p_set_width = 4
) (
  input wire logic i_bypass, // 当前请求使用已经完成的需求填充旁路
  input wire logic i_miss, // 前台状态正在处理需求缺失
  input wire logic [p_set_width-1:0] i_fill_set, // 旁路需求填充的缓存组号
  input wire logic [p_set_width-1:0] i_demand_set, // 已保存需求请求的缓存组号
  input wire logic [p_set_width-1:0] i_work_set, // 当前工作请求的缓存组号
  input wire logic [p_set_width-1:0] i_select_set, // 替换选择快照保存的缓存组号
  output logic o_match // 当前查询组号与替换选择快照的组号相同
);
  //! 0. 并行候选结果
  //! ----------------

  logic fill_match;
  logic demand_match;
  logic work_match;
  logic [p_set_width-1:0] selected_set;

  assign fill_match = i_fill_set == i_select_set;
  assign demand_match = i_demand_set == i_select_set;
  assign work_match = i_work_set == i_select_set;
  assign selected_set = i_bypass ? i_fill_set : (i_miss ? i_demand_set : i_work_set);

  //! 1. 状态末级选择
  //! ----------------

  always_comb begin
    o_match = i_bypass ? fill_match : (i_miss ? demand_match : work_match);
    // 过程式 case 区分确定控制与未知控制，保留条件运算符的四态逐位合并。
    case ({i_bypass, i_miss})
      2'b00, 2'b01, 2'b10, 2'b11: begin end
      default: o_match = selected_set == i_select_set;
    endcase
  end
endmodule

`default_nettype wire
