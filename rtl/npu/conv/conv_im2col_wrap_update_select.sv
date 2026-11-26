// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 配置、描述符和流传输按既有优先级选择已准备的回绕字段。
(* keep_hierarchy = "yes" *)
module conv_im2col_wrap_update_select (
  input wire logic i_configuration, // 当前周期接收新配置。
  input wire logic i_commit, // 当前周期接收描述符。
  input wire logic i_descriptor_check, // 当前状态检查已保存描述符。
  input wire logic i_stream_error, // 运行请求返回错误。
  input wire logic i_stream_accept, // 当前运行输出被接收。
  input wire logic i_running, // 当前状态属于数据输出阶段。
  input wire logic [3:0][5:0] i_candidate, // 配置、描述符、输出推进和解码的写入与回绕候选。
  output logic [2:0] o_write, // 输出行、当前核位置和初始核位置的写入资格。
  output logic [2:0] o_value // 对应三个字段的回绕值。
);
  always_comb begin
    {o_write, o_value} = '0;
    case (1'b1)
      i_configuration: {o_write, o_value} = i_candidate[0];
      i_commit: {o_write, o_value} = i_candidate[1];
      i_descriptor_check: {o_write, o_value} = '0;
      i_stream_error: {o_write, o_value} = '0;
      i_stream_accept: {o_write, o_value} = i_candidate[2];
      (!i_commit && i_stream_error !== 1'b1 && i_stream_accept !== 1'b1 && i_running): {o_write, o_value} = '0;
      default: {o_write, o_value} = i_candidate[3];
    endcase
  end
endmodule
`default_nettype wire
