// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 同拍清除和填充分别完成地址匹配后，在六输入边界内选择查询有效位。
// 清除优先于填充，未发生匹配写入时保持存储器读出的有效位。
(* keep_hierarchy = "yes" *)
module conv_cache_valid_forward (
  input logic i_clear_write, // 本周期写入清除有效位
  input logic i_clear_match, // 当前读取组号与清除组号相同
  input logic i_fill_write, // 本周期写入填充有效位
  input logic i_fill_match, // 当前读取组号与填充组号相同
  input logic i_fill_valid, // 填充写入的有效位
  input logic i_stored_valid, // 存储器读出的有效位
  output logic o_valid // 处理同拍写入转发后的查询有效位
);
  //! 0. 同拍有效位转发
  //! ------------------

  assign o_valid = (i_clear_write && i_clear_match) ? 1'b0 :
      ((i_fill_write && i_fill_match) ? i_fill_valid : i_stored_valid);
endmodule

`default_nettype wire
