// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 流式输出的通道范围、地址更新与写入数据选择。
module conv_im2col_stream #(
  parameter int p_size=16,
  parameter int p_slot_w=3,
  parameter int p_lanes=2,
  parameter int p_line_bytes=16,
  parameter int p_bus_width=32,
  parameter int p_narrow_lanes=p_bus_width/8,
  parameter bit p_register_cache_request=1'b1,
  parameter bit p_register_descriptor=1'b1,
  parameter bit p_register_row_address=p_register_descriptor,
  parameter int p_rw=$clog2(p_size+1),
  localparam int p_lane_bytes=p_lanes <= 4 ? 4 : (1 << $clog2(p_lanes)),
  localparam int p_cache_read_bytes=p_lane_bytes < p_line_bytes ? p_lane_bytes : p_line_bytes,
  localparam int p_cache_read_width=8 * p_cache_read_bytes,
  localparam int p_word_shift=$clog2(p_cache_read_bytes),
  localparam bit p_saved_word_range=p_lanes <= 16 && p_lanes <= p_cache_read_bytes,
  localparam int p_tile_count_w=$clog2(p_size+1),
  localparam int p_chunk_count_w=$clog2(p_lanes+1),
  localparam int p_group_low_w=p_lanes > 1 && p_lanes <= 32768 ? $clog2(p_lanes) : 1,
  localparam int p_group_high_w=16 - p_group_low_w,
  localparam int p_saved_group_lanes=p_lanes <= 16 ? p_lane_bytes : 4,
  localparam int p_coord_w=35,
  localparam bit p_contiguous_chunk=p_lanes <= 16 && p_lanes <= (1 << p_tile_count_w),
  localparam int p_prepared_tile_width=528+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
)(
  input wire logic i_clk, // 流式输出时钟
  input wire logic i_rst_n, // 异步低有效复位
  input wire logic i_cfg_valid, // 输入配置有效
  input wire logic i_cfg_ready, // 当前周期允许接收配置
  input wire conv_im2col_pkg::conv_cfg_t i_cfg, // 输入卷积配置
  input wire logic i_tile_valid, // 输入分块描述符有效
  input wire logic i_tile_ready, // 当前周期允许接收分块
  input wire logic i_tile_admission_ready, // 运行状态允许描述符提交
  input wire logic [p_rw-1:0] i_tile_rows, // 输入分块的有效行数
  input wire logic [p_rw-1:0] i_tile_cols, // 输入分块的有效列数
  input wire logic i_wr_valid, // 输出数据有效
  input wire logic i_wr_ready, // 下游允许接收输出
  input wire logic i_wr_last, // 当前输出完成本分块
  input wire conv_im2col_frontend_pkg::st_t i_state, // 当前前端运行状态
  input wire logic i_descriptor_check, // 当前运行项处于已寄存描述符的检查周期
  input wire logic i_descriptor_preview_safe, // 提前读取不会越过待提交项的后续数据字
  input wire logic i_word_output_q, // 当前输出使用缓存数据字
  input wire conv_im2col_pkg::conv_cfg_t i_c, // 当前保存的卷积配置
  input wire logic i_tile_rows_in_range, // 输入分块的全部行处于空间范围内
  input wire logic i_tile_q_before_end, // 输入归约起点小于归约长度
  input wire logic [15:0] i_last_group_channel_q, // 保存的通道组末位置
  input wire logic [16:0] i_window_group_remaining_q, // 保存窗口起点的剩余通道数
  input wire logic [31:0] i_q0, // 当前分块的归约起点
  input wire logic [p_tile_count_w-1:0] i_col_idx, // 当前输出列位置
  input wire logic [p_tile_count_w-1:0] i_cols_q, // 当前分块的总列数
  input wire logic [p_tile_count_w-1:0] i_active_cols_q, // 当前分块的有效归约列数
  input wire logic i_row_last_q, // 当前输出处于分块末行
  input wire logic i_past_active_q, // 当前输出已经越过有效归约范围
  input wire logic i_narrow_output, // 输出受总线窄通道范围限制
  input wire logic [15:0] i_ch0_q, // 当前分块保存的组内起始通道
  input wire logic [31:0] i_ch0, // 当前行使用的组内起始通道
  input wire logic [32:0] i_q_current, // 当前输出的完整归约位置
  input wire logic [31:0] i_channel_addr, // 当前通道的字节地址
  input wire logic i_pad_q, // 当前输入位置需要填充
  input wire logic [p_cache_read_width-1:0] i_word_buf, // 保存的缓存数据字
  input wire logic [31:0] i_saved_word_addr, // 运行寄存器保存的数据字地址
  input wire logic [31:0] i_word_addr, // 保存数据字的字节地址
  input wire logic i_word_valid, // 保存的数据字有效
  input wire logic [31:0] i_decode_index, // 当前归约解码位置
  input wire logic [31:0] i_decode_inner, // 当前归约解码的组内通道
  input wire logic i_cache_req_ready, // 缓存允许接收读取请求
  input wire logic i_cache_rsp_valid, // 缓存返回的数据有效
  input wire logic i_cache_rsp_error, // 缓存返回读取错误
  input wire logic [p_word_shift+1:0] i_byte_offset_sum, // 当前数据字内的推进字节位置
  input wire logic i_descriptor_response_forward, // 当前缓存返回可以直接供描述符使用
  input wire logic i_incoming_next_tile_fast, // 输入描述符继承下一空间分块位置
  input wire logic i_incoming_next_position_fast, // 输入描述符复用下一空间窗口
  input wire logic i_incoming_skip_tap, // 输入描述符跳过一个卷积核位置
  input wire logic [15:0] i_window_next_ch, // 保存窗口的组内起始通道
  input wire logic [p_cache_read_width-1:0] i_cache_rsp_data, // 缓存返回的数据字
  input wire logic i_pred_cfg_busy, // 预测器正在更新配置
  input wire logic i_cache_cfg_pending, // 缓存配置仍待提交
  input wire logic i_pred_cfg_pending, // 预测器配置仍待提交
  input wire logic i_geometry_tile, // 当前分块采用几何计算路径
  input wire logic i_incoming_fast, // 输入描述符可复用已准备的上下文
  input wire logic i_incoming_padding, // 输入描述符的首个位置需要填充
  input wire logic [31:0] i_incoming_addr, // 输入描述符的首个字节地址
  input wire logic [9:0][31:0] i_incoming_address_candidates, // 输入描述符的十种字节地址候选
  input wire logic [15:0] i_current_q_remainder, // 小范围归约解码的组内余数
  input wire logic i_next_word_o_equal, // 下一字节位置命中保存的数据字
  input wire logic [9:0][1:0] i_incoming_word_candidates, // 十个来源与保存字及运行字的匹配结果
  input wire logic [9:0] i_incoming_word_select, // 描述符来源的完整互斥选择位
  input wire logic i_incoming_word_o_equal, // 输入描述符命中保存的数据字
  input wire logic i_incoming_live_word_o_equal, // 输入描述符命中当前返回的数据字
  input wire logic i_row_base_valid, // 当前行起点上下文有效
  input wire logic i_coordinate_address_valid, // 当前输入坐标和地址上下文有效
  input wire logic i_row_coordinate_valid, // 下一行的输入坐标上下文有效
  input wire logic i_row_request_valid, // 下一行请求的寄存地址与元数据有效
  input wire logic [31:0] i_row_request_address, // 已提前保存的下一行请求地址
  input wire logic i_row_request_padding, // 已提前保存的下一行填充资格
  input wire logic i_next_row_padding, // 下一行起点需要填充
  input wire logic i_next_tap_padding, // 下一卷积核位置需要填充
  input wire logic i_incoming_tap_wrap_q, // 保存的输入卷积核列发生回绕
  input wire logic [31:0] i_next_row_addr, // 下一行起点的字节地址
  input wire logic [31:0] i_next_tap_addr, // 下一卷积核位置的字节地址
  input wire logic i_channel_accept_fire, // 当前周期接受快速描述符的通道状态
  input wire logic [p_prepared_tile_width-1:0] i_committing_tile_packed, // 当前提交的完整描述符字段
  input wire logic i_tile_commit, // 当前周期提交描述符
  input wire logic i_stream_operation_accept, // 已接受且继续当前分块的输出传输
  input wire logic i_stream_transfer_accept, // 已接受且未被空闲阶段提交替代的输出传输
  input wire logic i_committing_saved_word_hit, // 提交描述符命中保存的数据字
  input wire logic i_committing_live_word_hit, // 提交描述符命中当前返回的数据字
  input wire logic [1:0] i_next_row_word_match, // 下一行与保存字及运行字的标签匹配
  input wire logic [1:0] i_incoming_advanced_word_match, // 窗口分块及跳核候选的数据字匹配
  input wire logic i_group_shape_o_valid, // 通道组形状支持直接位选择解码
  output logic signed [15:0] o_wr_data [p_lanes], // 各输出通道的有符号样本
  output logic [p_lanes-1:0] o_wr_mask, // 各输出通道的有效掩码
  output logic [5:0][15:0] o_group_range_channel, // 六种通道范围候选的起始通道
  output logic [16:0] o_initial_group_remaining, // 当前分块起点的完整剩余通道数
  output logic [5:0][p_saved_group_lanes:0] o_group_range_next, // 六种起始通道对应的组末范围标志
  output logic [32:0] o_cfg_next_group, // 配置对应的下一组地址增量
  output logic [32:0] o_cfg_skip_group, // 配置对应的跳核地址增量
  output logic [p_lanes-1:0] o_chunk_lane_allowed, // 本次输出的逐通道范围许可
  output logic [p_lanes:0] o_chunk_selected, // 本次输出长度的独热选择
  output logic o_chunk_reaches_end, // 本次输出到达分块末列
  output logic [15:0] o_ch_q, // 保存的运行通道位置
  output logic [31:0] o_addr, // 保存的运行字节地址
  output logic o_current_word_hit, // 当前运行地址命中保存的数据字
  output logic [p_chunk_count_w-1:0] o_chunk_count, // 本次输出的有效通道数
  output logic o_cache_req_valid, // 当前缓存读取请求有效
  output logic o_cache_rsp_ready, // 当前周期允许接收缓存返回
  output logic o_stream_next_request, // 流式推进发起下一读取
  output logic o_next_row_request, // 跨行推进发起下一读取
  output logic o_request_stream_context, // 当前请求采用流式上下文
  output logic o_request_row_context, // 当前请求采用下一行上下文
  output logic o_request_tap_context, // 当前请求采用下一卷积核上下文
  output logic o_active_after_chunk, // 本次推进后仍处于有效归约范围
  output logic o_incoming_context, // 当前输入描述符的快速读取上下文有效
  output logic o_incoming_word_hit, // 输入描述符命中可直接使用的数据字
  output logic [1:0] o_incoming_tile_group_fits, // 窗口及当前起点的输入分块均未越过通道组
  output logic [31:0] o_cache_req_addr, // 当前缓存读取请求的字节地址
  output logic [31:0] o_stream_request_addr, // 流式推进所需的下一读取地址
  output logic o_cache_config_valid, // 缓存配置当前可以提交
  output logic o_incoming_tap_wrap, // 输入描述符推进后卷积核列回绕
  output logic [32:0] o_next_q_current, // 本次输出后的完整归约位置
  output logic o_group_end_o_equal, // 本次输出到达通道组末尾
  output conv_im2col_frontend_pkg::st_t o_stream_advance_state // 本次输出后采用的前端运行状态
);
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  localparam int p_prepared_count_w = p_tile_count_w;
  localparam int p_prepared_slot_w = p_slot_w;
  localparam int p_prepared_coord_w = p_coord_w;
  `include "conv_im2col_prepared_tile.svh"
  logic [p_cache_read_bytes-1:0] word_available_q;
  logic [p_lanes-1:0] group_lane_allowed;
  logic [p_saved_group_lanes:0] group_range_q;
  (* keep = "true" *) logic [p_saved_group_lanes:0] group_range_cfg;
  logic [p_saved_group_lanes:0] group_transfer_range;
  logic group_after_chunk;
  logic [16:0] cfg_next_group_low;
  logic [16:0] cfg_next_group_high;
  logic [p_tile_count_w-1:0] col_remaining;
  logic [p_tile_count_w-1:0] active_remaining;
  logic [p_lanes:0] active_lane_allowed_q;
  logic [p_lanes:0] active_lane_update;
  logic [p_lanes:0] column_lane_allowed_q;
  logic [p_lanes:0] column_lane_update;
  logic [2:0][p_tile_count_w-1:0] column_update_candidate;
  logic [p_tile_count_w-1:0] column_update_value;
  logic [2:0] active_update_select;
  logic active_select_commit;
  logic [2:0] active_data_select;
  logic [2:0][p_tile_count_w-1:0] active_update_candidate;
  logic [p_tile_count_w-1:0] active_update_value;
  logic [16:0] group_remaining;
  logic [p_lanes-1:0] word_lane_allowed;
  logic [p_lanes-1:0] lane_context_allowed;
  logic [p_lanes-1:0] word_lane_s8;
  logic [p_lanes-1:0] word_lane_s16;
  logic [p_lanes-1:0] chunk_data_allowed;
  logic [4:0] address_update_select;
  logic [31:0] address_update_value;
  logic address_stream_write;
  logic address_transfer_write;
  logic address_column_advance;
  logic addr_word_hit_q;
  logic next_tap_saved_hit, next_tap_word_equal;
  logic next_byte_saved_hit;
  logic channel_saved_hit;
  logic stream_context;
  logic next_row_word_hit;
  logic [31:0] stream_request_addr;
  logic [31-p_word_shift:0] request_increment_i_value, request_increment_o_result;
  logic request_increment_i_enable;
  logic [31-p_word_shift:0] request_increment_reference;
  logic [31-p_word_shift:0] request_increment_selected;
  logic request_increment_reference_carry;
  logic column_after_chunk;
  logic word_boundary;
  logic [p_lanes:0] step_word_boundary;
  logic [p_lanes:0] step_saved_hit;
  logic [p_cache_read_width-1:0] selected_word;
  logic [p_cache_read_width-1:0] stream_word;
  logic [p_lanes-1:0][7:0] selected_s8_byte;
  // 各通道的九位修正值独立计算，窄加法由综合工具组合为并行算术资源。
  logic [p_lanes-1:0][8:0] corrected_s8_sum;
  logic [p_lanes-1:0][7:0] sample_offsets_i_data;
  logic [8:0] sample_offsets_i_offset;
  logic [p_lanes-1:0][8:0] sample_offsets_o_sum;
  logic [p_lanes-1:0][15:0] corrected_s8_value;
  logic [31:0] next_byte_addr;
  logic [15:0] next_channel;
  logic [15:0] channel_update;
  logic [15:0] channel_value;
  prepared_tile_t committing_tile;
  (* keep = 1 *) logic [4:0] word_hit_update_select;
  logic [4:0] word_hit_candidate;
  logic word_hit_write_enable;
  logic word_hit_write_value;
  (* keep = 1 *) logic [1:0] word_hit_group;
  (* keep = 1 *) logic word_hit_any_update;
  logic word_response_write;
  logic [16:0] channel_position_sum;
  logic unused_channel_position_carry;
  logic stream_request_eligible;
  logic row_request_eligible;
  logic channel_word_equal;
  logic [p_saved_group_lanes:0] group_range_stream_value;
  logic [p_saved_group_lanes:0] group_range_row_value;
  logic [p_saved_group_lanes:0] group_range_restart_value;
  logic [p_saved_group_lanes:0] group_range_advance_value;
  logic group_range_restart_select;
  logic group_range_advance_select;
  logic range_stream_allowed;
  logic range_decode_write;
  (* keep = "true" *) logic [5:0] q_nonzero_group;
  logic q_nonzero, q_before_limit, decode_index_matches;
  logic [15:0] channel_decode_value;
  logic [p_saved_group_lanes:0] range_decode_value;
  logic [3:0] range_update_select;
  logic [p_saved_group_lanes:0] range_update_value;
  logic range_commit_context;
  st_t stream_static_state;
  logic stream_request_selected;
  logic stream_row_selected;
  logic stream_tap_selected;
  logic stream_read_accepted;
  st_t stream_accepted_state;
  assign committing_tile = prepared_tile_t'(i_committing_tile_packed);

  assign o_chunk_selected[0] = p_contiguous_chunk ? !o_chunk_lane_allowed[0] : !(|o_chunk_lane_allowed);
  for (genvar step = 1; step <= p_lanes; step++) begin : g_chunk_selected
    if (step == p_lanes) begin : g_last
      assign o_chunk_selected[step] = o_chunk_lane_allowed[step-1];
    end else if (p_contiguous_chunk) begin : g_contiguous
      assign o_chunk_selected[step] = o_chunk_lane_allowed[step-1] && !o_chunk_lane_allowed[step];
    end else begin : g_lower
      assign o_chunk_selected[step] = o_chunk_lane_allowed[step-1] && !(|o_chunk_lane_allowed[p_lanes-1:step]);
    end
  end
  if (p_chunk_count_w + 1 < 32) begin : g_byte_address
    localparam int p_step_width = p_chunk_count_w + 1;
    logic [p_step_width:0] address_low;
    logic [31-p_step_width:0] address_high_next;
    logic [32-p_step_width:0] address_high_sum;
    logic unused_address_carry;

    // 块内字节步长仅影响低位，高位加一提前完成。
    if (p_lanes <= 16) begin : g_parallel_byte_step
      logic [p_lanes:0][p_step_width:0] low_for_step;
      // 固定短步长按位生成和值，常量步长消除无效进位项并保留完整进位。
      function automatic logic [p_step_width:0] add_byte_step(
        input logic [p_step_width-1:0] value,
        input logic [p_step_width:0] amount
      );
        logic carry;
        logic value_bit;
        carry = 1'b0;
        for (int bit_index = 0; bit_index <= p_step_width; bit_index++) begin
          value_bit = bit_index < p_step_width ? value[bit_index] : 1'b0;
          add_byte_step[bit_index] = value_bit ^ amount[bit_index] ^ carry;
          carry = (value_bit & amount[bit_index]) |
              ((value_bit | amount[bit_index]) & carry);
        end
      endfunction
      // 每种传输数量先计算低位地址，通道资格只选择完整候选。
      for (genvar step = 0; step <= p_lanes; step++) begin : g_step
        logic [p_step_width:0] low_s8, low_s16;
        assign low_s8 = add_byte_step(o_addr[p_step_width-1:0], (p_step_width+1)'(step));
        assign low_s16 = add_byte_step(o_addr[p_step_width-1:0], (p_step_width+1)'(2*step));
        assign low_for_step[step] = i_c.input_s16 ? low_s16 : low_s8;
      end
      // 固定步长先完成算术，通道选择按三路分组后归并地址低位。
      conv_group_range_select #(.p_choices(p_lanes+1), .p_width(p_step_width+1)) u_step_address (
        .i_select(o_chunk_selected), .i_data(low_for_step), .o_data(address_low)
      );
    end else begin : g_encoded_byte_step
    logic [p_step_width-1:0] byte_step;
    assign byte_step = i_c.input_s16 ? {o_chunk_count, 1'b0} : {1'b0, o_chunk_count};
      assign address_low = {1'b0, o_addr[p_step_width-1:0]} + {1'b0, byte_step};
    end
    assign address_high_sum = {1'b0, o_addr[31:p_step_width]} + (33-p_step_width)'(1);
    assign {unused_address_carry, address_high_next} = address_high_sum;
    assign next_byte_addr = {
      address_low[p_step_width] ? address_high_next : o_addr[31:p_step_width],
      address_low[p_step_width-1:0]};
  end else begin : g_byte_address_wide
    logic unused_address_carry;
    assign {unused_address_carry, next_byte_addr} =
      {1'b0, o_addr} + {1'b0, (32'(o_chunk_count) << i_c.input_s16)};
  end

  if (p_chunk_count_w < 33) begin : g_reduction_position
    logic [p_chunk_count_w:0] position_low;
    logic [32-p_chunk_count_w:0] position_high_next;
    logic [33-p_chunk_count_w:0] position_high_sum;
    logic unused_position_carry;

    // 当前归约位置使用同一短步长，高位加一与低位求和并行。
    assign position_low = {1'b0, i_q_current[p_chunk_count_w-1:0]} + {1'b0, o_chunk_count};
    assign position_high_sum = {1'b0, i_q_current[32:p_chunk_count_w]} + (34-p_chunk_count_w)'(1);
    assign {unused_position_carry, position_high_next} = position_high_sum;
    assign o_next_q_current = {
      position_low[p_chunk_count_w] ? position_high_next : i_q_current[32:p_chunk_count_w],
      position_low[p_chunk_count_w-1:0]};
  end else begin : g_reduction_position_wide
    logic unused_position_carry;
    assign {unused_position_carry, o_next_q_current} = {1'b0, i_q_current} + 34'(o_chunk_count);
  end

  if (p_lanes <= 16 && p_chunk_count_w < 16) begin : g_channel_step
    logic [p_lanes:0][p_chunk_count_w:0] low_for_step;
    logic [p_chunk_count_w:0] channel_low;
    logic [16-p_chunk_count_w:0] channel_high_next;
    // 通道低位提前计算固定步长，高位加一与传输数量选择并行。
    for (genvar step = 0; step <= p_lanes; step++) begin : g_step
      assign low_for_step[step] = {1'b0, o_ch_q[p_chunk_count_w-1:0]} + (p_chunk_count_w+1)'(step);
    end
    always_comb begin
      channel_low = '0;
      for (int step = 0; step <= p_lanes; step++)
        channel_low |= {(p_chunk_count_w+1){o_chunk_selected[step]}} & low_for_step[step];
    end
    assign channel_high_next = {1'b0, o_ch_q[15:p_chunk_count_w]} + (17-p_chunk_count_w)'(1);
    assign channel_position_sum = {
        channel_low[p_chunk_count_w] ? channel_high_next : {1'b0, o_ch_q[15:p_chunk_count_w]},
        channel_low[p_chunk_count_w-1:0]};
  end else begin : g_channel_step_wide
    assign channel_position_sum = {1'b0, o_ch_q} + 17'(o_chunk_count);
  end
  assign {unused_channel_position_carry, next_channel} = channel_position_sum;

  // 当前组的剩余通道数共用一次扩展减法，窗口上下文保存对应剩余值。
  logic [16:0] initial_group_remaining_value;
  logic unused_initial_group_carry;
  parallel_prefix_add #(.p_width(17), .p_group_width(8), .p_preserve_groups(1'b1)) u_initial_group_remaining (
    .i_a({1'b0, i_c.group_c}), .i_b(~{1'b0, i_ch0_q}), .i_carry(1'b1),
    .o_sum(initial_group_remaining_value), .o_carry(unused_initial_group_carry)
  );
  always_comb begin
    case (^{i_c.group_c, i_ch0_q})
      1'b0, 1'b1: o_initial_group_remaining = initial_group_remaining_value;
      default: o_initial_group_remaining = 'x;
    endcase
  end
  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range
    logic [15:0] first_channel;
    logic [16:0] requested_columns;
    assign first_channel = source == 0 ? i_window_next_ch : i_ch0_q;
    assign requested_columns = i_tile_cols == '0 ? 17'(p_size) : 17'(i_tile_cols);
    if (source == 0 && p_tile_count_w < 16 && p_rw <= p_tile_count_w) begin : g_remaining
      conv_tile_remaining_range #(.p_width(p_tile_count_w), .p_size(p_size)) u_range (
        .i_remaining(i_window_group_remaining_q), .i_columns(p_tile_count_w'(i_tile_cols)),
        .o_fits(o_incoming_tile_group_fits[source])
      );
    end else if (p_tile_count_w < 16 && p_rw <= p_tile_count_w) begin : g_short_remaining
      logic low_borrow, high_before, high_equal, high_next_equal;
      logic low_less, default_allows, candidate_fits;

      conv_tile_group_low #(.p_width(p_tile_count_w), .p_size(p_size)) u_low_range (
        .i_group(i_c.group_c[p_tile_count_w-1:0]), .i_first(first_channel[p_tile_count_w-1:0]),
        .i_columns(p_tile_count_w'(i_tile_cols)), .o_borrow(low_borrow),
        .o_less(low_less), .o_default_allows(default_allows)
      );
      logic context_configure;
      logic [15:0] context_decode_channel;
      assign context_configure = i_cfg_valid && i_cfg_ready;
      always_comb begin
        context_decode_channel = 16'(i_decode_inner);
        if (i_state[$clog2(Q_DECODE)]) context_decode_channel = channel_decode_value;
      end
      // 高段关系与组宽或起始通道在同一边沿更新，晚到列数只参与低段判断。
      conv_descriptor_group_context #(
        .p_low_width(p_tile_count_w), .p_register_descriptor(p_register_descriptor)
      ) u_group_context (
        .clk(i_clk), .rst_n(i_rst_n), .i_configure(context_configure),
        .i_config_group(i_cfg.group_c), .i_group(i_c.group_c), .i_channel(first_channel),
        .i_commit(i_tile_commit), .i_invalid(committing_tile.invalid), .i_fast(committing_tile.fast),
        .i_commit_channel(16'(committing_tile.channel)), .i_window_channel(i_window_next_ch),
        .i_commit_window(i_incoming_next_position_fast),
        .i_decode_write(range_decode_write), .i_decode_channel(context_decode_channel),
        .o_high_before(high_before), .o_high_equal(high_equal), .o_high_next_equal(high_next_equal)
      );
      conv_tile_group_range_result u_result (
        .i_high_before(high_before), .i_high_equal(high_equal), .i_high_next_equal(high_next_equal),
        .i_low_borrow(low_borrow), .i_low_less(low_less), .i_default_allows(default_allows),
        .o_fits(candidate_fits)
      );
`ifdef SYNTHESIS
      assign o_incoming_tile_group_fits[source] = candidate_fits;
`else
      logic [p_tile_count_w:0] column_end_low;
      logic low_within, comparison_value;
      assign column_end_low = {1'b0, first_channel[p_tile_count_w-1:0]} +
          (p_tile_count_w+1)'(requested_columns);
      assign low_within = column_end_low[p_tile_count_w-1:0] <= i_c.group_c[p_tile_count_w-1:0];
      always_comb begin
        case (^{first_channel, i_c.group_c, i_tile_cols})
          1'b0, 1'b1: comparison_value = candidate_fits;
          default: comparison_value =
              (high_before && (!column_end_low[p_tile_count_w] || !high_next_equal || low_within)) ||
              (high_equal && !column_end_low[p_tile_count_w] && low_within);
        endcase
      end
      assign o_incoming_tile_group_fits[source] = comparison_value;
`endif
    end else if (p_tile_count_w < 16) begin : g_split
      localparam int p_high_w = 16 - p_tile_count_w;
      logic [p_tile_count_w:0] column_end_low;
      logic high_before, high_equal, low_within;
      logic [p_high_w-1:0] high_i_a, high_i_b, high_i_target;
      logic high_i_carry, high_o_equal;

      assign column_end_low = {1'b0, first_channel[p_tile_count_w-1:0]} +
        (p_tile_count_w+1)'(requested_columns);
      assign high_i_a = first_channel[15:p_tile_count_w];
      assign high_i_b = '0;
      assign high_i_target = i_c.group_c[15:p_tile_count_w];
      assign high_i_carry = 1'b1;
      assign high_before = high_i_a < high_i_target;
      assign high_equal = high_i_a == high_i_target;
      assign low_within = column_end_low[p_tile_count_w-1:0] <= i_c.group_c[p_tile_count_w-1:0];
      add_equal #(.p_width(p_high_w)) u_high_next (
        .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
        .i_carry_in(high_i_carry), .o_equal(high_o_equal)
      );
      assign o_incoming_tile_group_fits[source] =
        (high_before && (!column_end_low[p_tile_count_w] || !high_o_equal || low_within)) ||
        (high_equal && !column_end_low[p_tile_count_w] && low_within);
    end else begin : g_wide
      assign o_incoming_tile_group_fits[source] =
          {1'b0, first_channel} + requested_columns <= {1'b0, i_c.group_c};
    end
  end

  assign o_incoming_tap_wrap = i_incoming_tap_wrap_q;

  if (p_lanes <= 16 && p_lanes <= p_cache_read_bytes) begin : g_short_word_advance
    localparam int p_tag_count = 1 + (2*p_lanes + (1 << p_word_shift) - 1) / (1 << p_word_shift);
    localparam int p_tag_index_width = $clog2(p_tag_count);
    logic [p_lanes-1:0] crossing_s8, crossing_s16;
    logic [p_lanes:0] step_boundary_s8, step_boundary_s16;
    logic [p_tag_count-1:0] shared_word_equal;

    // 全部步长共用相邻字标签的比较，数据格式只选择已经完成的匹配结果。
    for (genvar word_step = 0; word_step < p_tag_count; word_step++) begin : g_tag
      conv_saved_word_step_match #(
        .p_width(32-p_word_shift), .p_step(word_step)
      ) u_match (
        .i_a(o_addr[31:p_word_shift]), .i_saved(i_saved_word_addr[31:p_word_shift]),
        .i_forward(p_register_descriptor && i_descriptor_check && i_committing_saved_word_hit),
        .o_equal(shared_word_equal[word_step])
      );
    end
    for (genvar step = 0; step <= p_lanes; step++) begin : g_step
      logic [p_word_shift+1:0] offset_sum;
      logic saved_word_equal;
      assign offset_sum = {2'b0, o_addr[p_word_shift-1:0]} +
        (i_c.input_s16 ? (p_word_shift+2)'(2*step) : (p_word_shift+2)'(step));
      logic boundary_s8, boundary_s16;
      // 固定步长直接与字内剩余字节比较，边界条件不经过地址求和。
      if (step == 0) begin : g_no_advance
        assign boundary_s8 = 1'b0;
        assign boundary_s16 = 1'b0;
      end else begin : g_positive_advance
        if (step >= p_cache_read_bytes) begin : g_s8_full_word
          assign boundary_s8 = 1'b1;
        end else begin : g_s8_remaining
          assign boundary_s8 = p_saved_word_range ? !word_available_q[step] :
              o_addr[p_word_shift-1:0] >= p_word_shift'(p_cache_read_bytes-step);
        end
        if (2*step >= p_cache_read_bytes) begin : g_s16_full_word
          assign boundary_s16 = 1'b1;
        end else begin : g_s16_remaining
          assign boundary_s16 = p_saved_word_range ? !word_available_q[2*step] :
              o_addr[p_word_shift-1:0] >= p_word_shift'(p_cache_read_bytes-2*step);
        end
      end
      assign step_boundary_s8[step] = boundary_s8;
      assign step_boundary_s16[step] = boundary_s16;
      assign step_word_boundary[step] = i_c.input_s16 ? boundary_s16 : boundary_s8;
      assign saved_word_equal = shared_word_equal[p_tag_index_width'(offset_sum[p_word_shift+1:p_word_shift])];
      assign step_saved_hit[step] = i_state[$clog2(WAIT_WORD)] ? !step_word_boundary[step] :
        i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && saved_word_equal;
    end
    // 固定步长的跨字条件随通道号递增，任意有效通道越界即可确定跨字。
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_crossing_lane
      assign crossing_s8[lane] = lane_context_allowed[lane] && column_lane_allowed_q[lane] &&
          (!i_word_output_q || word_lane_s8[lane]) && step_boundary_s8[lane+1];
      assign crossing_s16[lane] = lane_context_allowed[lane] && column_lane_allowed_q[lane] &&
          (!i_word_output_q || word_lane_s16[lane]) && step_boundary_s16[lane+1];
    end
    // 两种格式先分别归并字末条件，格式寄存位只参与最终选择。
    assign word_boundary = i_c.input_s16 ? (|crossing_s16) : (|crossing_s8);
    assign next_byte_saved_hit = |(o_chunk_selected & step_saved_hit);
  end else begin : g_wide_word_advance
    assign word_boundary = i_byte_offset_sum >= (p_word_shift+2)'(p_cache_read_bytes);
    assign next_byte_saved_hit = i_state[$clog2(WAIT_WORD)] ?
      next_byte_addr[31:p_word_shift] == o_addr[31:p_word_shift] :
      i_word_valid && i_word_addr == {next_byte_addr[31:p_word_shift], {p_word_shift{1'b0}}};
    assign step_word_boundary = '0;
    assign step_saved_hit = '0;
  end
  // 连续读取只在耗尽当前缓存字时发起，下一请求地址独立于传输数量编码。
  assign stream_request_addr[p_word_shift-1:0] = '0;
  assign stream_request_addr[31:p_word_shift] = request_increment_selected;
  assign request_increment_i_value = o_addr[31:p_word_shift];
  assign request_increment_i_enable = 1'b1;
  // 固定加一步长只依赖各组的全一条件，进位前缀与组内结果并行形成。
  conditional_increment #(.p_width(32-p_word_shift), .p_group_width(5)) u_stream_request_word (
    .i_value(request_increment_i_value), .i_enable(request_increment_i_enable),
    .o_result(request_increment_o_result)
  );
  parallel_prefix_add #(.p_width(32-p_word_shift), .p_group_width(8), .p_preserve_groups(1'b1)) u_stream_request_reference (
    .i_a(request_increment_i_value), .i_b((32-p_word_shift)'(1)), .i_carry(1'b0),
    .o_sum(request_increment_reference), .o_carry(request_increment_reference_carry)
  );
  // 含未知位的字地址保持分组进位传播；确定地址使用并行的固定步长结果。
  always_comb begin
    request_increment_selected = request_increment_reference;
    case (^request_increment_i_value)
      1'b0, 1'b1: request_increment_selected = request_increment_o_result;
      default: begin end
    endcase
  end
  if (p_tile_count_w >= p_chunk_count_w) begin : g_stream_remaining
    logic [p_lanes-1:0] column_after_lane, active_after_lane;
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
      assign column_after_lane[lane] = column_lane_allowed_q[lane+1];
      assign active_after_lane[lane] = active_lane_allowed_q[lane+1];
    end
    logic [p_lanes-1:0] static_lane;
    assign static_lane = lane_context_allowed & column_lane_allowed_q[p_lanes-1:0];
    conv_stream_format_range #(.p_lanes(p_lanes)) u_column_after (
      .i_first_allowed(column_lane_allowed_q[0]), .i_static_lane(static_lane), .i_word_s8(word_lane_s8), .i_word_s16(word_lane_s16), .i_input_s16(i_c.input_s16),
      .i_after_lane(column_after_lane), .i_word_output(i_word_output_q), .o_after(column_after_chunk)
    );
    conv_stream_format_range #(.p_lanes(p_lanes)) u_active_after (
      .i_first_allowed(active_lane_allowed_q[0]), .i_static_lane(static_lane), .i_word_s8(word_lane_s8), .i_word_s16(word_lane_s16), .i_input_s16(i_c.input_s16),
      .i_after_lane(active_after_lane), .i_word_output(i_word_output_q), .o_after(o_active_after_chunk)
    );
  end else begin : g_stream_remaining_wide
    assign column_after_chunk = p_tile_count_w'(o_chunk_count) < col_remaining;
    assign o_active_after_chunk = p_tile_count_w'(o_chunk_count) < active_remaining;
  end

  assign stream_context=i_state[$clog2(STREAM)] || i_state[$clog2(WAIT_WORD)];

  // 请求的静态资格提前计算，输出握手仅控制最终请求有效位。
  conv_stream_request_eligible u_stream_qualification (
    .i_zero_stream(i_state[$clog2(ZERO_STREAM)]), .i_column_after(column_after_chunk),
    .i_active_after(o_active_after_chunk), .i_group_after(group_after_chunk),
    .i_word_boundary(word_boundary), .o_eligible(stream_request_eligible)
  );
  assign row_request_eligible = (!p_register_row_address || i_row_request_valid) && o_chunk_reaches_end && !i_row_last_q &&
      i_row_base_valid && !i_geometry_tile &&
      !(p_register_row_address ? i_row_request_padding : i_next_row_padding) && !next_row_word_hit;
  assign o_stream_next_request = i_wr_valid && i_wr_ready && stream_request_eligible;
  // 请求坐标由运行阶段提前选择，传输握手控制请求有效信号。
  assign o_request_stream_context = stream_context;
  assign o_request_row_context =
      (stream_context || i_state[$clog2(ZERO_STREAM)]) && row_request_eligible;
  assign o_request_tap_context = p_register_cache_request &&
      (stream_context || i_state[$clog2(ZERO_STREAM)]) &&
      !o_chunk_reaches_end && o_group_end_o_equal;
  // 字命中标志与当前地址同时保存，请求有效条件只读取一位状态。
  assign o_current_word_hit = p_register_descriptor ?
    (i_descriptor_check ? i_committing_saved_word_hit || i_committing_live_word_hit : addr_word_hit_q) :
    i_word_valid && i_word_addr == {o_addr[31:p_word_shift], {p_word_shift{1'b0}}};
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1), .p_reduce_group_width(6)) u_next_tap_word_match (
    .i_a(i_word_addr), .i_b({i_next_tap_addr[31:p_word_shift], {p_word_shift{1'b0}}}), .o_equal(next_tap_word_equal)
  );
  assign next_tap_saved_hit = i_state[$clog2(WAIT_WORD)] ? i_next_word_o_equal :
    i_word_valid && next_tap_word_equal;
  // 字地址先保存，再在检查周期比较标签与有效位。

  conv_descriptor_match #(.p_width(32-p_word_shift), .p_preserve_groups(1'b1), .p_reduce_group_width(6)) u_channel_word_match (
    .i_a(o_addr[31:p_word_shift]), .i_b(i_word_addr[31:p_word_shift]), .o_equal(channel_word_equal)
  );
  assign channel_saved_hit = i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && channel_word_equal;
  // 当前行最后一拍被接收时，下一行的地址已经由独立加法器准备完成。
  assign next_row_word_hit = i_state[$clog2(WAIT_WORD)] ? i_next_row_word_match[1] :
      i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && i_next_row_word_match[0];
  // 下一行地址准备完成时，当前输出的接收边沿同时提交下一次读取。
  assign o_next_row_request = i_wr_valid && i_wr_ready && row_request_eligible;
  // 运行字与当前响应分别提供复用资格，每个提前请求保存独立的描述符归属。
  logic incoming_word_hit_reference;
  assign incoming_word_hit_reference = i_incoming_next_position_fast || i_incoming_next_tile_fast || i_incoming_skip_tap ?
    (i_descriptor_response_forward ? i_incoming_advanced_word_match[1] :
      i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && i_incoming_advanced_word_match[0]) :
    (i_descriptor_response_forward ? i_incoming_live_word_o_equal :
      (i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && i_incoming_word_o_equal));
  if (p_register_descriptor) begin : g_parallel_incoming_hit
    conv_incoming_word_hit u_hit (
      .i_select(i_incoming_word_select), .i_candidate(i_incoming_word_candidates),
      .i_response_forward(i_descriptor_response_forward),
      .i_saved_valid(i_word_valid && i_word_addr[p_word_shift-1:0] == '0),
      .i_reference(incoming_word_hit_reference), .o_hit(o_incoming_word_hit)
    );
  end else begin : g_direct_incoming_hit
    assign o_incoming_word_hit = incoming_word_hit_reference;
  end
  // 三类请求分别形成资格，地址和命中比较不接收最终传输条件。
  conv_im2col_request_control #(
    .p_size(p_size), .p_rw(p_rw), .p_register_descriptor(p_register_descriptor),
    .p_preview_registered(p_register_descriptor)
  ) u_request_control (
    .i_tile_valid(i_tile_valid && (!p_register_descriptor || i_descriptor_preview_safe)),
    .i_tile_ready(i_tile_ready),
    .i_incoming_fast(i_incoming_fast), .i_incoming_padding(i_incoming_padding),
    .i_incoming_word_hit(o_incoming_word_hit),
    .i_tile_rows(i_tile_rows), .i_tile_cols(i_tile_cols),
    .i_tile_q_before_end(i_tile_q_before_end), .i_tile_rows_in_range(i_tile_rows_in_range),
    .i_fetch(i_state[$clog2(FETCH)]), .i_current_word_hit(o_current_word_hit),
    .i_wr_valid(i_wr_valid), .i_wr_ready(i_wr_ready),
    .i_stream_request_eligible(stream_request_eligible),
    .i_row_request_eligible(row_request_eligible), .i_tap_selected(stream_tap_selected),
    .o_cache_req_valid(o_cache_req_valid)
  );
  assign o_incoming_context=i_tile_valid &&
    (i_state[$clog2(IDLE)] || ((i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]) && i_wr_last));
  assign o_cache_req_addr=o_request_tap_context ? i_next_tap_addr :
      o_incoming_context ? i_incoming_addr : o_request_row_context ?
      (p_register_row_address ? i_row_request_address : i_next_row_addr) :
      stream_context ? stream_request_addr : o_addr;
  assign o_stream_request_addr = stream_request_addr;
  assign o_cache_rsp_ready = i_state[$clog2(WAIT_WORD)] && (i_wr_ready || i_cache_rsp_error);
  assign o_cache_config_valid = i_cache_cfg_pending && !i_pred_cfg_pending && !i_pred_cfg_busy;
  // 各种通道来源并行计算组内范围，接收边沿只选择相应标志。
  assign o_group_range_channel[0] = 16'd0;
  assign o_group_range_channel[1] = i_ch0_q;
  assign o_group_range_channel[2] = i_q0[15:0] & i_last_group_channel_q;
  assign o_group_range_channel[3] = i_current_q_remainder;
  assign o_group_range_channel[4] = 16'(i_decode_inner);
  assign o_group_range_channel[5] = next_channel;

  // 传输到组末的条件直接检查加法等式，保留第十七位的回绕语义。
  if (p_lanes <= 16) begin : g_group_end_by_lane
    conv_stream_group_end #(
      .p_lanes(p_lanes), .p_narrow_lanes(p_narrow_lanes), .p_contiguous(p_contiguous_chunk)
    ) u_end (
      .i_group_range(group_range_q[p_lanes:0]), .i_active_lane(active_lane_allowed_q[p_lanes-1:0]),
      .i_column_lane(column_lane_allowed_q[p_lanes-1:0]), .i_word_s8(word_lane_s8), .i_word_s16(word_lane_s16),
      .i_narrow_output(i_narrow_output), .i_past_active(i_past_active_q),
      .i_word_output(i_word_output_q), .i_input_s16(i_c.input_s16), .o_end(o_group_end_o_equal)
    );
  end else begin : g_group_end_wide
    logic [16:0] group_end_i_a, group_end_i_b, group_end_i_target;
    logic group_end_i_carry_in;
  assign group_end_i_a = {1'b0, o_ch_q};
  assign group_end_i_b = 17'(o_chunk_count);
  assign group_end_i_target = {1'b0, i_c.group_c};
  assign group_end_i_carry_in = 1'b0;
    add_equal #(.p_width(17)) u_group_end (
      .i_a(group_end_i_a), .i_b(group_end_i_b), .i_target(group_end_i_target),
      .i_carry_in(group_end_i_carry_in), .o_equal(o_group_end_o_equal)
    );
  end

  if (p_lanes <= 16) begin : g_short_group_lane
    logic unused_group_after_chunk;
    logic [p_lanes-1:0] static_lane;
    conv_im2col_group_ranges #(
      .p_lanes(p_lanes), .p_narrow_lanes(p_narrow_lanes),
      .p_saved_group_lanes(p_saved_group_lanes), .p_contiguous_chunk(p_contiguous_chunk)
    ) u_ranges (
      .i_cfg_group_c(i_cfg.group_c), .i_group_c(i_c.group_c), .i_channel(o_ch_q),
      .i_channel_source(o_group_range_channel), .i_range(group_range_q),
      .i_active_lane(active_lane_allowed_q), .i_column_lane(column_lane_allowed_q),
      .i_word_lane(word_lane_allowed), .i_chunk_selected(o_chunk_selected),
      .i_chunk_lane(o_chunk_lane_allowed), .i_narrow_output(i_narrow_output),
      .i_word_output_q(i_word_output_q), .o_cfg_range(group_range_cfg),
      .o_next_range(o_group_range_next), .o_transfer_range(group_transfer_range),
      .o_lane_allowed(group_lane_allowed), .o_after_chunk(unused_group_after_chunk)
    );
    // 数据字格式只选择预先准备的组末资格，范围归并与通道掩码同时计算。
    assign static_lane = lane_context_allowed & column_lane_allowed_q[p_lanes-1:0];
    conv_stream_format_range #(.p_lanes(p_lanes)) u_group_after (
      .i_first_allowed(group_range_q[0]), .i_static_lane(static_lane),
      .i_word_s8(word_lane_s8), .i_word_s16(word_lane_s16), .i_input_s16(i_c.input_s16), .i_after_lane(group_range_q[p_lanes:1]),
      .i_word_output(i_word_output_q), .o_after(group_after_chunk)
    );
  end else if (p_lanes <= 32768) begin : g_group_lane_range
    logic [p_group_high_w-1:0] group_high_minus_one_q;
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) group_high_minus_one_q <= '1;
      else if (i_cfg_valid && i_cfg_ready)
        group_high_minus_one_q <= i_cfg.group_c[15:p_group_low_w] - p_group_high_w'(1);
    end
    assign group_transfer_range = '0;
    assign group_range_cfg = '0;
    assign o_group_range_next = '0;
    logic [p_lanes:0] group_range;
    assign group_lane_allowed = group_range[p_lanes-1:0];
    // 常量步数的范围同时计算，通道掩码只参与末级并行归并。
    assign group_after_chunk = group_range[0] && (&(~o_chunk_lane_allowed | group_range[p_lanes:1]));
    logic high_before_end, high_at_end, high_before_end_by_one, remaining_wrap;
    if (p_group_low_w == 2) begin : g_split_high_compare
      // 两段高位关系并行计算，最高一段不相等时直接确定整体顺序。
      assign high_before_end = o_ch_q[15:9] < i_c.group_c[15:9] ||
        (o_ch_q[15:9] == i_c.group_c[15:9] && o_ch_q[8:2] < i_c.group_c[8:2]);
    end else begin : g_general_high_compare
      assign high_before_end = o_ch_q[15:p_group_low_w] < i_c.group_c[15:p_group_low_w];
    end
    assign high_at_end = o_ch_q[15:p_group_low_w] == i_c.group_c[15:p_group_low_w];
    assign high_before_end_by_one = o_ch_q[15:p_group_low_w] == group_high_minus_one_q;
    assign remaining_wrap = (!high_before_end && !high_at_end) ||
        (high_at_end && o_ch_q[p_group_low_w-1:0] > i_c.group_c[p_group_low_w-1:0]);
    for (genvar lane = 0; lane <= p_lanes; lane++) begin : g_lane
      logic [p_group_low_w:0] lane_last_low;
      logic low_before_end;
      if (p_group_low_w == 2) begin : g_two_bit_offset
        // 两位偏移按位生成进位与和值，通道范围检查直接使用三位结果。
        if (lane == 0) begin : g_zero
          assign lane_last_low = {1'b0, o_ch_q[1:0]};
        end else if (lane == 1) begin : g_one
          assign lane_last_low = {(&o_ch_q[1:0]), o_ch_q[1] ^ o_ch_q[0], ~o_ch_q[0]};
        end else if (lane == 2) begin : g_two
          assign lane_last_low = {o_ch_q[1], ~o_ch_q[1], o_ch_q[0]};
        end else begin : g_three
          assign lane_last_low = {(|o_ch_q[1:0]), o_ch_q[1] ^ ~o_ch_q[0], ~o_ch_q[0]};
        end
      end else begin : g_general_offset
        assign lane_last_low = {1'b0, o_ch_q[p_group_low_w-1:0]} + (p_group_low_w+1)'(lane);
      end
      assign low_before_end = lane_last_low[p_group_low_w-1:0] < i_c.group_c[p_group_low_w-1:0];
      assign group_range[lane] = remaining_wrap ||
          (high_before_end && (!lane_last_low[p_group_low_w] || !high_before_end_by_one || low_before_end)) ||
          (high_at_end && !lane_last_low[p_group_low_w] && low_before_end);
    end
  end else begin : g_group_lane_range_wide
    assign group_transfer_range = '0;
    assign group_range_cfg = '0;
    assign o_group_range_next = '0;
    assign group_after_chunk = 17'(o_chunk_count) < group_remaining;
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
      assign group_lane_allowed[lane] = 17'(lane) < group_remaining;
    end
  end

  // 每条通道直接检查字内偏移，常量边界同时覆盖八位和十六位输入。
  for (genvar lane = 0; lane < p_lanes; lane++) begin : g_word_lane
    logic allowed_s8, allowed_s16;
    // 字内偏移扩展一位后与固定边界比较，覆盖一个完整读取字。
    function automatic logic before_word_end(
      input logic [p_word_shift-1:0] value,
      input logic [p_word_shift:0] limit
    );
      before_word_end = {1'b0, value} < limit;
    endfunction
    if (lane < p_cache_read_bytes) begin : g_s8
      assign allowed_s8 = p_saved_word_range ? word_available_q[lane] :
          before_word_end(o_addr[p_word_shift-1:0], (p_word_shift+1)'(p_cache_read_bytes-lane));
    end else begin : g_s8_empty
      assign allowed_s8 = 1'b0;
    end
    if (lane < p_cache_read_bytes/2) begin : g_s16
      assign allowed_s16 = p_saved_word_range ? word_available_q[2*lane+1] :
          before_word_end(o_addr[p_word_shift-1:0], (p_word_shift+1)'(p_cache_read_bytes-1-2*lane));
    end else begin : g_s16_empty
      assign allowed_s16 = 1'b0;
    end
    assign word_lane_s8[lane] = allowed_s8;
    assign word_lane_s16[lane] = allowed_s16;
    assign word_lane_allowed[lane] = i_c.input_s16 ? allowed_s16 : allowed_s8;
    // 列数、组范围与输出宽度先形成公共资格，输入格式单独选择字内通道。
    assign lane_context_allowed[lane] = (!i_narrow_output || lane<p_narrow_lanes) &&
        (i_past_active_q || (group_lane_allowed[lane] && active_lane_allowed_q[lane]));
    assign chunk_data_allowed[lane] = lane_context_allowed[lane] &&
        (!i_word_output_q || word_lane_allowed[lane]);
  end
  if (p_tile_count_w >= p_chunk_count_w) begin : g_direct_chunk_end
    conv_stream_chunk_end #(.p_lanes(p_lanes), .p_narrow_lanes(p_narrow_lanes)) u_end (
      .i_column_lane(column_lane_allowed_q), .i_group_lane(group_lane_allowed),
      .i_active_lane(active_lane_allowed_q[p_lanes-1:0]), .i_word_s8(word_lane_s8), .i_word_s16(word_lane_s16),
      .i_narrow_output(i_narrow_output), .i_past_active(i_past_active_q),
      .i_word_output(i_word_output_q), .i_input_s16(i_c.input_s16), .o_end(o_chunk_reaches_end)
    );
  end else begin : g_narrow_chunk_end
    assign o_chunk_reaches_end = p_tile_count_w'(o_chunk_count) == col_remaining;
  end

  // 八位输入的配置偏移范围为负127至128，完整和值由九位有符号数表示。
  for (genvar data_lane = 0; data_lane < p_lanes; data_lane++) begin : g_signed_byte_offset
    assign selected_s8_byte[data_lane] = 8'(selected_word >> (data_lane * 8));
    assign corrected_s8_value[data_lane] =
        {{7{corrected_s8_sum[data_lane][8]}}, corrected_s8_sum[data_lane]};
  end
  assign sample_offsets_i_data = selected_s8_byte;
  assign sample_offsets_i_offset = i_c.input_offset[8:0];
  assign corrected_s8_sum = sample_offsets_o_sum;
  conv_im2col_sample_offsets #(.p_lanes(p_lanes)) u_sample_offsets (
    .i_data(sample_offsets_i_data), .i_offset(sample_offsets_i_offset),
    .o_sum(sample_offsets_o_sum)
  );
  assign stream_word = i_state[$clog2(WAIT_WORD)] ? i_cache_rsp_data : i_word_buf;

  always_comb begin
    group_remaining={1'b0,i_c.group_c}-{1'b0,o_ch_q};
    o_chunk_count = '0;
    for (int lane=0;lane<p_lanes;lane++) begin
      // 描述符选择写入宽度；缓存字仍保留完整读取宽度供后续拍使用。
      o_chunk_lane_allowed[lane] = chunk_data_allowed[lane] && column_lane_allowed_q[lane];
      if (o_chunk_lane_allowed[lane]) o_chunk_count=p_chunk_count_w'(lane+1);
    end
  end

  // 字节移位仅选择当前自然地址分组内的有效数据，字尾由通道掩码限制。
  assign selected_word = stream_word >> (8*o_addr[p_word_shift-1:0]);

  // 各项范围均从零号通道连续有效，范围交集直接形成连续输出掩码。
  // 列索引可能发生定宽回绕的参数组合保留逐通道后缀归并。
  for (genvar output_lane = 0; output_lane < p_lanes; output_lane++) begin : g_output_mask
    if (p_contiguous_chunk) begin : g_contiguous
      assign o_wr_mask[output_lane] = o_chunk_lane_allowed[output_lane];
    end else begin : g_general
      assign o_wr_mask[output_lane] = |o_chunk_lane_allowed[p_lanes-1:output_lane];
    end
  end
  // 数据字与字节位置共用选择结果，各输出通道分别完成符号扩展和配置偏移。
  // 字尾之外的八位样本为零，九位加法仍保留完整的偏移结果。
  for (genvar data_lane = 0; data_lane < p_lanes; data_lane++) begin : g_formatter
    always_comb begin
      o_wr_data[data_lane] = '0;
      if (stream_context && o_wr_mask[data_lane]) begin
        if (i_c.input_s16)
          o_wr_data[data_lane] = $signed(16'(selected_word >> (data_lane*16)));
        else
          o_wr_data[data_lane] = $signed(corrected_s8_value[data_lane]);
      end
    end
  end

  always_comb begin
    channel_update = o_ch_q;
    unique case (1'b1)
      i_state[$clog2(WAIT_WORD)], i_state[$clog2(STREAM)], i_state[$clog2(ZERO_STREAM)]: begin
        if (!(i_state[$clog2(WAIT_WORD)] && i_cache_rsp_valid && i_cache_rsp_error) && i_wr_valid && i_wr_ready) begin
          if (o_chunk_reaches_end) begin
            if (!i_row_last_q) begin
              channel_update = 16'(i_ch0);
            end
          end else if (i_col_idx < i_active_cols_q && p_tile_count_w'(o_chunk_count) < active_remaining) begin
            if (o_group_end_o_equal) begin
              channel_update = 16'd0;
            end else begin
              channel_update = next_channel;
            end
          end
        end
      end
      i_state[$clog2(Q_DECODE)]: begin
        if (!q_nonzero) begin
          channel_update = 16'd0;
        end else if (i_group_shape_o_valid) begin
          channel_update = o_group_range_channel[2];
        end else if (i_c.group_c == 16'd3 && q_before_limit) begin
          channel_update = i_current_q_remainder;
        end
      end
      i_state[$clog2(Q_WAIT)]: begin
        if (decode_index_matches) begin
          channel_update = 16'(i_decode_inner);
        end
      end
      default: ;
    endcase
  end
  // 行切换、组切换和通道递增先选择范围，写入握手只控制最终保存。

  // 组末选择先完成一位条件，各通道范围独立合并三种数据来源。
  assign group_range_restart_select = !o_chunk_reaches_end && o_group_end_o_equal;
  assign group_range_advance_select = !o_chunk_reaches_end && !o_group_end_o_equal;
  assign group_range_row_value = {(p_saved_group_lanes+1){o_chunk_reaches_end}} & o_group_range_next[1];
  assign group_range_restart_value = {(p_saved_group_lanes+1){group_range_restart_select}} & o_group_range_next[0];
  assign group_range_advance_value = {(p_saved_group_lanes+1){group_range_advance_select}} & o_group_range_next[5];
  assign group_range_stream_value = p_lanes <= 16 ?
      (group_range_row_value | ({(p_saved_group_lanes+1){!o_chunk_reaches_end}} & group_transfer_range)) :
      (group_range_row_value | group_range_restart_value | group_range_advance_value);

  // 流式范围的保存资格与三种候选值并行计算，返回有效只控制寄存器写入。

  if (!(p_lanes <= 16)) begin : g_qualified_range_write
  logic range_write_context;
  logic range_position_allowed;
  // 运行状态与行列位置独立检查，传输状态只作用于最后的保存资格。
  always_comb begin
    range_write_context = 1'b0;
    unique case (1'b1)
      i_state[$clog2(WAIT_WORD)], i_state[$clog2(STREAM)], i_state[$clog2(ZERO_STREAM)]: begin
        if (i_state[$clog2(WAIT_WORD)] && i_cache_rsp_valid && i_cache_rsp_error) begin
        end else if (i_wr_ready) range_write_context = 1'b1;
      end
      default: ;
    endcase
  end
  always_comb begin
    range_position_allowed = 1'b0;
    if (o_chunk_reaches_end) begin
      if (i_row_last_q) begin
      end else range_position_allowed = 1'b1;
    end else if (i_past_active_q || !o_active_after_chunk) begin
    end else range_position_allowed = 1'b1;
  end
  assign range_stream_allowed = range_write_context && range_position_allowed;
  end else begin : g_stream_range_write
    assign range_stream_allowed = i_wr_ready;
  end
  logic [3:0] range_decode_select;
  logic range_q_before_limit;
  // 小范围译码分别检查高位零值和五位位置。
  assign q_nonzero_group[0] = |i_q0[4:0];
  for (genvar group_index = 0; group_index < 5; group_index++) begin : g_q_nonzero
    localparam int p_first = 5 + group_index * 6;
    localparam int p_bits = 32 - p_first < 6 ? 32 - p_first : 6;
    assign q_nonzero_group[group_index+1] = |i_q0[p_first+:p_bits];
  end
  assign q_nonzero = |q_nonzero_group;
  assign range_q_before_limit = !(|q_nonzero_group[5:1]) && (i_q0[4:0] < 5'd27);
  // 小常量比较将高位零值与低位关系并行准备，未知输入保留完整比较语义。
  always_comb begin
    q_before_limit = i_q0 < 32'd27;
    case (^i_q0)
      1'b0, 1'b1: q_before_limit = range_q_before_limit;
      default: ;
    endcase
  end
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_decode_index_match (
    .i_a(i_decode_index), .i_b(i_q0), .o_equal(decode_index_matches)
  );
  // 译码选择保持状态优先次序，其数据准备与配置及输出握手独立。
  always_comb begin
    range_decode_write = 1'b0;
    range_decode_value = o_group_range_next[4];
    range_decode_select = 4'b1000;
    unique case (1'b1)
      i_state[$clog2(P_DECODE)], i_state[$clog2(P_START)], i_state[$clog2(P_WAIT)]: ;
      i_state[$clog2(Q_DECODE)]: begin
        if (!q_nonzero) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[0];
          range_decode_select = 4'b0001;
        end else if (i_group_shape_o_valid) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[2];
          range_decode_select = 4'b0010;
        end else if (i_c.group_c == 16'd3 && range_q_before_limit) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[3];
          range_decode_select = 4'b0100;
        end
      end
      i_state[$clog2(Q_START)]: ;
      i_state[$clog2(Q_WAIT)]: begin
        if (decode_index_matches) range_decode_write = 1'b1;
      end
      default: ;
    endcase
  end
  // 前一分块完成时，新描述符优先更新通道范围。
  assign range_update_select[0] = range_decode_write;
  assign range_update_select[1] = i_cfg_valid && i_cfg_ready;
  assign range_update_select[2] = i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign range_update_select[3] = p_lanes <= 16 ? address_stream_write :
      !i_tile_commit && i_wr_valid && range_stream_allowed;
  assign range_commit_context = p_register_descriptor ? range_update_select[2] :
      o_incoming_context && i_tile_admission_ready;
  if (p_lanes <= 16) begin : g_range_data_choice
    logic [3:0] range_value_select;
    logic [6:0] range_source_select;
    logic [7:0] range_data_select;
    logic [7:0][p_saved_group_lanes:0] range_candidate;
    logic [p_saved_group_lanes:0] selected_range_value;
    // 先确定范围来源，再选择各来源独立准备的通道范围。
    always_comb begin
      range_value_select = 4'b0001;
      case (1'b1)
        range_update_select[1]: range_value_select = 4'b0010;
        (!p_register_descriptor &&
            (i_state[$clog2(Q_DECODE)] || i_state[$clog2(Q_WAIT)])):
          range_value_select = 4'b1000;
        range_commit_context: range_value_select = 4'b0100;
        // 直接描述符路径已由译码状态选择来源，保存资格只控制寄存器写入。
        (p_register_descriptor && range_update_select[0]): range_value_select = 4'b1000;
        default: ;
      endcase
    end
    assign range_source_select[2:0] = range_value_select[2:0];
    assign range_source_select[6:3] = {4{range_value_select[3]}} & range_decode_select;
    if (p_register_descriptor) begin : g_registered_choice
      logic [3:0] decoded_source;
      conv_group_decode_select u_decode (
        .i_state(i_state), .i_q_nonzero(q_nonzero), .i_group_shape(i_group_shape_o_valid),
        .i_group_three(i_c.group_c == 16'd3), .i_q_before_limit(range_q_before_limit),
        .i_decode_match(decode_index_matches), .o_select(decoded_source)
      );
      conv_group_range_choice u_choice (
        .i_configure(range_update_select[1]), .i_commit(range_commit_context),
        .i_decoded_source(decoded_source), .i_chunk_end(o_chunk_reaches_end),
        .o_select(range_data_select)
      );
    end else begin : g_direct_choice
      assign range_data_select[6:1] = range_source_select[6:1];
      assign range_data_select[0] = range_source_select[0] && !o_chunk_reaches_end;
      assign range_data_select[7] = range_source_select[0] && o_chunk_reaches_end;
    end
    assign range_candidate[0] = group_transfer_range;
    assign range_candidate[1] = group_range_cfg;
    assign range_candidate[2] = committing_tile.channel_range;
    assign range_candidate[3] = o_group_range_next[0];
    assign range_candidate[4] = o_group_range_next[2];
    assign range_candidate[5] = o_group_range_next[3];
    assign range_candidate[6] = o_group_range_next[4];
    assign range_candidate[7] = o_group_range_next[1];
    // 解码及运行范围先分别归并，描述符提交只控制最终数据选择。
    if (p_register_descriptor) begin : g_saved_range_value
      conv_stream_group_value #(.p_width(p_saved_group_lanes+1)) u_value (
        .i_configure(range_update_select[1]), .i_commit(range_commit_context),
        .i_decoded_source(g_registered_choice.decoded_source),
        .i_chunk_end(o_chunk_reaches_end), .i_candidate(range_candidate),
        .o_value(selected_range_value)
      );
    end else begin : g_direct_range_value
      conv_group_range_select #(.p_choices(8), .p_width(p_saved_group_lanes+1)) u_value (
        .i_select(range_data_select), .i_data(range_candidate), .o_data(selected_range_value)
      );
    end
    always_comb begin
      range_update_value = selected_range_value;
`ifndef SYNTHESIS
      if ((^{range_data_select, range_candidate}) === 1'bx) begin
        range_update_value = '0;
        unique case (1'b1)
          range_source_select[0]: range_update_value = group_range_stream_value;
          range_source_select[1]: range_update_value = group_range_cfg;
          range_source_select[2]: range_update_value = committing_tile.channel_range;
          range_source_select[3]: range_update_value = o_group_range_next[0];
          range_source_select[4]: range_update_value = o_group_range_next[2];
          range_source_select[5]: range_update_value = o_group_range_next[3];
          range_source_select[6]: range_update_value = o_group_range_next[4];
          default: ;
        endcase
      end
`endif
    end
  end else begin : g_range_qualified_choice
    assign range_update_value =
        ({(p_saved_group_lanes+1){range_update_select[0]}} & range_decode_value) |
        ({(p_saved_group_lanes+1){range_update_select[1]}} & group_range_cfg) |
        ({(p_saved_group_lanes+1){range_update_select[2]}} & committing_tile.channel_range) |
        ({(p_saved_group_lanes+1){range_update_select[3]}} & group_range_stream_value);
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) group_range_q <= '0;
    else if (|range_update_select) group_range_q <= range_update_value;
  end

  // 通道数据按运行阶段预选，缓存返回只控制最终保存。
  logic channel_write_enable;
  logic [15:0] channel_store_value;
  logic [3:0] channel_data_select;
  logic [3:0][15:0] channel_data_candidate;
  logic [15:0] channel_selected_value, channel_stream_value;
  logic channel_phase_write, channel_commit_context;
  assign channel_value = i_channel_accept_fire ? 16'(committing_tile.channel) : channel_update;
  assign channel_commit_context = p_register_descriptor ? i_channel_accept_fire :
      o_incoming_context && i_tile_admission_ready;
  assign channel_stream_value = o_chunk_reaches_end ? 16'(i_ch0) :
      o_group_end_o_equal ? 16'd0 : next_channel;
  always_comb begin
    channel_decode_value = 16'd0;
    if (q_nonzero) begin
      if (i_group_shape_o_valid) channel_decode_value = o_group_range_channel[2];
      else if (i_c.group_c == 16'd3 && q_before_limit)
        channel_decode_value = i_current_q_remainder;
    end
    channel_phase_write = 1'b0;
    channel_data_select = 4'b0000;
    unique case (1'b1)
      i_state[$clog2(WAIT_WORD)], i_state[$clog2(STREAM)], i_state[$clog2(ZERO_STREAM)]: begin
        channel_data_select = 4'b0001;
        channel_phase_write =
            !(i_state[$clog2(WAIT_WORD)] && i_cache_rsp_valid && i_cache_rsp_error) &&
            i_wr_valid && i_wr_ready &&
            ((o_chunk_reaches_end && !i_row_last_q) ||
             (!o_chunk_reaches_end && i_col_idx < i_active_cols_q &&
              p_tile_count_w'(o_chunk_count) < active_remaining));
      end
      i_state[$clog2(Q_DECODE)]: begin
        channel_data_select = 4'b0010;
        channel_phase_write = !q_nonzero || i_group_shape_o_valid ||
            (i_c.group_c == 16'd3 && q_before_limit);
      end
      i_state[$clog2(Q_WAIT)]: begin
        channel_data_select = 4'b0100;
        channel_phase_write = decode_index_matches;
      end
      default: ;
    endcase
    if (channel_commit_context) channel_data_select = 4'b1000;
  end
  assign channel_data_candidate[0] = channel_stream_value;
  assign channel_data_candidate[1] = channel_decode_value;
  assign channel_data_candidate[2] = 16'(i_decode_inner);
  assign channel_data_candidate[3] = 16'(committing_tile.channel);
  onehot_mux #(.p_choices(4), .p_width(16)) u_channel_data (
    .i_select(channel_data_select), .i_data(channel_data_candidate), .o_data(channel_selected_value)
  );
  always_comb begin
    channel_write_enable = 1'b1;
    channel_store_value = channel_value;
    // 未知输入按逐条件更新值保存，已知输入采用独立的写入资格。
    case (^{i_state, i_cache_rsp_valid, i_cache_rsp_error, i_wr_valid, i_wr_ready,
            o_chunk_reaches_end, i_row_last_q, i_col_idx, i_active_cols_q, o_chunk_count,
            active_remaining, o_group_end_o_equal, i_q0, i_group_shape_o_valid, i_c.group_c,
            i_current_q_remainder, i_decode_index, i_decode_inner, i_channel_accept_fire,
            committing_tile.channel, o_ch_q, i_ch0, o_group_range_channel[2], next_channel,
            o_incoming_context, i_tile_admission_ready})
      1'b0, 1'b1: begin
        channel_write_enable = i_channel_accept_fire || channel_phase_write;
        channel_store_value = channel_selected_value;
      end
      default: ;
    endcase
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_ch_q <= 16'd0;
    end else if (channel_write_enable) begin
      o_ch_q <= channel_store_value;
    end
  end

  // 已保存配置的通道数作用于低十六位，高位递增与低位求和并行完成。
  assign cfg_next_group_low = {1'b0, i_q0[15:0]} + {1'b0, i_c.group_c};
  assign cfg_next_group_high = {1'b0, i_q0[31:16]} + 17'd1;
  assign o_cfg_next_group = {
    cfg_next_group_low[16] ? cfg_next_group_high : {1'b0, i_q0[31:16]},
    cfg_next_group_low[15:0]};
  conv_cfg_skip_group u_cfg_skip_group (
    .i_reduction(i_q0), .i_group_channels(i_c.group_c), .o_result(o_cfg_skip_group)
  );

  // 描述符提交优先于当前流式输出的完成推进。
  // 输出接收与描述符上下文并行合并，数据保存使用已经完成的传输资格。
  always_comb begin
    address_stream_write = i_wr_valid && i_wr_ready && !i_tile_commit;
    if (p_register_descriptor) begin
      case (^{i_wr_valid, i_wr_ready, i_tile_commit, i_stream_operation_accept})
        1'b0, 1'b1: address_stream_write = i_stream_operation_accept;
        default: ;
      endcase
    end
  end
  // 地址与范围推进已经单独检查分块末尾，接收资格无需再次等待末尾判断。
  always_comb begin
    address_transfer_write = i_wr_valid && i_wr_ready && !i_tile_commit;
    if (p_register_descriptor) begin
      case (^{i_wr_valid, i_wr_ready, i_tile_commit, i_stream_transfer_accept,
               o_chunk_reaches_end, i_row_last_q})
        1'b0, 1'b1: address_transfer_write = i_stream_transfer_accept;
        default: ;
      endcase
    end
  end
  assign address_column_advance = !o_chunk_reaches_end && !i_past_active_q && o_active_after_chunk;
  conv_stream_address_select u_address_choice (
    .i_commit(i_tile_commit), .i_invalid(committing_tile.invalid), .i_fast(committing_tile.fast),
    .i_transfer(address_transfer_write), .i_chunk_end(o_chunk_reaches_end), .i_row_last(i_row_last_q),
    .i_row_valid(i_row_base_valid), .i_geometry(i_geometry_tile), .i_column_advance(address_column_advance),
    .i_group_end(o_group_end_o_equal), .i_coordinate_valid(i_coordinate_address_valid),
    .i_address_channel(i_state[$clog2(ADDRESS_CHANNEL)]), .o_select(address_update_select)
  );
  if (!p_register_descriptor) begin : g_early_address_data
    logic [31:0] selected_address;
    // 运行阶段提前选择地址，传输接收条件控制寄存器使能。
    always_comb begin
      selected_address = next_byte_addr;
      if (active_select_commit) begin
        selected_address = committing_tile.address;
      end else if (i_state[$clog2(ADDRESS_CHANNEL)]) begin
        selected_address = i_channel_addr;
      end else if (o_chunk_reaches_end) begin
        selected_address = i_next_row_addr;
      end else if (o_group_end_o_equal && i_coordinate_address_valid) begin
        selected_address = i_next_tap_addr;
      end
    end
    // 按位传递保留四态仿真的未知值传播。
    assign address_update_value = selected_address & 32'hffff_ffff;
  end else begin : g_qualified_address_data
    assign address_update_value = ({32{address_update_select[0]}} & committing_tile.address) |
      ({32{address_update_select[1]}} & i_next_row_addr) |
      ({32{address_update_select[2]}} & i_next_tap_addr) |
      ({32{address_update_select[3]}} & next_byte_addr) |
      ({32{address_update_select[4]}} & i_channel_addr);
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) o_addr <= 32'd0;
    else if (|address_update_select) o_addr <= address_update_value;
  end

  if (p_saved_word_range) begin : g_saved_word_range
    logic [4:0][p_word_shift-1:0] source_low;
    logic [p_cache_read_bytes-1:0][4:0] source_available;
    logic [p_cache_read_bytes-1:0] next_available;
    (* keep = 1 *) logic [p_cache_read_bytes-1:0] available_write_value;
    // 各地址候选并行计算字内剩余范围，接收地址的边沿同时保存范围位。
    assign source_low[0] = committing_tile.address[p_word_shift-1:0];
    assign source_low[1] = i_next_row_addr[p_word_shift-1:0];
    assign source_low[2] = i_next_tap_addr[p_word_shift-1:0];
    assign source_low[3] = next_byte_addr[p_word_shift-1:0];
    assign source_low[4] = i_channel_addr[p_word_shift-1:0];
    for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_byte
      for (genvar source = 0; source < 5; source++) begin : g_source
        conv_word_byte_range #(.p_offset_width(p_word_shift), .p_word_bytes(p_cache_read_bytes),
            .p_byte_index(byte_index)) u_range (
          .i_offset(source_low[source]), .o_available(source_available[byte_index][source])
        );
      end
      // 地址写入资格保持独立；发生保存时，运行状态直接选择对应字内范围。
      assign next_available[byte_index] = active_select_commit ? source_available[byte_index][0] :
          i_state[$clog2(ADDRESS_CHANNEL)] ? source_available[byte_index][4] :
          o_chunk_reaches_end ? source_available[byte_index][1] :
          (o_group_end_o_equal && i_coordinate_address_valid) ? source_available[byte_index][2] :
          source_available[byte_index][3];
    end
    if (!p_register_descriptor) begin : g_parallel_descriptor
      logic [13:0] range_select;
      logic [13:0][p_cache_read_bytes-1:0] range_data;
      logic [p_cache_read_bytes-1:0] parallel_available;
      // 描述符地址先分别计算字内范围，完整来源选择只进入末级位归并。
      for (genvar candidate = 0; candidate < 10; candidate++) begin : g_candidate
        assign range_select[candidate] = active_select_commit && committing_tile.operation[candidate];
        for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_byte
          assign range_data[candidate][byte_index] =
              {1'b0, i_incoming_address_candidates[candidate][p_word_shift-1:0]} <
              (p_word_shift+1)'(p_cache_read_bytes-byte_index);
        end
      end
      assign range_select[10] = !active_select_commit && i_state[$clog2(ADDRESS_CHANNEL)];
      assign range_select[11] = !active_select_commit && !i_state[$clog2(ADDRESS_CHANNEL)] &&
          o_chunk_reaches_end;
      assign range_select[12] = !active_select_commit && !i_state[$clog2(ADDRESS_CHANNEL)] &&
          !o_chunk_reaches_end && o_group_end_o_equal && i_coordinate_address_valid;
      assign range_select[13] = !active_select_commit && !i_state[$clog2(ADDRESS_CHANNEL)] &&
          !o_chunk_reaches_end && !(o_group_end_o_equal && i_coordinate_address_valid);
      for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_live
        assign range_data[10][byte_index] = source_available[byte_index][4];
        assign range_data[11][byte_index] = source_available[byte_index][1];
        assign range_data[12][byte_index] = source_available[byte_index][2];
        assign range_data[13][byte_index] = source_available[byte_index][3];
      end
      onehot_mux #(.p_choices(14), .p_width(p_cache_read_bytes)) u_range (
        .i_select(range_select), .i_data(range_data), .o_data(parallel_available)
      );
`ifdef SYNTHESIS
      assign available_write_value = parallel_available;
`else
      // 未知来源保留按地址比较和优先选择的四态传播。
      always_comb begin
        case (^{active_select_commit, i_state[$clog2(ADDRESS_CHANNEL)],
                o_chunk_reaches_end, o_group_end_o_equal, i_coordinate_address_valid,
                committing_tile.operation, i_incoming_address_candidates, source_available})
          1'b0, 1'b1: available_write_value = parallel_available;
          default: available_write_value = next_available;
        endcase
      end
`endif
    end else begin : g_saved_descriptor
      logic [p_cache_read_bytes-1:0] row_available, tap_available, step_available;
      logic [p_cache_read_bytes-1:0] running_available;
      // 运行数据先完成行、卷积核和连续地址选择，接收描述符的优先级保存在末级。
      for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_source
        assign row_available[byte_index] = source_available[byte_index][1];
        assign tap_available[byte_index] = source_available[byte_index][2];
        assign step_available[byte_index] = source_available[byte_index][3];
        assign available_write_value[byte_index] = active_select_commit ? source_available[byte_index][0] :
            i_state[$clog2(ADDRESS_CHANNEL)] ? source_available[byte_index][4] : running_available[byte_index];
      end
      conv_stream_word_select #(.p_bytes(p_cache_read_bytes)) u_running_range (
        .i_chunk_end(o_chunk_reaches_end), .i_group_end(o_group_end_o_equal),
        .i_coordinate_valid(i_coordinate_address_valid), .i_row(row_available),
        .i_tap(tap_available), .i_step(step_available), .o_available(running_available)
      );
    end
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) word_available_q <= '1;
      else if (|address_update_select) word_available_q <= available_write_value;
    end
  end else begin : g_combinational_word_range
    assign word_available_q = '0;
  end
  // 保存字命中标志与地址共用更新事件，比较结果仅经过末端选择。
  assign word_response_write = i_state[$clog2(WAIT_WORD)] && i_wr_valid && i_wr_ready;
  assign word_hit_update_select[0] = p_register_descriptor ? i_descriptor_check && !i_stream_transfer_accept :
      i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign word_hit_update_select[3:1] = address_update_select[3:1];
  assign word_hit_update_select[4] = i_state[$clog2(ADDRESS_MATCH)];
  assign word_hit_candidate = {channel_saved_hit, next_byte_saved_hit,
      next_tap_saved_hit, next_row_word_hit,
      p_register_descriptor ? i_committing_saved_word_hit || i_committing_live_word_hit : committing_tile.word_hit};
  // 各来源的命中值分两组归并，完整写入资格和回传命中在末级合并。
  assign word_hit_group[0] = |(word_hit_update_select[2:0] & word_hit_candidate[2:0]);
  assign word_hit_group[1] = |(word_hit_update_select[4:3] & word_hit_candidate[4:3]);
  assign word_hit_any_update = |word_hit_update_select;
  assign word_hit_write_enable = (i_cfg_valid && i_cfg_ready) ||
      word_hit_any_update || word_response_write;
  assign word_hit_write_value = (|word_hit_group) ||
      (!word_hit_any_update && word_response_write);
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) addr_word_hit_q <= 1'b0;
    else if (word_hit_write_enable) addr_word_hit_q <= word_hit_write_value;
  end
  // 有效列数量与逐通道范围在同一边沿更新，运行期直接读取范围寄存器。
  // 数据选择使用任务阶段；传输和行末资格只控制寄存器使能。
  assign active_select_commit = p_register_descriptor ? i_tile_commit :
      i_state[$clog2(IDLE)] ||
      ((i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] ||
        i_state[$clog2(ZERO_STREAM)]) && i_wr_last);
  assign active_data_select[0] = active_select_commit;
  assign active_data_select[1] = !active_select_commit && o_chunk_reaches_end;
  assign active_data_select[2] = !active_select_commit && !o_chunk_reaches_end;
  assign active_update_select[0] = i_tile_commit && !committing_tile.invalid;
  assign active_update_select[1] = address_transfer_write && o_chunk_reaches_end && !i_row_last_q;
  assign active_update_select[2] = address_transfer_write && !o_chunk_reaches_end;
  assign active_update_candidate[0] = committing_tile.active_columns;
  assign active_update_candidate[1] = i_active_cols_q;
  assign active_update_candidate[2] = active_remaining - p_tile_count_w'(o_chunk_count);
  assign active_update_value =
      ({p_tile_count_w{active_data_select[0]}} & active_update_candidate[0]) |
      ({p_tile_count_w{active_data_select[1]}} & active_update_candidate[1]) |
      ({p_tile_count_w{active_data_select[2]}} & active_update_candidate[2]);
  assign column_update_candidate[0] = committing_tile.columns;
  assign column_update_candidate[1] = i_cols_q;
  assign column_update_candidate[2] = col_remaining - p_tile_count_w'(o_chunk_count);
  assign column_update_value =
      ({p_tile_count_w{active_data_select[0]}} & column_update_candidate[0]) |
      ({p_tile_count_w{active_data_select[1]}} & column_update_candidate[1]) |
      ({p_tile_count_w{active_data_select[2]}} & column_update_candidate[2]);
  for (genvar lane = 0; lane <= p_lanes; lane++) begin : g_active_lane_update
    // 各来源先完成固定通道阈值比较，来源选择只参与末级归并。
    (* keep = 1 *) logic [2:0] candidate_allowed, column_allowed;
    for (genvar source = 0; source < 3; source++) begin : g_source
      if (source == 2 && p_lanes <= 16) begin : g_step
        logic [p_lanes:0] active_allowed, remaining_allowed;
        // 各种传输长度提前计算范围，末通道选择只参与最后归并。
        for (genvar step = 0; step <= p_lanes; step++) begin : g_length
          localparam logic [p_tile_count_w-1:0] p_step = p_tile_count_w'(step);
          localparam logic [p_tile_count_w-1:0] p_lane = p_tile_count_w'(lane);
          localparam logic [p_tile_count_w:0] p_boundary = {1'b0, p_step} + {1'b0, p_lane};
          logic active_before_step, remaining_before_step;
          logic active_after_boundary, remaining_after_boundary;
          if (p_step == '0) begin : g_zero_step
            assign active_before_step = 1'b0;
            assign remaining_before_step = 1'b0;
          end else begin : g_positive_step
            assign active_before_step = active_remaining < p_step;
            assign remaining_before_step = col_remaining < p_step;
          end
          if (&p_boundary[p_tile_count_w-1:0]) begin : g_last_boundary
            assign active_after_boundary = 1'b0;
            assign remaining_after_boundary = 1'b0;
          end else begin : g_lower_boundary
            assign active_after_boundary = active_remaining > p_boundary[p_tile_count_w-1:0];
            assign remaining_after_boundary = col_remaining > p_boundary[p_tile_count_w-1:0];
          end
          // 模减法后的范围直接表示为两个常量边界之间的区间。
          if (p_boundary[p_tile_count_w]) begin : g_wrapped_boundary
            assign active_allowed[step] = active_before_step && active_after_boundary;
            assign remaining_allowed[step] = remaining_before_step && remaining_after_boundary;
          end else begin : g_ordered_boundary
            assign active_allowed[step] = active_before_step || active_after_boundary;
            assign remaining_allowed[step] = remaining_before_step || remaining_after_boundary;
          end
        end
        assign candidate_allowed[source] = |(o_chunk_selected & active_allowed);
        assign column_allowed[source] = |(o_chunk_selected & remaining_allowed);
      end else begin : g_count
        if (source == 0) begin : g_descriptor_threshold
          conv_count_threshold #(.p_width(p_tile_count_w), .p_threshold(lane)) u_active (
            .i_count(active_update_candidate[source]), .o_above(candidate_allowed[source])
          );
        end else begin : g_saved_threshold
          assign candidate_allowed[source] = p_tile_count_w'(lane) < active_update_candidate[source];
        end
        assign column_allowed[source] = p_tile_count_w'(lane) < column_update_candidate[source];
      end
    end
    assign active_lane_update[lane] = |(active_data_select & candidate_allowed);
    assign column_lane_update[lane] = |(active_data_select & column_allowed);
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) column_lane_allowed_q[lane] <= $unsigned(p_tile_count_w'(lane)) < $unsigned(p_tile_count_w'(p_size));
      else if (|active_update_select) column_lane_allowed_q[lane] <= column_lane_update[lane];
    end
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) col_remaining <= p_tile_count_w'(p_size);
    else if (|active_update_select) col_remaining <= column_update_value;
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      active_remaining <= '0;
      active_lane_allowed_q <= '0;
    end else if (|active_update_select) begin
      active_remaining <= active_update_value;
      active_lane_allowed_q <= active_lane_update;
    end
  end
  // 各运行来源先形成目标状态，通道结束条件只选择已经完成的候选。
  conv_im2col_stream_control u_stream_control (
    .i_chunk_end(o_chunk_reaches_end), .i_row_last(i_row_last_q),
    .i_row_base_valid(i_row_base_valid), .i_geometry_tile(i_geometry_tile),
    .i_next_row_padding(i_next_row_padding), .i_next_row_word_hit(next_row_word_hit),
    .i_row_coordinate_valid(i_row_coordinate_valid),
    .i_past_active(i_past_active_q), .i_active_after(o_active_after_chunk),
    .i_group_end(o_group_end_o_equal), .i_coordinate_address_valid(i_coordinate_address_valid),
    .i_next_tap_padding(i_next_tap_padding), .i_next_word_equal(i_next_word_o_equal),
    .i_padding(i_pad_q), .i_tap_context(o_request_tap_context),
    .i_word_boundary(word_boundary), .i_stream_eligible(stream_request_eligible),
    .o_state(stream_static_state), .o_request_selected(stream_request_selected),
    .o_row_selected(stream_row_selected), .o_tap_selected(stream_tap_selected)
  );
  // 接收条件只改变 FETCH 和 WAIT_WORD 两个状态位。
  assign stream_read_accepted = i_cache_req_ready &&
      (stream_request_selected || (stream_row_selected && row_request_eligible));
  for (genvar state_bit = 0; state_bit < $bits(st_t); state_bit++) begin : g_stream_accept_state
    if (state_bit == $clog2(FETCH)) begin : g_fetch
      assign stream_accepted_state[state_bit] = stream_static_state[state_bit] && !stream_read_accepted;
    end else if (state_bit == $clog2(WAIT_WORD)) begin : g_wait
      assign stream_accepted_state[state_bit] = stream_read_accepted;
    end else begin : g_static
      assign stream_accepted_state[state_bit] = stream_static_state[state_bit];
    end
  end
`ifdef SYNTHESIS
  assign o_stream_advance_state = stream_accepted_state;
`else
  always_comb begin
    o_stream_advance_state = stream_static_state;
    if (stream_request_selected && i_cache_req_ready) o_stream_advance_state = WAIT_WORD;
    if (stream_row_selected)
      o_stream_advance_state = row_request_eligible && i_cache_req_ready ? WAIT_WORD : FETCH;
    case (^{stream_static_state, stream_request_selected, stream_row_selected,
            row_request_eligible, i_cache_req_ready})
      1'b0, 1'b1: o_stream_advance_state = stream_accepted_state;
      default: ;
    endcase
  end
`endif
endmodule

`default_nettype wire
