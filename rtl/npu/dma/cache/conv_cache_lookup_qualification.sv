// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 已保存来源与预读来源分别完成计算，较晚的预读比较只进入这一层资格选择。
module conv_cache_lookup_qualification (
  input wire logic i_stored_conflict /* 已保存来源的读写冲突 */, i_stored_valid /* 存储器读出的有效位 */, i_preview_selected /* 选择预读来源 */ , // 已保存来源的读写冲突；存储器读出的有效位；选择预读来源
  input wire logic i_preview_set_match /* 预读组号与填充组号匹配 */, i_preview_word_match /* 预读字位置与填充字位置匹配 */ , // 预读组号与填充组号匹配；预读字位置与填充字位置匹配
  input wire logic i_data_write /* 本周期写入缓存数据 */, i_metadata_write /* 本周期完成元数据写入 */ , // 本周期写入缓存数据；本周期完成元数据写入
  output logic o_conflict /* 当前读取存在写入冲突 */, o_valid /* 读取或传输有效结果 */  // 当前读取存在写入冲突；读取或传输有效结果
);
  assign o_conflict = i_stored_conflict ||
      (i_preview_selected && i_preview_set_match && i_preview_word_match && i_data_write);
  assign o_valid = i_stored_valid ||
      (i_preview_selected && !(i_preview_set_match &&
        (i_metadata_write || (i_data_write && i_preview_word_match))));
endmodule

`default_nettype wire
