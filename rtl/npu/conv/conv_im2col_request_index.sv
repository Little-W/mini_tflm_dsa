// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 生成描述符和运行请求的完整窗口索引，并同步选择请求的输入行坐标。
// 像素与输入行使用相同来源控制，完整像素先归并再计算窗口索引。
module conv_im2col_request_index #(
  parameter int p_coord_width = 35,
  parameter bit p_register_descriptor = 1'b0,
  parameter bit p_descriptor_preview = 1'b0
) (
  input wire logic i_short_pixel, // 短像素模式下按窗口粒度缩放像素索引。
  input wire logic [4:0] i_index_shift, // 窗口索引的右移位数。
  input wire logic i_descriptor, // 当前请求选用描述符候选。
  input wire logic i_row, // 当前请求选用下一输出行。
  input wire logic i_tap, // 当前请求选用下一卷积核位置。
  input wire logic [9:0] i_incoming_select, // 十个描述符来源的并行选择位。
  input wire logic [9:0][31:0] i_incoming_pixel, // 描述符像素索引候选。
  input wire logic [9:0][p_coord_width-1:0] i_incoming_y, // 描述符输入行坐标候选。
  input wire logic [31:0] i_saved_pixel, // 已准备描述符的像素索引。
  input wire logic [2:0][31:0] i_running_pixel, // 下一行、下一核位置和当前像素索引。
  input wire logic [2:0][p_coord_width-1:0] i_running_y, // 对应三个运行位置的输入行坐标。
  input wire logic [31:0] i_current_index, // 当前像素经过模式选择后的完整索引。
  output logic [31:0] o_incoming_index, // 描述符来源的完整窗口索引。
  output logic [31:0] o_request_index, // 当前请求的完整窗口索引。
  output logic [31:0] o_request_pixel, // 当前请求在窗口缩放之前的完整像素位置。
  output logic [p_coord_width-1:0] o_request_y // 当前请求的输入行坐标。
);

  if (!p_register_descriptor || p_descriptor_preview) begin : g_parallel_descriptor
    logic [31:0] incoming_pixel, request_pixel;
    logic [p_coord_width-1:0] incoming_y, request_y_full;
    localparam int p_saved_y_width = p_coord_width < 16 ? p_coord_width : 16;
    logic [9:0][p_saved_y_width-1:0] incoming_y_low;
    logic [2:0][p_saved_y_width-1:0] running_y_low;
    logic [3:0] request_select;
    logic [3:0][p_coord_width-1:0] request_y_candidate;
    logic [31:0] incoming_shared, request_shared;
    logic [4:0] effective_shift;
`ifndef SYNTHESIS
    logic [9:0][p_coord_width+31:0] qualified_incoming_candidate;
`endif

    // 像素与行坐标共用来源控制，像素选择保留各组三路结果。
    // 两种字段分别归并，未使用的行坐标高位仍可由综合工具删除。
    for (genvar candidate = 0; candidate < 10; candidate++) begin : g_incoming
      assign incoming_y_low[candidate] = i_incoming_y[candidate][p_saved_y_width-1:0];
`ifndef SYNTHESIS
      assign qualified_incoming_candidate[candidate] =
          {i_incoming_y[candidate], i_incoming_pixel[candidate]} &
          {(p_coord_width+32){i_descriptor}};
`endif
    end
    // 组合描述符路径保留提交索引的分组；寄存模式允许删除未使用的提交候选。
    (* keep_hierarchy = !p_register_descriptor *) onehot_mux #(
      .p_choices(10), .p_width(32), .p_preserve_groups(!p_register_descriptor)
    ) u_incoming (
      .i_select(i_incoming_select), .i_data(i_incoming_pixel), .o_data(incoming_pixel)
    );
    onehot_mux #(.p_choices(10), .p_width(p_coord_width)) u_incoming_y (
      .i_select(i_incoming_select), .i_data(i_incoming_y), .o_data(incoming_y)
    );
    assign request_select[0] = i_descriptor;
    assign request_select[1] = !i_descriptor && i_row;
    assign request_select[2] = !i_descriptor && !i_row && i_tap;
    assign request_select[3] = !i_descriptor && !i_row && !i_tap;
    assign request_y_candidate[0] = incoming_y;
    for (genvar candidate = 0; candidate < 3; candidate++) begin : g_running
      assign request_y_candidate[candidate+1] = i_running_y[candidate];
      assign running_y_low[candidate] = i_running_y[candidate][p_saved_y_width-1:0];
    end
    (* keep_hierarchy = "yes" *) conv_request_pixel_select u_request (
      .i_descriptor(i_descriptor), .i_row(i_row), .i_tap(i_tap),
      .i_incoming_select(i_incoming_select), .i_incoming_pixel(i_incoming_pixel),
      .i_running_pixel(i_running_pixel), .o_pixel(request_pixel)
    );
    onehot_mux #(.p_choices(4), .p_width(p_coord_width)) u_request_y (
      .i_select(request_select), .i_data(request_y_candidate), .o_data(request_y_full)
    );
    // 输入行低十六位与请求同步保存，分组结果直接进入末级来源选择。
    (* keep_hierarchy = "yes" *)
    conv_request_pixel_select #(.p_width(p_saved_y_width)) u_request_y_low (
      .i_descriptor(i_descriptor), .i_row(i_row), .i_tap(i_tap),
      .i_incoming_select(i_incoming_select), .i_incoming_pixel(incoming_y_low),
      .i_running_pixel(running_y_low), .o_pixel(o_request_y[p_saved_y_width-1:0])
    );
    if (p_coord_width > p_saved_y_width) begin : g_complete_y
      assign o_request_y[p_coord_width-1:p_saved_y_width] =
          request_y_full[p_coord_width-1:p_saved_y_width];
    end
    assign o_request_pixel = request_pixel;
    // 模式只决定有效移位量，两个完整像素索引共用相同的移位控制。
    assign effective_shift = i_index_shift & {5{i_short_pixel}};
    always_comb begin
      incoming_shared = i_short_pixel ? incoming_pixel >> i_index_shift : incoming_pixel;
      request_shared = i_short_pixel ? request_pixel >> i_index_shift : request_pixel;
      // 未知控制输入保留条件选择的逐位合并结果。
      case (^{i_short_pixel, i_index_shift})
        1'b0, 1'b1: begin
          incoming_shared = incoming_pixel >> effective_shift;
          request_shared = request_pixel >> effective_shift;
        end
        default: begin end
      endcase
    end

    always_comb begin
      o_incoming_index = incoming_shared;
      o_request_index = request_shared;
`ifndef SYNTHESIS
      // 含未知输入时，各候选独立求值并保留按位选择的四态传播。
      if ((^{i_short_pixel, i_index_shift, i_incoming_select, i_incoming_pixel,
              request_select[3:1], qualified_incoming_candidate,
              i_running_y, i_running_pixel}) === 1'bx) begin
        o_incoming_index = '0;
        o_request_index = '0;
        for (int candidate = 0; candidate < 10; candidate++) begin
          o_incoming_index |= (i_short_pixel ? i_incoming_pixel[candidate] >> i_index_shift :
              i_incoming_pixel[candidate]) & {32{i_incoming_select[candidate]}};
          o_request_index |= (i_short_pixel ? i_incoming_pixel[candidate] >> i_index_shift :
              i_incoming_pixel[candidate]) & {32{i_incoming_select[candidate] & i_descriptor}};
        end
        o_request_index |= (i_short_pixel ? i_running_pixel[0] >> i_index_shift :
            i_running_pixel[0]) & {32{request_select[1]}};
        o_request_index |= (i_short_pixel ? i_running_pixel[1] >> i_index_shift :
            i_running_pixel[1]) & {32{request_select[2]}};
        o_request_index |= i_current_index & {32{request_select[3]}};
      end
`endif
    end
  end else begin : g_registered_descriptor
    logic [2:0] request_select;
    logic [2:0][p_coord_width+31:0] request_candidate;

    assign o_incoming_index = i_short_pixel ? i_saved_pixel >> i_index_shift : i_saved_pixel;
    assign request_select[0] = i_row;
    assign request_select[1] = !i_row && i_tap;
    assign request_select[2] = !i_row && !i_tap;
    assign o_request_pixel = (i_running_pixel[0] & {32{request_select[0]}}) |
        (i_running_pixel[1] & {32{request_select[1]}}) |
        (i_running_pixel[2] & {32{request_select[2]}});
    for (genvar candidate = 0; candidate < 2; candidate++) begin : g_advanced
      assign request_candidate[candidate] = {i_running_y[candidate],
          i_short_pixel ? i_running_pixel[candidate] >> i_index_shift : i_running_pixel[candidate]};
    end
    assign request_candidate[2] = {i_running_y[2], i_current_index};
    onehot_mux #(.p_choices(3), .p_width(p_coord_width+32)) u_request (
      .i_select(request_select), .i_data(request_candidate), .o_data({o_request_y, o_request_index})
    );
  end
endmodule
`default_nettype wire
