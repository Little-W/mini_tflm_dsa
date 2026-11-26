// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 保存输入、权重、偏置、量化参数与累加值，按通道分组共享读写选择。
module vector_engine_operand_store #(
  parameter int p_tile = 16,
  parameter int p_bus_width = 32,
  parameter int p_dma_size = 4*p_tile,
  parameter int p_pe_count = (p_tile < 8) ? p_tile : 8,
  parameter int p_window_lanes = 4,
  parameter bit p_shared_quant_enable = 1'b0,
  parameter int p_quant_lanes = p_shared_quant_enable ? p_tile : 1,
  parameter bit p_shared_storage_enable = 1'b0,
  parameter int p_shared_storage_addr_width = 12,
  parameter int p_max_taps = 49,
  parameter int p_pool_max_taps = 256,
  localparam int p_bus_bytes=p_bus_width/8,
  localparam int p_bus_shift=$clog2(p_bus_bytes),
  localparam int p_input_banks=p_window_lanes>p_bus_bytes ? p_window_lanes : p_bus_bytes,
  localparam int p_active_count_w = $clog2(p_tile + 1),
  localparam int p_tap_limit = p_max_taps > p_pool_max_taps ? p_max_taps : p_pool_max_taps,
  localparam int p_tap_count_w = $clog2(p_tap_limit + 1),
  localparam int p_tile_index_w = $clog2(p_tile + p_pe_count + 1),
  localparam int p_input_index_w = $clog2(p_dma_size),
  localparam int p_input_stored_elements = p_pe_count>=16 ? 4*p_tile : 2*p_tile,
  localparam bit p_input_bank_storage = p_tile==16 && p_pe_count==8 && p_dma_size==64 &&
      p_bus_width==64 && p_window_lanes==8,
  localparam int p_input_bank_rows = (p_input_stored_elements+p_input_banks-1)/p_input_banks,
  localparam int p_input_row_width = p_input_bank_rows>1 ? $clog2(p_input_bank_rows) : 1,
  localparam int p_pool_row_w=p_input_index_w>p_bus_shift ? p_input_index_w-p_bus_shift : 1,
  localparam int p_weight_dma_groups=(p_tile+p_bus_bytes-1)/p_bus_bytes,
  localparam int p_window_bank_w=$clog2(p_window_lanes),
  localparam int p_bias_words_per_beat = p_bus_width / 32
) (
  input wire logic clk, // 模块工作时钟。
  input wire logic rst_n, // 低有效复位输入。
  input wire logic [31:0] i_win_rsp_col, // 返回窗口数据的起始通道索引。
  input wire logic signed [15:0] i_win_rsp_data [p_window_lanes], // 卷积前端返回的逐通道十六位数据。
  input wire logic [p_window_lanes-1:0] i_win_rsp_mask, // 本拍返回窗口数据的有效通道掩码。
  output logic signed [31:0] o_quant_req_multiplier [p_tile], // 各通道量化请求使用的三十二位乘数。
  output logic [5:0] o_quant_req_right [p_tile], // 各通道量化请求使用的右移位数。
  output logic o_weight_read_en, // 共享权重存储的读取使能。
  output logic [p_shared_storage_addr_width-1:0] o_weight_read_addr, // 共享权重存储的读取地址。
  input wire logic i_weight_read_valid, // 共享权重存储返回数据有效。
  input wire logic [127:0] i_weight_read_data, // 共享权重存储返回的一百二十八位数据。
  output logic o_weight_write_en, // 共享权重存储的写入使能。
  output logic [p_shared_storage_addr_width-1:0] o_weight_write_addr, // 共享权重存储的写入地址。
  output logic [127:0] o_weight_write_data, // 送入共享权重存储的一百二十八位数据。
  output logic [15:0] o_weight_write_mask, // 共享权重存储各字节的写入使能。
  input wire logic i_storage_error, // 共享操作数存储报告错误。
  input wire logic signed [15:0] i_rd_data [p_bus_width/8], // DMA 返回并完成格式处理的逐通道数据。
  input wire logic i_rd_valid [p_bus_width/8], // DMA 返回数据各通道的有效标志。
  input wire logic [$clog2(p_dma_size)-1:0] i_rd_col_base, // DMA 本拍返回数据的起始列索引。
  input wire logic [p_bus_width-1:0] i_rd_raw_data, // DMA 返回的原始总线数据。
  input wire logic i_rd_raw_valid, // DMA 原始总线返回数据有效。
  input wire logic i_read_done_q, // 已保存的 DMA 读取完成状态。
  input wire vector_engine_control_pkg::state_t i_state, // 向量控制器当前的状态编码。
  input wire logic i_state_failed, // 控制器正在处理任务错误。
  input wire logic i_state_compute_commit, // 控制器正在提交本轮计算结果。
  input wire logic i_state_weight_read_phase, // 当前阶段允许准备权重读取。
  input wire logic i_state_weight_zero_address, // 当前阶段使用卷积核首位置读取权重。
  input wire logic i_state_output_init, // 控制器正在初始化当前输出分块。
  input wire logic i_state_vector_init, // 控制器正在初始化当前向量分块。
  input wire vector_engine_control_pkg::load_t i_load_kind, // 当前 DMA 读取的数据类型。
  input wire vector_engine_pkg::vector_engine_cfg_t i_c, // 当前已保存的向量任务配置。
  input wire logic i_spatial, // 当前任务为深度卷积或空间池化运算。
  input wire logic i_depthwise, // 当前任务执行八位深度卷积。
  input wire logic i_add_s8, // 当前任务执行量化八位向量加法。
  input wire logic i_softmax_s8, // 当前任务执行八位 Softmax。
  input wire logic i_max_pool, // 当前任务执行最大值池化。
  input wire logic i_min_pool, // 当前任务执行最小值池化。
  input wire logic i_vector_max, // 当前向量任务执行最大值归约。
  input wire logic i_vector_min, // 当前向量任务执行最小值归约。
  input wire logic i_vector_hadamard, // 当前向量任务执行逐元素乘法。
  input wire logic [p_active_count_w-1:0] i_active, // 当前分块实际使用的通道或元素数量。
  input wire logic [p_tile-1:0] i_active_lane_mask, // 当前分块各计算通道的有效掩码。
  input wire logic [p_tap_count_w-1:0] i_taps, // 当前卷积核或池化窗口的总位置数。
  input wire logic [p_tap_count_w-1:0] i_tap, // 当前计算使用的卷积核线性位置。
  input wire logic [p_tap_count_w-1:0] i_load_tap, // 当前 DMA 权重数据对应的卷积核位置。
  input wire logic [p_tile_index_w-1:0] i_compute_index, // 当前并行计算组的首元素索引。
  input wire logic i_compute_group_last_q, // 已保存的当前并行计算组为末组的条件。
  output logic signed [15:0] o_input_buf [p_dma_size], // 按元素索引访问的输入数据缓存视图。
  output logic signed [15:0] o_rhs_buf [p_tile], // 当前分块的第二路有符号向量输入。
  output logic [7:0] o_input_softmax_data, // 当前 Softmax 输入索引对应的八位数据。
  output logic [7:0] o_add_input_saved, // 已保存的当前量化加法输入字节。
  output logic o_weight_row_last_fire, // 本拍权重返回数据结束一个卷积核位置。
  output logic o_weight_data_ready, // 当前卷积核位置的权重数据已经可用。
  output logic o_shared_weight_write_pending, // 共享权重存储仍有等待完成的写入。
  output logic [p_tap_count_w-1:0] o_weight_tap_nxt, // 当前卷积核位置加一后的索引。
  output logic [p_tap_count_w-1:0] o_weight_tap_after_next, // 当前卷积核位置加二后的索引。
  input wire logic [p_tap_count_w-1:0] i_weight_prefetch_q, // 已保存的下一权重预取位置。
  output logic o_tap_last_wide, // 扩展位宽比较确认当前卷积核位置为末项。
  input wire logic i_tap_last_modulo, // 随卷积核位置保存的末项标志。
  output logic o_tap_last_config, // 按新配置的核元素数计算的末项条件。
  output logic o_tap_last_zero, // 卷积核位置归零后即为末项的条件。
  output logic o_tap_last_increment, // 卷积核位置递增一次后成为末项的条件。
  output logic signed [31:0] o_acc_buf [p_tile], // 当前输出分块各通道的累加结果。
  input wire logic [p_tile-1:0] i_result_write_enable, // 各通道量化结果的写回使能。
  input wire logic [7:0] i_result_write_data [p_tile], // 各通道待写回的八位量化结果。
  input wire logic signed [31:0] i_pe_result [p_pe_count], // 本轮并行计算单元返回的三十二位结果。
  input wire logic i_global_pool, // 当前池化窗口覆盖整个输入图像。
  input wire logic [63:0] i_kernel_count, // 配置检查得到的卷积核或池化窗口位置总数。
  input wire logic [p_tile_index_w-1:0] i_q_issue, // 当前准备送入量化流水的通道索引。
  input wire logic i_dw_commit_vld, // 深度卷积乘加结果可以写回累加存储。
  input wire logic i_dw_tap_advance, // 深度卷积计算推进到下一卷积核位置。
  input wire logic [p_tile_index_w-1:0] i_dw_commit_index, // 当前深度卷积写回结果的首通道索引。
  input wire logic i_dw_snapshot_fire, // 保存一个输出位置的完整深度卷积累加结果。
  input wire logic i_writeback_busy, // 结果写回仍有待处理数据或事务。
  input wire logic [p_input_index_w-1:0] i_input_read_base, // 当前计算读取槽的输入存储起始元素索引。
  input wire logic [p_input_index_w-1:0] i_input_response_base, // 当前返回槽的输入存储起始元素索引。
  input wire logic i_window_response_fire, // 本周期接收卷积窗口返回数据。
  output logic o_window_write_pending, // 已接收窗口数据尚待写入输入存储。
  input wire logic [$clog2(p_tile)-1:0] i_soft_input_index, // Softmax 当前需要读取的输入元素索引。
  input wire logic [p_input_index_w:0] i_pool_received, // 当前池化输入批次已接收的有效元素数。
  input wire logic [p_input_index_w:0] i_pool_elements, // 当前池化输入批次需要接收的元素总数。
  input wire logic [p_input_index_w:0] i_pool_input_index, // 当前池化计算在输入缓存中的首元素索引。
  input wire logic i_pool_response_fire, // 本周期接收一拍池化输入数据。
  input wire logic [p_bus_shift:0] i_pool_beat_count, // 当前池化返回拍包含的有效元素数。
  output logic signed [15:0] o_input_lane [p_pe_count], // 送入本组计算单元的输入操作数。
  output logic signed [15:0] o_rhs_lane [p_pe_count], // 送入本组计算单元的第二路向量操作数。
  output logic signed [7:0] o_weight_lane [p_pe_count], // 送入本组计算单元的八位有符号权重。
  output logic signed [31:0] o_accum_lane [p_pe_count], // 送入本组计算单元的三十二位累加初值。
  output logic signed [31:0] o_params_o_multiplier, // 当前串行量化通道的有符号乘数。
  output logic [5:0] o_params_o_right_shift // 当前串行量化通道的右移位数。
);
  logic [31:0] win_rsp_col;
  logic signed [15:0] win_rsp_data [p_window_lanes];
  logic [p_window_lanes-1:0] win_rsp_mask;
  logic signed [31:0] quant_req_multiplier [p_tile];
  logic [5:0] quant_req_right [p_tile];
  logic signed [15:0] rd_data [p_bus_width/8];
  logic rd_valid [p_bus_width/8];
  logic [$clog2(p_dma_size)-1:0] rd_col_base;
  logic [p_bus_width-1:0] rd_raw_data;
  logic rd_raw_valid;
  logic read_done_q;
  vector_engine_control_pkg::state_t state;
  logic state_failed;
  logic state_compute_commit;
  logic state_weight_read_phase;
  logic state_weight_zero_address;
  logic state_output_init;
  logic state_vector_init;
  vector_engine_control_pkg::load_t load_kind;
  vector_engine_pkg::vector_engine_cfg_t c;
  logic spatial;
  logic depthwise;
  logic add_s8;
  logic softmax_s8;
  logic max_pool;
  logic min_pool;
  logic vector_max;
  logic vector_min;
  logic vector_hadamard;
  logic [p_active_count_w-1:0] active;
  logic [p_tile-1:0] active_lane_mask;
  logic [p_tap_count_w-1:0] taps;
  logic [p_tap_count_w-1:0] tap;
  logic [p_tap_count_w-1:0] load_tap;
  logic [p_tile_index_w-1:0] compute_index;
  logic compute_group_last_q;
  logic signed [15:0] input_buf [p_dma_size];
  logic signed [15:0] rhs_buf [p_tile];
  logic [7:0] input_softmax_data;
  logic [7:0] add_input_saved;
  logic weight_row_last_fire;
  logic weight_data_ready;
  logic shared_weight_write_pending;
  logic [p_tap_count_w-1:0] weight_tap_nxt;
  logic [p_tap_count_w-1:0] weight_tap_after_next;
  logic [p_tap_count_w-1:0] weight_prefetch_q;
  logic tap_last_wide;
  logic tap_last_modulo;
  logic tap_last_config;
  logic tap_last_zero;
  logic tap_last_increment;
  logic signed [31:0] acc_buf [p_tile];
  logic [p_tile-1:0] result_write_enable;
  logic [7:0] result_write_data [p_tile];
  logic signed [31:0] pe_result [p_pe_count];
  logic global_pool;
  logic [63:0] kernel_count;
  logic [p_tile_index_w-1:0] q_issue;
  logic dw_commit_vld;
  logic dw_tap_advance;
  logic [p_tile_index_w-1:0] dw_commit_index;
  logic dw_snapshot_fire;
  logic writeback_busy;
  logic [p_input_index_w-1:0] input_read_base;
  logic [p_input_index_w-1:0] input_response_base;
  logic window_response_fire;
  logic window_write_pending;
  logic [$clog2(p_tile)-1:0] soft_input_index;
  logic [p_input_index_w:0] pool_received;
  logic [p_input_index_w:0] pool_elements;
  logic [p_input_index_w:0] pool_input_index;
  logic pool_response_fire;
  logic [p_bus_shift:0] pool_beat_count;
  logic signed [15:0] input_lane [p_pe_count];
  logic signed [15:0] rhs_lane [p_pe_count];
  logic signed [7:0] weight_lane [p_pe_count];
  logic signed [31:0] accum_lane [p_pe_count];
  logic signed [31:0] params_o_multiplier;
  logic [5:0] params_o_right_shift;

  // 端口与内部保存值之间使用显式连续连接。
  assign win_rsp_col = i_win_rsp_col;
  assign win_rsp_data = i_win_rsp_data;
  assign win_rsp_mask = i_win_rsp_mask;
  assign o_quant_req_multiplier = quant_req_multiplier;
  assign o_quant_req_right = quant_req_right;
  assign rd_data = i_rd_data;
  assign rd_valid = i_rd_valid;
  assign rd_col_base = i_rd_col_base;
  assign rd_raw_data = i_rd_raw_data;
  assign rd_raw_valid = i_rd_raw_valid;
  assign read_done_q = i_read_done_q;
  assign state = i_state;
  assign state_failed = i_state_failed;
  assign state_compute_commit = i_state_compute_commit;
  assign state_weight_read_phase = i_state_weight_read_phase;
  assign state_weight_zero_address = i_state_weight_zero_address;
  assign state_output_init = i_state_output_init;
  assign state_vector_init = i_state_vector_init;
  assign load_kind = i_load_kind;
  assign c = i_c;
  assign spatial = i_spatial;
  assign depthwise = i_depthwise;
  assign add_s8 = i_add_s8;
  assign softmax_s8 = i_softmax_s8;
  assign max_pool = i_max_pool;
  assign min_pool = i_min_pool;
  assign vector_max = i_vector_max;
  assign vector_min = i_vector_min;
  assign vector_hadamard = i_vector_hadamard;
  assign active = i_active;
  assign active_lane_mask = i_active_lane_mask;
  assign taps = i_taps;
  assign tap = i_tap;
  assign load_tap = i_load_tap;
  assign compute_index = i_compute_index;
  assign compute_group_last_q = i_compute_group_last_q;
  assign o_input_buf = input_buf;
  assign o_rhs_buf = rhs_buf;
  assign o_input_softmax_data = input_softmax_data;
  assign o_add_input_saved = add_input_saved;
  assign o_weight_row_last_fire = weight_row_last_fire;
  assign o_weight_data_ready = weight_data_ready;
  assign o_shared_weight_write_pending = shared_weight_write_pending;
  assign o_weight_tap_nxt = weight_tap_nxt;
  assign o_weight_tap_after_next = weight_tap_after_next;
  assign weight_prefetch_q = i_weight_prefetch_q;
  assign o_tap_last_wide = tap_last_wide;
  assign tap_last_modulo = i_tap_last_modulo;
  assign o_tap_last_config = tap_last_config;
  assign o_tap_last_zero = tap_last_zero;
  assign o_tap_last_increment = tap_last_increment;
  assign o_acc_buf = acc_buf;
  assign result_write_enable = i_result_write_enable;
  assign result_write_data = i_result_write_data;
  assign pe_result = i_pe_result;
  assign global_pool = i_global_pool;
  assign kernel_count = i_kernel_count;
  assign q_issue = i_q_issue;
  assign dw_commit_vld = i_dw_commit_vld;
  assign dw_tap_advance = i_dw_tap_advance;
  assign dw_commit_index = i_dw_commit_index;
  assign dw_snapshot_fire = i_dw_snapshot_fire;
  assign writeback_busy = i_writeback_busy;
  assign input_read_base = i_input_read_base;
  assign input_response_base = i_input_response_base;
  assign window_response_fire = i_window_response_fire;
  assign o_window_write_pending = window_write_pending;
  assign soft_input_index = i_soft_input_index;
  assign pool_received = i_pool_received;
  assign pool_elements = i_pool_elements;
  assign pool_input_index = i_pool_input_index;
  assign pool_response_fire = i_pool_response_fire;
  assign pool_beat_count = i_pool_beat_count;
  assign o_input_lane = input_lane;
  assign o_rhs_lane = rhs_lane;
  assign o_weight_lane = weight_lane;
  assign o_accum_lane = accum_lane;
  assign o_params_o_multiplier = params_o_multiplier;
  assign o_params_o_right_shift = params_o_right_shift;


  logic signed [15:0] input_bank_data [p_input_banks];
  logic signed [15:0] input_bank_read_data [p_input_banks];
  logic signed [15:0] input_bank_contents [p_input_banks][p_input_bank_rows];
  logic [p_input_index_w:0] input_vector_base;
  logic [p_input_index_w-1:0] input_scalar_index;
  logic signed [15:0] input_scalar_data;
  logic [p_input_row_width-1:0] input_bank_read_row;
  logic weights_i_wr_en;
  logic weights_i_rd_en;
  logic [31:0] weights_i_wr_tap;
  logic [p_tile-1:0] weights_i_wr_mask;
  logic [8*p_tile-1:0] weights_i_wr_data;
  logic [8*p_tile-1:0] weights_o_rd_data;
  logic weight_tap_advance;
  logic unused_weight_tap_carry;
  logic unused_weight_prefetch_carry;
  logic signed [7:0] weight_tap_data [p_tile];
  logic signed [31:0] bias_buf [p_tile];
  logic [p_window_lanes-1:0] window_bank_valid;
  logic [p_window_lanes-1:0] window_bank_valid_next;
  logic [p_bus_bytes-1:0] pool_bank_valid;
  logic [p_pool_row_w-1:0] pool_bank_row [p_bus_bytes];
  logic [p_weight_dma_groups-1:0] weight_column_match;
  (* keep = 1 *) logic [p_weight_dma_groups-1:0] weight_group_nonempty;
  logic [p_tile-1:0] weight_lane_valid;
  logic weight_write_nonempty;
  (* keep = 1 *) logic window_write_valid [p_window_lanes];
  logic [p_window_lanes-1:0] window_lane_valid;
  logic window_write_pending_next;
  logic dma_input_write_valid [p_bus_bytes];
  logic [p_input_index_w-1:0] window_write_index [p_window_lanes];
  logic [p_input_index_w-1:0] dma_input_write_index [p_bus_bytes];
  logic [p_input_index_w-1:0] window_bank_index [p_window_lanes];
  logic signed [15:0] window_bank_data [p_window_lanes];
  logic [p_window_bank_w-1:0] window_first_bank;
  logic [p_input_index_w-1:0] window_start_index;
  logic [p_input_index_w-1:0] window_row_next;
  logic [p_bus_shift-1:0] pool_first_bank;
  logic bias_load_fire;
  logic [31:0] bias_word_index [p_bias_words_per_beat];
  logic bias_bank_valid [p_bias_words_per_beat];
  logic [31:0] bias_bank_index [p_bias_words_per_beat];
  logic [31:0] bias_bank_data [p_bias_words_per_beat];
  logic params_i_wr_en;
  logic params_i_wr_multiplier;
  logic params_i_wr_shift;
  logic [p_input_index_w-1:0] params_i_wr_byte_index;
  logic [p_bus_width-1:0] params_i_wr_data;
  logic [p_active_count_w-1:0] params_i_active;
  logic [p_tile_index_w-1:0] params_i_rd_index;
  logic signed [15:0] rhs_write_data [p_bus_bytes];
  logic rhs_write_valid [p_bus_bytes];
  logic [31:0] rhs_write_index [p_bus_bytes];
  logic accumulator_compute_fire;
  logic accumulator_init_fire;
  logic accumulator_bias_selected;
  logic signed [31:0] accumulator_init_data;

  generate if (p_tile % p_pe_count == 0) begin : g_compute_lane_banks
    for (genvar lane=0;lane<p_pe_count;lane++) begin : g_lane
      logic signed [15:0] rhs_value;
      logic signed [7:0] weight_value;
      logic signed [31:0] accum_value;
      always_comb begin
        rhs_value='0;weight_value='0;accum_value='0;
        for (int group=0;group<p_tile/p_pe_count;group++) begin
          if (compute_index==p_tile_index_w'(group*p_pe_count)) begin
            rhs_value=rhs_buf[group*p_pe_count+lane];
            weight_value=weight_tap_data[group*p_pe_count+lane];
            accum_value=acc_buf[group*p_pe_count+lane];
          end
        end
      end
      assign rhs_lane[lane]=rhs_value;
      if (p_shared_storage_enable && p_tile == 2*p_pe_count &&
          (p_pe_count & (p_pe_count-1)) == 0) begin : g_shared_weight_select
        localparam int p_group_bit = $clog2(p_pe_count);
        logic [8*p_tile-1:0] saved_weights, returned_weights;
        logic signed [7:0] saved_value, returned_value, selected_value;
        assign saved_weights = (8*p_tile)'(g_shared_weights.saved_data);
        assign returned_weights = (8*p_tile)'(i_weight_read_data);
        // 通道组先选择两份数据中的对应字节，返回资格只选择当前通道组。
        assign saved_value = compute_index[p_group_bit] ?
            saved_weights[8*(p_pe_count+lane)+:8] : saved_weights[8*lane+:8];
        assign returned_value = compute_index[p_group_bit] ?
            returned_weights[8*(p_pe_count+lane)+:8] : returned_weights[8*lane+:8];
        assign selected_value = g_shared_weights.return_matches ? returned_value : saved_value;
        always_comb begin
          weight_lane[lane] = '0;
          if (compute_index == p_tile_index_w'(0) || compute_index == p_tile_index_w'(p_pe_count))
            weight_lane[lane] = selected_value;
        end
      end else begin : g_weight_select
        assign weight_lane[lane] = weight_value;
      end
      assign accum_lane[lane]=accum_value;
    end
  end else begin : g_compute_lane_fallback
    for (genvar lane=0;lane<p_pe_count;lane++) begin : g_lane
      assign rhs_lane[lane]=rhs_buf[compute_index+32'(lane)];
      assign weight_lane[lane]=weight_tap_data[compute_index+32'(lane)];
      assign accum_lane[lane]=acc_buf[compute_index+32'(lane)];
    end
  end endgenerate
  // 向量与标量运算共用每个银行的读取端口，标量字节在独立边沿保存。
  always_comb begin
    input_vector_base = (p_input_index_w+1)'(compute_index);
    if (state==vector_engine_control_pkg::EXECUTE && global_pool)
      input_vector_base = (p_input_index_w+1)'(pool_input_index) + (p_input_index_w+1)'(compute_index);
    else if (spatial && !global_pool)
      input_vector_base = (p_input_index_w+1)'(input_read_base) + (p_input_index_w+1)'(compute_index);
  end
  assign input_scalar_index = add_s8 ?
      (state==vector_engine_control_pkg::ADD_CLAMP || state==vector_engine_control_pkg::ADD_STORE ? p_input_index_w'(compute_index+1'b1) : '0) :
      p_input_index_w'(soft_input_index);
  assign input_bank_read_row = add_s8 || softmax_s8 ?
      p_input_row_width'(input_scalar_index>>$clog2(p_input_banks)) :
      p_input_row_width'(input_vector_base>>$clog2(p_input_banks));
  // Add 在结果限幅周期准备下一项，Softmax 在读取状态等待寄存数据。
  if (p_input_bank_storage) begin : g_add_input_prepare
    always_ff @(posedge clk) begin
      if (add_s8 || softmax_s8) add_input_saved <= input_scalar_data[7:0];
    end
  end
  generate if (p_input_bank_storage) begin : g_input_memory_read
    logic read_valid, half_group;
    assign half_group = state==vector_engine_control_pkg::EXECUTE && global_pool && active==4 && input_vector_base[2];
    always_comb begin
      read_valid = 1'b0;
      if ((input_vector_base>>$clog2(p_input_banks)) < (p_input_index_w+1)'(p_input_bank_rows))
        read_valid = 1'b1;
    end
    assign input_scalar_data = {8'd0, input_bank_read_data[input_scalar_index[$clog2(p_input_banks)-1:0]][7:0]};
    assign input_softmax_data = add_input_saved;
    for (genvar lane=0;lane<p_pe_count;lane++) begin : g_lane
      assign input_lane[lane] = read_valid ?
          (half_group ? input_bank_read_data[(lane+4)%p_pe_count] : input_bank_read_data[lane]) : 16'sd0;
    end
  end else begin : g_input_general_read
    assign input_scalar_data = 16'sd0;
    assign input_softmax_data = 8'd0;
  if (p_pe_count > 1 && (p_pe_count & (p_pe_count-1)) == 0 &&
               p_dma_size % p_pe_count == 0) begin : g_input_lane_banks
    localparam int p_bank_shift = $clog2(p_pe_count);
    localparam int p_bank_rows = p_dma_size / p_pe_count;
    logic [p_input_index_w:0] vector_base;
    logic signed [15:0] bank_current [p_pe_count], bank_next [p_pe_count];
    always_comb begin
      if (state==vector_engine_control_pkg::EXECUTE && global_pool)
        vector_base = (p_input_index_w+1)'(pool_input_index) + (p_input_index_w+1)'(compute_index);
      else if (spatial && !global_pool)
        vector_base = (p_input_index_w+1)'(input_read_base) + (p_input_index_w+1)'(compute_index);
      else vector_base = (p_input_index_w+1)'(compute_index);
    end
    for (genvar bank=0;bank<p_pe_count;bank++) begin : g_bank
      always_comb begin
        bank_current[bank] = '0;
        bank_next[bank] = '0;
        for (int row=0;row<p_bank_rows;row++) begin
          if ((vector_base >> p_bank_shift)==(p_input_index_w+1)'(row))
            bank_current[bank] = input_buf[row*p_pe_count+bank];
          if ((vector_base >> p_bank_shift)+1==(p_input_index_w+1)'(row))
            bank_next[bank] = input_buf[row*p_pe_count+bank];
        end
      end
    end
    if (p_tile==16 && p_pe_count==8 && p_dma_size==64) begin : g_aligned_lanes
      localparam int p_stored_rows = (2*p_tile)/p_pe_count;
      localparam int p_row_width = $clog2(p_stored_rows);
      logic [p_row_width-1:0] read_row;
      logic signed [15:0] read_data [p_pe_count];
      logic read_valid;
      logic half_group;

      assign read_row = vector_base[p_bank_shift+:p_row_width];
      assign half_group = state==vector_engine_control_pkg::EXECUTE && global_pool && active==4 && vector_base[2];

      // 输入存储的前两个 p_tile 保存数据，其余项由 g_unused 固定为零。
      // 银行内使用二进制行号选择数据，完整地址的有效条件在银行交换后统一处理。
      always_comb begin
        read_valid = 1'b0;
        if ((vector_base >> p_bank_shift) < (p_input_index_w+1)'(p_stored_rows))
          read_valid = 1'b1;
      end
      for (genvar bank=0;bank<p_pe_count;bank++) begin : g_read_bank
        logic signed [15:0] rows [p_stored_rows];
        for (genvar row=0;row<p_stored_rows;row++) begin : g_row
          assign rows[row] = input_buf[row*p_pe_count+bank];
        end
        assign read_data[bank] = rows[read_row];
      end
      for (genvar lane=0;lane<p_pe_count;lane++) begin : g_lane
        assign input_lane[lane] = read_valid ?
            (half_group ? read_data[(lane+4)%p_pe_count] : read_data[lane]) : 16'sd0;
      end
    end else begin : g_general_lanes
      for (genvar lane=0;lane<p_pe_count;lane++) begin : g_lane
        logic [p_bank_shift:0] lane_sum;
        assign lane_sum = {1'b0,vector_base[p_bank_shift-1:0]} + (p_bank_shift+1)'(lane);
        logic signed [15:0] lane_value;
        always_comb begin
          lane_value = '0;
          for (int bank=0;bank<p_pe_count;bank++)
            if (lane_sum[p_bank_shift-1:0]==p_bank_shift'(bank))
              lane_value = lane_sum[p_bank_shift] ? bank_next[bank] : bank_current[bank];
        end
        assign input_lane[lane] = lane_value;
      end
    end
  end else begin : g_input_lane_fallback
    for (genvar lane=0;lane<p_pe_count;lane++) begin : g_lane
      logic [31:0] base;
      assign base = state==vector_engine_control_pkg::EXECUTE && global_pool ? pool_input_index :
          spatial && !global_pool ? 32'(input_read_base) : 32'd0;
      assign input_lane[lane] = input_buf[base+32'(compute_index)+32'(lane)];
    end
  end

  end endgenerate
  // 权重按卷积核位置整行保存，字节掩码允许每个通道独立接收 DMA 数据。
  // 提交当前计算结果时准备下一位置，使同步读取在下一次计算前完成。
  assign weights_i_wr_en = rst_n && (state == vector_engine_control_pkg::LOAD_WAIT) && !read_done_q && (load_kind == vector_engine_control_pkg::LD_WEIGHT);
  assign weights_i_wr_tap = 32'(load_tap);
  // 一个二维 DMA 描述符读取整组卷积核，各行末拍推进权重存储行号。
  assign weight_row_last_fire = weights_i_wr_en && (|weights_i_wr_mask) &&
      32'(rd_col_base)+32'(p_bus_bytes)>=32'(active);
  assign weight_tap_advance = ((state_compute_commit) &&
      compute_group_last_q && !global_pool && spatial &&
      !tap_last_wide) || (dw_tap_advance && !tap_last_modulo);
  // 递增数据和末项条件并行计算，分别保留扩展比较与窄位回绕比较。
  parallel_prefix_add #(
      .p_width(p_tap_count_w), .p_group_width(3), .p_preserve_groups(1'b1)
  ) u_weight_tap_increment (
      .i_a(tap), .i_b(p_tap_count_w'(1)), .i_carry(1'b0),
      .o_sum(weight_tap_nxt), .o_carry(unused_weight_tap_carry)
  );
  // 下一读取地址在核位置更新边沿保存，预取端口只保留初始化选择。
  parallel_prefix_add #(
      .p_width(p_tap_count_w), .p_group_width(3), .p_preserve_groups(1'b1)
  ) u_weight_prefetch_increment (
      .i_a(tap), .i_b(p_tap_count_w'(2)), .i_carry(1'b0),
      .o_sum(weight_tap_after_next), .o_carry(unused_weight_prefetch_carry)
  );
  add_equal #(.p_width(32)) u_tap_last_wide (
      .i_a(32'(tap)), .i_b(32'd1), .i_target(32'(taps)), .i_carry_in(1'b0),
      .o_equal(tap_last_wide)
  );
  // 末项资格与核位置同时保存，权重预取直接读取该寄存结果。
  // 三种更新分别对应配置载入、位置归零和核位置递增。
  add_equal #(.p_width(p_tap_count_w)) u_tap_last_config (
      .i_a(tap), .i_b(p_tap_count_w'(1)), .i_target(p_tap_count_w'(kernel_count)),
      .i_carry_in(1'b0), .o_equal(tap_last_config)
  );
  add_equal #(.p_width(p_tap_count_w)) u_tap_last_zero (
      .i_a({p_tap_count_w{1'b0}}), .i_b(p_tap_count_w'(1)), .i_target(taps),
      .i_carry_in(1'b0), .o_equal(tap_last_zero)
  );
  add_equal #(.p_width(p_tap_count_w)) u_tap_last_increment (
      .i_a(tap), .i_b(p_tap_count_w'(2)), .i_target(taps),
      .i_carry_in(1'b0), .o_equal(tap_last_increment)
  );
  // 同步读取提前准备当前或下一卷积核位置；加载权重期间不发起共享 RAM 读取。
  assign weights_i_rd_en = !p_shared_storage_enable || (rst_n && depthwise && !i_storage_error &&
      state_weight_read_phase);
  assign weight_write_nonempty = |(weight_column_match & weight_group_nonempty);
  for (genvar group=0;group<p_weight_dma_groups;group++) begin : g_weight_write_group
    logic [31:0] column_mismatch;
    assign column_mismatch =32'(rd_col_base)^32'(group*p_bus_bytes);
    logic [p_bus_bytes-1:0] eligible_lanes;
    // 同一总线字共用列地址比较；零加法保留原三十二位算术的未知值传播。
    assign weight_column_match[group]=(column_mismatch+32'd0)==32'd0;
    for (genvar lane=0;lane<p_bus_bytes;lane++) begin : g_lane
      if (group*p_bus_bytes+lane<p_tile) begin : g_present
        assign eligible_lanes[lane]=weight_lane_valid[group*p_bus_bytes+lane];
      end else begin : g_empty
        assign eligible_lanes[lane]=1'b0;
      end
    end
    // 先归并各组有效字节，列地址资格在最后参与写请求的非空判断。
    assign weight_group_nonempty[group]=|eligible_lanes;
  end
  for (genvar channel = 0; channel < p_tile; channel++) begin : g_weight_channel
    localparam int p_dma_lane = channel % p_bus_bytes;
    assign weight_lane_valid[channel]=rd_valid[p_dma_lane] && active_lane_mask[channel];
    assign weights_i_wr_mask[channel]=weight_column_match[channel/p_bus_bytes] && weight_lane_valid[channel];
    assign weights_i_wr_data[8*channel+:8] = rd_data[p_dma_lane][7:0];
    assign weight_tap_data[channel] = $signed(weights_o_rd_data[8*channel+:8]);
  end
  if (p_shared_storage_enable) begin : g_shared_weights
    logic [p_shared_storage_addr_width-1:0] prefetch_tap, return_tap, saved_tap;
    logic [127:0] saved_data;
    logic saved_valid, return_matches, saved_matches;
    logic write_capture, write_valid_q;
    logic [p_shared_storage_addr_width-1:0] write_tap_q;
    logic [127:0] write_data_q;
    logic [15:0] write_mask_q;
    localparam int p_tag_groups = (p_shared_storage_addr_width+2)/3;
    (* keep = 1 *) logic [p_tag_groups-1:0] return_match_groups, saved_match_groups;
    logic [p_shared_storage_addr_width-1:0] current_tap;

    // 每组分别比较三个地址位，再合并有效标志，保留并行的权重标签比较。
    assign current_tap = p_shared_storage_addr_width'(tap);
    for (genvar group=0;group<p_tag_groups;group++) begin : g_tag_match
      localparam int p_low = 3*group;
      localparam int p_width = p_shared_storage_addr_width-p_low<3 ?
          p_shared_storage_addr_width-p_low : 3;
      assign return_match_groups[group] = return_tap[p_low+:p_width] == current_tap[p_low+:p_width];
      assign saved_match_groups[group] = saved_tap[p_low+:p_width] == current_tap[p_low+:p_width];
    end

    // 当前权重和下一核位置并行保留。预取地址只取决于已保存的核位置，
    // 当前输入是否就绪以及是否发射均不参与共享存储器的地址选择。
    assign prefetch_tap = state_weight_zero_address ?
        '0 : p_shared_storage_addr_width'(weight_prefetch_q);
    assign return_matches = i_weight_read_valid && (&return_match_groups);
    assign saved_matches = saved_valid && (&saved_match_groups);
    assign weight_data_ready = return_matches || saved_matches;
    assign o_weight_read_en = weights_i_rd_en;
    assign o_weight_read_addr = prefetch_tap;
    // 线性响应的地址、数据和有效字节同拍保存，每个周期提交一组权重。
    // 错误状态停止发布，排空条件同时等待已经保存的写请求。
    assign write_capture = weights_i_wr_en && weight_write_nonempty;
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) write_valid_q <= 1'b0;
      else write_valid_q <= write_capture && !i_storage_error && !state_failed;
    end
    always_ff @(posedge clk) begin
      if (write_capture) begin
        write_tap_q <= p_shared_storage_addr_width'(weights_i_wr_tap);
        write_data_q <= 128'(weights_i_wr_data);
        write_mask_q <= 16'(weights_i_wr_mask);
      end
    end
    assign shared_weight_write_pending = write_valid_q;
    assign o_weight_write_en = write_valid_q && !i_storage_error && !state_failed;
    assign o_weight_write_addr = write_tap_q;
    assign o_weight_write_data = write_data_q;
    assign o_weight_write_mask = write_mask_q;
    assign weights_o_rd_data = (8*p_tile)'(return_matches ? i_weight_read_data : saved_data);

    // 返回地址与同步 RAM 请求同拍保存；首次返回可直接供发射使用，
    // 下一边沿保存该行，使后续通道组及输入等待周期继续使用同一份权重。
    always_ff @(posedge clk) begin
      if (o_weight_read_en) return_tap <= prefetch_tap;
      if (return_matches) begin
        saved_tap <= return_tap;
        saved_data <= i_weight_read_data;
      end
    end
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        saved_valid <= 1'b0;
      end else if ((state == vector_engine_control_pkg::CHECK) || state == vector_engine_control_pkg::TILE_INIT ||
                   state_output_init || state_failed) begin
        saved_valid <= 1'b0;
      end else if (return_matches) begin
        saved_valid <= 1'b1;
      end
    end
  end else begin : g_private_weights
    logic [31:0] weights_i_rd_tap;
    assign weights_i_rd_tap = state_weight_zero_address ? 32'd0 :
        weight_tap_advance ? 32'(weight_tap_nxt) : 32'(tap);
    assign shared_weight_write_pending = 1'b0;
    vector_weight_store #(.p_channels(p_tile), .p_depth(p_max_taps)) u_weights (
        .clk(clk), .i_wr_en(weights_i_wr_en), .i_wr_tap(weights_i_wr_tap),
        .i_wr_mask(weights_i_wr_mask), .i_wr_data(weights_i_wr_data),
        .i_rd_tap(weights_i_rd_tap), .o_rd_data(weights_o_rd_data)
    );
    assign o_weight_read_en = 1'b0;
    assign o_weight_read_addr = '0;
    assign o_weight_write_en = 1'b0;
    assign o_weight_write_addr = '0;
    assign o_weight_write_data = '0;
    assign o_weight_write_mask = '0;
    assign weight_data_ready = 1'b1;
  end
  for (genvar lane=0;lane<p_window_lanes;lane++) begin : g_window_write_address
    logic [p_input_index_w:0] column_sum;
    assign column_sum ={1'b0,win_rsp_col[p_input_index_w-1:0]}+(p_input_index_w+1)'(lane);
    logic [p_input_index_w+1:0] column_difference;
    // 扩展减法保留最高借位，完整宽度同时参与四态算术传播。
    assign column_difference = {1'b0,column_sum} - (p_input_index_w+2)'(active);
    assign window_write_valid[lane]=window_response_fire && win_rsp_mask[lane] &&
        win_rsp_col<32'(active) && column_difference[p_input_index_w+1];
    assign window_lane_valid[lane]=window_write_valid[lane];
    assign window_write_index[lane]=input_response_base+p_input_index_w'(column_sum);
  end
  if (p_window_lanes == 8) begin : g_window_bank_map
    logic [7:0][2:0] mapped_source;

    // 循环起点和各分区来源同时计算，列号低三位支持全部八种取值。
    vector_window_bank_map u_map (
      .i_base(3'(input_response_base)), .i_column(3'(win_rsp_col)),
      .o_first(window_first_bank), .o_source(mapped_source)
    );
  end else begin : g_window_bank_arithmetic
    assign window_first_bank = p_window_bank_w'(input_response_base)+p_window_bank_w'(win_rsp_col);
  end
  assign window_start_index = input_response_base + p_input_index_w'(win_rsp_col);
  assign window_row_next = (window_start_index >> p_window_bank_w) + p_input_index_w'(1);
  for (genvar bank=0;bank<p_window_lanes;bank++) begin : g_window_bank
    logic [p_window_bank_w-1:0] source_lane;
    if (p_window_lanes == 8) begin : g_mapped_source
      assign source_lane = g_window_bank_map.mapped_source[bank];
    end else begin : g_arithmetic_source
      assign source_lane =p_window_bank_w'(bank)-window_first_bank;
    end
    if (p_window_lanes == 8) begin : g_grouped_valid
      // 四路选择分别保存组合分组，最后由高位选择对应分组。
      (* keep = 1 *) logic [1:0] selected_half;
      for (genvar half=0;half<2;half++) begin : g_half
        logic [3:0] half_valid;
        assign half_valid =window_lane_valid[4*half+:4];
        vector_window_valid_mux u_select (
          .i_values(half_valid), .i_index(source_lane[1:0]), .o_value(selected_half[half])
        );
      end
      assign window_bank_valid_next[bank]=selected_half[source_lane[2]];
    end else begin : g_direct_valid
      assign window_bank_valid_next[bank]=window_write_valid[source_lane];
    end
    if (p_input_bank_storage) begin : g_registered_write
      logic [p_input_index_w-1:0] selected_index;
      logic [p_input_index_w-p_window_bank_w-1:0] selected_row;
      // 固定目标银行只需要选择当前行或进位后的下一行。
      assign selected_row = p_window_bank_w'(bank) < window_first_bank ?
          window_row_next : window_start_index[p_input_index_w-1:p_window_bank_w];
      always_comb begin
        selected_index = window_write_index[source_lane];
        case (^{window_start_index, window_first_bank})
          1'b0, 1'b1: selected_index = {selected_row, p_window_bank_w'(bank)};
        endcase
      end
      always_ff @(posedge clk) begin
        if (!rst_n) window_bank_valid[bank] <= 1'b0;
        else begin
          window_bank_valid[bank] <= window_bank_valid_next[bank];
          if (window_bank_valid_next[bank]) window_bank_index[bank] <= selected_index;
        end
      end
    end else begin : g_direct_write
      assign window_bank_valid[bank]=window_write_valid[source_lane];
      assign window_bank_index[bank]=window_write_index[source_lane];
    end
    if (!p_input_bank_storage) begin : g_direct_data
      assign window_bank_data[bank]=win_rsp_data[source_lane];
    end
  end
  // 二的整数次幂银行数允许先归并有效位，再选择对应的循环起点。
  // 选择索引仍参与表达式，保留未知索引时的四态结果。
  if ((p_window_lanes & (p_window_lanes-1)) == 0) begin : g_window_pending_reduce
    logic [p_window_lanes-1:0] nonempty_by_rotation;
    assign nonempty_by_rotation ={p_window_lanes{|window_lane_valid}};
    assign window_write_pending_next=nonempty_by_rotation[window_first_bank];
  end else begin : g_window_pending_direct
    assign window_write_pending_next=|window_bank_valid_next;
  end
  // 保存本拍写入是否非空，排空控制直接使用与各银行有效位同拍的汇总标志。
  always_ff @(posedge clk) begin
    if (!rst_n) window_write_pending <= 1'b0;
    else window_write_pending <= window_write_pending_next;
  end
  for (genvar lane=0;lane<p_bus_bytes;lane++) begin : g_dma_write_address
    logic [p_input_index_w:0] column_sum;
    assign column_sum ={1'b0,rd_col_base}+(p_input_index_w+1)'(lane);
    assign dma_input_write_valid[lane]=state==vector_engine_control_pkg::LOAD_WAIT && load_kind==vector_engine_control_pkg::LD_A && rd_valid[lane] &&
        column_sum<(p_input_index_w+1)'(active);
    assign dma_input_write_index[lane]=p_input_index_w'(column_sum);
  end
  // 线性 S8 响应包含按列顺序连续排列的有效数据。
  // 每次响应统一循环选择数据，写入对应的输入存储银行。
  assign pool_first_bank = p_bus_shift'(pool_received);
  for (genvar bank=0;bank<p_bus_bytes;bank++) begin : g_pool_bank
    logic [p_bus_shift-1:0] source_lane;
    assign source_lane =p_bus_shift'(bank)-pool_first_bank;
    logic [p_input_index_w:0] destination_index;
    assign destination_index =pool_received+(p_input_index_w+1)'(source_lane);
    logic bank_receive;
    assign bank_receive =pool_response_fire && (p_bus_shift+1)'(source_lane)<pool_beat_count &&
        destination_index<pool_elements;
    logic [p_pool_row_w-1:0] destination_row;
    assign destination_row =p_pool_row_w'(pool_received>>p_bus_shift)+
        p_pool_row_w'(p_bus_shift'(bank)<pool_first_bank);
    always_ff @(posedge clk) begin
      if (!rst_n) pool_bank_valid[bank]<=1'b0;
      else begin
        pool_bank_valid[bank]<=bank_receive;
        if (bank_receive) begin
          pool_bank_row[bank]<=destination_row;

        end
      end
    end
    if (!p_input_bank_storage) begin : g_rotated_register
      logic signed [15:0] data;
      always_ff @(posedge clk) begin
        if (rst_n && bank_receive) data <= rd_data[source_lane];
      end
    end
  end

  // 空间响应保存原始数据和起始银行，窗口与全局池化共用循环选择器。
  // 数据与写入行号同时进入寄存阶段，下一边沿写入输入存储并发布完成。
  if (p_input_bank_storage) begin : g_spatial_input_data
    logic [p_window_bank_w-1:0] first_bank_saved, selected_first;
    logic signed [15:0] spatial_raw_data [p_input_banks];
    logic signed [15:0] rotated_half [p_input_banks];

    always_ff @(posedge clk) begin
      if (pool_response_fire || window_response_fire) begin
        first_bank_saved <= global_pool ? pool_first_bank : window_first_bank;
        for (int lane=0;lane<p_input_banks;lane++)
          spatial_raw_data[lane] <= global_pool ? rd_data[lane] : win_rsp_data[lane];
      end
    end
    assign selected_first = first_bank_saved;
    // 先交换两个半组，再由各银行共享四路细分选择结果。
    for (genvar bank=0;bank<p_input_banks;bank++) begin : g_half_bank
      logic signed [15:0] half_candidates [2];
      assign half_candidates[0] = spatial_raw_data[bank];
      assign half_candidates[1] = spatial_raw_data[(bank+p_input_banks-4)%p_input_banks];
      assign rotated_half[bank] = half_candidates[selected_first[2]];
    end
    for (genvar bank=0;bank<p_input_banks;bank++) begin : g_selected_bank
      logic signed [15:0] selected_candidates [4];
      for (genvar step=0;step<4;step++) begin : g_selected_candidate
        assign selected_candidates[step] = rotated_half[(bank+p_input_banks-step)%p_input_banks];
      end
      assign window_bank_data[bank] = selected_candidates[selected_first[1:0]];
    end
  end


  // 每个总线银行共用一个数据选择器，存储项分别保留地址比较和写使能。
  // 已保存的运算模式确定普通向量、窗口和全局池化响应的数据来源。
  for (genvar bank=0;bank<p_input_banks;bank++) begin : g_input_bank_data
    localparam int p_s16_lane = bank % (p_bus_bytes / 2);
    localparam int p_s8_lane = bank % p_bus_bytes;
    localparam int p_window_bank = bank % p_window_lanes;
    logic signed [15:0] dma_bank_data;

    assign dma_bank_data = c.vector_s16 ? rd_data[p_s16_lane] : rd_data[p_s8_lane];
    if (p_input_bank_storage) begin : g_shared_rotation
      assign input_bank_data[bank] = spatial ? window_bank_data[p_window_bank] : dma_bank_data;
    end else begin : g_separate_rotation
      assign input_bank_data[bank] = global_pool ? g_pool_bank[p_s8_lane].g_rotated_register.data :
          spatial ? window_bank_data[p_window_bank] : dma_bank_data;
    end
  end

  // 一个银行每拍至多写入一行，完整数据字保存到普通数组并异步读取。
  if (p_input_bank_storage) begin : g_input_memory
    for (genvar bank=0;bank<p_input_banks;bank++) begin : g_bank
      logic signed [15:0] mem [p_input_bank_rows];
      logic [p_input_row_width-1:0] write_row;
      logic [p_input_index_w-1:0] load_index;
      logic load_valid, write_valid;

      assign load_index = c.vector_s16 ? dma_input_write_index[bank%(p_bus_bytes/2)] :
          dma_input_write_index[bank%p_bus_bytes];
      assign load_valid = (c.vector_s16 ? dma_input_write_valid[bank%(p_bus_bytes/2)] :
          dma_input_write_valid[bank%p_bus_bytes]) &&
          load_index[$clog2(p_input_banks)-1:0] == $clog2(p_input_banks)'(bank);
      assign write_valid = pool_bank_valid[bank] || window_bank_valid[bank] || load_valid;
      assign write_row = global_pool ? p_input_row_width'(pool_bank_row[bank]) : spatial ?
          p_input_row_width'(window_bank_index[bank]>>$clog2(p_input_banks)) :
          p_input_row_width'(load_index>>$clog2(p_input_banks));

      always_ff @(posedge clk) begin
        if (rst_n && write_valid) mem[write_row] <= input_bank_data[bank];
      end
      assign input_bank_read_data[bank] = mem[input_bank_read_row];
      for (genvar row=0;row<p_input_bank_rows;row++) begin : g_row
        assign input_bank_contents[bank][row] = mem[row];
      end
    end
  end

  for (genvar entry=0;entry<p_dma_size;entry++) begin : g_input_write
    if (entry>=p_input_stored_elements) begin : g_unused
      assign input_buf[entry]=16'sd0;
    end else begin : g_buffer
    if (p_input_bank_storage) begin : g_memory_value
      assign input_buf[entry] = input_bank_contents[entry%p_input_banks][entry/p_input_banks];
    end else begin : g_register_value
      localparam int p_s8_lane=entry%p_bus_bytes;
      localparam int p_s16_lane=entry%(p_bus_bytes/2);
      logic load_match;
      assign load_match =c.vector_s16 ?
          dma_input_write_valid[p_s16_lane] && dma_input_write_index[p_s16_lane]==p_input_index_w'(entry) :
          dma_input_write_valid[p_s8_lane] && dma_input_write_index[p_s8_lane]==p_input_index_w'(entry);
      logic write_enable;
      logic signed [15:0] write_value;
      localparam int p_window_bank=entry%p_window_lanes;
      logic window_match;
      assign window_match =window_bank_valid[p_window_bank] &&
          window_bank_index[p_window_bank]==p_input_index_w'(entry);
      logic pool_match;
      assign pool_match =pool_bank_valid[p_s8_lane] &&
          pool_bank_row[p_s8_lane]==p_pool_row_w'(entry/p_bus_bytes);

      assign write_enable = window_match || load_match || pool_match;
      assign write_value = input_bank_data[entry%p_input_banks];
      always_ff @(posedge clk) if (rst_n && write_enable) input_buf[entry] <= write_value;
    end
    end
  end

  // 每拍的连续偏置字分配到固定分组，同组存储项共用数据字选择。

  assign bias_load_fire = (state == vector_engine_control_pkg::LOAD_WAIT) && (load_kind == vector_engine_control_pkg::LD_BIAS) && rd_raw_valid;
  for (genvar word = 0; word < p_bias_words_per_beat; word++) begin : g_bias_word_index
    assign bias_word_index[word] = (32'(rd_col_base) >> 2) + 32'(word);
  end
  for (genvar bank = 0; bank < p_bias_words_per_beat; bank++) begin : g_bias_write_bank
    always_comb begin
      bias_bank_valid[bank] = 1'b0;
      bias_bank_index[bank] = 32'd0;
      bias_bank_data[bank] = 32'd0;
      for (int word = 0; word < p_bias_words_per_beat; word++) begin
        if ((bias_word_index[word] % 32'(p_bias_words_per_beat)) == 32'(bank)) begin
          bias_bank_valid[bank] = bias_load_fire && (bias_word_index[word] < 32'(active));
          bias_bank_index[bank] = bias_word_index[word];
          bias_bank_data[bank] = rd_raw_data[word*32 +: 32];
        end
      end
      if (state == vector_engine_control_pkg::TILE_INIT) begin
        bias_bank_data[bank] = 32'd0;
      end
    end
  end
  // 深度为一的存储保留所有偏置的并行读取，初始化周期同时写入零值。
  for (genvar entry = 0; entry < p_tile; entry++) begin : g_bias_storage
    localparam int p_bank = entry % p_bias_words_per_beat;
    logic bias_storage_i_wr_en;
    logic [0:0] bias_storage_i_wr_addr;
    logic [31:0] bias_storage_i_wr_data;
    logic [0:0] bias_storage_i_wr_mask;
    logic [0:0] bias_storage_i_rd_en;
    logic [0:0][0:0] bias_storage_i_rd_addr;
    logic [0:0][31:0] bias_storage_o_rd_data;

    assign bias_storage_i_wr_en = rst_n && ((state == vector_engine_control_pkg::TILE_INIT) ||
        (bias_bank_valid[p_bank] && (bias_bank_index[p_bank] == 32'(entry))));
    assign bias_storage_i_wr_addr = '0;
    assign bias_storage_i_wr_data = bias_bank_data[p_bank];
    assign bias_storage_i_wr_mask = '1;
    assign bias_storage_i_rd_en = '1;
    assign bias_storage_i_rd_addr = '0;
    assign bias_buf[entry] = $signed(bias_storage_o_rd_data[0]);
    regfile #(
        .p_data_width(32),
        .p_depth(1),
        .p_addr_width(1),
        .p_write_unit(32),
        .p_read_ports(1),
        .p_sync_read(1'b0)
    ) u_bias_storage (
        .clk(clk),
        .i_wr_en(bias_storage_i_wr_en),
        .i_wr_addr(bias_storage_i_wr_addr),
        .i_wr_data(bias_storage_i_wr_data),
        .i_wr_mask(bias_storage_i_wr_mask),
        .i_rd_en(bias_storage_i_rd_en),
        .i_rd_addr(bias_storage_i_rd_addr),
        .o_rd_data(bias_storage_o_rd_data)
    );
  end

  // DMA 参数写入按数据字分组，量化阶段仍在原有时钟边沿接收异步读数据。
  assign params_i_wr_en = rst_n && state==vector_engine_control_pkg::LOAD_WAIT && rd_raw_valid;
  assign params_i_wr_multiplier = (load_kind==vector_engine_control_pkg::LD_MULT);
  assign params_i_wr_shift = (load_kind==vector_engine_control_pkg::LD_SHIFT);
  assign params_i_wr_byte_index = rd_col_base;
  assign params_i_wr_data = rd_raw_data;
  assign params_i_active = active;
  assign params_i_rd_index = q_issue;
  vector_quant_params #(
      .p_entries(p_tile),
      .p_bus_width(p_bus_width),
      .p_dma_index_width(p_input_index_w),
      .p_read_index_width(p_tile_index_w),
      .p_active_width(p_active_count_w),
      .p_parallel_output(p_shared_quant_enable)
  ) u_quant_params (
      .clk(clk),
      .i_wr_en(params_i_wr_en),
      .i_wr_multiplier(params_i_wr_multiplier),
      .i_wr_shift(params_i_wr_shift),
      .i_wr_byte_index(params_i_wr_byte_index),
      .i_wr_data(params_i_wr_data),
      .i_active(params_i_active),
      .i_rd_index(params_i_rd_index),
      .o_multiplier(params_o_multiplier),
      .o_right_shift(params_o_right_shift),
      .o_multiplier_vec(quant_req_multiplier),
      .o_right_shift_vec(quant_req_right)
  );

  // 每个 DMA 通道共享格式选择，存储项只检查各自的目标地址。
  for (genvar bank=0;bank<p_bus_bytes;bank++) begin : g_rhs_write_bank
    localparam int p_s16_lane = bank % (p_bus_bytes/2);
    always_comb begin
      rhs_write_data[bank] = rd_data[bank];
      rhs_write_valid[bank] = rd_valid[bank];
      rhs_write_index[bank] = 32'(rd_col_base) + 32'(bank);
      if (c.vector_s16) begin
        rhs_write_data[bank] = rd_data[p_s16_lane];
        rhs_write_valid[bank] = rd_valid[p_s16_lane];
        rhs_write_index[bank] = 32'(rd_col_base) + 32'(p_s16_lane);
      end
    end
  end

  assign accumulator_compute_fire = (state_compute_commit && (!vector_hadamard || !writeback_busy)) ||
      (dw_commit_vld && !state_failed && !dw_snapshot_fire);
  assign accumulator_init_fire = state_output_init || state_vector_init || dw_snapshot_fire;
  assign accumulator_bias_selected = depthwise && (state_output_init || dw_snapshot_fire);
  always_comb begin
    accumulator_init_data = 32'sd0;
    if (state_output_init) begin
      if (max_pool) accumulator_init_data = -32'sd128;
      else if (min_pool) accumulator_init_data = 32'sd127;
    end else if (state_vector_init) begin
      if (vector_max) accumulator_init_data = 32'sh8000_0000;
      else if (vector_min) accumulator_init_data = 32'sh7fff_ffff;
    end
  end
  for (genvar entry=0;entry<p_tile;entry++) begin : g_accumulator_write
    localparam int p_lane_index = entry % p_pe_count;
    localparam int p_group_base = entry - p_lane_index;
    logic compute_write, bias_write, constant_write;
    logic write_enable;
    logic [31:0] write_value;
    assign compute_write = accumulator_compute_fire && active_lane_mask[entry] &&
        (depthwise ? dw_commit_index : compute_index) == p_tile_index_w'(p_group_base);
    assign bias_write = accumulator_init_fire && accumulator_bias_selected;
    assign constant_write = accumulator_init_fire && !accumulator_bias_selected;
    assign write_enable = compute_write || accumulator_init_fire;
    assign write_value = ({32{accumulator_compute_fire}} & pe_result[p_lane_index]) |
        ({32{bias_write}} & bias_buf[entry]) |
        ({32{constant_write}} & accumulator_init_data);
    // 字节输出在当前累加项已完成全部读取后更新低字节。
    always_ff @(posedge clk) begin
      if (rst_n && write_enable) acc_buf[entry][31:8] <= write_value[31:8];
      if (rst_n) begin
        if (result_write_enable[entry]) acc_buf[entry][7:0] <= result_write_data[entry];
        else if (write_enable) acc_buf[entry][7:0] <= write_value[7:0];
      end
    end
    always_ff @(posedge clk) begin
      if (rst_n && state==vector_engine_control_pkg::LOAD_WAIT &&
          load_kind==vector_engine_control_pkg::LD_B && 32'(entry)<active &&
          rhs_write_valid[entry%p_bus_bytes] && rhs_write_index[entry%p_bus_bytes]==32'(entry))
        rhs_buf[entry] <= rhs_write_data[entry%p_bus_bytes];
    end
  end
endmodule

`default_nettype wire
