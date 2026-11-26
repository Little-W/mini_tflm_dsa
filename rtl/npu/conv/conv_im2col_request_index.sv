// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 生成描述符和运行请求的完整窗口索引，并同步选择请求的输入行坐标。
// 描述符像素与输入行共用一次归并，运行来源共用完整索引移位计算。
module conv_im2col_request_index #(
  parameter int p_coord_width = 35,
  parameter bit p_register_descriptor = 1'b0
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
  output logic [p_coord_width-1:0] o_request_y // 当前请求的输入行坐标。
);

  if (!p_register_descriptor) begin : g_parallel_descriptor
    logic [31:0] incoming_pixel, request_pixel;
    logic [p_coord_width-1:0] incoming_y;
    logic [9:0][p_coord_width+31:0] incoming_candidate;
    logic [3:0] request_select;
    logic [3:0][p_coord_width+31:0] request_candidate;
    logic [31:0] incoming_shared, request_shared;
    logic [4:0] effective_shift;
`ifndef SYNTHESIS
    logic [9:0][p_coord_width+31:0] qualified_incoming_candidate;
`endif

    // 先共用描述符内部的像素与行坐标选择，末端仅保留四个请求来源。
    for (genvar candidate = 0; candidate < 10; candidate++) begin : g_incoming
      assign incoming_candidate[candidate] =
          {i_incoming_y[candidate], i_incoming_pixel[candidate]};
`ifndef SYNTHESIS
      assign qualified_incoming_candidate[candidate] =
          {i_incoming_y[candidate], i_incoming_pixel[candidate]} &
          {(p_coord_width+32){i_descriptor}};
`endif
    end
    onehot_mux #(.p_choices(10), .p_width(p_coord_width+32)) u_incoming (
      .i_select(i_incoming_select), .i_data(incoming_candidate),
      .o_data({incoming_y, incoming_pixel})
    );
    assign request_select[0] = i_descriptor;
    assign request_select[1] = !i_descriptor && i_row;
    assign request_select[2] = !i_descriptor && !i_row && i_tap;
    assign request_select[3] = !i_descriptor && !i_row && !i_tap;
    assign request_candidate[0] = {incoming_y, incoming_pixel};
    for (genvar candidate = 0; candidate < 3; candidate++) begin : g_running
      assign request_candidate[candidate+1] =
          {i_running_y[candidate], i_running_pixel[candidate]};
    end
    onehot_mux #(.p_choices(4), .p_width(p_coord_width+32)) u_request (
      .i_select(request_select), .i_data(request_candidate),
      .o_data({o_request_y, request_pixel})
    );
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
