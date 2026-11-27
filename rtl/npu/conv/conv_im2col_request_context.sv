// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 统一选择缓存请求的地址、窗口索引、通道纪元和输入行坐标。
// 各来源并行准备候选，正式请求及预读快照使用同一组元数据。
module conv_im2col_request_context #(
  parameter int p_coord_width = 35,
  parameter int p_line_bytes = 128,
  parameter bit p_register_descriptor = 1'b1
) (
  input wire conv_im2col_pkg::conv_cfg_t i_configuration, // 当前任务的输入格式与通道偏移
  input wire logic i_descriptor, // 当前请求选择输入描述符
  input wire logic i_row_metadata, // 当前请求的元数据选择下一输出行
  input wire logic i_tap, // 当前请求选择下一卷积核位置
  input wire logic i_row, // 当前请求地址选择下一输出行
  input wire logic i_stream, // 当前请求选择连续输出位置
  input wire logic [9:0] i_select, // 十种描述符候选的独热选择位
  input wire logic [9:0][31:0] i_address_candidate, // 十种描述符字节地址候选
  input wire logic [9:0][31:0] i_pixel_candidate, // 十种描述符像素位置候选
  input wire logic [9:0][p_coord_width-1:0] i_y_candidate, // 十种描述符输入行坐标候选
  input wire logic [31:0] i_incoming_address, // 输入描述符按优先次序选择的地址
  input wire logic [31:0] i_incoming_pixel, // 输入描述符按优先次序选择的像素位置
  input wire logic [p_coord_width-1:0] i_incoming_y, // 输入描述符按优先次序选择的行坐标
  input wire logic [31:0] i_cache_address_reference, // 运行与描述符共用的地址参考值
  input wire logic [31:0] i_next_tap_address, // 下一卷积核位置的字节地址
  input wire logic [31:0] i_next_row_address, // 下一输出行的字节地址
  input wire logic [31:0] i_stream_address, // 连续输出的下一字节地址
  input wire logic [31:0] i_address, // 当前运行项的字节地址
  input wire logic [2:0][31:0] i_pixel, // 下一行、下一核位置和当前像素位置
  input wire logic [2:0][p_coord_width-1:0] i_y, // 下一行、下一核位置和当前输入行坐标
  input wire logic [3:0][31:0] i_epoch_sum, // 四种通道纪元的未缩放候选
  input wire logic i_short_pixel, // 按窗口粒度缩放像素索引
  input wire logic [4:0] i_index_shift, // 窗口索引的右移位数
  input wire logic i_index_valid, // 当前配置支持窗口索引
  input wire logic i_next_position, // 描述符复用下一空间窗口
  input wire logic i_next_tile, // 描述符紧随当前空间分块
  input wire logic i_row_wrap, // 当前输出列推进时换行
  input wire logic [15:0] i_window_y, // 已保存下一窗口的输出行
  input wire logic [31:0] i_output_y, // 当前输出行坐标
  output logic [31:0] o_cache_address, // 当前缓存请求的字节地址
  output logic [31:0] o_request_address, // 进入请求寄存器的完整字节地址
  output logic signed [p_coord_width-1:0] o_request_y, // 与请求地址对应的输入行坐标
  output logic [31:0] o_output_y, // 与请求地址对应的输出进度
  output logic [31:0] o_index, // 与请求地址对应的窗口索引
  output logic [31:0] o_request_pixel, // 与请求地址对应的未缩放像素位置
  output logic [31:0] o_epoch, // 与请求地址对应的通道纪元
  output logic o_index_valid // 当前请求的窗口索引有效
);

  logic [31:0] request_address_reference;
  logic [31:0] request_epoch_selected;
  logic [p_coord_width-1:0] request_y_selected;
  logic [31:0] request_index_selected;
  logic [31:0] current_req_index, current_req_epoch;
  logic [31:0] incoming_req_index, incoming_req_epoch;
  logic [1:0][31:0] incoming_epoch_candidate;

  assign request_address_reference = i_row_metadata ? i_next_row_address : i_cache_address_reference;

  // 描述符地址与运行位置地址共用末级归并，选择条件分别准备。
  if (1) begin : g_parallel_request_address
    (* keep = "true" *) logic [4:0] cache_select, request_select;
    logic [4:0][31:0] address_candidate;
    logic [31:0] incoming_address_selected;
    logic [31:0] cache_address_selected, request_address_selected;
    (* keep_hierarchy = "yes" *) conv_im2col_address_sources u_sources (
      .i_tap(i_tap), .i_incoming(i_descriptor),
      .i_row(i_row), .i_stream(i_stream),
      .i_row_metadata(i_row_metadata),
      .o_cache(cache_select), .o_saved(request_select)
    );
    // 描述符先完成内部地址选择，行末资格只选择五种完整请求来源。
    onehot_mux #(.p_choices(10), .p_width(32)) u_incoming_address (
      .i_select(i_select), .i_data(i_address_candidate), .o_data(incoming_address_selected)
    );
    assign address_candidate[0] = incoming_address_selected;
    assign address_candidate[4:1] = {i_address, i_stream_address, i_next_row_address, i_next_tap_address};
    onehot_mux #(.p_choices(5), .p_width(32)) u_cache_address (
      .i_select(cache_select), .i_data(address_candidate), .o_data(cache_address_selected)
    );
    conv_group_range_select #(.p_choices(5), .p_width(32)) u_saved_address (
      .i_select(request_select), .i_data(address_candidate), .o_data(request_address_selected)
    );
    always_comb begin
      o_cache_address = i_cache_address_reference;
      o_request_address = request_address_reference;
      // 未知输入继续使用条件选择的逐位合并语义。
      case (^{i_tap, i_descriptor, i_row, i_stream,
               i_row_metadata, i_select, i_address_candidate,
               i_incoming_address, i_next_tap_address, i_next_row_address, i_stream_address, i_address})
        1'b0, 1'b1: begin
          o_cache_address = cache_address_selected;
          o_request_address = request_address_selected;
        end
        default: begin end
      endcase
    end
  end

  // 请求索引和输入行坐标由同一组候选来源生成。
  conv_im2col_request_index #(
    .p_coord_width(p_coord_width),
    .p_register_descriptor(p_register_descriptor), .p_descriptor_preview(p_register_descriptor)
  ) u_request_index (
    .i_short_pixel(i_short_pixel), .i_index_shift(i_index_shift),
    .i_descriptor(i_descriptor), .i_row(i_row_metadata),
    .i_tap(i_tap), .i_incoming_select(i_select),
    .i_incoming_pixel(i_pixel_candidate), .i_incoming_y(i_y_candidate),
    .i_saved_pixel(i_incoming_pixel), .i_running_pixel({i_pixel[2], i_pixel[1], i_pixel[0]}),
    .i_running_y({i_y[2], i_y[1], i_y[0]}), .i_current_index(current_req_index),
    .o_incoming_index(incoming_req_index), .o_request_index(request_index_selected),
    .o_request_pixel(o_request_pixel),
    .o_request_y(request_y_selected)
  );
  // 两个描述符纪元独立计算格式和行内偏移，窗口匹配只选择最终结果。
  for (genvar candidate = 0; candidate < 2; candidate++) begin : g_incoming_request_epoch
    assign incoming_epoch_candidate[candidate] = i_short_pixel ? 32'd0 :
      (i_epoch_sum[candidate] << i_configuration.input_s16) >> $clog2(p_line_bytes);
  end
  assign incoming_req_epoch = i_next_position ? incoming_epoch_candidate[0] : incoming_epoch_candidate[1];

  // 各来源的纪元先完成格式变换，互斥选择只归并完整结果。
  if (1) begin : g_request_epoch
    logic [4:0] epoch_select;
    logic [4:0][31:0] epoch_candidate;
    assign epoch_select[0] = i_descriptor;
    assign epoch_select[1] = !i_descriptor && i_row_metadata;
    assign epoch_select[2] = !i_descriptor && !i_row_metadata &&
        i_tap;
    assign epoch_select[3] = !i_descriptor && !i_row_metadata &&
        !i_tap && i_stream;
    assign epoch_select[4] = !i_descriptor && !i_row_metadata &&
        !i_tap && !i_stream;
    assign epoch_candidate[0] = incoming_req_epoch;
    assign epoch_candidate[1] = i_short_pixel ? 32'd0 :
        (i_epoch_sum[1] << i_configuration.input_s16) >> $clog2(p_line_bytes);
    assign epoch_candidate[2] = i_short_pixel ? 32'd0 :
        ({16'd0, i_configuration.group_offset} << i_configuration.input_s16) >> $clog2(p_line_bytes);
    assign epoch_candidate[3] = i_short_pixel ? 32'd0 :
        (i_epoch_sum[3] << i_configuration.input_s16) >> $clog2(p_line_bytes);
    assign epoch_candidate[4] = current_req_epoch;
    (* keep_hierarchy = "yes" *) onehot_mux #(
      .p_choices(5), .p_width(32), .p_preserve_groups(1'b1)
    ) u_select (
      .i_select(epoch_select), .i_data(epoch_candidate), .o_data(request_epoch_selected)
    );
  end

  // 换核位置的元数据与下一地址共用静态上下文选择。
  always_comb begin
    o_request_y=i_descriptor ? i_incoming_y : i_row_metadata ? i_y[0] :
      i_tap ? i_y[1] : i_y[2];
    o_output_y=i_descriptor ?
      (i_next_position ? {16'd0, i_window_y} :
       i_next_tile ? (i_row_wrap ? i_output_y+32'd1 : i_output_y) : i_output_y) :
      i_row_metadata && i_row_wrap ? i_output_y+32'd1 : i_output_y;
    o_index_valid=i_index_valid;
    o_index=i_descriptor ? incoming_req_index : i_row_metadata ?
      (i_short_pixel ? i_pixel[0]>>i_index_shift : i_pixel[0]) :
      i_tap ? (i_short_pixel ? i_pixel[1]>>i_index_shift : i_pixel[1]) :
      current_req_index;
    o_epoch=i_descriptor ? incoming_req_epoch : i_row_metadata ?
      (i_short_pixel ? 32'd0 : (i_epoch_sum[1]<<i_configuration.input_s16)>>$clog2(p_line_bytes)) :
      i_tap ? (i_short_pixel ? 32'd0 :
        ({16'd0,i_configuration.group_offset}<<i_configuration.input_s16)>>$clog2(p_line_bytes)) :
      i_stream ? (i_short_pixel ? 32'd0 :
        (i_epoch_sum[3]<<i_configuration.input_s16)>>$clog2(p_line_bytes)) : current_req_epoch;
    // 未知输入保持条件选择的逐位合并语义。
    case (^{i_descriptor, i_row_metadata,
             i_tap, i_select, i_y_candidate,
             i_incoming_y, i_y[0], i_y[1], i_y[2], i_pixel_candidate,
             i_incoming_pixel, i_short_pixel, i_index_shift,
             i_pixel[0], i_pixel[1], current_req_index})
      1'b0, 1'b1: begin
        o_request_y = request_y_selected;
        o_index = request_index_selected;
      end
      default: begin end
    endcase
    case (^{i_descriptor, i_row_metadata,
             i_tap, i_stream, incoming_req_epoch,
             i_short_pixel, i_epoch_sum[1], i_epoch_sum[3], i_configuration.input_s16,
             i_configuration.group_offset, current_req_epoch})
      1'b0, 1'b1: o_epoch = request_epoch_selected;
      default: begin end
    endcase
  end


  always_comb begin
    current_req_index = i_pixel[2];
    current_req_epoch = (i_epoch_sum[2]<<i_configuration.input_s16)>>$clog2(p_line_bytes);
    if (i_short_pixel) begin
      current_req_index = i_pixel[2]>>i_index_shift;
      current_req_epoch = 0;
    end
  end
endmodule
`default_nettype wire
