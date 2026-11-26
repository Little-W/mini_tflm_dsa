// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 并行选择描述符、输出推进和地址计算的下一状态，并确定状态保存条件。
module conv_im2col_state_control #(
  parameter int p_count_width = 5
) (
  input wire conv_im2col_frontend_pkg::st_t i_state, // 当前运行状态。
  input wire conv_im2col_frontend_pkg::st_t i_descriptor_state, // 描述符字段决定的下一状态。
  input wire conv_im2col_frontend_pkg::st_t i_stream_state, // 输出推进后应进入的状态。
  input wire logic i_descriptor_context, // 当前周期使用描述符状态。
  input wire logic i_descriptor_eligible, // 描述符已经满足接收资格。
  input wire logic i_tile_commit, // 当前周期接收描述符。
  input wire logic i_descriptor_padding, // 已保存描述符需要输出填充值。
  input wire logic i_saved_word_hit, // 描述符命中已保存的数据字。
  input wire logic i_live_word_hit, // 描述符命中当前返回的数据字。
  input wire logic i_fast_position_valid, // 输出位置快速解码结果有效。
  input wire logic i_group_shape_valid, // 每组通道数支持位移解码。
  input wire logic i_kernel_shape_valid, // 卷积核宽度支持位移解码。
  input wire logic [15:0] i_group_channels, // 每个通道组包含的通道数。
  input wire logic [15:0] i_kernel_width, // 卷积核列数。
  input wire logic [31:0] i_position, // 分块起始输出位置。
  input wire logic [31:0] i_reduction, // 分块起始归约位置。
  input wire logic [31:0] i_tap, // 分块初始卷积核位置。
  input wire logic [31:0] i_decode_index, // 通用除法解码的当前计数。
  input wire logic i_position_valid, // 当前输入坐标和归约位置有效。
  input wire logic i_geometry_tile, // 当前分块使用几何预测。
  input wire logic [p_count_width-1:0] i_column, // 当前输出列索引。
  input wire logic i_predictor_busy, // 后续使用预测器正在工作。
  input wire logic i_hint_pending, // 缓存仍在等待预测提示。
  input wire logic i_word_hit, // 当前请求命中已保存缓存字。
  input wire logic i_request_ready, // 当前请求可以被接收。
  input wire logic i_response_failure, // 缓存返回失败响应。
  input wire logic i_stream_error, // 运行请求发生错误。
  input wire logic i_output_accept, // 当前输出传输被接收。
  input wire logic i_cfg_valid, // 新卷积配置有效。
  input wire logic i_cfg_ready, // 新卷积配置可被接收。
  output conv_im2col_frontend_pkg::st_t o_selected_state, // 本周期需要保存的下一运行状态。
  output logic o_state_update // 本周期允许运行状态寄存器更新。
);
  import conv_im2col_frontend_pkg::*;
  (* keep = 1 *) st_t operation_state;

  logic [2:0] decode_equal;
  logic [2:0][31:0] decode_target;
  assign decode_target = {i_tap, i_reduction, i_position};
  // 三种解码目标分别保留分组结果，公共计数无需经过串行全宽归并。
  for (genvar target_index = 0; target_index < 3; target_index++) begin : g_decode_match
    conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_match (
      .i_a(i_decode_index), .i_b(decode_target[target_index]), .o_equal(decode_equal[target_index])
    );
  end
  // 流式输出在末级选择运行状态，其余状态并行准备各自的后继值。
  function automatic st_t operation_for(input st_t stream_value);
    st_t operation_value;
    operation_value = i_state;
    unique case (1'b1)
      i_state[$clog2(DESCRIPTOR_CHECK)]: begin
        if (i_descriptor_padding) operation_value = ZERO_STREAM;
        else if (i_saved_word_hit || i_live_word_hit) operation_value = STREAM;
        else operation_value = FETCH;
      end
      (i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]):
        operation_value = stream_value;
      i_state[$clog2(P_HISTORY)]: operation_value = P_DECODE;
      i_state[$clog2(P_DECODE)]: begin
        if (i_fast_position_valid) operation_value = Q_DECODE;
        else operation_value = P_START;
      end
      i_state[$clog2(P_START)]: operation_value = P_WAIT;
      i_state[$clog2(P_WAIT)]: operation_value = Q_DECODE;
      i_state[$clog2(Q_DECODE)]: begin
        if (i_reduction==0 || i_group_shape_valid || (i_group_channels==3 && i_reduction<27)) operation_value = K_DECODE;
        else operation_value = Q_START;
      end
      i_state[$clog2(Q_START)]: operation_value = Q_WAIT;
      i_state[$clog2(Q_WAIT)]: operation_value = K_DECODE;
      i_state[$clog2(K_DECODE)]: begin
        if (i_kernel_shape_valid || (i_kernel_width==3 && i_tap<9)) operation_value = COORD;
        else operation_value = K_START;
      end
      i_state[$clog2(K_START)]: operation_value = K_WAIT;
      i_state[$clog2(K_WAIT)]: operation_value = COORD;
      i_state[$clog2(COORD)]: operation_value = COORD_SUM;
      i_state[$clog2(COORD_SUM)]: operation_value = COORD_BORROW;
      i_state[$clog2(COORD_BORROW)]: operation_value = COORD_PAD;
      i_state[$clog2(COORD_PAD)]: operation_value = ADDRESS;
      i_state[$clog2(ADDRESS)]: begin
        if (!i_position_valid) operation_value = ZERO_STREAM;
        else operation_value = ADDRESS_PIXEL;
      end
      i_state[$clog2(ADDRESS_PIXEL)]: operation_value = ADDRESS_PRODUCT;
      i_state[$clog2(ADDRESS_PRODUCT)]: operation_value = ADDRESS_MERGE;
      i_state[$clog2(ADDRESS_MERGE)]: operation_value = ADDRESS_BASE;
      i_state[$clog2(ADDRESS_BASE)]: operation_value = ADDRESS_CHANNEL;
      i_state[$clog2(ADDRESS_CHANNEL)]: operation_value = ADDRESS_MATCH;
      i_state[$clog2(ADDRESS_MATCH)]: begin
        if (!i_position_valid) operation_value = ZERO_STREAM;
        else operation_value = FETCH;
      end
      i_state[$clog2(FETCH)]: begin
        if (i_word_hit) operation_value = STREAM;
        else operation_value = WAIT_WORD;
      end
      i_state[$clog2(IDLE)]: ;
      default: operation_value = IDLE;
    endcase
    return operation_value;
  endfunction
  always_comb operation_state = operation_for(IDLE);

  logic stream_context, response_failed;
  (* keep = 1 *) logic [3:0] state_source_select;
  logic [3:0][26:0] state_candidate;
  // 打包联合体为同一组状态位提供位向量和枚举表示，保留每一位的四态值。
  union packed {
    st_t state;
    logic [26:0] bits;
  } selected_value;
  st_t selected_state;
  logic [26:0] selected_bits;
  assign selected_value.bits = selected_bits;
  assign selected_state = selected_value.state;
  // 描述符检查在状态顺序中先于流式输出，保留任意状态位组合的选择次序。
  assign stream_context = !i_state[$clog2(DESCRIPTOR_CHECK)] &&
      (i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]);
  assign response_failed = i_state[$clog2(WAIT_WORD)] && i_response_failure;
  assign state_source_select[0] = !response_failed && !i_descriptor_context && !stream_context;
  assign state_source_select[1] = !response_failed && !i_descriptor_context && stream_context;
  assign state_source_select[2] = !response_failed && i_descriptor_context;
  assign state_source_select[3] = response_failed;
  assign state_candidate = {IDLE, i_descriptor_state, i_stream_state, operation_state};
  (* keep_hierarchy = "yes" *)
  onehot_mux #(.p_choices(4), .p_width(27)) u_state_choice (
      .i_select(state_source_select), .i_data(state_candidate), .o_data(selected_bits)
  );

  // 已知选择条件只经过最终独热选择，未知条件仍按逐项顺序形成相同结果。
  always_comb begin
    o_selected_state = operation_for(i_stream_state);
    if (i_descriptor_context) o_selected_state = i_descriptor_state;
    if (i_state[$clog2(WAIT_WORD)] && i_response_failure) o_selected_state = IDLE;
    case (^{i_state, i_descriptor_context, i_response_failure, i_tile_commit, state_candidate})
      1'b0, 1'b1: o_selected_state = selected_state;
      default: begin
        case (i_tile_commit)
          1'b0, 1'b1: ;
          default: o_selected_state = IDLE;
        endcase
      end
    endcase
  end
  always_comb begin
    o_state_update = 1'b1;
    unique case (1'b1)
      (i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]): begin
        o_state_update = 1'b0;
        if (i_stream_error) o_state_update = 1'b1;
        else if (i_output_accept) o_state_update = 1'b1;
      end
      i_state[$clog2(P_WAIT)]: o_state_update = decode_equal[0];
      i_state[$clog2(Q_WAIT)]: o_state_update = decode_equal[1];
      i_state[$clog2(K_WAIT)]: o_state_update = decode_equal[2];
      i_state[$clog2(ADDRESS)]: begin
        o_state_update = 1'b0;
        if (!i_position_valid) o_state_update = 1'b1;
        else if (!i_geometry_tile || i_column!=0 || (!i_predictor_busy && !i_hint_pending)) o_state_update = 1'b1;
      end
      i_state[$clog2(FETCH)]: o_state_update = i_word_hit || i_request_ready;
      i_state[$clog2(IDLE)]: o_state_update = i_descriptor_eligible;
      default: ;
    endcase
    case (i_tile_commit)
      1'b0, 1'b1: ;
      default: o_state_update = 1'b1;
    endcase
    if (i_cfg_valid && i_cfg_ready) o_state_update = 1'b0;
  end

endmodule
`default_nettype wire
