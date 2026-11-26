// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 下一行读取只依赖本行结束、行起点和数据字是否可直接使用。
(* keep_hierarchy = "yes" *)
module conv_stream_row_request (
  input wire logic i_selected, // 当前选择下一行推进。
  input wire logic i_last, // 当前输出为分块最后一行。
  input wire logic i_base_valid, // 行起点上下文有效。
  input wire logic i_geometry, // 当前采用独立几何准备。
  input wire logic i_padding, // 下一行位置需要填充。
  input wire logic i_word_hit, // 下一行命中可直接使用的数据字。
  output logic o_request // 下一行需要请求缓存读取。
);
  assign o_request = i_selected && !i_last && i_base_valid && !i_geometry &&
      !i_padding && !i_word_hit;
endmodule

`default_nettype wire
