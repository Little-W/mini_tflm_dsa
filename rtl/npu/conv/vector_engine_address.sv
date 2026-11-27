// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 生成向量、窗口及 DMA 地址，并保存坐标边界与请求资格。
module vector_engine_address #(
  parameter int p_tile = 16,
  parameter bit p_registered_read_phase = 1'b0,
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
  localparam int p_active_count_w = $clog2(p_tile + 1),
  localparam int p_tap_limit = p_max_taps > p_pool_max_taps ? p_max_taps : p_pool_max_taps,
  localparam int p_tap_count_w = $clog2(p_tap_limit + 1),
  localparam int p_tile_index_w = $clog2(p_tile + p_pe_count + 1),
  localparam int p_input_index_w = $clog2(p_dma_size),
  localparam bit p_input_bank_storage = p_tile==16 && p_pe_count==8 && p_dma_size==64 &&
      p_bus_width==64 && p_window_lanes==8,
  localparam int p_window_count_width = $clog2(p_window_lanes+1),
  localparam int p_window_count_leaves = 1 << $clog2(p_window_lanes)
) (
  input wire logic clk, // 模块工作时钟。
  input wire logic rst_n, // 低有效复位输入。
  input wire logic i_start, // 提交一个新的向量计算任务。
  input wire vector_engine_pkg::vector_engine_cfg_t i_cfg, // 当前待接收的向量任务配置。
  input wire logic i_dma_cfg_ready, // 共享 DMA 能够接收当前读取配置。
  output logic o_dma_conv_enable, // 共享 DMA 采用卷积窗口展开方式。
  output logic o_dma_range_enable, // 共享 DMA 启用已配置的读取区间检查。
  output conv_im2col_pkg::conv_cfg_t o_dma_conv_cfg, // 提供给共享 DMA 的卷积窗口配置。
  output logic [31:0] o_dma_range_base [4], // 共享 DMA 各读取区间的起始字节地址。
  output logic [32:0] o_dma_range_end [4], // 共享 DMA 各读取区间的右端地址，不包含该地址。
  output logic o_win_req_valid, // 卷积窗口读取请求有效。
  input wire logic i_win_req_ready, // 卷积前端能够接收当前窗口请求。
  output logic [31:0] o_win_req_p0, // 窗口请求对应的线性输出位置起点。
  output logic [31:0] o_win_req_q0, // 窗口请求对应的卷积归约位置起点。
  output logic [31:0] o_win_req_cols, // 当前窗口请求需要返回的通道数。
  output logic [1:0] o_win_req_tag, // 当前窗口请求分配的输入缓存槽标签。
  input wire logic i_win_rsp_valid, // 卷积前端返回的窗口数据有效。
  output logic o_win_rsp_ready, // 能够接收卷积前端的窗口数据。
  input wire logic [1:0] i_win_rsp_tag, // 返回窗口数据所属的输入缓存槽标签。
  input wire logic [p_window_lanes-1:0] i_win_rsp_mask, // 本拍返回窗口数据的有效通道掩码。
  input wire logic i_win_rsp_last, // 当前返回数据结束本次窗口请求。
  input wire logic i_win_rsp_error, // 卷积前端报告当前窗口读取错误。
  input wire logic i_win_busy, // 卷积窗口前端仍有正在处理的请求。
  input wire logic i_weight_read_valid, // 共享权重存储返回数据有效。
  input wire logic i_ps_read_valid, // 共享部分和存储返回数据有效。
  input wire logic i_rd_req, // 向共享 DMA 仲裁器申请读取资源。
  output logic o_rd_start, // 启动已获得授权的 DMA 读取任务。
  input wire logic i_rd_granted, // 共享 DMA 仲裁器授予读取资源。
  output logic o_rd_im2col, // 当前 DMA 读取使用卷积窗口展开。
  output logic [31:0] o_rd_p0, // DMA 卷积读取的线性输出位置起点。
  output logic [31:0] o_rd_q0, // DMA 卷积读取的归约位置起点。
  output logic [31:0] o_rd_base_addr, // DMA 读取的起始字节地址。
  output logic [31:0] o_rd_row_stride, // DMA 相邻读取行的字节间隔。
  output logic [31:0] o_rd_rows_to_read, // 当前 DMA 任务需要读取的行数。
  output logic [31:0] o_rd_valid_cols, // 当前 DMA 读取行的有效列数。
  output logic [7:0] o_rd_burst_len_m1, // DMA 每行读取的突发拍数减一。
  output logic o_rd_use_16bits, // DMA 返回数据采用十六位元素。
  input wire logic i_rd_busy, // 共享 DMA 正在执行读取。
  input wire logic i_rd_done, // 共享 DMA 的当前读取任务完成。
  input wire logic i_rd_valid [p_bus_width/8], // DMA 返回数据各通道的有效标志。
  input wire logic [$clog2(p_dma_size)-1:0] i_rd_col_base, // DMA 本拍返回数据的起始列索引。
  input wire logic [p_bus_width-1:0] i_rd_raw_data, // DMA 返回的原始总线数据。
  input wire logic i_rd_raw_valid, // DMA 原始总线返回数据有效。
  input wire logic i_wr_busy, // 共享 DMA 仍在执行写入。
  input wire logic i_read_done_q, // 已保存的 DMA 读取完成状态。
  input wire vector_engine_control_pkg::state_t i_state, // 向量控制器当前的状态编码。
  input wire logic i_state_soft_lut_read = 1'b0, // 控制器正在读取 Softmax 指数近似表。
  input wire logic i_state_pool_read = 1'b0, // 控制器正在读取池化输入数据。
  input wire logic i_state_failed, // 控制器正在处理任务错误。
  input wire logic i_state_compute_commit, // 控制器正在提交本轮计算结果。
  input wire logic i_state_dw_execute, // 控制器正在发射深度卷积计算。
  input wire logic i_state_output_init, // 控制器正在初始化当前输出分块。
  input wire logic i_state_dw_finish, // 控制器正在完成当前深度卷积输出位置。
  input wire logic i_window_fetch_phase, // 当前状态允许继续预取输入窗口。
  input wire vector_engine_control_pkg::load_t i_load_kind, // 当前 DMA 读取的数据类型。
  input wire logic [5:0] i_load_read_select = 6'b000000, // 各类读取来源的独立选择标志。
  input wire vector_engine_pkg::vector_engine_cfg_t i_c, // 当前已保存的向量任务配置。
  input wire logic i_spatial, // 当前任务为深度卷积或空间池化运算。
  input wire logic i_depthwise, // 当前任务执行八位深度卷积。
  input wire logic i_vector_hadamard, // 当前向量任务执行逐元素乘法。
  input wire logic i_add_s8, // 当前任务执行量化八位向量加法。
  input wire logic i_binary_vector, // 当前任务需要两路向量输入。
  input wire logic i_softmax_s8, // 当前任务执行八位 Softmax。
  output logic [31:0] o_channels, // 当前空间任务的通道总数。
  input wire logic [31:0] i_position, // 当前处理的线性输出空间位置。
  input wire logic [15:0] i_channel_base, // 当前通道分块的首通道编号。
  input wire logic [p_active_count_w-1:0] i_active, // 当前分块实际使用的通道或元素数量。
  input wire logic [p_tap_count_w-1:0] i_taps, // 当前卷积核或池化窗口的总位置数。
  input wire logic [15:0] i_ox, // 当前计算输出位置的横坐标。
  output logic [15:0] o_fetch_ox_next, // 窗口预取扫描的下一输出横坐标。
  input wire logic [p_tap_count_w-1:0] i_kx, // 当前卷积核位置的横坐标。
  input wire logic [p_tap_count_w-1:0] i_kernel_last_column, // 当前卷积核的最后一个列坐标。
  input wire logic [p_tap_count_w-1:0] i_tap, // 当前计算使用的卷积核线性位置。
  input wire logic [p_tap_count_w-1:0] i_valid_taps, // 当前输出位置已累计的有效窗口位置数。
  input wire logic [31:0] i_vector_offset, // 当前向量分块相对输入起点的元素偏移。
  output logic [31:0] o_channel_remaining, // 当前通道起点之后尚需处理的通道数。
  output logic [15:0] o_channel_next, // 完成当前分块后的下一首通道编号。
  output logic o_channel_has_more, // 当前分块之后仍有空间通道需要处理。
  output logic [p_active_count_w-1:0] o_vector_next_active, // 下一向量分块需要处理的有效元素数。
  output logic o_vector_has_more, // 当前分块之后仍有向量元素需要处理。
  input wire logic [p_tile_index_w-1:0] i_compute_index, // 当前并行计算组的首元素索引。
  output logic o_compute_group_last_q, // 已保存的当前并行计算组为末组的条件。
  output logic o_pool_pixel_has_more_q, // 已保存的池化批次还有后续像素的条件。
  input wire logic [31:0] i_fetch_tap_offset, // 预取卷积核位置相对窗口起点的通道偏移。
  input wire logic [31:0] i_position_offset, // 当前输出空间位置的线性字节偏移。
  input wire logic [31:0] i_pool_byte_offset, // 当前池化批次相对输入基址的字节偏移。
  output logic [31:0] o_fetch_position_next, // 窗口预取扫描的下一线性输出位置。
  output logic [31:0] o_fetch_tap_offset_next, // 下一预取卷积核位置的通道偏移。
  output logic [31:0] o_position_offset_next, // 下一输出空间位置的线性字节偏移。
  output logic [31:0] o_pool_byte_offset_next, // 下一池化输入批次的字节偏移。
  output logic [31:0] o_vector_offset_next, // 下一向量分块相对输入起点的元素偏移。
  output logic signed [31:0] o_add_input_sum, // 八位加法两路缩放输入相加后的中间结果。
  output logic o_parameter_row_last_fire, // 本拍参数返回数据结束当前参数数组行。
  output logic o_parameter_three_rows, // 偏置、乘数和移位数组能够用三行连续描述符读取。
  output logic o_parameter_two_rows, // 乘数和移位数组能够用两行连续描述符读取。
  input wire logic i_shared_weight_write_pending, // 共享权重存储仍有等待完成的写入。
  input wire logic i_tap_last_modulo, // 随卷积核位置保存的末项标志。
  input wire logic signed [31:0] i_add_scaled_a, // 已保存的第一路八位加法输入缩放值。
  input wire logic signed [63:0] i_add_rounded, // 已保存的八位加法缩放舍入中间结果。
  input wire logic signed [33:0] i_input_y, // 当前计算对应的有符号输入纵坐标。
  input wire logic signed [33:0] i_input_x, // 当前计算对应的有符号输入横坐标。
  input wire logic signed [33:0] i_input_origin_x, // 当前输出窗口起点的有符号输入横坐标。
  input wire logic signed [33:0] i_input_origin_y, // 当前输出窗口起点的有符号输入纵坐标。
  output logic o_param_bad, // 运行地址或参数检查发现错误。
  output logic o_dw_in_bounds, // 当前深度卷积采样坐标处于输入图像范围。
  output logic [15:0] o_output_last_column, // 输出图像的最后一个列坐标。
  input wire logic [32:0] i_checked_range_end [4], // 配置检查完成的四个读取区间右端地址。
  output logic o_global_pool, // 当前池化窗口覆盖整个输入图像。
  input wire logic [63:0] i_position_count, // 配置检查得到的输出空间位置总数。
  input wire logic i_config_check_done, // 当前向量配置检查完成。
  input wire logic i_dw_issue_fire, // 本周期接受一组深度卷积乘加输入。
  input wire logic i_dw_group_last, // 当前深度卷积输入为本次通道分块的末组。
  input wire logic i_dw_tap_advance, // 深度卷积计算推进到下一卷积核位置。
  input wire logic i_dw_snapshot_fire, // 保存一个输出位置的完整深度卷积累加结果。
  input wire logic [1:0] i_dw_shared_inflight, // 共享量化器中仍在处理的深度卷积请求数量。
  input wire logic i_writeback_busy, // 结果写回仍有待处理数据或事务。
  output logic o_avg_power_two, // 当前平均池化的除数为二的整数次幂。
  output logic [5:0] o_avg_shift, // 二的整数次幂平均池化所需的右移位数。
  input wire logic i_input_range_mode, // DMA 当前配置采用输入张量读取区间。
  input wire logic [1:0] i_read_bank, // 当前计算读取的输入缓存槽号。
  input wire logic [1:0] i_wf_bank, // 窗口预取分配的输入缓存槽号。
  output logic [1:0] o_input_bank_mask, // 输入缓存槽号循环推进时使用的低位掩码。
  output logic [3:0] o_input_ready, // 四个输入缓存槽的数据就绪标志。
  output logic [3:0] o_input_reserved, // 四个输入缓存槽的请求预留标志。
  output logic o_input_drain_ready, // 输入读取、共享存储及结果写回均已排空。
  output logic [p_input_index_w-1:0] o_input_read_base, // 当前计算读取槽的输入存储起始元素索引。
  output logic [p_input_index_w-1:0] o_input_response_base, // 当前返回槽的输入存储起始元素索引。
  input wire logic [31:0] i_window_received, // 当前窗口已接收的有效元素数。
  output logic [31:0] o_window_count_o_sum, // 计入本拍有效通道后的窗口接收元素总数。
  output logic o_window_response_fire, // 本周期接收卷积窗口返回数据。
  output logic o_window_request_fire, // 本周期提交卷积窗口请求。
  output logic o_window_fetch_advance, // 预取窗口已提交或越过无效坐标，可以推进扫描。
  output logic o_window_response_fault, // 窗口返回的错误标志或元素数量检查失败。
  input wire logic i_window_write_pending, // 已接收窗口数据尚待写入输入存储。
  input wire logic [31:0] i_fetch_position, // 窗口预取当前的线性输出位置。
  input wire logic [15:0] i_fetch_ox, // 窗口预取当前的输出横坐标。
  input wire logic signed [33:0] i_fetch_x, // 窗口预取当前的有符号输入横坐标。
  input wire logic signed [33:0] i_fetch_y, // 窗口预取当前的有符号输入纵坐标。
  input wire logic signed [33:0] i_fetch_origin_x, // 预取输出窗口起点的有符号输入横坐标。
  input wire logic signed [33:0] i_fetch_origin_y, // 预取输出窗口起点的有符号输入纵坐标。
  output logic [33:0] o_coordinate_step_o_value [8], // 八个并行坐标步进候选的计算结果。
  output logic o_next_window_valid_q, // 已保存的下一采样窗口坐标有效条件。
  output logic signed [33:0] o_next_window_x, // 下一采样窗口的有符号输入横坐标。
  output logic signed [33:0] o_next_window_y, // 下一采样窗口的有符号输入纵坐标。
  output logic o_kernel_column_end, // 当前卷积核横坐标已到达末列。
  output logic [15:0] o_padding_x_negative, // 横向填充尺寸取负后保留的低十六位。
  output logic [15:0] o_padding_y_negative, // 纵向填充尺寸取负后保留的低十六位。
  input wire logic [7:0] i_soft_lut_index_q, // 已保存的 Softmax 指数表读取索引。
  input wire logic [p_tap_count_w-1:0] i_pool_taps_remaining, // 尚需读取的池化窗口位置数量。
  input wire logic [p_input_index_w:0] i_pool_pixels, // 当前池化输入批次覆盖的像素数量。
  input wire logic [p_input_index_w:0] i_pool_received, // 当前池化输入批次已接收的有效元素数。
  input wire logic [p_input_index_w:0] i_pool_pixel, // 当前正在归约的池化批次内像素索引。
  input wire logic [p_input_index_w:0] i_pool_elements, // 当前池化输入批次需要接收的元素总数。
  output logic [p_input_index_w:0] o_pool_next_elements, // 下一池化输入批次需要接收的元素总数。
  output logic [p_input_index_w:0] o_pool_next_pixels, // 下一池化输入批次覆盖的像素数量。
  input wire logic [p_input_index_w:0] i_pool_row_remaining, // 当前池化读取行尚需返回的字节数。
  output logic [p_bus_shift:0] o_pool_beat_count, // 当前池化返回拍包含的有效元素数。
  output logic o_pool_read_complete_saved, // DMA 完成时保存的池化输入数量完整条件。
  output logic [31:0] o_position_next, // 当前线性输出位置加一后的结果。
  output logic [31:0] o_write_origin_next // 下一写回阶段需要采用的输出字节地址。
);
  logic start;
  vector_engine_pkg::vector_engine_cfg_t cfg;
  logic dma_cfg_ready;
  logic dma_conv_enable;
  logic dma_range_enable;
  conv_im2col_pkg::conv_cfg_t dma_conv_cfg;
  logic [31:0] dma_range_base [4];
  logic [32:0] dma_range_end [4];
  logic win_req_valid;
  logic win_req_ready;
  logic [31:0] win_req_p0;
  logic [31:0] win_req_q0;
  logic [31:0] win_req_cols;
  logic [1:0] win_req_tag;
  logic win_rsp_valid;
  logic win_rsp_ready;
  logic [1:0] win_rsp_tag;
  logic [p_window_lanes-1:0] win_rsp_mask;
  logic win_rsp_last;
  logic win_rsp_error;
  logic win_busy;
  logic rd_req;
  logic rd_start;
  logic rd_granted;
  logic rd_im2col;
  logic [31:0] rd_p0;
  logic [31:0] rd_q0;
  logic [31:0] rd_base_addr;
  logic [31:0] rd_row_stride;
  logic [31:0] rd_rows_to_read;
  logic [31:0] rd_valid_cols;
  logic [7:0] rd_burst_len_m1;
  logic rd_use_16bits;
  logic rd_busy;
  logic rd_done;
  logic rd_valid [p_bus_width/8];
  logic [$clog2(p_dma_size)-1:0] rd_col_base;
  logic [p_bus_width-1:0] rd_raw_data;
  logic rd_raw_valid;
  logic wr_busy;
  logic read_done_q;
  vector_engine_control_pkg::state_t state;
  logic state_failed;
  logic state_compute_commit;
  logic state_dw_execute;
  logic state_output_init;
  logic state_dw_finish;
  logic window_fetch_phase;
  vector_engine_control_pkg::load_t load_kind;
  vector_engine_pkg::vector_engine_cfg_t c;
  logic spatial;
  logic depthwise;
  logic binary_vector;
  logic softmax_s8;
  logic [31:0] channels;
  logic [31:0] position;
  logic [15:0] channel_base;
  logic [p_active_count_w-1:0] active;
  logic [p_tap_count_w-1:0] taps;
  logic [15:0] ox;
  logic [15:0] fetch_ox_next;
  logic [p_tap_count_w-1:0] kx;
  logic [p_tap_count_w-1:0] kernel_last_column;
  logic [p_tap_count_w-1:0] tap;
  logic [p_tap_count_w-1:0] valid_taps;
  logic [31:0] vector_offset;
  logic [31:0] channel_remaining;
  logic signed [16:0] channel_remaining_q;
  logic [15:0] channel_next;
  logic channel_has_more;
  logic [p_active_count_w-1:0] vector_next_active;
  logic vector_has_more;
  logic [p_tile_index_w-1:0] compute_index;
  logic compute_group_last_q;
  logic pool_pixel_has_more_q;
  logic [31:0] fetch_tap_offset;
  logic [31:0] position_offset;
  logic [31:0] pool_byte_offset;
  logic [31:0] fetch_position_next;
  logic [31:0] fetch_tap_offset_next;
  logic [31:0] position_offset_next;
  logic [31:0] pool_byte_offset_next;
  logic [31:0] vector_offset_next;
  logic signed [31:0] add_input_sum;
  logic parameter_row_last_fire;
  logic parameter_row_complete;
  logic parameter_three_rows;
  logic parameter_two_rows;
  logic shared_weight_write_pending;
  logic tap_last_modulo;
  logic signed [31:0] add_scaled_a;
  logic signed [63:0] add_rounded;
  logic signed [33:0] input_y;
  logic signed [33:0] input_x;
  logic signed [33:0] input_origin_x;
  logic signed [33:0] input_origin_y;
  logic param_bad;
  logic dw_in_bounds;
  logic [15:0] output_last_column;
  logic [32:0] checked_range_end [4];
  logic global_pool;
  logic [63:0] position_count;
  logic config_check_done;
  logic dw_issue_fire;
  logic dw_group_last;
  logic dw_tap_advance;
  logic dw_snapshot_fire;
  logic [1:0] dw_shared_inflight;
  logic writeback_busy;
  logic avg_power_two;
  logic [5:0] avg_shift;
  logic input_range_mode;
  logic [1:0] read_bank;
  logic [1:0] wf_bank;
  logic [1:0] input_bank_mask;
  logic [3:0] input_ready;
  logic [3:0] input_reserved;
  (* keep = 1 *) logic input_drain_ready;
  logic [p_input_index_w-1:0] input_read_base;
  logic [p_input_index_w-1:0] input_response_base;
  logic [31:0] window_received;
  logic [31:0] window_count_o_sum;
  logic window_response_fire;
  logic window_request_fire;
  logic window_fetch_advance;
  logic window_response_fault;
  logic window_write_pending;
  logic [31:0] fetch_position;
  logic [15:0] fetch_ox;
  logic signed [33:0] fetch_x;
  logic signed [33:0] fetch_y;
  logic signed [33:0] fetch_origin_x;
  logic signed [33:0] fetch_origin_y;
  logic [33:0] coordinate_step_o_value [8];
  logic next_window_valid_q;
  logic signed [33:0] next_window_x;
  logic signed [33:0] next_window_y;
  logic kernel_column_end;
  logic [15:0] padding_x_negative;
  logic [15:0] padding_y_negative;
  logic [7:0] soft_lut_index_q;
  logic [p_tap_count_w-1:0] pool_taps_remaining;
  logic [p_input_index_w:0] pool_pixels;
  logic [p_input_index_w:0] pool_received;
  logic [p_input_index_w:0] pool_pixel;
  logic [p_input_index_w:0] pool_elements;
  logic [p_input_index_w:0] pool_next_elements;
  logic [p_input_index_w:0] pool_next_pixels;
  logic [p_input_index_w:0] pool_row_remaining;
  logic [p_bus_shift:0] pool_beat_count;
  logic pool_read_complete_saved;
  logic [31:0] position_next;
  logic [31:0] write_origin_next;

  // 端口与内部保存值之间使用显式连续连接。
  assign start = i_start;
  assign cfg = i_cfg;
  assign dma_cfg_ready = i_dma_cfg_ready;
  assign o_dma_conv_enable = dma_conv_enable;
  assign o_dma_range_enable = dma_range_enable;
  assign o_dma_conv_cfg = dma_conv_cfg;
  assign o_dma_range_base = dma_range_base;
  assign o_dma_range_end = dma_range_end;
  assign o_win_req_valid = win_req_valid;
  assign win_req_ready = i_win_req_ready;
  assign o_win_req_p0 = win_req_p0;
  assign o_win_req_q0 = win_req_q0;
  assign o_win_req_cols = win_req_cols;
  assign o_win_req_tag = win_req_tag;
  assign win_rsp_valid = i_win_rsp_valid;
  assign o_win_rsp_ready = win_rsp_ready;
  assign win_rsp_tag = i_win_rsp_tag;
  assign win_rsp_mask = i_win_rsp_mask;
  assign win_rsp_last = i_win_rsp_last;
  assign win_rsp_error = i_win_rsp_error;
  assign win_busy = i_win_busy;
  assign rd_req = i_rd_req;
  assign o_rd_start = rd_start;
  assign rd_granted = i_rd_granted;
  assign o_rd_im2col = rd_im2col;
  assign o_rd_p0 = rd_p0;
  assign o_rd_q0 = rd_q0;
  assign o_rd_base_addr = rd_base_addr;
  assign o_rd_row_stride = rd_row_stride;
  assign o_rd_rows_to_read = rd_rows_to_read;
  assign o_rd_valid_cols = rd_valid_cols;
  assign o_rd_burst_len_m1 = rd_burst_len_m1;
  assign o_rd_use_16bits = rd_use_16bits;
  assign rd_busy = i_rd_busy;
  assign rd_done = i_rd_done;
  assign rd_valid = i_rd_valid;
  assign rd_col_base = i_rd_col_base;
  assign rd_raw_data = i_rd_raw_data;
  assign rd_raw_valid = i_rd_raw_valid;
  assign wr_busy = i_wr_busy;
  assign read_done_q = i_read_done_q;
  assign state = i_state;
  assign state_failed = i_state_failed;
  assign state_compute_commit = i_state_compute_commit;
  assign state_dw_execute = i_state_dw_execute;
  assign state_output_init = i_state_output_init;
  assign state_dw_finish = i_state_dw_finish;
  assign window_fetch_phase = i_window_fetch_phase;
  assign load_kind = i_load_kind;
  assign c = i_c;
  assign spatial = i_spatial;
  assign depthwise = i_depthwise;
  assign binary_vector = i_binary_vector;
  assign softmax_s8 = i_softmax_s8;
  assign o_channels = channels;
  assign position = i_position;
  assign channel_base = i_channel_base;
  assign active = i_active;
  assign taps = i_taps;
  assign ox = i_ox;
  assign o_fetch_ox_next = fetch_ox_next;
  assign kx = i_kx;
  assign kernel_last_column = i_kernel_last_column;
  assign tap = i_tap;
  assign valid_taps = i_valid_taps;
  assign vector_offset = i_vector_offset;
  assign o_channel_remaining = channel_remaining;
  assign o_channel_next = channel_next;
  assign o_channel_has_more = channel_has_more;
  assign o_vector_next_active = vector_next_active;
  assign o_vector_has_more = vector_has_more;
  assign compute_index = i_compute_index;
  assign o_compute_group_last_q = compute_group_last_q;
  assign o_pool_pixel_has_more_q = pool_pixel_has_more_q;
  assign fetch_tap_offset = i_fetch_tap_offset;
  assign position_offset = i_position_offset;
  assign pool_byte_offset = i_pool_byte_offset;
  assign o_fetch_position_next = fetch_position_next;
  assign o_fetch_tap_offset_next = fetch_tap_offset_next;
  assign o_position_offset_next = position_offset_next;
  assign o_pool_byte_offset_next = pool_byte_offset_next;
  assign o_vector_offset_next = vector_offset_next;
  assign o_add_input_sum = add_input_sum;
  assign o_parameter_row_last_fire = parameter_row_last_fire;
  assign o_parameter_three_rows = parameter_three_rows;
  assign o_parameter_two_rows = parameter_two_rows;
  assign shared_weight_write_pending = i_shared_weight_write_pending;
  assign tap_last_modulo = i_tap_last_modulo;
  assign add_scaled_a = i_add_scaled_a;
  assign add_rounded = i_add_rounded;
  assign input_y = i_input_y;
  assign input_x = i_input_x;
  assign input_origin_x = i_input_origin_x;
  assign input_origin_y = i_input_origin_y;
  assign o_param_bad = param_bad;
  assign o_dw_in_bounds = dw_in_bounds;
  assign o_output_last_column = output_last_column;
  assign checked_range_end = i_checked_range_end;
  assign o_global_pool = global_pool;
  assign position_count = i_position_count;
  assign config_check_done = i_config_check_done;
  assign dw_issue_fire = i_dw_issue_fire;
  assign dw_group_last = i_dw_group_last;
  assign dw_tap_advance = i_dw_tap_advance;
  assign dw_snapshot_fire = i_dw_snapshot_fire;
  assign dw_shared_inflight = i_dw_shared_inflight;
  assign writeback_busy = i_writeback_busy;
  assign o_avg_power_two = avg_power_two;
  assign o_avg_shift = avg_shift;
  assign input_range_mode = i_input_range_mode;
  assign read_bank = i_read_bank;
  assign wf_bank = i_wf_bank;
  assign o_input_bank_mask = input_bank_mask;
  assign o_input_ready = input_ready;
  assign o_input_reserved = input_reserved;
  assign o_input_drain_ready = input_drain_ready;
  assign o_input_read_base = input_read_base;
  assign o_input_response_base = input_response_base;
  assign window_received = i_window_received;
  assign o_window_count_o_sum = window_count_o_sum;
  assign o_window_response_fire = window_response_fire;
  assign o_window_request_fire = window_request_fire;
  assign o_window_fetch_advance = window_fetch_advance;
  assign o_window_response_fault = window_response_fault;
  assign window_write_pending = i_window_write_pending;
  assign fetch_position = i_fetch_position;
  assign fetch_ox = i_fetch_ox;
  assign fetch_x = i_fetch_x;
  assign fetch_y = i_fetch_y;
  assign fetch_origin_x = i_fetch_origin_x;
  assign fetch_origin_y = i_fetch_origin_y;
  assign o_coordinate_step_o_value = coordinate_step_o_value;
  assign o_next_window_valid_q = next_window_valid_q;
  assign o_next_window_x = next_window_x;
  assign o_next_window_y = next_window_y;
  assign o_kernel_column_end = kernel_column_end;
  assign o_padding_x_negative = padding_x_negative;
  assign o_padding_y_negative = padding_y_negative;
  assign soft_lut_index_q = i_soft_lut_index_q;
  assign pool_taps_remaining = i_pool_taps_remaining;
  assign pool_pixels = i_pool_pixels;
  assign pool_received = i_pool_received;
  assign pool_pixel = i_pool_pixel;
  assign pool_elements = i_pool_elements;
  assign o_pool_next_elements = pool_next_elements;
  assign o_pool_next_pixels = pool_next_pixels;
  assign pool_row_remaining = i_pool_row_remaining;
  assign o_pool_beat_count = pool_beat_count;
  assign o_pool_read_complete_saved = pool_read_complete_saved;
  assign o_position_next = position_next;
  assign o_write_origin_next = write_origin_next;


  logic [16:0] channel_next_value;
  logic [p_active_count_w:0] vector_low_sum;
  logic vector_high_equal;
  logic vector_high_less;
  logic vector_high_next_equal;
  logic vector_high_next_less;
  logic [p_active_count_w:0] vector_remaining_low;
  logic [p_active_count_w-1:0] vector_next_active_comb;
  logic [31-p_active_count_w:0] vector_high_increment;
  logic [31-p_active_count_w:0] vector_remaining_carry_needed;
  logic [31-p_active_count_w:0] vector_remaining_carry_generated;
  logic [31-p_active_count_w:0] vector_remaining_carry_expected;
  logic vector_remaining_high_zero;
  logic unused_vector_remaining_carry;
  logic vector_has_more_comb;
  logic [31:0] window_request_offset;
  logic [31:0] parameter_row_stride;
  logic input_row_in_bounds;
  logic origin_column_in_bounds;
  logic origin_row_in_bounds;
  logic next_origin_column_valid;
  logic next_origin_row_valid;
  logic signed [16:0] dilation_x_min;
  logic signed [16:0] dilation_x_max;
  logic signed [16:0] dilation_y_min;
  logic signed [16:0] dilation_y_max;
  logic signed [16:0] stride_x_min;
  logic signed [16:0] stride_x_max;
  logic signed [16:0] stride_y_min;
  logic signed [16:0] stride_y_max;
  logic [31:0] load_bytes;
  logic avg_power_two_next;
  logic [5:0] avg_shift_next;
  logic cache_power_two;
  logic [5:0] cache_channel_shift;
  logic cache_power_two_next;
  logic [5:0] cache_channel_shift_next;
  logic input_slot_release;
  logic input_ready_clear_all;
  logic input_ready_release;
  (* keep = 1 *) logic input_drain_local_idle;
  logic window_slot_available;
  logic window_request_idle;
  logic window_request_release_enabled;
  logic window_position_valid;
  logic unused_window_position_equal;
  logic input_reservations_clear;
  logic [$clog2(p_window_lanes+1)-1:0] window_response_count;
  logic [31:0] window_count_i_value;
  logic [31:0] window_count_i_increment;
  logic [31:0] window_count_i_target;
  logic window_count_i_carry;
  logic window_count_o_equal;
  logic unused_window_count_carry;
  logic [p_window_count_width-1:0] window_count_tree [2*p_window_count_leaves];
  logic window_fetch_enabled;
  logic window_fetch_in_bounds;
  logic window_response_last_q;
  logic window_response_error_q;
  logic window_response_count_ok_q;
  logic [1:0] window_response_tag;
  logic input_response_pending;
  logic [33:0] coordinate_step_i_value [8];
  logic [33:0] coordinate_step_i_delta [8];
  logic next_window_valid;
  logic signed [33:0] next_column_x;
  logic signed [33:0] next_row_y;
  logic input_x_fits_interval;
  logic input_y_fits_interval;
  logic origin_x_fits_interval;
  logic origin_y_fits_interval;
  logic next_column_valid;
  logic next_row_valid;
  logic [3:0] coordinate_interval_valid;
  logic signed [16:0] interval_coordinate [4];
  logic signed [16:0] interval_minimum [4];
  logic signed [16:0] interval_maximum [4];
  logic [15:0] dilation_x_negative;
  logic signed [16:0] dilation_x_maximum;
  logic [15:0] dilation_y_negative;
  logic signed [16:0] dilation_y_maximum;
  logic [15:0] stride_x_negative;
  logic signed [16:0] stride_x_maximum;
  logic [15:0] stride_y_negative;
  logic signed [16:0] stride_y_maximum;
  logic [15:0] output_last_column_next;
  logic [p_input_index_w:0] pool_capacity;
  logic [p_input_index_w:0] pool_count_i_a;
  logic [p_input_index_w:0] pool_count_i_b;
  logic [p_input_index_w:0] pool_count_i_target;
  logic pool_count_i_carry;
  (* keep = 1 *) logic pool_count_o_equal;
  (* keep = 1 *) logic pool_received_equal;
  logic pool_receive_complete;
  logic unused_position_carry;
  logic [31:0] read_address_base;
  logic [31:0] read_address_offset;
  logic [15:0] read_address_channel;
  logic [31:0] read_select_i_load_base;
  logic [31:0] read_select_i_load_offset;
  logic read_select_i_lut_read;
  logic read_select_i_pool_read;
  logic [1:0] unused_read_address_carry;
  logic [31:0] parameter_stride_i_b;
  logic parameter_stride_carry;
  (* keep = 1 *) logic parameter_stride_equal;
  logic parameter_bases_equal;
  logic [31:0] parameter_row_stride_next;
  logic parameter_two_rows_next;
  logic parameter_three_rows_next;
  logic parameter_bias_before_multiplier;
  logic unused_parameter_bias_equal;
  logic [31:0] write_address_offset;
  logic [31:0] write_main_offset;
  logic [15:0] write_channel_offset;
  logic [1:0] unused_write_origin_carry;
  logic [31:0] write_origin_fast;
  logic [31:0] write_origin_four_state;
  logic unused_write_origin_four_state_carry;

  assign fetch_ox_next = fetch_ox + 16'd1;
  // 宽计数和地址偏移并行计算，状态只选择各自已完成的下一值。
  assign fetch_position_next = fetch_position + 32'd1;
  assign fetch_tap_offset_next = fetch_tap_offset + channels;
  assign position_offset_next = position_offset + channels;
  assign pool_byte_offset_next = pool_byte_offset + 32'(channels);
  assign vector_offset_next = vector_offset + 32'(active);
  assign window_request_offset = fetch_tap_offset + {16'd0, channel_base};
  assign add_input_sum = add_scaled_a + 32'(add_rounded);

  // 输入扫描和预取扫描各自并行准备坐标；状态只选择已完成的计算结果。
  assign coordinate_step_i_value[0] = $unsigned(input_x);
  assign coordinate_step_i_value[1] = $unsigned(input_y);
  assign coordinate_step_i_value[2] = $unsigned(input_origin_x);
  assign coordinate_step_i_value[3] = $unsigned(input_origin_y);
  assign coordinate_step_i_value[4] = $unsigned(fetch_x);
  assign coordinate_step_i_value[5] = $unsigned(fetch_y);
  assign coordinate_step_i_value[6] = $unsigned(fetch_origin_x);
  assign coordinate_step_i_value[7] = $unsigned(fetch_origin_y);
  for (genvar coordinate_group = 0; coordinate_group < 2; coordinate_group++) begin : g_coordinate_delta
    assign coordinate_step_i_delta[4*coordinate_group] = {18'd0, c.image.dilation_w};
    assign coordinate_step_i_delta[4*coordinate_group+1] = {18'd0, c.image.dilation_h};
    assign coordinate_step_i_delta[4*coordinate_group+2] = {18'd0, c.image.stride_w};
    assign coordinate_step_i_delta[4*coordinate_group+3] = {18'd0, c.image.stride_h};
  end
  for (genvar coordinate = 0; coordinate < 8; coordinate++) begin : g_coordinate_step
    logic signed [18:0] coordinate_extended, increment_extended;
    (* use_dsp = "simd" *) logic signed [18:0] coordinate_sum;
    logic signed [17:0] coordinate_next;
    // 步长非负，越界坐标只会继续增大；行切换时重新装载对应起点。
    // 完整十九位和保留符号与进位，多路相同宽度算术共同推断 SIMD 加法。
    assign coordinate_extended = $signed({coordinate_step_i_value[coordinate][17],
                                          coordinate_step_i_value[coordinate][17:0]});
    assign increment_extended = $signed({3'b000, coordinate_step_i_delta[coordinate][15:0]});
    assign coordinate_sum = coordinate_extended + increment_extended;
    assign coordinate_next = !coordinate_sum[18] && (|coordinate_sum[17:16]) ?
        18'sd65536 : coordinate_sum[17:0];
    assign coordinate_step_o_value[coordinate] = {{16{coordinate_next[17]}}, coordinate_next};
  end
  // 完成条件逐位检查所需进位，保留接收计数的三十二位回绕行为。
  assign window_count_i_value = window_received;
  assign window_count_i_increment = 32'(window_response_count);
  assign window_count_i_target = 32'(active);
  assign window_count_i_carry = 1'b0;
  add_equal #(.p_width(32)) u_window_count_equal (
      .i_a(window_count_i_value), .i_b(window_count_i_increment),
      .i_target(window_count_i_target), .i_carry_in(window_count_i_carry),
      .o_equal(window_count_o_equal)
  );
  // 本拍元素数只进入低段加法，高段预先准备全部传播条件。
  vector_window_count_add #(.p_width(32), .p_increment_width($clog2(p_window_lanes+1))) u_window_count_sum (
      .i_value(window_count_i_value), .i_increment(window_response_count), .o_sum(window_count_o_sum)
  );
  assign unused_window_count_carry = 1'b0;
  // 每组三位并行检查核列编号，组间归并供坐标与范围选择共同使用。
  localparam int p_column_equal_groups = (p_tap_count_w + 2) / 3;
  (* keep = 1 *) logic [p_column_equal_groups-1:0] kernel_column_equal;
  for (genvar group = 0; group < p_column_equal_groups; group++) begin : g_kernel_column_equal
    localparam int p_group_width = p_tap_count_w-3*group < 3 ? p_tap_count_w-3*group : 3;
    assign kernel_column_equal[group] =
        kx[3*group+:p_group_width] == kernel_last_column[3*group+:p_group_width];
  end
  assign kernel_column_end = &kernel_column_equal;
  assign next_column_x = $signed(coordinate_step_o_value[0]);
  assign next_row_y = $signed(coordinate_step_o_value[1]);

  // 配置阶段保存坐标增量对应的有效区间。运行时并行比较当前坐标与两个端点，
  // 十七位符号扩展检查覆盖完整三十四位坐标，范围判断不再依赖坐标加法的进位。
  assign input_x_fits_interval = input_x[33:17] == {17{input_x[16]}};
  assign input_y_fits_interval = input_y[33:17] == {17{input_y[16]}};
  assign origin_x_fits_interval = input_origin_x[33:17] == {17{input_origin_x[16]}};
  assign origin_y_fits_interval = input_origin_y[33:17] == {17{input_origin_y[16]}};
  assign interval_coordinate[0]=input_x[16:0];
  assign interval_coordinate[1]=input_y[16:0];
  assign interval_coordinate[2]=input_origin_x[16:0];
  assign interval_coordinate[3]=input_origin_y[16:0];
  assign interval_minimum[0]=dilation_x_min;
  assign interval_minimum[1]=dilation_y_min;
  assign interval_minimum[2]=stride_x_min;
  assign interval_minimum[3]=stride_y_min;
  assign interval_maximum[0]=dilation_x_max;
  assign interval_maximum[1]=dilation_y_max;
  assign interval_maximum[2]=stride_x_max;
  assign interval_maximum[3]=stride_y_max;
  for (genvar interval=0;interval<4;interval++) begin : g_coordinate_interval
    vector_interval_bound u_bound (
        .i_coordinate(interval_coordinate[interval]),
        .i_minimum(interval_minimum[interval]), .i_maximum(interval_maximum[interval]),
        .o_inside(coordinate_interval_valid[interval])
    );
  end
  assign next_column_valid = input_x_fits_interval && coordinate_interval_valid[0] && input_row_in_bounds;
  assign next_row_valid = origin_column_in_bounds && input_y_fits_interval && coordinate_interval_valid[1];
  assign next_origin_column_valid = origin_x_fits_interval && coordinate_interval_valid[2] && origin_row_in_bounds;
  assign next_origin_row_valid = (c.image.pad_left == 16'd0) && (c.image.input_w != 16'd0) &&
      origin_y_fits_interval && coordinate_interval_valid[3];

  // 配置增量的完整差值先由普通算术表达，寄存边沿分别保存各有效区间。
  assign dilation_x_negative = 16'd0 - c.image.dilation_w;
  assign dilation_x_maximum = $signed({1'b0, c.image.input_w}) - $signed({1'b0, c.image.dilation_w});
  assign dilation_y_negative = 16'd0 - c.image.dilation_h;
  assign dilation_y_maximum = $signed({1'b0, c.image.input_h}) - $signed({1'b0, c.image.dilation_h});
  assign stride_x_negative = 16'd0 - c.image.stride_w;
  assign stride_x_maximum = $signed({1'b0, c.image.input_w}) - $signed({1'b0, c.image.stride_w});
  assign stride_y_negative = 16'd0 - c.image.stride_h;
  assign stride_y_maximum = $signed({1'b0, c.image.input_h}) - $signed({1'b0, c.image.stride_h});
  assign output_last_column_next = c.image.output_w - 16'd1;
  assign padding_x_negative = 16'd0 - c.image.pad_left;
  assign padding_y_negative = 16'd0 - c.image.pad_top;

  always_ff @(posedge clk) begin
    if (state == vector_engine_control_pkg::CHECK_WAIT && config_check_done) begin
      dilation_x_min <= $signed({(|c.image.dilation_w), dilation_x_negative});
      dilation_x_max <= dilation_x_maximum;
      dilation_y_min <= $signed({(|c.image.dilation_h), dilation_y_negative});
      dilation_y_max <= dilation_y_maximum;
      stride_x_min <= $signed({(|c.image.stride_w), stride_x_negative});
      stride_x_max <= stride_x_maximum;
      stride_y_min <= $signed({(|c.image.stride_h), stride_y_negative});
      stride_y_max <= stride_y_maximum;
      output_last_column <= output_last_column_next;
    end
  end
  // 单拍数量由已保存的行长度决定，完成条件在响应到达前并行计算。
  assign pool_beat_count = pool_row_remaining>p_bus_bytes ? (p_bus_shift+1)'(p_bus_bytes) :
      (p_bus_shift+1)'(pool_row_remaining);
  assign pool_count_i_a = pool_received;
  assign pool_count_i_b = (p_input_index_w+1)'(pool_beat_count);
  assign pool_count_i_target = pool_elements;
  assign pool_count_i_carry = 1'b0;
  assign pool_received_equal = pool_received == pool_elements;
  assign pool_receive_complete = rd_valid[0] ? pool_count_o_equal : pool_received_equal;
  always_ff @(posedge clk) begin
    if (rd_done) pool_read_complete_saved <= pool_receive_complete;
  end
  add_equal #(.p_width(p_input_index_w+1)) u_pool_count_equal (
      .i_a(pool_count_i_a), .i_b(pool_count_i_b), .i_target(pool_count_i_target),
      .i_carry_in(pool_count_i_carry), .o_equal(pool_count_o_equal)
  );

  // 像素位置的递增结果供完成判断和状态更新共同使用。
  parallel_prefix_add #(.p_width(32), .p_preserve_groups(1'b1)) u_position_next (
      .i_a(position), .i_b(32'd0), .i_carry(1'b1),
      .o_sum(position_next), .o_carry(unused_position_carry)
  );

  // 有效通道数只影响低位；高位比较与低位加法并行执行，保留三十二位回绕。
  assign vector_low_sum = {1'b0, vector_offset[p_active_count_w-1:0]} + {1'b0, active};
  unsigned_compare #(.p_width(32-p_active_count_w)) u_vector_length_compare (
      .i_a(vector_offset[31:p_active_count_w]), .i_b(c.length[31:p_active_count_w]),
      .o_less(vector_high_less), .o_equal(vector_high_equal)
  );
  assign vector_high_next_equal =
      ((vector_offset[31:p_active_count_w] ^ c.length[31:p_active_count_w]) ==
       {(vector_offset[30:p_active_count_w] & ~c.length[30:p_active_count_w]), 1'b1});
  assign vector_high_next_less = (vector_high_less && !vector_high_next_equal) ||
      ((&vector_offset[31:p_active_count_w]) && (|c.length[31:p_active_count_w]));
  assign vector_has_more_comb = vector_low_sum[p_active_count_w] ?
      (vector_high_next_less || (vector_high_next_equal &&
          (vector_low_sum[p_active_count_w-1:0] < c.length[p_active_count_w-1:0]))) :
      (vector_high_less || (vector_high_equal &&
          (vector_low_sum[p_active_count_w-1:0] < c.length[p_active_count_w-1:0])));
  // 剩余长度复用低位偏移加法；低位借位与加法进位共同决定高位的递增量。
  // 逐位检查高位差值是否为零，只保留下一批需要的有效通道数。
  assign vector_remaining_low = {1'b0, c.length[p_active_count_w-1:0]} -
      {1'b0, vector_low_sum[p_active_count_w-1:0]};
  assign vector_high_increment = (32-p_active_count_w)'({
      vector_low_sum[p_active_count_w] && vector_remaining_low[p_active_count_w],
      vector_low_sum[p_active_count_w] ^ vector_remaining_low[p_active_count_w]});
  assign vector_remaining_carry_needed = vector_offset[31:p_active_count_w] ^
      vector_high_increment ^ c.length[31:p_active_count_w];
  assign vector_remaining_carry_generated =
      (vector_offset[31:p_active_count_w] & vector_high_increment) |
      ((vector_offset[31:p_active_count_w] | vector_high_increment) & ~c.length[31:p_active_count_w]);
  assign {unused_vector_remaining_carry, vector_remaining_carry_expected} =
      {vector_remaining_carry_generated, 1'b0};
  assign vector_remaining_high_zero = vector_remaining_carry_needed == vector_remaining_carry_expected;
  assign vector_next_active_comb = vector_remaining_high_zero &&
      vector_remaining_low[p_active_count_w-1:0] < p_active_count_w'(p_tile) ?
      vector_remaining_low[p_active_count_w-1:0] : p_active_count_w'(p_tile);
  // 一个分块的偏移和有效通道数在计算期间保持稳定，转移周期使用准备好的条件。
  always_ff @(posedge clk) begin
    vector_has_more <= vector_has_more_comb;
    vector_next_active <= vector_next_active_comb;
  end
  assign channels = {16'd0,c.image.input_c};
  // CONFIGURE 或 DRAIN_TILE 保存完整差值，TILE_INIT 再形成通道数与掩码。
  always_ff @(posedge clk) begin
    channel_remaining_q <= $signed({1'b0, c.image.input_c}) - $signed({1'b0, channel_base});
  end
  assign channel_remaining = 32'(channel_remaining_q);
  assign channel_next_value = {1'b0,channel_base} + 17'(active);
  always_ff @(posedge clk) begin
    channel_next <= channel_next_value[15:0];
    channel_has_more <= channel_next_value < 17'(channels);
  end
  vector_coordinate_bound u_input_row_bound (
      .i_coordinate(input_y), .i_limit(c.image.input_h), .o_in_bounds(input_row_in_bounds)
  );
  vector_coordinate_bound u_origin_column_bound (
      .i_coordinate(input_origin_x), .i_limit(c.image.input_w), .o_in_bounds(origin_column_in_bounds)
  );
  vector_coordinate_bound u_origin_row_bound (
      .i_coordinate(input_origin_y), .i_limit(c.image.input_h), .o_in_bounds(origin_row_in_bounds)
  );
  // DW 发射读取与坐标同时保存的有效位；权重地址选择只经过寄存后的范围结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      dw_in_bounds <= 1'b0;
    end else if (state_output_init) begin
      dw_in_bounds <= origin_column_in_bounds && origin_row_in_bounds;
    end else if (state_dw_execute && dw_tap_advance && !tap_last_modulo) begin
      dw_in_bounds <= kernel_column_end ? next_row_valid : next_column_valid;
    end else if (state_dw_finish && dw_snapshot_fire) begin
      dw_in_bounds <= (ox == output_last_column) ? next_origin_row_valid : next_origin_column_valid;
    end else if (state == vector_engine_control_pkg::TAP_NEXT) begin
      dw_in_bounds <= next_window_valid;
    end else if (state_compute_commit && compute_group_last_q && spatial && !global_pool) begin
      dw_in_bounds <= next_window_valid_q;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) global_pool <= 1'b0;
    else if (state==vector_engine_control_pkg::IDLE && start)
      global_pool <= cfg.op <= vector_engine_pkg::MINPOOL_S8 && cfg.op != vector_engine_pkg::DW_S8 &&
                     cfg.image.output_h==1 && cfg.image.output_w==1 &&
                     cfg.image.kernel_h==cfg.image.input_h && cfg.image.kernel_w==cfg.image.input_w &&
                     cfg.image.pad_top==0 && cfg.image.pad_left==0 &&
                     cfg.image.dilation_h==1 && cfg.image.dilation_w==1;
  end
  // 十六路计算配置保存四个完整通道组；较窄配置保存两个完整组或四个半组。
  // 槽位预留允许 DMA 提前发出请求，并按顺序接收响应。
  assign window_fetch_enabled=spatial && !global_pool && window_fetch_phase;
  vector_window_bounds u_window_bounds (
      .i_x(fetch_x), .i_y(fetch_y), .i_width(c.image.input_w), .i_height(c.image.input_h),
      .o_in_bounds(window_fetch_in_bounds)
  );
  assign input_bank_mask=p_pe_count>=16 || active<=p_active_count_w'(p_tile/2) ? 2'b11 : 2'b01;
  assign input_read_base=active<=p_active_count_w'(p_tile/2) ?
      (p_input_index_w'(read_bank)<<($clog2(p_tile)-1)) : (p_input_index_w'(read_bank)<<$clog2(p_tile));
  assign input_response_base=active<=p_active_count_w'(p_tile/2) ?
      (p_input_index_w'(win_rsp_tag)<<($clog2(p_tile)-1)) : (p_input_index_w'(win_rsp_tag)<<$clog2(p_tile));
  // 完整三十二位位置先独立比较，范围资格与返回释放条件分别准备。
  parallel_unsigned_compare #(.p_width(32)) u_window_position (
      .i_a(fetch_position), .i_b(32'(position_count)),
      .o_less(window_position_valid), .o_equal(unused_window_position_equal)
  );
  assign window_slot_available = window_fetch_enabled &&
      window_position_valid && window_fetch_in_bounds;
  // 就绪标志保存当前窗口，预留标志保存下一窗口，两者分别记录数据和请求。
  // 少于十六路 PE 的深度卷积可提前预约，其余配置在当前槽位消费完成时预约。
  assign input_slot_release = dw_issue_fire && dw_group_last && (wf_bank == read_bank);
  // 槽位范围、预留和故障资格先并行完成，权重返回触发的发射只参与末级选择。
  assign window_request_idle = window_slot_available && !window_response_fault &&
      !input_reserved[wf_bank] && ((p_pe_count < 16 && depthwise) || !input_ready[wf_bank]);
  assign window_request_release_enabled = window_slot_available && !window_response_fault &&
      !input_reserved[wf_bank] && dw_group_last && (wf_bank == read_bank);
  vector_window_request_qualify u_window_request_qualify (
      .i_idle(window_request_idle), .i_release_enabled(window_request_release_enabled),
      .i_release(dw_issue_fire), .o_valid(win_req_valid)
  );
  assign win_req_p0=fetch_position;
  assign win_req_q0=window_request_offset;
  assign win_req_cols=active;
  assign win_req_tag=wf_bank;
  // 末组操作数捕获后，就绪标志在边沿清空，随后才接收对应槽位的后续数据。
  // 错误响应和失败状态持续接收待完成请求，使任务能够排空窗口队列。
  assign win_rsp_ready = !depthwise || !input_ready[win_rsp_tag] ||
      state_failed || win_rsp_error;
  assign window_request_fire=win_req_valid && win_req_ready;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      window_response_last_q <= 1'b0;
      window_response_error_q <= 1'b0;
      window_response_count_ok_q <= 1'b0;
    end else begin
      window_response_last_q <= window_response_fire && win_rsp_last;
      if (window_response_fire) begin
        window_response_error_q <= win_rsp_error;
        window_response_count_ok_q <= window_count_o_equal;
      end
    end
  end
  // 响应标签由有效位保护，复位期间保持数据，接收边沿保存同拍标签。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else if (window_response_fire) window_response_tag <= win_rsp_tag;
  end
  assign window_response_fault = window_response_last_q &&
      (window_response_error_q || !window_response_count_ok_q);
  assign window_response_fire=win_rsp_valid && win_rsp_ready;
  assign window_fetch_advance=window_request_fire ||
    (window_fetch_enabled && window_position_valid && !window_fetch_in_bounds);
  assign input_reservations_clear = (state == vector_engine_control_pkg::CHECK) || (state == vector_engine_control_pkg::TILE_INIT) ||
      (state_failed && input_drain_ready);
  assign input_response_pending = p_input_bank_storage &&
      (window_response_last_q || window_write_pending);
  // 本地活动并行归并，共享存储返回的有效资格只参与最后一级排空判断。
  assign input_drain_local_idle = !rd_busy && !read_done_q && !wr_busy && !win_busy &&
      !input_response_pending && !writeback_busy && !shared_weight_write_pending &&
      dw_shared_inflight == 0 && dma_cfg_ready;
  assign input_drain_ready = input_drain_local_idle &&
      (!p_shared_storage_enable || (!i_weight_read_valid && !i_ps_read_valid));
  assign input_ready_clear_all = (state == vector_engine_control_pkg::CHECK) || (state == vector_engine_control_pkg::TILE_INIT) ||
      (state_failed && input_drain_ready);
  assign input_ready_release = (dw_issue_fire && dw_group_last) ||
      (state_compute_commit && compute_group_last_q && !global_pool && spatial);

  // 各槽分别保存就绪状态，完成返回与计算释放并行译码，清空条件具有最高优先级。
  for (genvar bank = 0; bank < 4; bank++) begin : g_input_ready
    logic response_selected, clear_selected;
    assign response_selected = p_input_bank_storage ?
        window_response_last_q && window_response_tag == 2'(bank) :
        window_response_fire && win_rsp_last && win_rsp_tag == 2'(bank);
    assign clear_selected = input_ready_clear_all || (input_ready_release && read_bank == 2'(bank));
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) input_ready[bank] <= 1'b0;
      else input_ready[bank] <= !clear_selected &&
          (response_selected ? !(p_input_bank_storage ? window_response_error_q : win_rsp_error) : input_ready[bank]);
    end
  end

  // 每个槽位并行生成接收和释放条件，就绪信号只参与最后的数据选择。
  // 同周期返回完成优先释放对应槽位，初始化和错误恢复同时清空全部槽位。
  for (genvar bank = 0; bank < 4; bank++) begin : g_input_reservation
    (* keep = 1 *) logic request_selected, release_selected;
    assign request_selected = window_slot_available && (wf_bank == 2'(bank)) &&
        ((p_pe_count < 16 && depthwise) || !input_ready[bank] || input_slot_release);
    assign release_selected = input_reservations_clear ||
        (p_input_bank_storage ? window_response_last_q && window_response_tag == 2'(bank) :
         window_response_fire && win_rsp_last && win_rsp_tag == 2'(bank));
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) input_reserved[bank] <= 1'b0;
      else input_reserved[bank] <= !release_selected &&
          (input_reserved[bank] || (win_req_ready && request_selected));
    end
  end
  // 相邻通道成对求和，逐层统计有效元素数量。
  assign window_count_tree[0] = '0;
  for (genvar lane = 0; lane < p_window_count_leaves; lane++) begin : g_window_count_leaf
    if (lane < p_window_lanes) begin : g_present
      assign window_count_tree[p_window_count_leaves+lane] = p_window_count_width'(win_rsp_mask[lane]);
    end else begin : g_empty
      assign window_count_tree[p_window_count_leaves+lane] = '0;
    end
  end
  for (genvar node = 1; node < p_window_count_leaves; node++) begin : g_window_count_sum
    assign window_count_tree[node] = window_count_tree[2*node] + window_count_tree[2*node+1];
  end
  assign window_response_count = window_count_tree[1];
  always_comb begin
    cache_power_two_next=1'b1;
    case (active)
      32'd1: cache_channel_shift_next=0;
      32'd2: cache_channel_shift_next=1;
      32'd4: cache_channel_shift_next=2;
      32'd8: cache_channel_shift_next=3;
      32'd16: cache_channel_shift_next=4;
      32'd32: cache_channel_shift_next=5;
      32'd64: cache_channel_shift_next=6;
      default: begin cache_channel_shift_next=0;cache_power_two_next=1'b0;end
    endcase
    pool_next_pixels=pool_capacity;
    if (32'(pool_next_pixels)>32'(pool_taps_remaining)) pool_next_pixels=(p_input_index_w+1)'(pool_taps_remaining);
    pool_next_elements=cache_power_two ? pool_next_pixels<<cache_channel_shift : (p_input_index_w+1)'(active);
    next_window_x=kernel_column_end ? input_origin_x : next_column_x;
    next_window_y=kernel_column_end ? next_row_y : input_y;
    // 两组候选坐标先分别检查范围，再选择下一个卷积核位置。
    next_window_valid=spatial && !global_pool && tap+1<taps &&
      (kernel_column_end ? next_row_valid : next_column_valid);
    avg_power_two_next=valid_taps!=0 && (valid_taps&(valid_taps-1))==0;
    avg_shift_next=0;
    for (int bit_index=0;bit_index<p_tap_count_w;bit_index++) if (valid_taps[bit_index]) avg_shift_next=6'(bit_index);
  end

  // 通道数在分块初始化时保存，池化请求准备前完成容量和移位量译码。
  always_ff @(posedge clk) begin
    cache_power_two <= cache_power_two_next;
    cache_channel_shift <= cache_channel_shift_next;
    pool_capacity <= cache_power_two_next && active >= 4 ?
        (p_input_index_w+1)'(2*p_tile) >> cache_channel_shift_next : (p_input_index_w+1)'(1);
    avg_power_two <= avg_power_two_next;
    avg_shift <= avg_shift_next;
  end

  // 执行阶段提前保存下一坐标的范围判断，提交阶段直接选择后续状态。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) next_window_valid_q <= 1'b0;
    else if (state == vector_engine_control_pkg::EXECUTE) next_window_valid_q <= next_window_valid;
  end

  // 执行周期保存通道组末项判断，提交周期直接使用该条件。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      compute_group_last_q <= 1'b0;
      pool_pixel_has_more_q <= 1'b0;
    end else if (state == vector_engine_control_pkg::EXECUTE) begin
      compute_group_last_q <= compute_index + 32'(p_pe_count) >= active;
      pool_pixel_has_more_q <= pool_pixel + 1 < pool_pixels;
    end
  end

  // 四个末地址已在检查阶段按当前配置分配槽位。
  for (genvar range_index = 0; range_index < 4; range_index++) begin : g_dma_range_end
    assign dma_range_end[range_index] = checked_range_end[range_index];
  end
  always_comb begin
    // 配置等待期间持续提供描述符，接收边沿由就绪信号决定。
    dma_conv_enable = spatial;
    dma_range_enable = 1'b1;
    dma_conv_cfg = c.image;
    dma_conv_cfg.input_base = c.input_base;
    dma_conv_cfg.group_c = c.image.input_c;
    dma_conv_cfg.group_offset = 0;
    dma_conv_cfg.input_s16 = 0;
    dma_conv_cfg.windowed = spatial;
    dma_conv_cfg.prefetch_enable = 1;
    for (int i=0;i<4;i++) begin dma_range_base[i]=0; end
    if (global_pool && input_range_mode) begin
      dma_range_base[0]=c.input_base;
    end else if (depthwise) begin
      dma_range_base[0]=c.rhs_base;
      if (c.bias_base!=0) begin
        dma_range_base[1]=c.bias_base;
      end
      dma_range_base[2]=c.multiplier_base;
      dma_range_base[3]=c.shift_base;
    end else if (!spatial) begin
      dma_range_base[0]=c.input_base;
      if (binary_vector || softmax_s8) begin
        dma_range_base[1]=c.rhs_base;
      end
    end
  end

  assign rd_start = rd_req && rd_granted;

  // 等距参数数组由二维 DMA 连续读取，接收端在每行结束后切换参数类型。
  // 两个地址的完整三十二位差值由分段算术和并行进位修正生成。
  assign parameter_stride_i_b = ~c.multiplier_base;
  parallel_prefix_add #(.p_width(32),
        .p_dsp_split_width(16), .p_parallel_high_prefix(1'b1),
        .p_keep_carry(1'b0), .p_preserve_grouped_unknowns(1'b1),
        .p_direct_subtract(1'b1)) u_parameter_stride (
      .i_a(c.shift_base), .i_b(parameter_stride_i_b), .i_carry(1'b1),
      .o_sum(parameter_row_stride_next), .o_carry(parameter_stride_carry)
  );
  add_equal #(.p_width(32)) u_parameter_stride_equal (
      .i_a(c.bias_base), .i_b(c.shift_base), .i_target({c.multiplier_base[30:0], 1'b0}),
      .i_carry_in(1'b0), .o_equal(parameter_stride_equal)
  );
  parallel_equal #(.p_width(32)) u_parameter_bases_equal (
      .i_a(c.shift_base), .i_b(c.multiplier_base), .o_equal(parameter_bases_equal)
  );
  // 地址相等判断与减法借位并行生成，严格递增条件直接合并两个单比特结果。
  always_comb begin
    case (^{c.shift_base, c.multiplier_base})
      1'b0, 1'b1: parameter_two_rows_next = parameter_stride_carry && !parameter_bases_equal;
      default: parameter_two_rows_next = c.shift_base > c.multiplier_base;
    endcase
  end
  parallel_unsigned_compare #(.p_width(32)) u_parameter_bias_order (
      .i_a(c.bias_base), .i_b(c.multiplier_base),
      .o_less(parameter_bias_before_multiplier), .o_equal(unused_parameter_bias_equal)
  );
  assign parameter_three_rows_next = c.bias_base!=0 &&
      parameter_bias_before_multiplier && parameter_two_rows_next &&
      parameter_stride_equal;
  // 配置检查期间保存参数行描述符，随后各通道复用相同的步长与行数判断。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      parameter_row_stride <= '0;
      parameter_two_rows <= 1'b0;
      parameter_three_rows <= 1'b0;
    end else if (state == vector_engine_control_pkg::CHECK) begin
      parameter_row_stride <= parameter_row_stride_next;
      parameter_two_rows <= parameter_two_rows_next;
      parameter_three_rows <= parameter_three_rows_next;
    end
  end
  // 返回列与本行元素数在独立组合模块中形成末拍资格，控制器直接选择该结果。
  vector_parameter_row_end #(
    .p_column_width(p_input_index_w), .p_active_width(p_active_count_w), .p_bus_bytes(p_bus_bytes)
  ) u_parameter_row_end (
    .i_column_base(rd_col_base), .i_active(active), .o_complete(parameter_row_complete)
  );
  assign parameter_row_last_fire = state==vector_engine_control_pkg::LOAD_WAIT && rd_raw_valid &&
      (load_kind==vector_engine_control_pkg::LD_BIAS || load_kind==vector_engine_control_pkg::LD_MULT || load_kind==vector_engine_control_pkg::LD_SHIFT) &&
      parameter_row_complete;

  // 低八位突发编码直接判断减一的借位，避免先向上取整再减一。
  function automatic logic [7:0] burst_length_from_bytes(input logic [31:0] value);
    burst_length_from_bytes = 8'(((value+p_bus_bytes-1)>>p_bus_shift)-1);
    if (p_bus_shift <= 24) begin
      case (^value)
        1'b0, 1'b1: begin
          for (int bit_index = 0; bit_index < 8; bit_index++) begin
            burst_length_from_bytes[bit_index] = value[p_bus_shift+bit_index] ^
                ((value & ((32'd1 << (p_bus_shift+bit_index))-1)) == 32'd0);
          end
        end
        default: begin end
      endcase
    end
  endfunction

  // 普通读取先准备完整地址分量，专用模式在独立末级选择。
  always_comb begin
    read_select_i_load_base = 32'd0;
    read_select_i_load_offset = 32'd0;
    if (p_registered_read_phase) begin
      read_select_i_load_base =
          ({32{i_load_read_select[0] | i_load_read_select[5]}} & c.rhs_base) |
          ({32{i_load_read_select[1]}} & c.bias_base) |
          ({32{i_load_read_select[2]}} & c.multiplier_base) |
          ({32{i_load_read_select[3]}} & c.shift_base) |
          ({32{i_load_read_select[4]}} & c.input_base);
      read_select_i_load_offset =
          ({32{i_load_read_select[0]}} & {16'd0, channel_base}) |
          ({32{|i_load_read_select[3:1]}} & {14'd0, channel_base, 2'b00}) |
          ({32{|i_load_read_select[5:4]}} & (vector_offset << c.vector_s16));
    end else begin
      case (load_kind)
        vector_engine_control_pkg::LD_WEIGHT: begin
          read_select_i_load_base = c.rhs_base;
          read_select_i_load_offset = {16'd0, channel_base};
        end
        vector_engine_control_pkg::LD_BIAS, vector_engine_control_pkg::LD_MULT, vector_engine_control_pkg::LD_SHIFT: begin
          case (load_kind)
            vector_engine_control_pkg::LD_BIAS: read_select_i_load_base = c.bias_base;
            vector_engine_control_pkg::LD_MULT: read_select_i_load_base = c.multiplier_base;
            default: read_select_i_load_base = c.shift_base;
          endcase
          read_select_i_load_offset = {14'd0, channel_base, 2'b00};
        end
        vector_engine_control_pkg::LD_A: begin
          read_select_i_load_base = c.input_base;
          read_select_i_load_offset = vector_offset << c.vector_s16;
        end
        vector_engine_control_pkg::LD_B: begin
          read_select_i_load_base = c.rhs_base;
          read_select_i_load_offset = vector_offset << c.vector_s16;
        end
        default: begin end
      endcase
    end
  end
  assign read_select_i_lut_read = p_registered_read_phase ? i_state_soft_lut_read :
      (state == vector_engine_control_pkg::SOFT_LUT_REQ ||
       state == vector_engine_control_pkg::SOFT_LUT_WAIT);
  assign read_select_i_pool_read = p_registered_read_phase ? i_state_pool_read :
      (state == vector_engine_control_pkg::POOL_LOAD_REQ ||
       state == vector_engine_control_pkg::POOL_LOAD_WAIT);
  vector_read_address_select u_read_select (
    .i_lut_read(read_select_i_lut_read), .i_pool_read(read_select_i_pool_read),
    .i_load_base(read_select_i_load_base), .i_load_offset(read_select_i_load_offset),
    .i_lut_base(c.rhs_base), .i_lut_index(soft_lut_index_q),
    .i_pool_base(c.input_base), .i_pool_offset(pool_byte_offset), .i_pool_channel(channel_base),
    .o_base(read_address_base), .o_offset(read_address_offset), .o_channel(read_address_channel)
  );
  vector_read_address_add u_read_address (
    .clk(clk), .i_base(read_address_base), .i_offset(read_address_offset),
    .i_channel(read_address_channel), .o_address(rd_base_addr),
    .o_carry(unused_read_address_carry)
  );
  always_comb begin
    rd_im2col = 1'b0;
    rd_p0 = 0;
    rd_q0 = 0;
    rd_row_stride = 0;
    rd_rows_to_read = 1;
    rd_valid_cols = 32'(active);
    rd_use_16bits = !spatial && c.vector_s16;
    load_bytes = 32'(active) << rd_use_16bits;
    case (load_kind)
      vector_engine_control_pkg::LD_WEIGHT: begin
        rd_use_16bits = 1'b0;
        rd_rows_to_read = 32'(taps);
        rd_row_stride = channels;
        load_bytes = 32'(active);
      end
      vector_engine_control_pkg::LD_BIAS, vector_engine_control_pkg::LD_MULT, vector_engine_control_pkg::LD_SHIFT: begin
        rd_use_16bits = 1'b0;
        load_bytes = 32'(active) << 2;
        rd_valid_cols = 32'(active) << 2;
        if (load_kind==vector_engine_control_pkg::LD_BIAS && parameter_three_rows) begin
          rd_rows_to_read = 3;
          rd_row_stride = parameter_row_stride;
        end else if (load_kind==vector_engine_control_pkg::LD_MULT && parameter_two_rows) begin
          rd_rows_to_read = 2;
          rd_row_stride = parameter_row_stride;
        end
      end
      default: begin
      end
    endcase
    rd_burst_len_m1 = burst_length_from_bytes(load_bytes);
    if (p_registered_read_phase ? i_state_soft_lut_read :
        (state==vector_engine_control_pkg::SOFT_LUT_REQ || state==vector_engine_control_pkg::SOFT_LUT_WAIT)) begin
      rd_use_16bits=0;rd_valid_cols=4;rd_burst_len_m1=0;
    end
    if (p_registered_read_phase ? i_state_pool_read :
        (state==vector_engine_control_pkg::POOL_LOAD_REQ || state==vector_engine_control_pkg::POOL_LOAD_WAIT)) begin
      rd_use_16bits = 1'b0;
      if (channels==32'(active)) begin
        rd_rows_to_read=1;rd_valid_cols=32'(pool_elements);rd_row_stride=0;
        rd_burst_len_m1=burst_length_from_bytes(32'(pool_elements));
      end else begin
        rd_rows_to_read=32'(pool_pixels);rd_valid_cols=32'(active);rd_row_stride=channels;
        rd_burst_len_m1=burst_length_from_bytes(32'(active));
      end
    end
    param_bad = 1'b0;
    for(int word=0;word<p_bus_width/32;word++) begin
      if(state==vector_engine_control_pkg::LOAD_WAIT && rd_raw_valid && ((32'(rd_col_base)>>2)+32'(word))<active)
        param_bad |= (load_kind==vector_engine_control_pkg::LD_SHIFT && ($signed(rd_raw_data[word*32+:32])<-31 ||
                     $signed(rd_raw_data[word*32+:32])>30)) ||
                     (load_kind==vector_engine_control_pkg::LD_MULT && $signed(rd_raw_data[word*32+:32])<0);
    end
  end

  // 任务模式选择完整偏移，公共加法器生成各有效写入阶段的输出地址。
  always_comb begin
    write_address_offset = 32'd0;
    write_main_offset = 32'd0;
    write_channel_offset = 16'd0;
    if (spatial) begin
      write_address_offset = position_offset + {16'd0, channel_base};
      write_main_offset = position_offset;
      write_channel_offset = channel_base;
    end else if (i_vector_hadamard) begin
      write_address_offset = vector_offset << 2;
      write_main_offset = vector_offset << 2;
    end else if (i_add_s8) begin
      write_address_offset = vector_offset;
      write_main_offset = vector_offset;
    end
  end
  vector_read_address_add u_write_origin (
      .clk(clk), .i_base(c.output_base), .i_offset(write_main_offset),
      .i_channel(write_channel_offset), .o_address(write_origin_fast),
      .o_carry(unused_write_origin_carry)
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b0)) u_write_origin_four_state (
      .i_a(c.output_base), .i_b(write_address_offset), .i_carry(1'b0),
      .o_sum(write_origin_four_state), .o_carry(unused_write_origin_four_state_carry)
  );
  always_comb begin
    case (^{c.output_base, write_address_offset})
      1'b0, 1'b1: write_origin_next = write_origin_fast;
      default: write_origin_next = write_origin_four_state;
    endcase
  end
endmodule

`default_nettype wire
