// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在已经完成移位的两组释放位置之间选择一位，并合并各自的禁止释放标志。
// 来源信号采用过程条件语义，未知来源选择保存请求，禁止释放标志保留条件合并语义。
(* keep_hierarchy = "yes" *)
module conv_cache_retire_select (
  input wire logic i_use_incoming, // 当前处理采用正式输入请求的元数据
  input wire logic i_incoming_disabled, // 正式输入请求禁止释放缓存行
  input wire logic i_saved_disabled, // 已保存请求禁止释放缓存行
  input wire logic i_incoming_bit, // 正式输入请求完成移位后的一位
  input wire logic i_saved_bit, // 已保存请求完成移位后的一位
  output logic o_bit // 当前处理对应的释放序号位
);
  always_comb begin
    if (i_use_incoming) o_bit = i_incoming_disabled ? 1'b1 : i_incoming_bit;
    else o_bit = i_saved_disabled ? 1'b1 : i_saved_bit;
  end
endmodule

`default_nettype wire
