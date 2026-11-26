// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 下一卷积核读取同时检查坐标、填充、数据命中和提前准备资格。
(* keep_hierarchy = "yes" *)
module conv_stream_tap_request (
  input wire logic i_selected, // 当前选择下一卷积核位置。
  input wire logic i_address_valid, // 当前坐标及地址上下文有效。
  input wire logic i_next_padding, // 下一卷积核位置需要填充。
  input wire logic i_word_equal, // 下一位置与已保存数据字相同。
  input wire logic i_padding, // 当前输入位置需要填充。
  input wire logic i_context, // 下一位置已有有效读取上下文。
  output logic o_request // 下一卷积核位置需要请求缓存读取。
);
  assign o_request = i_selected && i_address_valid && !i_next_padding &&
      (!i_word_equal || i_padding) && i_context;
endmodule

`default_nettype wire
