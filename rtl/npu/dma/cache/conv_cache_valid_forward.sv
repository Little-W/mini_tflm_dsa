// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 清除和填充的地址匹配独立完成，最终转发保留清除优先级。
module conv_cache_valid_forward (
  input wire logic i_clear_write /* 本周期写入清除有效位 */, i_clear_match /* 读取组号命中清除组号 */ , // 本周期写入清除有效位；读取组号命中清除组号
  input wire logic i_fill_write /* 本周期写入填充有效位 */, i_fill_match /* 读取组号命中填充组号 */, i_fill_valid /* 填充写入的有效位 */, i_stored_valid /* 存储器读出的有效位 */ , // 本周期写入填充有效位；读取组号命中填充组号；填充写入的有效位；存储器读出的有效位
  output logic o_valid // 读取或传输有效结果
);
  assign o_valid = (i_clear_write && i_clear_match) ? 1'b0 :
      ((i_fill_write && i_fill_match) ? i_fill_valid : i_stored_valid);
endmodule

`default_nettype wire
