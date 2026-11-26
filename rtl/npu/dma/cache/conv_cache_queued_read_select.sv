// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 为保持队首和消费队首分别准备读写冲突及快照资格，接收事件只选择最终结果。
// 缺失请求优先使用已保存的需求地址；空队列直接使用当前输入地址。
(* keep_hierarchy = "yes" *)
module conv_cache_queued_read_select (
  input wire logic i_miss, // 前台正在处理缺失请求
  input wire logic i_empty, // 请求队列当前为空
  input wire logic i_many, // 请求队列包含多个条目
  input wire logic i_fire, // 当前需求请求被接收
  input wire logic i_input_valid, // 当前输入请求有效
  input wire logic [3:0][1:0] i_result, // 队首、下一项、输入及缺失请求的冲突与快照资格
  output logic [1:0] o_result // 所选地址的冲突与快照资格
);
  //! 0. Helper
  //! ---------

  logic [1:0] held_result, advanced_result;

  //! 1. Candidate Selection
  //! ----------------------

  assign held_result = i_empty ? i_result[2] : i_result[0];
  assign advanced_result = i_empty ? i_result[2] :
      (i_many ? i_result[1] : (i_input_valid ? i_result[2] : i_result[0]));

  //! 2. Output Generation
  //! --------------------

  assign o_result = i_miss ? i_result[3] : (i_fire ? advanced_result : held_result);
endmodule

`default_nettype wire
