// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 配置、描述符和运行分支只在末级选择完整的错误标志。
(* keep_hierarchy = "yes" *)
module conv_im2col_error_select (
  input wire logic i_configuration, // 当前周期接收新配置。
  input wire logic i_commit, // 当前周期接收描述符。
  input wire logic [1:0] i_configuration_value, // 配置分支的分块错误和累计错误。
  input wire logic [1:0] i_commit_value, // 描述符分支的分块错误和累计错误。
  input wire logic [1:0] i_operation_value, // 运行分支的分块错误和累计错误。
  output logic [1:0] o_value // 按接收优先级选择的完整错误标志。
);
  assign o_value = i_configuration ? i_configuration_value :
      (i_commit ? i_commit_value : i_operation_value);
endmodule
`default_nettype wire
