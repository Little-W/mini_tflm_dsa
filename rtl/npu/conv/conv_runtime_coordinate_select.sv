// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 选择输出与卷积核坐标的写入字段和值，配置、描述符、错误和运行接收保持既定优先级。
// 状态与运行候选提前准备，描述符提交只参与最后一级选择，所有字段仍在原有边沿保存。
(* keep_hierarchy = "yes" *)
module conv_runtime_coordinate_select #(
  parameter int unsigned p_fields = 6,
  parameter int unsigned p_width = 16
) (
  input logic i_cfg_write, // 当前周期接收配置并保持全部坐标。
  input logic i_tile_commit, // 当前周期选择描述符坐标候选。
  input logic i_stream_error, // 缓存响应错误使运行与状态坐标保持。
  input logic i_stream_accept, // 当前周期选择运行推进坐标候选。
  input logic [p_fields-1:0] i_descriptor_write, // 描述符候选的逐字段写入资格。
  input logic [p_fields-1:0][p_width-1:0] i_descriptor_data, // 描述符准备完成的完整坐标。
  input logic [p_fields-1:0] i_stream_write, // 运行推进候选的逐字段写入资格。
  input logic [p_fields-1:0][p_width-1:0] i_stream_data, // 输出行或卷积核推进后的完整坐标。
  input logic [p_fields-1:0] i_state_write, // 状态解码候选的逐字段写入资格。
  input logic [p_fields-1:0][p_width-1:0] i_state_data, // 状态解码得到的完整坐标。
  output logic [p_fields-1:0] o_write, // 当前边沿需要保存的坐标字段。
  output logic [p_fields-1:0][p_width-1:0] o_data // 与各字段写入资格对应的坐标值。
);
  (* keep = "true" *) logic [p_fields-1:0] runtime_write;

  // 错误优先于运行推进，逐字段资格在描述符选择前完成。
  always_comb begin
    runtime_write = i_state_write;
    if (i_stream_error) runtime_write = '0;
    else if (i_stream_accept) runtime_write = i_stream_write;

    o_write = runtime_write;
    if (i_cfg_write) o_write = '0;
    else if (i_tile_commit) o_write = i_descriptor_write;

    // 顺序 if 保留未知控制跳过分支及被选数据中的 X、Z。
    o_data = i_state_data;
    if (i_tile_commit) o_data = i_descriptor_data;
    else if (i_stream_accept) o_data = i_stream_data;
  end
endmodule
`default_nettype wire
