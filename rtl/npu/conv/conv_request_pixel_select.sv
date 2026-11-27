// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 为已寄存的缓存请求选择像素位置或输入行坐标等固定宽度字段。
// 描述符候选分为四组，运行候选独立归并，末级同时选择来源与完整结果。
module conv_request_pixel_select #(
  parameter int p_width = 32
) (
  input wire logic i_descriptor, // 当前请求选用描述符候选
  input wire logic i_row, // 运行请求选用下一输出行
  input wire logic i_tap, // 运行请求选用下一卷积核位置
  input wire logic [9:0] i_incoming_select, // 十个描述符候选的并行选择位
  input wire logic [9:0][p_width-1:0] i_incoming_pixel, // 十个描述符候选的完整字段值
  input wire logic [2:0][p_width-1:0] i_running_pixel, // 下一行、下一卷积核位置和当前位置的字段值
  output logic [p_width-1:0] o_pixel // 当前请求选择的完整字段值
);
  for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
    (* keep = "true" *) logic [3:0] incoming_group;
    (* keep = "true" *) logic running_pixel;
    for (genvar group_index = 0; group_index < 4; group_index++) begin : g_group
      localparam int p_count = group_index == 3 ? 1 : 3;
      logic [p_count-1:0] candidate;
      for (genvar item = 0; item < p_count; item++) begin : g_candidate
        assign candidate[item] = i_incoming_pixel[3*group_index+item][bit_index];
      end
      onehot_mux_group #(.p_count(p_count)) u_group (
        .i_select(i_incoming_select[3*group_index+:p_count]), .i_data(candidate),
        .o_data(incoming_group[group_index])
      );
    end
    assign running_pixel = (i_row & i_running_pixel[0][bit_index]) |
        (!i_row & i_tap & i_running_pixel[1][bit_index]) |
        (!i_row & !i_tap & i_running_pixel[2][bit_index]);
    assign o_pixel[bit_index] = (i_descriptor & (|incoming_group)) |
        (!i_descriptor & running_pixel);
  end
endmodule

`default_nettype wire
