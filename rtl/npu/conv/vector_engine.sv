// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 向量引擎顶层：连接任务控制、地址计算、操作数存储、运算单元和结果写回。
// 支持向量归约、逐元素运算、量化加法、深度卷积、池化及 Softmax。
// 各子模块保留独立的接收与返回周期，任务完成前接收全部已发出的存储响应。
module vector_engine #(
  parameter int TILE = 16,
  parameter int BUS_WIDTH = 32,
  parameter int DMA_SIZE = 4*TILE,
  parameter int PE_COUNT = (TILE < 8) ? TILE : 8,
  parameter int WINDOW_LANES = 4,
  parameter bit SHARED_QUANT_ENABLE = 1'b0,
  parameter int QUANT_LANES = SHARED_QUANT_ENABLE ? TILE : 1,
  parameter bit SHARED_STORAGE_ENABLE = 1'b0,
  parameter int SHARED_STORAGE_ADDR_WIDTH = 12,
  parameter int MAX_TAPS = 49,
  parameter int POOL_MAX_TAPS = 256
) (
  input wire logic clk, // 向量引擎工作时钟
  input wire logic rst_n, // 低有效异步复位
  input wire logic start, // 提交新的向量任务
  input wire vector_engine_pkg::vector_engine_cfg_t cfg, // 提交任务的完整运算配置
  output logic ready, // 允许接收新任务
  output logic done_valid, // 任务完成信息有效
  input wire logic done_ready, // 接收任务完成信息
  output logic [1:0] error, // 任务完成时的错误分类

  output logic dma_cfg_valid, // DMA 配置请求有效
  input wire logic dma_cfg_ready, // DMA 已准备接收配置
  output logic dma_conv_enable, // 启用卷积窗口读取
  output logic dma_range_enable, // 启用地址范围检查
  output conv_im2col_pkg::conv_cfg_t dma_conv_cfg, // 卷积窗口几何和地址配置
  output logic [31:0] dma_range_base [4], // 四个可访问地址区间的起点
  output logic [32:0] dma_range_end [4], // 四个可访问地址区间的扩展末端

  output logic win_req_valid, // 窗口读取请求有效
  input wire logic win_req_ready, // 窗口读取请求可接收
  output logic [31:0] win_req_p0, // 窗口请求的输出空间起点
  output logic [31:0] win_req_q0, // 窗口请求的归约维起点
  output logic [31:0] win_req_cols, // 窗口请求的有效通道数量
  output logic [1:0] win_req_tag, // 窗口请求使用的输入存储编号
  input wire logic win_rsp_valid, // 窗口响应数据有效
  output logic win_rsp_ready, // 引擎允许接收窗口响应
  input wire logic [1:0] win_rsp_tag, // 窗口响应对应的输入存储编号
  input wire logic [31:0] win_rsp_col, // 窗口响应的起始列编号
  input wire logic signed [15:0] win_rsp_data[WINDOW_LANES], // 并行返回的有符号输入元素
  input wire logic [WINDOW_LANES-1:0] win_rsp_mask, // 各返回通道的数据有效标志
  input wire logic win_rsp_last, // 当前窗口请求的最后一次响应
  input wire logic win_rsp_error, // 当前窗口请求发生读取错误
  input wire logic win_busy, // 窗口读取模块仍有未完成请求

  // DW 请求预留结果缓冲，矩阵量化流水按标签返回全部有效通道。
  output logic quant_req_valid, // 共享量化请求有效
  input wire logic quant_req_ready = 1'b0, // 共享量化流水允许接收请求
  output logic quant_req_tag, // 共享量化结果存储编号
  output logic signed [31:0] quant_req_accumulator[TILE], // 各通道待量化的累加结果
  output logic signed [31:0] quant_req_multiplier[TILE], // 各通道的量化乘数
  output logic [5:0] quant_req_right[TILE], // 各通道的量化右移位数
  output logic [TILE-1:0] quant_req_mask, // 本次共享量化的有效通道
  output logic signed [31:0] quant_req_offset, // 共享量化的输出零点偏移
  output logic signed [31:0] quant_req_minimum, // 共享量化的激活下限
  output logic signed [31:0] quant_req_maximum, // 共享量化的激活上限
  input wire logic quant_rsp_valid = 1'b0, // 共享量化返回数据有效
  input wire logic quant_rsp_tag = 1'b0, // 共享量化返回结果的存储编号
  input wire logic signed [7:0] quant_rsp_data[TILE] = '{default:8'sd0}, // 共享量化返回的各通道字节

  // 权重地址以 16 字节为单位，部分和地址以 64 字节为单位；读取在下一周期返回。
  output logic o_weight_read_en, // 共享权重存储读取使能
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_weight_read_addr, // 以十六字节为单位的权重读取地址
  input wire logic i_weight_read_valid = 1'b0, // 共享权重读取返回有效
  input wire logic [127:0] i_weight_read_data = '0, // 共享权重读取返回的数据
  output logic o_weight_write_en, // 共享权重存储写入使能
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_weight_write_addr, // 以十六字节为单位的权重写入地址
  output logic [127:0] o_weight_write_data, // 共享权重存储写入数据
  output logic [15:0] o_weight_write_mask, // 共享权重写入的逐字节有效掩码
  output logic o_ps_read_en, // 共享累加存储读取使能
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_ps_read_addr, // 以六十四字节为单位的累加读取地址
  input wire logic i_ps_read_valid = 1'b0, // 共享累加读取返回有效
  input wire logic [511:0] i_ps_read_data = '0, // 共享累加读取返回的数据
  output logic o_ps_write_en, // 共享累加存储写入使能
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_ps_write_addr, // 以六十四字节为单位的累加写入地址
  output logic [511:0] o_ps_write_data, // 共享累加存储写入数据
  input wire logic i_storage_error = 1'b0, // 共享存储访问错误

  output logic rd_req, // 申请 DMA 读取通道
  output logic rd_start, // 启动已授权的 DMA 读取
  input wire logic rd_granted, // DMA 读取通道已授权
  output logic rd_im2col, // 本次 DMA 读取使用卷积窗口模式
  output logic [31:0] rd_p0, // 卷积读取的输出空间起点
  output logic [31:0] rd_q0, // 卷积读取的归约维起点
  output logic [31:0] rd_base_addr, // 线性读取的字节起始地址
  output logic [31:0] rd_row_stride, // 相邻读取行的字节地址步长
  output logic [31:0] rd_rows_to_read, // 本次读取的行数
  output logic [31:0] rd_valid_cols, // 每行需要保留的有效列数
  output logic [7:0] rd_burst_len_m1, // 读取突发长度减一
  output logic rd_use_16bits, // 输入元素采用十六位格式
  input wire logic rd_busy, // DMA 读取仍在进行
  input wire logic rd_done, // DMA 读取事务完成
  input wire logic rd_error, // DMA 读取事务发生错误
  input wire logic signed [15:0] rd_data [BUS_WIDTH/8], // DMA 返回的并行有符号元素
  input wire logic rd_valid [BUS_WIDTH/8], // 各 DMA 返回元素的有效标志
  input wire logic [$clog2(DMA_SIZE)-1:0] rd_col_base, // DMA 返回数据的起始列位置
  input wire logic [BUS_WIDTH-1:0] rd_raw_data, // DMA 返回的原始总线数据
  input wire logic rd_raw_valid, // DMA 原始总线数据有效

  output logic wr_req, // 申请 DMA 写入通道
  output logic wr_start, // 启动已授权的 DMA 写入
  input wire logic wr_granted, // DMA 写入通道已授权
  output logic [31:0] wr_base_addr, // 结果写入的字节起始地址
  output logic [31:0] wr_row_stride, // 相邻结果行的字节地址步长
  output logic [31:0] wr_rows_to_write, // 本次结果写入的行数
  output logic [7:0] wr_burst_len_m1, // 结果写入突发长度减一
  output logic [BUS_WIDTH-1:0] src_wdata, // 交给 DMA 的结果总线数据
  output logic [BUS_WIDTH/8-1:0] src_wmask, // 结果总线的逐字节写入掩码
  output logic src_wvalid, // 结果总线数据有效
  input wire logic src_wready, // DMA 允许接收结果数据
  input wire logic wr_busy, // DMA 写入仍在进行
  input wire logic wr_done, // DMA 写入事务完成
  input wire logic wr_error // DMA 写入事务发生错误
);
  import vector_engine_pkg::*;
  import vector_engine_control_pkg::*;
  localparam int BUS_BYTES=BUS_WIDTH/8;
  localparam int BUS_SHIFT=$clog2(BUS_BYTES);
  localparam int ACTIVE_COUNT_W = $clog2(TILE + 1);
  localparam int TAP_LIMIT = MAX_TAPS > POOL_MAX_TAPS ? MAX_TAPS : POOL_MAX_TAPS;
  localparam int TAP_COUNT_W = $clog2(TAP_LIMIT + 1);
  localparam int TILE_INDEX_W = $clog2(TILE + PE_COUNT + 1);
  localparam int INPUT_INDEX_W = $clog2(DMA_SIZE);
  localparam bit p_input_bank_storage = TILE==16 && PE_COUNT==8 && DMA_SIZE==64 &&
      BUS_WIDTH==64 && WINDOW_LANES==8;
  localparam int POOL_GROUP_COUNT=(TILE+PE_COUNT-1)/PE_COUNT;
  localparam int AVG_SCALE_BITS = 8+$clog2(POOL_MAX_TAPS+1);
  localparam int ADD_INDEX_WIDTH=$clog2(TILE)>0 ? $clog2(TILE) : 1;
  localparam int POOL_SUM_WIDTH=8+$clog2(POOL_MAX_TAPS);

  logic read_done_q;
  logic read_error_q;
  logic write_response_done_q;
  logic write_response_error_q;
  state_t state;
  logic state_failed;
  logic state_compute_commit;
  logic state_pool_store;
  logic state_dw_execute;
  logic state_weight_read_phase;
  logic state_weight_zero_address;
  logic state_output_init;
  logic state_vector_init;
  logic state_dw_finish;
  logic window_fetch_phase;
  logic state_soft_lut_read;
  logic state_pool_read;
  load_t load_kind;
  logic [5:0] load_read_select;
  vector_engine_cfg_t c;
  logic spatial;
  logic depthwise;
  logic binary_vector;
  logic add_s8;
  logic softmax_s8;
  logic byte_output;
  logic avg_pool;
  logic max_pool;
  logic min_pool;
  logic vector_max;
  logic vector_min;
  logic vector_hadamard;
  logic [31:0] channels;
  logic [31:0] position;
  logic position_is_last;
  logic [15:0] channel_base;
  logic [ACTIVE_COUNT_W-1:0] active;
  logic [TILE-1:0] active_lane_mask;
  logic [TAP_COUNT_W-1:0] taps;
  logic [15:0] ox;
  logic [15:0] oy;
  logic [15:0] fetch_ox_next;
  logic [15:0] ox_next;
  logic [15:0] oy_next;
  logic [TAP_COUNT_W-1:0] kx;
  logic [TAP_COUNT_W-1:0] kernel_last_column;
  logic [TAP_COUNT_W-1:0] tap;
  logic [TAP_COUNT_W-1:0] load_tap;
  logic [TAP_COUNT_W-1:0] valid_taps;
  logic [31:0] vector_offset;
  logic [31:0] channel_remaining;
  logic [15:0] channel_next;
  logic channel_has_more;
  logic [ACTIVE_COUNT_W-1:0] vector_next_active;
  logic vector_has_more;
  logic [TILE_INDEX_W-1:0] compute_index;
  logic [TILE_INDEX_W-1:0] quant_index;
  logic [TILE_INDEX_W-1:0] reduce_index;
  logic [POOL_GROUP_COUNT-1:0] compute_pool_group;
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
  logic signed [15:0] input_buf [DMA_SIZE];
  logic signed [15:0] rhs_buf [TILE];
  logic [7:0] input_softmax_data;
  logic [7:0] add_input_saved;
  logic weight_row_last_fire;
  logic parameter_row_last_fire;
  logic parameter_three_rows;
  logic parameter_two_rows;
  logic weight_data_ready;
  logic shared_weight_write_pending;
  logic [TAP_COUNT_W-1:0] weight_tap_nxt;
  logic [TAP_COUNT_W-1:0] weight_tap_after_next;
  logic [TAP_COUNT_W-1:0] weight_prefetch_q;
  logic tap_last_wide;
  logic tap_last_modulo;
  logic tap_last_config;
  logic tap_last_zero;
  logic tap_last_increment;
  logic signed [31:0] acc_buf [TILE];
  logic [TILE-1:0] result_write_enable;
  logic [7:0] result_write_data [TILE];
  logic [2:0] pe_op;
  logic pe_operand_en;
  logic signed [15:0] pe_a [PE_COUNT];
  logic signed [15:0] pe_b [PE_COUNT];
  logic signed [31:0] pe_acc [PE_COUNT];
  logic signed [31:0] pe_result [PE_COUNT];
  logic [1:0] add_stage;
  logic [5:0] add_right;
  logic signed [31:0] add_multiplier;
  logic signed [31:0] add_operand;
  logic signed [31:0] add_scaled_a;
  logic signed [63:0] add_rounded;
  logic signed [31:0] reduce_acc;
  logic signed [31:0] reduce_next;
  logic signed [33:0] input_y;
  logic signed [33:0] input_x;
  logic signed [33:0] input_origin_x;
  logic signed [33:0] input_origin_y;
  logic param_bad;
  logic dw_in_bounds;
  logic [15:0] output_last_column;
  logic [32:0] checked_range_end [4];
  logic global_pool;
  wire [31:0] checked_kernel_count;
  wire [31:0] checked_position_count;
  wire [63:0] kernel_count;
  wire [63:0] position_count;
  logic config_check_ready;
  logic config_check_done;
  logic config_check_error;
  logic signed [31:0] q_accumulator;
  logic signed [31:0] q_multiplier;
  logic signed [63:0] q_rounded;
  logic signed [31:0] q_clamped_data;
  logic [6:0] q_valid;
  logic [7:0] q_clamped_q;
  logic [7:0] serial_clamped_q;
  logic [TILE_INDEX_W-1:0] q_issue;
  logic [TILE_INDEX_W-1:0] q_count;
  logic dw_issue_fire;
  logic dw_commit_vld;
  logic dw_group_last;
  logic dw_tap_advance;
  logic [TILE_INDEX_W-1:0] dw_commit_index;
  logic dw_snapshot_fire;
  logic dw_snapshot_vld;
  logic signed [31:0] dw_snapshot_value [TILE];
  logic dw_quant_start;
  logic dw_quant_last_issue;
  logic dw_snapshot_data_ready;
  logic [31:0] dw_snapshot_address;
  logic dw_snapshot_last;
  logic dw_quant_input_active;
  logic dw_quant_slot;
  logic dw_quant_next_slot;
  logic [6:0] dw_quant_slot_pipe;
  logic [1:0] dw_result_reserved;
  logic [1:0] dw_result_ready;
  logic [7:0] dw_result_bytes [2][TILE];
  logic [31:0] dw_result_address [2];
  logic [ACTIVE_COUNT_W-1:0] dw_result_count [2];
  logic [1:0] dw_result_last;
  logic dw_result_read_slot;
  logic dw_result_accept;
  logic dw_quant_complete;
  logic dw_group_pending;
  logic dw_work_pending;
  logic dw_shared_fire;
  logic [1:0] dw_shared_inflight;
  logic writeback_request_valid;
  logic writeback_request_last;
  logic [31:0] writeback_request_address;
  logic [$clog2(4*TILE+1)-1:0] writeback_request_bytes;
  logic [31:0] write_origin;
  logic [31:0] write_total;
  wire writeback_ready;
  wire writeback_busy_raw;
  wire writeback_done;
  wire writeback_error;
  logic writeback_sink_ready;
  logic writeback_metadata_valid;
  logic writeback_metadata_coalesce;
  logic writeback_metadata_last;
  logic writeback_metadata_capture;
  logic writeback_sink_fire;
  logic writeback_accept_pending;
  logic [31:0] writeback_metadata_address;
  logic [$clog2(4*TILE+1)-1:0] writeback_metadata_bytes;
  logic writeback_busy;
  wire [32*TILE-1:0] writeback_words;
  logic avg_negative;
  logic avg_power_two;
  logic avg_done;
  logic [5:0] avg_shift;
  logic [AVG_SCALE_BITS:0] avg_reciprocal [0:POOL_MAX_TAPS];
  logic [AVG_SCALE_BITS:0] avg_reciprocal_data;
  logic [AVG_SCALE_BITS-1:0] avg_numerator_q;
  logic [7:0] avg_estimate_q;
  logic [7:0] avg_quotient_q;
  logic [7:0] avg_magnitude_q;
  logic signed [8:0] avg_signed_q;
  logic [AVG_SCALE_BITS:0] avg_check_q;
  logic signed [AVG_SCALE_BITS+1:0] avg_residual_q;
  logic [TAP_COUNT_W-1:0] avg_remainder_q;
  logic [TAP_COUNT_W:0] avg_twice_remainder;
  logic [3:0] avg_phase;
  logic [31:0] avg_input_magnitude;
  logic avg_overestimate;
  logic input_range_mode;
  logic [1:0] read_bank;
  logic [1:0] wf_bank;
  logic [1:0] input_bank_mask;
  logic [3:0] input_ready;
  logic [3:0] input_reserved;
  (* keep = 1 *) logic input_drain_ready;
  logic [INPUT_INDEX_W-1:0] input_read_base;
  logic [INPUT_INDEX_W-1:0] input_response_base;
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
  wire kernel_column_end;
  logic [15:0] padding_x_negative;
  logic [15:0] padding_y_negative;
  logic soft_ready;
  logic soft_done;
  logic soft_exp_we;
  logic soft_out_we;
  logic [1:0] soft_error;
  logic [$clog2(TILE)-1:0] soft_input_index;
  logic [$clog2(TILE)-1:0] soft_exp_index;
  logic [$clog2(TILE)-1:0] soft_out_index;
  logic soft_lut_req_valid;
  logic soft_lut_req_ready;
  logic soft_lut_rsp_valid;
  logic [7:0] soft_lut_index;
  logic [7:0] soft_lut_index_q;
  logic [31:0] soft_lut_data;
  logic signed [31:0] soft_mul_a;
  logic signed [31:0] soft_mul_b;
  logic signed [31:0] soft_exp_data;
  logic signed [7:0] soft_out_data;
  logic soft_exp_write_valid;
  logic soft_out_write_valid;
  logic [$clog2(TILE)-1:0] soft_exp_write_index;
  logic [$clog2(TILE)-1:0] soft_out_write_index;
  logic signed [31:0] multiplier_a;
  logic signed [31:0] multiplier_b;
  logic signed [63:0] multiplier_product;
  logic [TAP_COUNT_W-1:0] pool_taps_remaining;
  logic [INPUT_INDEX_W:0] pool_pixels;
  logic [INPUT_INDEX_W:0] pool_received;
  logic [INPUT_INDEX_W:0] pool_pixel;
  logic [INPUT_INDEX_W:0] pool_elements;
  logic [INPUT_INDEX_W:0] pool_next_elements;
  logic [INPUT_INDEX_W:0] pool_next_pixels;
  logic [INPUT_INDEX_W:0] pool_input_index;
  logic [INPUT_INDEX_W:0] pool_row_remaining;
  wire pool_response_fire;
  logic [BUS_SHIFT:0] pool_beat_count;
  logic pool_read_complete_saved;
  logic [31:0] position_next;
  logic [31:0] write_origin_next;
  wire signed [15:0] input_lane [PE_COUNT];
  wire signed [15:0] rhs_lane [PE_COUNT];
  wire signed [7:0] weight_lane [PE_COUNT];
  wire signed [31:0] accum_lane [PE_COUNT];
  wire signed [7:0] add_first_lhs;
  wire signed [7:0] add_next_lhs;
  wire signed [7:0] add_rhs;
  wire signed [8:0] add_first_lhs_offset;
  wire signed [8:0] add_next_lhs_offset;
  wire signed [8:0] add_rhs_offset;
  logic [TILE_INDEX_W-1:0] serial_acc_read_index;
  logic signed [31:0] serial_acc_read_data;
  logic signed [31:0] softmax_i_exp_rdata;
  logic signed [31:0] soft_exp_memory [TILE];
  logic signed [31:0] reduce_alu_i_lhs;
  logic signed [31:0] reduce_alu_i_rhs;
  logic signed [31:0] reduce_rhs_q;
  logic reduce_alu_i_max;
  logic reduce_alu_i_min;
  wire signed [POOL_SUM_WIDTH-1:0] avg_pool_sum;
  logic signed [POOL_SUM_WIDTH-1:0] avg_sum_q;
  logic [POOL_SUM_WIDTH-1:0] avg_negated_sum;
  logic signed [AVG_SCALE_BITS+1:0] avg_residual_next;
  wire [POOL_SUM_WIDTH-1:0] avg_unsigned_magnitude;
  logic signed [31:0] params_o_multiplier;
  logic [5:0] params_o_right_shift;
  wire signed [63:0] rounding_input;
  wire [5:0] rounding_amount;
  wire signed [63:0] rounding_result;
  wire signed [63:0] rounding_floor;
  wire signed [31:0] avg_power_result;
  wire signed [31:0] avg_div_result;
  wire signed [31:0] add_clamped;
  logic result_background_write;
  logic [TILE_INDEX_W-1:0] result_background_index;
  logic result_serial_write;
  logic [TILE_INDEX_W-1:0] result_serial_index;
  logic [7:0] result_serial_data;
  logic [7:0] result_common_data;
  logic result_byte_pending;
  logic [TILE_INDEX_W-1:0] result_byte_index;
  logic [7:0] result_byte_data;
  logic [7:0] pool_lane_value [PE_COUNT];
  logic [5:0] q_right [3];
  logic [TILE_INDEX_W-1:0] q_index [7];
  logic signed [63:0] activation_i_quantized_value;
  logic signed [63:0] activation_i_add_rounding_value;
  logic signed [7:0] activation_i_average_floor;
  logic signed [7:0] activation_i_average_rounded;
  logic signed [8:0] activation_i_average_divided;
  logic signed [31:0] activation_cfg_output_offset;
  logic [1:0][31:0] activation_cfg_bounds;
  logic [3:0][31:0] activation_o_result;

  vector_engine_control #(
    .p_tile(TILE),
    .p_bus_width(BUS_WIDTH),
    .p_dma_size(DMA_SIZE),
    .p_pe_count(PE_COUNT),
    .p_window_lanes(WINDOW_LANES),
    .p_shared_quant_enable(SHARED_QUANT_ENABLE),
    .p_quant_lanes(QUANT_LANES),
    .p_shared_storage_enable(SHARED_STORAGE_ENABLE),
    .p_shared_storage_addr_width(SHARED_STORAGE_ADDR_WIDTH),
    .p_max_taps(MAX_TAPS),
    .p_pool_max_taps(POOL_MAX_TAPS)
  ) u_control (
    .clk(clk),
    .rst_n(rst_n),
    .i_start(start),
    .i_cfg(cfg),
    .o_ready(ready),
    .o_done_valid(done_valid),
    .i_done_ready(done_ready),
    .o_error(error),
    .o_dma_cfg_valid(dma_cfg_valid),
    .i_dma_cfg_ready(dma_cfg_ready),
    .i_win_rsp_last(win_rsp_last),
    .i_win_busy(win_busy),
    .i_quant_req_accumulator(quant_req_accumulator),
    .i_storage_error(i_storage_error),
    .o_rd_req(rd_req),
    .i_rd_granted(rd_granted),
    .i_rd_done(rd_done),
    .i_rd_error(rd_error),
    .i_rd_raw_data(rd_raw_data),
    .i_rd_raw_valid(rd_raw_valid),
    .i_wr_done(wr_done),
    .i_wr_error(wr_error),
    .o_read_done_q(read_done_q),
    .o_read_error_q(read_error_q),
    .o_write_response_done_q(write_response_done_q),
    .o_write_response_error_q(write_response_error_q),
    .o_state(state),
    .o_state_failed(state_failed),
    .o_state_compute_commit(state_compute_commit),
    .o_state_pool_store(state_pool_store),
    .o_state_dw_execute(state_dw_execute),
    .o_state_weight_read_phase(state_weight_read_phase),
    .o_state_weight_zero_address(state_weight_zero_address),
    .o_state_output_init(state_output_init),
    .o_state_vector_init(state_vector_init),
    .o_state_dw_finish(state_dw_finish),
    .o_window_fetch_phase(window_fetch_phase),
    .o_state_soft_lut_read(state_soft_lut_read),
    .o_state_pool_read(state_pool_read),
    .o_load_kind(load_kind),
    .o_load_read_select(load_read_select),
    .o_c(c),
    .o_spatial(spatial),
    .o_depthwise(depthwise),
    .o_binary_vector(binary_vector),
    .o_add_s8(add_s8),
    .o_softmax_s8(softmax_s8),
    .o_byte_output(byte_output),
    .o_avg_pool(avg_pool),
    .o_max_pool(max_pool),
    .o_min_pool(min_pool),
    .o_vector_max(vector_max),
    .o_vector_min(vector_min),
    .o_vector_hadamard(vector_hadamard),
    .i_channels(channels),
    .o_position(position),
    .o_position_is_last(position_is_last),
    .o_channel_base(channel_base),
    .o_active(active),
    .o_active_lane_mask(active_lane_mask),
    .o_taps(taps),
    .o_ox(ox),
    .o_oy(oy),
    .i_fetch_ox_next(fetch_ox_next),
    .i_ox_next(ox_next),
    .i_oy_next(oy_next),
    .o_kx(kx),
    .o_kernel_last_column(kernel_last_column),
    .o_tap(tap),
    .o_load_tap(load_tap),
    .o_valid_taps(valid_taps),
    .o_vector_offset(vector_offset),
    .i_channel_remaining(channel_remaining),
    .i_channel_next(channel_next),
    .i_channel_has_more(channel_has_more),
    .i_vector_next_active(vector_next_active),
    .i_vector_has_more(vector_has_more),
    .o_compute_index(compute_index),
    .o_quant_index(quant_index),
    .o_reduce_index(reduce_index),
    .o_compute_pool_group(compute_pool_group),
    .i_compute_group_last_q(compute_group_last_q),
    .i_pool_pixel_has_more_q(pool_pixel_has_more_q),
    .o_fetch_tap_offset(fetch_tap_offset),
    .o_position_offset(position_offset),
    .o_pool_byte_offset(pool_byte_offset),
    .i_fetch_position_next(fetch_position_next),
    .i_fetch_tap_offset_next(fetch_tap_offset_next),
    .i_position_offset_next(position_offset_next),
    .i_pool_byte_offset_next(pool_byte_offset_next),
    .i_vector_offset_next(vector_offset_next),
    .i_weight_row_last_fire(weight_row_last_fire),
    .i_parameter_row_last_fire(parameter_row_last_fire),
    .i_parameter_three_rows(parameter_three_rows),
    .i_parameter_two_rows(parameter_two_rows),
    .i_weight_tap_nxt(weight_tap_nxt),
    .i_weight_tap_after_next(weight_tap_after_next),
    .o_weight_prefetch_q(weight_prefetch_q),
    .i_tap_last_wide(tap_last_wide),
    .o_tap_last_modulo(tap_last_modulo),
    .i_tap_last_config(tap_last_config),
    .i_tap_last_zero(tap_last_zero),
    .i_tap_last_increment(tap_last_increment),
    .o_pe_op(pe_op),
    .o_add_stage(add_stage),
    .o_add_scaled_a(add_scaled_a),
    .o_add_rounded(add_rounded),
    .o_reduce_acc(reduce_acc),
    .i_reduce_next(reduce_next),
    .o_input_y(input_y),
    .o_input_x(input_x),
    .o_input_origin_x(input_origin_x),
    .o_input_origin_y(input_origin_y),
    .i_param_bad(param_bad),
    .i_dw_in_bounds(dw_in_bounds),
    .i_output_last_column(output_last_column),
    .i_global_pool(global_pool),
    .i_kernel_count(kernel_count),
    .i_position_count(position_count),
    .i_config_check_ready(config_check_ready),
    .i_config_check_done(config_check_done),
    .i_config_check_error(config_check_error),
    .o_q_accumulator(q_accumulator),
    .o_q_multiplier(q_multiplier),
    .o_q_rounded(q_rounded),
    .i_q_clamped_data(q_clamped_data),
    .o_q_valid(q_valid),
    .o_q_clamped_q(q_clamped_q),
    .o_q_issue(q_issue),
    .o_q_count(q_count),
    .i_dw_issue_fire(dw_issue_fire),
    .i_dw_group_last(dw_group_last),
    .i_dw_tap_advance(dw_tap_advance),
    .i_dw_snapshot_fire(dw_snapshot_fire),
    .i_dw_quant_start(dw_quant_start),
    .i_dw_quant_input_active(dw_quant_input_active),
    .i_dw_group_pending(dw_group_pending),
    .i_dw_work_pending(dw_work_pending),
    .o_write_origin(write_origin),
    .o_write_total(write_total),
    .i_writeback_ready(writeback_ready),
    .i_writeback_done(writeback_done),
    .i_writeback_error(writeback_error),
    .i_writeback_busy(writeback_busy),
    .o_avg_negative(avg_negative),
    .i_avg_power_two(avg_power_two),
    .i_avg_done(avg_done),
    .o_input_range_mode(input_range_mode),
    .o_read_bank(read_bank),
    .o_wf_bank(wf_bank),
    .i_input_bank_mask(input_bank_mask),
    .i_input_ready(input_ready),
    .i_input_reserved(input_reserved),
    .i_input_drain_ready(input_drain_ready),
    .o_window_received(window_received),
    .i_window_count_o_sum(window_count_o_sum),
    .i_window_response_fire(window_response_fire),
    .i_window_request_fire(window_request_fire),
    .i_window_fetch_advance(window_fetch_advance),
    .i_window_response_fault(window_response_fault),
    .o_fetch_position(fetch_position),
    .o_fetch_ox(fetch_ox),
    .o_fetch_x(fetch_x),
    .o_fetch_y(fetch_y),
    .o_fetch_origin_x(fetch_origin_x),
    .o_fetch_origin_y(fetch_origin_y),
    .i_coordinate_step_o_value(coordinate_step_o_value),
    .i_next_window_valid_q(next_window_valid_q),
    .i_next_window_x(next_window_x),
    .i_next_window_y(next_window_y),
    .i_kernel_column_end(kernel_column_end),
    .i_padding_x_negative(padding_x_negative),
    .i_padding_y_negative(padding_y_negative),
    .i_soft_ready(soft_ready),
    .i_soft_done(soft_done),
    .i_soft_error(soft_error),
    .i_soft_lut_req_valid(soft_lut_req_valid),
    .i_soft_lut_index(soft_lut_index),
    .o_soft_lut_index_q(soft_lut_index_q),
    .o_soft_lut_data(soft_lut_data),
    .o_pool_taps_remaining(pool_taps_remaining),
    .o_pool_pixels(pool_pixels),
    .o_pool_received(pool_received),
    .o_pool_pixel(pool_pixel),
    .o_pool_elements(pool_elements),
    .i_pool_next_elements(pool_next_elements),
    .i_pool_next_pixels(pool_next_pixels),
    .o_pool_input_index(pool_input_index),
    .o_pool_row_remaining(pool_row_remaining),
    .i_pool_response_fire(pool_response_fire),
    .i_pool_beat_count(pool_beat_count),
    .i_pool_read_complete_saved(pool_read_complete_saved),
    .i_position_next(position_next),
    .i_write_origin_next(write_origin_next),
    .i_serial_acc_read_data(serial_acc_read_data),
    .i_params_o_multiplier(params_o_multiplier),
    .i_params_o_right_shift(params_o_right_shift),
    .i_rounding_result(rounding_result),
    .o_q_right(q_right),
    .o_q_index(q_index)
  );
  vector_engine_address #(
    .p_registered_read_phase(1'b1),
    .p_tile(TILE),
    .p_bus_width(BUS_WIDTH),
    .p_dma_size(DMA_SIZE),
    .p_pe_count(PE_COUNT),
    .p_window_lanes(WINDOW_LANES),
    .p_shared_quant_enable(SHARED_QUANT_ENABLE),
    .p_quant_lanes(QUANT_LANES),
    .p_shared_storage_enable(SHARED_STORAGE_ENABLE),
    .p_shared_storage_addr_width(SHARED_STORAGE_ADDR_WIDTH),
    .p_max_taps(MAX_TAPS),
    .p_pool_max_taps(POOL_MAX_TAPS)
  ) u_address (
    .clk(clk),
    .rst_n(rst_n),
    .i_start(start),
    .i_cfg(cfg),
    .i_dma_cfg_ready(dma_cfg_ready),
    .o_dma_conv_enable(dma_conv_enable),
    .o_dma_range_enable(dma_range_enable),
    .o_dma_conv_cfg(dma_conv_cfg),
    .o_dma_range_base(dma_range_base),
    .o_dma_range_end(dma_range_end),
    .o_win_req_valid(win_req_valid),
    .i_win_req_ready(win_req_ready),
    .o_win_req_p0(win_req_p0),
    .o_win_req_q0(win_req_q0),
    .o_win_req_cols(win_req_cols),
    .o_win_req_tag(win_req_tag),
    .i_win_rsp_valid(win_rsp_valid),
    .o_win_rsp_ready(win_rsp_ready),
    .i_win_rsp_tag(win_rsp_tag),
    .i_win_rsp_mask(win_rsp_mask),
    .i_win_rsp_last(win_rsp_last),
    .i_win_rsp_error(win_rsp_error),
    .i_win_busy(win_busy),
    .i_weight_read_valid(i_weight_read_valid),
    .i_ps_read_valid(i_ps_read_valid),
    .i_rd_req(rd_req),
    .o_rd_start(rd_start),
    .i_rd_granted(rd_granted),
    .o_rd_im2col(rd_im2col),
    .o_rd_p0(rd_p0),
    .o_rd_q0(rd_q0),
    .o_rd_base_addr(rd_base_addr),
    .o_rd_row_stride(rd_row_stride),
    .o_rd_rows_to_read(rd_rows_to_read),
    .o_rd_valid_cols(rd_valid_cols),
    .o_rd_burst_len_m1(rd_burst_len_m1),
    .o_rd_use_16bits(rd_use_16bits),
    .i_rd_busy(rd_busy),
    .i_rd_done(rd_done),
    .i_rd_valid(rd_valid),
    .i_rd_col_base(rd_col_base),
    .i_rd_raw_data(rd_raw_data),
    .i_rd_raw_valid(rd_raw_valid),
    .i_wr_busy(wr_busy),
    .i_read_done_q(read_done_q),
    .i_state(state),
    .i_state_failed(state_failed),
    .i_state_compute_commit(state_compute_commit),
    .i_state_dw_execute(state_dw_execute),
    .i_state_output_init(state_output_init),
    .i_state_dw_finish(state_dw_finish),
    .i_window_fetch_phase(window_fetch_phase),
    .i_state_soft_lut_read(state_soft_lut_read),
    .i_state_pool_read(state_pool_read),
    .i_load_kind(load_kind),
    .i_load_read_select(load_read_select),
    .i_c(c),
    .i_spatial(spatial),
    .i_depthwise(depthwise),
    .i_vector_hadamard(vector_hadamard),
    .i_add_s8(add_s8),
    .i_binary_vector(binary_vector),
    .i_softmax_s8(softmax_s8),
    .o_channels(channels),
    .i_position(position),
    .i_channel_base(channel_base),
    .i_active(active),
    .i_taps(taps),
    .i_ox(ox),
    .o_fetch_ox_next(fetch_ox_next),
    .i_kx(kx),
    .i_kernel_last_column(kernel_last_column),
    .i_tap(tap),
    .i_valid_taps(valid_taps),
    .i_vector_offset(vector_offset),
    .o_channel_remaining(channel_remaining),
    .o_channel_next(channel_next),
    .o_channel_has_more(channel_has_more),
    .o_vector_next_active(vector_next_active),
    .o_vector_has_more(vector_has_more),
    .i_compute_index(compute_index),
    .o_compute_group_last_q(compute_group_last_q),
    .o_pool_pixel_has_more_q(pool_pixel_has_more_q),
    .i_fetch_tap_offset(fetch_tap_offset),
    .i_position_offset(position_offset),
    .i_pool_byte_offset(pool_byte_offset),
    .o_fetch_position_next(fetch_position_next),
    .o_fetch_tap_offset_next(fetch_tap_offset_next),
    .o_position_offset_next(position_offset_next),
    .o_pool_byte_offset_next(pool_byte_offset_next),
    .o_vector_offset_next(vector_offset_next),
    .o_add_input_sum(add_input_sum),
    .o_parameter_row_last_fire(parameter_row_last_fire),
    .o_parameter_three_rows(parameter_three_rows),
    .o_parameter_two_rows(parameter_two_rows),
    .i_shared_weight_write_pending(shared_weight_write_pending),
    .i_tap_last_modulo(tap_last_modulo),
    .i_add_scaled_a(add_scaled_a),
    .i_add_rounded(add_rounded),
    .i_input_y(input_y),
    .i_input_x(input_x),
    .i_input_origin_x(input_origin_x),
    .i_input_origin_y(input_origin_y),
    .o_param_bad(param_bad),
    .o_dw_in_bounds(dw_in_bounds),
    .o_output_last_column(output_last_column),
    .i_checked_range_end(checked_range_end),
    .o_global_pool(global_pool),
    .i_position_count(position_count),
    .i_config_check_done(config_check_done),
    .i_dw_issue_fire(dw_issue_fire),
    .i_dw_group_last(dw_group_last),
    .i_dw_tap_advance(dw_tap_advance),
    .i_dw_snapshot_fire(dw_snapshot_fire),
    .i_dw_shared_inflight(dw_shared_inflight),
    .i_writeback_busy(writeback_busy),
    .o_avg_power_two(avg_power_two),
    .o_avg_shift(avg_shift),
    .i_input_range_mode(input_range_mode),
    .i_read_bank(read_bank),
    .i_wf_bank(wf_bank),
    .o_input_bank_mask(input_bank_mask),
    .o_input_ready(input_ready),
    .o_input_reserved(input_reserved),
    .o_input_drain_ready(input_drain_ready),
    .o_input_read_base(input_read_base),
    .o_input_response_base(input_response_base),
    .i_window_received(window_received),
    .o_window_count_o_sum(window_count_o_sum),
    .o_window_response_fire(window_response_fire),
    .o_window_request_fire(window_request_fire),
    .o_window_fetch_advance(window_fetch_advance),
    .o_window_response_fault(window_response_fault),
    .i_window_write_pending(window_write_pending),
    .i_fetch_position(fetch_position),
    .i_fetch_ox(fetch_ox),
    .i_fetch_x(fetch_x),
    .i_fetch_y(fetch_y),
    .i_fetch_origin_x(fetch_origin_x),
    .i_fetch_origin_y(fetch_origin_y),
    .o_coordinate_step_o_value(coordinate_step_o_value),
    .o_next_window_valid_q(next_window_valid_q),
    .o_next_window_x(next_window_x),
    .o_next_window_y(next_window_y),
    .o_kernel_column_end(kernel_column_end),
    .o_padding_x_negative(padding_x_negative),
    .o_padding_y_negative(padding_y_negative),
    .i_soft_lut_index_q(soft_lut_index_q),
    .i_pool_taps_remaining(pool_taps_remaining),
    .i_pool_pixels(pool_pixels),
    .i_pool_received(pool_received),
    .i_pool_pixel(pool_pixel),
    .i_pool_elements(pool_elements),
    .o_pool_next_elements(pool_next_elements),
    .o_pool_next_pixels(pool_next_pixels),
    .i_pool_row_remaining(pool_row_remaining),
    .o_pool_beat_count(pool_beat_count),
    .o_pool_read_complete_saved(pool_read_complete_saved),
    .o_position_next(position_next),
    .o_write_origin_next(write_origin_next)
  );
  vector_engine_operand_store #(
    .p_tile(TILE),
    .p_bus_width(BUS_WIDTH),
    .p_dma_size(DMA_SIZE),
    .p_pe_count(PE_COUNT),
    .p_window_lanes(WINDOW_LANES),
    .p_shared_quant_enable(SHARED_QUANT_ENABLE),
    .p_quant_lanes(QUANT_LANES),
    .p_shared_storage_enable(SHARED_STORAGE_ENABLE),
    .p_shared_storage_addr_width(SHARED_STORAGE_ADDR_WIDTH),
    .p_max_taps(MAX_TAPS),
    .p_pool_max_taps(POOL_MAX_TAPS)
  ) u_operand_store (
    .clk(clk),
    .rst_n(rst_n),
    .i_win_rsp_col(win_rsp_col),
    .i_win_rsp_data(win_rsp_data),
    .i_win_rsp_mask(win_rsp_mask),
    .o_quant_req_multiplier(quant_req_multiplier),
    .o_quant_req_right(quant_req_right),
    .o_weight_read_en(o_weight_read_en),
    .o_weight_read_addr(o_weight_read_addr),
    .i_weight_read_valid(i_weight_read_valid),
    .i_weight_read_data(i_weight_read_data),
    .o_weight_write_en(o_weight_write_en),
    .o_weight_write_addr(o_weight_write_addr),
    .o_weight_write_data(o_weight_write_data),
    .o_weight_write_mask(o_weight_write_mask),
    .i_storage_error(i_storage_error),
    .i_rd_data(rd_data),
    .i_rd_valid(rd_valid),
    .i_rd_col_base(rd_col_base),
    .i_rd_raw_data(rd_raw_data),
    .i_rd_raw_valid(rd_raw_valid),
    .i_read_done_q(read_done_q),
    .i_state(state),
    .i_state_failed(state_failed),
    .i_state_compute_commit(state_compute_commit),
    .i_state_weight_read_phase(state_weight_read_phase),
    .i_state_weight_zero_address(state_weight_zero_address),
    .i_state_output_init(state_output_init),
    .i_state_vector_init(state_vector_init),
    .i_load_kind(load_kind),
    .i_c(c),
    .i_spatial(spatial),
    .i_depthwise(depthwise),
    .i_add_s8(add_s8),
    .i_softmax_s8(softmax_s8),
    .i_max_pool(max_pool),
    .i_min_pool(min_pool),
    .i_vector_max(vector_max),
    .i_vector_min(vector_min),
    .i_vector_hadamard(vector_hadamard),
    .i_active(active),
    .i_active_lane_mask(active_lane_mask),
    .i_taps(taps),
    .i_tap(tap),
    .i_load_tap(load_tap),
    .i_compute_index(compute_index),
    .i_compute_group_last_q(compute_group_last_q),
    .o_input_buf(input_buf),
    .o_rhs_buf(rhs_buf),
    .o_input_softmax_data(input_softmax_data),
    .o_add_input_saved(add_input_saved),
    .o_weight_row_last_fire(weight_row_last_fire),
    .o_weight_data_ready(weight_data_ready),
    .o_shared_weight_write_pending(shared_weight_write_pending),
    .o_weight_tap_nxt(weight_tap_nxt),
    .o_weight_tap_after_next(weight_tap_after_next),
    .i_weight_prefetch_q(weight_prefetch_q),
    .o_tap_last_wide(tap_last_wide),
    .i_tap_last_modulo(tap_last_modulo),
    .o_tap_last_config(tap_last_config),
    .o_tap_last_zero(tap_last_zero),
    .o_tap_last_increment(tap_last_increment),
    .o_acc_buf(acc_buf),
    .i_result_write_enable(result_write_enable),
    .i_result_write_data(result_write_data),
    .i_pe_result(pe_result),
    .i_global_pool(global_pool),
    .i_kernel_count(kernel_count),
    .i_q_issue(q_issue),
    .i_dw_commit_vld(dw_commit_vld),
    .i_dw_tap_advance(dw_tap_advance),
    .i_dw_commit_index(dw_commit_index),
    .i_dw_snapshot_fire(dw_snapshot_fire),
    .i_writeback_busy(writeback_busy),
    .i_input_read_base(input_read_base),
    .i_input_response_base(input_response_base),
    .i_window_response_fire(window_response_fire),
    .o_window_write_pending(window_write_pending),
    .i_soft_input_index(soft_input_index),
    .i_pool_received(pool_received),
    .i_pool_elements(pool_elements),
    .i_pool_input_index(pool_input_index),
    .i_pool_response_fire(pool_response_fire),
    .i_pool_beat_count(pool_beat_count),
    .o_input_lane(input_lane),
    .o_rhs_lane(rhs_lane),
    .o_weight_lane(weight_lane),
    .o_accum_lane(accum_lane),
    .o_params_o_multiplier(params_o_multiplier),
    .o_params_o_right_shift(params_o_right_shift)
  );

  // 完成与错误在接口边界共同保存，数据仍在各自有效周期写入存储。
  // 初始化、提交、池化写入和失败资格与状态同时保存，直接控制数据选择及排空。
  // 有效通道数及逐通道资格共同保存，各数据端口直接读取这些寄存结果。
  assign ox_next = ox + 16'd1;
  assign oy_next = oy + 16'd1;
  // PE 组的选择资格与下标同时保存，结果写入直接使用对应组的寄存标志。

  assign kernel_count = {32'd0,checked_kernel_count};
  assign position_count = {32'd0,checked_position_count};
  vector_config_check #(.TILE(TILE),.MAX_TAPS(MAX_TAPS),.POOL_MAX_TAPS(POOL_MAX_TAPS)) u_config_check (
    .clk,.rst_n,.start(state==CHECK),.cfg(c),.ready(config_check_ready),
    .i_input_range(global_pool),
    .done(config_check_done),.error(config_check_error),
    .kernel_count(checked_kernel_count),.position_count(checked_position_count),
    .input_bytes(),.output_bytes(),.weight_bytes(),
    .o_read_end(checked_range_end));
  // DW 前台每周期发射一组操作数，提交下标独立保存，连续卷积位置转发累加结果。
  for (genvar word_index=0;word_index<TILE;word_index++) begin : g_writeback_word
    wire [31:0] word_value = word_index==0 && !byte_output && !vector_hadamard ?
        reduce_acc : acc_buf[word_index];
    // 标量字节结果保存在已消费的累加项中，DW 使用独立的双组结果存储。
    assign writeback_words[32*word_index+:32] = {word_value[31:8],
        depthwise ? dw_result_bytes[dw_result_read_slot][word_index] : word_value[7:0]};
  end
  assign writeback_request_valid = depthwise ?
      (dw_result_ready[dw_result_read_slot] && !state_failed) : state==WRITE_PREP;
  assign writeback_request_address = depthwise ? dw_result_address[dw_result_read_slot] : write_origin;
  assign writeback_request_bytes = depthwise ? $clog2(4*TILE+1)'(dw_result_count[dw_result_read_slot]) :
      $clog2(4*TILE+1)'(write_total);
  assign writeback_request_last = !depthwise || dw_result_last[dw_result_read_slot];
  assign dw_result_accept = depthwise && writeback_request_valid && writeback_ready;
  // 地址、长度与槽位共同保存；接收事件寄存后再释放源存储。
  // 等待接收确认期间保持原结果，写回端只接收一次当前请求。
  assign writeback_metadata_capture = writeback_request_valid &&
      !writeback_metadata_valid && !writeback_accept_pending;
  assign writeback_sink_fire = writeback_metadata_valid && writeback_sink_ready;
  assign writeback_ready = writeback_accept_pending;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) writeback_accept_pending <= 1'b0;
    else writeback_accept_pending <= writeback_sink_fire;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) writeback_metadata_valid <= 1'b0;
    else if (state==CHECK || state_failed || writeback_sink_fire)
      writeback_metadata_valid <= 1'b0;
    else if (writeback_metadata_capture) writeback_metadata_valid <= 1'b1;
  end
  always_ff @(posedge clk) begin
    if (writeback_metadata_capture) begin
      writeback_metadata_address <= writeback_request_address;
      writeback_metadata_bytes <= writeback_request_bytes;
      writeback_metadata_last <= writeback_request_last;
      writeback_metadata_coalesce <= depthwise && channels==32'(dw_result_count[dw_result_read_slot]);
    end
  end
  // 请求有效时提前保存占用状态，完成后的空闲状态在下一周期提供给控制逻辑。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) writeback_busy <= 1'b0;
    else writeback_busy <= writeback_busy_raw || writeback_request_valid;
  end
  // 引擎仅合并连续 DW 字节结果，完整数据字使用独立写事务。
  vector_banked_writeback #(.TILE(TILE),.BUS_WIDTH(BUS_WIDTH),.p_coalesce_bytes_only(1'b1)) u_writeback (
    .clk,.rst_n,.request_valid(writeback_metadata_valid),.request_ready(writeback_sink_ready),
    .request_address(writeback_metadata_address),.request_bytes(writeback_metadata_bytes),
    .request_byte_output(byte_output),.result_words(writeback_words),
    .request_coalesce(writeback_metadata_coalesce),
    .request_last(writeback_metadata_last),
    .flush(state_failed),
    .busy(writeback_busy_raw),.done(writeback_done),.error(writeback_error),
    .wr_req,.wr_start,.wr_granted,.wr_base_addr,.wr_row_stride,.wr_rows_to_write,
    .wr_burst_len_m1,.src_wdata,.src_wmask,.src_wvalid,.src_wready,.wr_done(write_response_done_q),.wr_error(write_response_error_q));
  // 倒数表使用完整精度的静态常量，同步读取阶段保存当前分母对应的数值。
  assign avg_reciprocal[0]='0;
  for (genvar denominator=1;denominator<=POOL_MAX_TAPS;denominator++) begin : g_avg_reciprocal
    localparam logic [AVG_SCALE_BITS:0] RECIPROCAL =
      (AVG_SCALE_BITS+1)'(((64'd1 << AVG_SCALE_BITS) + denominator - 1) / denominator);
    assign avg_reciprocal[denominator]=RECIPROCAL;
  end
  // AVG_START 的前一拍已保持分母，同步读取结果在原乘法采样边沿消费。
  always_ff @(posedge clk) begin
    avg_reciprocal_data <= avg_reciprocal[valid_taps];
  end
  assign pool_response_fire = state==POOL_LOAD_WAIT && rd_valid[0];

  always_comb begin
    add_multiplier = add_stage==0 ? c.add.input1_multiplier :
                     add_stage==1 ? c.add.input2_multiplier : c.add.output_multiplier;
    // 公共左移量合入输入除数，保留完整定点商，每级只执行一次最近偶数舍入。
    add_right = add_stage==0 ? 6'(31-c.add.input1_shift-c.add.left_shift) :
                add_stage==1 ? 6'(31-c.add.input2_shift-c.add.left_shift) :
                               6'(31-c.add.output_shift);
  end
  assign dw_group_last = compute_index + TILE_INDEX_W'(PE_COUNT) >= TILE_INDEX_W'(active);
  assign dw_issue_fire = state_dw_execute && !window_response_fault && dw_in_bounds && input_ready[read_bank] && weight_data_ready;
  assign dw_tap_advance = state_dw_execute && (!dw_in_bounds || (dw_issue_fire && dw_group_last));
  // 最后一个通道组的 PE 结果可在完成边沿直接写入快照。
  assign dw_snapshot_fire = state_dw_finish && !dw_snapshot_vld;
  assign quant_req_valid = SHARED_QUANT_ENABLE && dw_snapshot_vld && dw_snapshot_data_ready &&
      !dw_result_reserved[dw_quant_next_slot] && !state_failed;
  assign quant_req_tag = dw_quant_next_slot;
  assign quant_req_offset = c.output_offset;
  assign quant_req_minimum = c.activation_min;
  assign quant_req_maximum = c.activation_max;
  for (genvar lane=0;lane<TILE;lane++) begin : g_quant_request_mask
    assign quant_req_mask[lane] = active_lane_mask[lane];
  end
  assign dw_shared_fire = quant_req_valid && quant_req_ready;
  assign dw_quant_start = SHARED_QUANT_ENABLE ? dw_shared_fire :
      dw_snapshot_vld && dw_snapshot_data_ready && !dw_quant_input_active &&
      !dw_result_reserved[dw_quant_next_slot] && !state_failed;
  assign dw_quant_last_issue = SHARED_QUANT_ENABLE ? dw_shared_fire :
      dw_quant_input_active && q_issue+1'b1>=q_count;
  assign dw_quant_complete = SHARED_QUANT_ENABLE ? quant_rsp_valid :
      depthwise && q_valid[6] && q_index[6]+1'b1>=q_count;
  assign dw_group_pending = dw_snapshot_vld || dw_quant_input_active || (|q_valid);
  assign dw_work_pending = dw_group_pending || (|dw_result_reserved) || (dw_shared_inflight!=0);
  assign pe_operand_en = dw_issue_fire || ((state == EXECUTE) && ((!vector_hadamard) || !writeback_busy));
  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_operand_select
    wire enabled=(TILE_INDEX_W+1)'(compute_index)+(TILE_INDEX_W+1)'(lane)<(TILE_INDEX_W+1)'(active);
    assign pe_a[lane]=enabled ? input_lane[lane] : 16'sd0;
    // 无效通道的 a 和 acc 已为零，各运算结果与 b 的取值无关。
    assign pe_b[lane]=depthwise ? 16'($signed(weight_lane[lane])) : rhs_lane[lane];
    // 同一通道连续发射时使用上一拍乘加结果，其余通道读取已提交的累加值。
    // 逐元素乘法的零累加值由 PE 在操作数接收边沿选择。
    assign pe_acc[lane]=!enabled ? 32'sd0 :
        (depthwise && dw_commit_vld && dw_commit_index==compute_index) ? pe_result[lane] : accum_lane[lane];
  end
  // 操作码与操作数共同等待写出允许，在统一 PE 内保存并计算。
  for (genvar lane = 0; lane < PE_COUNT; lane++) begin : g_pe
    logic pe_i_en;
    logic [2:0] pe_i_op;
    logic signed [15:0] pe_i_a;
    logic signed [15:0] pe_i_b;
    logic signed [31:0] pe_i_acc;
    logic signed [31:0] pe_o_result;

    assign pe_i_en = pe_operand_en;
    assign pe_i_op = pe_op;
    assign pe_i_a = pe_a[lane];
    assign pe_i_b = pe_b[lane];
    assign pe_i_acc = pe_acc[lane];
    assign pe_result[lane] = pe_o_result;
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_pe (
      .clk(clk), .i_en(pe_i_en), .i_op(pe_i_op), .i_a(pe_i_a), .i_b(pe_i_b),
      .i_acc(pe_i_acc), .o_result(pe_o_result)
    );
  end

  logic [ADD_INDEX_WIDTH-1:0] add_next_input_index;
  assign add_next_input_index = ADD_INDEX_WIDTH'(compute_index)+ADD_INDEX_WIDTH'(1);
  assign add_first_lhs = p_input_bank_storage ? add_input_saved : input_buf[0][7:0];
  assign add_next_lhs = p_input_bank_storage ? add_input_saved :
      input_buf[INPUT_INDEX_W'(add_next_input_index)][7:0];
  assign add_rhs = rhs_buf[ADD_INDEX_WIDTH'(compute_index)][7:0];
  // 有效 S8 操作数加上 [-127,128] 内的偏移，结果范围为 [-255,255]。
  assign add_first_lhs_offset = $signed({add_first_lhs[7],add_first_lhs})+$signed(c.add.input1_offset[8:0]);
  assign add_next_lhs_offset = $signed({add_next_lhs[7],add_next_lhs})+$signed(c.add.input1_offset[8:0]);
  assign add_rhs_offset = $signed({add_rhs[7],add_rhs})+$signed(c.add.input2_offset[8:0]);
  // 加载、舍入和求和周期分别准备下一次乘法操作数。
  // 输出缩放阶段所需的和也保存在同一个寄存器中。
  always_ff @(posedge clk) begin
    if(state==LOAD_WAIT && load_kind==LD_B && read_done_q && add_s8)
      add_operand<=32'(add_first_lhs_offset);
    else if(state==ADD_ROUND_WAIT && add_stage==0)
      add_operand<=32'(add_rhs_offset);
    else if(state==ADD_SUM)
      add_operand<=add_input_sum;
    else if(state==ADD_STORE && !writeback_busy && compute_index+1<active)
      add_operand<=32'(add_next_lhs_offset);
  end

  // 标量量化、平均池化和向量归约共用累加数组的串行读取端口。
  always_comb begin
    serial_acc_read_index = quant_index;
    if (depthwise) begin
      serial_acc_read_index = q_issue;
    end else if (!spatial) begin
      serial_acc_read_index = state == VECTOR_REDUCE ?
          reduce_index + TILE_INDEX_W'(1) : '0;
    end
  end
  assign serial_acc_read_data = acc_buf[32'(serial_acc_read_index)];
  // 指数值采用单写入、单读取的普通数组，计算通道保存独立的工作累加值。
  always_ff @(posedge clk) begin
    if (rst_n && soft_exp_write_valid) soft_exp_memory[soft_exp_write_index] <= soft_lut_data;
  end
  assign softmax_i_exp_rdata = soft_exp_memory[soft_exp_index];

  assign reduce_alu_i_lhs = reduce_acc;
  // 归约期间缓冲区保持稳定，提前一拍读取下一项并保存完整 INT32 操作数。
  assign reduce_alu_i_rhs = reduce_rhs_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) reduce_rhs_q <= '0;
    else if (state == VECTOR_NEXT && !vector_has_more && !vector_hadamard && !add_s8)
      reduce_rhs_q <= serial_acc_read_data;
    else if (state == VECTOR_REDUCE && reduce_index + 1 < TILE)
      reduce_rhs_q <= serial_acc_read_data;
  end
  assign reduce_alu_i_max = vector_max;
  assign reduce_alu_i_min = vector_min;
  // 当前索引在本周期提供操作数，加法与有符号极值比较共用归约单元。
  vector_reduce_alu u_reduce_alu (
    .clk(clk), .i_lhs(reduce_alu_i_lhs), .i_rhs(reduce_alu_i_rhs),
    .i_max(reduce_alu_i_max), .i_min(reduce_alu_i_min), .o_result(reduce_next)
  );
  assign avg_pool_sum = avg_sum_q;
  assign avg_negated_sum = $unsigned(-avg_pool_sum);
  assign avg_residual_next = $signed({2'b00,avg_numerator_q}) - $signed({1'b0,avg_check_q});
  assign avg_unsigned_magnitude = avg_pool_sum<0 ?
      avg_negated_sum : $unsigned(avg_pool_sum);
  assign avg_input_magnitude=32'(avg_unsigned_magnitude);
  assign avg_overestimate=avg_residual_q[AVG_SCALE_BITS+1];
  assign avg_twice_remainder={avg_remainder_q,1'b0};
  assign avg_done=state==AVG_WAIT && avg_phase==4'd10;
  always_ff @(posedge clk) begin
    // 累加项在 QUANT_INIT 保存，下一周期准备绝对值并启动倒数乘法。
    if (state==QUANT_INIT && avg_pool)
      avg_sum_q<=serial_acc_read_data[POOL_SUM_WIDTH-1:0];
    if (state==AVG_START && !avg_power_two) begin
      avg_numerator_q<=AVG_SCALE_BITS'(avg_input_magnitude);
      avg_phase<=0;
    end else if (state==AVG_WAIT) begin
      if (avg_phase==1) avg_estimate_q<=8'(multiplier_product >> AVG_SCALE_BITS);
      if (avg_phase==4) avg_check_q<=(AVG_SCALE_BITS+1)'(multiplier_product);
      if (avg_phase==5) avg_residual_q<=avg_residual_next;
      // 向上取整的倒数可使商增加一；修正后的余数小于 valid_taps，
      // 因而可由 TAP_COUNT_W 位完整保存。
      if (avg_phase==6) begin
        avg_quotient_q<=avg_estimate_q-8'(avg_overestimate);
        avg_remainder_q<=TAP_COUNT_W'(avg_residual_q)+
            (avg_overestimate ? valid_taps : TAP_COUNT_W'(0));
      end
      if (avg_phase==7) begin
        avg_magnitude_q<=avg_quotient_q+8'(
            avg_twice_remainder>{1'b0,valid_taps} ||
            (avg_twice_remainder=={1'b0,valid_taps} && avg_quotient_q[0]));
      end
      // 符号恢复与激活范围比较分处两个寄存阶段，保存完整九位结果。
      if (avg_phase==8) begin
        avg_signed_q <= avg_negative ? -$signed({1'b0,avg_magnitude_q}) :
            $signed({1'b0,avg_magnitude_q});
      end
      avg_phase<=avg_phase+1'b1;
    end
  end

  assign multiplier_a=avg_pool ?
      (state==AVG_START ? $signed(32'(avg_input_magnitude)) : $signed({24'd0,avg_estimate_q})) :
      add_s8 ? add_operand : softmax_s8 ? soft_mul_a : q_accumulator;
  assign multiplier_b=avg_pool ?
      (state==AVG_START ? $signed(32'(avg_reciprocal_data)) : $signed(32'(valid_taps))) :
      add_s8 ? add_multiplier : softmax_s8 ? soft_mul_b : q_multiplier;
  vector_scalar_multiplier u_scalar_multiplier (
    .clk(clk),.a(multiplier_a),.b(multiplier_b),.product(multiplier_product));
  assign soft_lut_req_ready=state==SOFT_LUT_REQ && rd_granted;
  assign soft_lut_rsp_valid=state==SOFT_LUT_WAIT && read_done_q;
  vector_softmax #(.MAX_DEPTH(TILE),.MULTIPLIER_LATENCY(2),
      .INPUT_REGISTERED(p_input_bank_storage)) u_softmax (
    .clk,.rst_n,.start(state==SOFT_START),.depth(c.length),.ready(soft_ready),.done(soft_done),.error(soft_error),
    .input_index(soft_input_index),.input_data(p_input_bank_storage ? input_softmax_data : 8'(input_buf[32'(soft_input_index)])),
    .lut_req_valid(soft_lut_req_valid),.lut_req_ready(soft_lut_req_ready),.lut_index(soft_lut_index),
    .lut_rsp_valid(soft_lut_rsp_valid),.lut_rsp_data(soft_lut_data),.lut_rsp_error(read_error_q),
    .exp_we(soft_exp_we),.exp_index(soft_exp_index),.exp_rdata(softmax_i_exp_rdata),
`ifdef NPU_SIM_ASSERT
    .exp_wdata(soft_exp_data),
`else
    .exp_wdata(),
`endif
    .out_we(soft_out_we),.out_index(soft_out_index),.out_data(soft_out_data),
    .mul_a(soft_mul_a),.mul_b(soft_mul_b),.mul_product(multiplier_product)
  );

  // 指数与输出字节的写入资格及下标先保存一拍，数据由已有结果寄存器保持。
  // 下一边沿提交存储，后续归一化和写回准备使用完整结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      soft_exp_write_valid <= 1'b0;
      soft_out_write_valid <= 1'b0;
    end else begin
      soft_exp_write_valid <= softmax_s8 && soft_exp_we;
      soft_out_write_valid <= softmax_s8 && soft_out_we;
    end
  end
  always_ff @(posedge clk) begin
    if (softmax_s8 && soft_exp_we) begin
      soft_exp_write_index <= soft_exp_index;
    end
    if (softmax_s8 && soft_out_we) begin
      soft_out_write_index <= soft_out_index;
    end
  end

  // 乘法器已完成的输出直接进入舍入输入寄存器，乘积与移位量同拍保存。
  assign rounding_input = avg_pool ? $signed(64'(serial_acc_read_data)) : multiplier_product;
  assign rounding_amount = add_s8 ? add_right : avg_pool ? avg_shift : q_right[2];
  vector_round_shift #(.REGISTER_MIDDLE(1'b1),.REGISTER_INPUT(1'b1)) u_rounding (
    .clk(clk),.value(rounding_input),.amount(rounding_amount),.result(rounding_result),.floor_value(rounding_floor));
  // 加法限幅在现有舍入保存边沿准备偏移候选，其余限幅保持各自输入周期。
  assign activation_i_quantized_value = q_rounded;
  assign activation_i_add_rounding_value = rounding_result;
  assign activation_i_average_floor = rounding_floor[7:0];
  assign activation_i_average_rounded = rounding_result[7:0];
  assign activation_i_average_divided = avg_signed_q;
  assign activation_cfg_output_offset = c.output_offset;
  assign activation_cfg_bounds[0] = c.activation_min;
  assign activation_cfg_bounds[1] = c.activation_max;
  assign q_clamped_data = activation_o_result[0];
  assign add_clamped = activation_o_result[1];
  assign avg_power_result = activation_o_result[2];
  assign avg_div_result = activation_o_result[3];
  vector_activation_stage u_activation (
    .clk(clk),
    .cfg_output_offset(activation_cfg_output_offset),
    .cfg_minimum(activation_cfg_bounds[0]),
    .cfg_maximum(activation_cfg_bounds[1]),
    .i_quantized_value(activation_i_quantized_value),
    .i_add_rounding_value(activation_i_add_rounding_value),
    .i_average_floor(activation_i_average_floor),
    .i_average_rounded(activation_i_average_rounded),
    .i_average_divided(activation_i_average_divided),
    .o_result(activation_o_result)
  );

  // 标量限幅先保存字节结果，存储写使能仅选择已经完成的数值。
  always_ff @(posedge clk) begin
    if (state == ADD_CLAMP) serial_clamped_q <= add_clamped[7:0];
    else if (state == AVG_POWER_CLAMP) serial_clamped_q <= avg_power_result[7:0];
    else if (state == AVG_WAIT && avg_phase == 4'd9) serial_clamped_q <= avg_div_result[7:0];
  end

  // 串行结果共用字节数据选择，每个存储项仅保留地址使能和并行结果选择。
  assign result_background_write = soft_out_write_valid;
  assign result_background_index = TILE_INDEX_W'(soft_out_write_index);
  always_comb begin
    result_serial_write = 1'b0;
    result_serial_index = '0;
    result_serial_data = '0;
    case (state)
      ADD_STORE: begin
        result_serial_write = !writeback_busy && compute_index<TILE_INDEX_W'(active);
        result_serial_index = compute_index;
        result_serial_data = serial_clamped_q;
      end
      AVG_POWER_STORE: begin
        result_serial_write = 1'b1;
        result_serial_index = quant_index;
        result_serial_data = serial_clamped_q;
      end
      AVG_WAIT: begin
        result_serial_write = avg_done;
        result_serial_index = quant_index;
        result_serial_data = serial_clamped_q;
      end
      default: ;
    endcase
  end
  // 字节写入来源互斥，各存储项共用已按写使能选择的数据。
  assign result_common_data = ({8{soft_out_write_valid}} & soft_out_data) |
      ({8{result_serial_write}} & result_serial_data);
  // 串行字节的地址、数据和有效位同拍保存，下一边沿写入累加存储。
  // 输出元数据在最后一个字节提交时准备，写回模块随后读取完整结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) result_byte_pending <= 1'b0;
    else if (state_failed) result_byte_pending <= 1'b0;
    else result_byte_pending <= result_background_write || result_serial_write;
  end
  always_ff @(posedge clk) begin
    result_byte_index <= result_serial_write ? result_serial_index : result_background_index;
    result_byte_data <= result_common_data;
  end
  // 极值池化按 PE 组提交，读取选择器与计算通道共用。
  // 每个通道保留一个八位限幅器，当前组全部字节在同一边沿写入。
  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_pool_lane_clamp
    wire [7:0] value = accum_lane[lane][7:0];
    (* use_dsp = "simd" *) wire [8:0] minimum_difference, maximum_difference;
    // 九位补码差值包含八位输入的完整数值范围，符号位直接给出次序。
    assign minimum_difference = {value[7],value} - {c.activation_min[7],c.activation_min[7:0]};
    assign maximum_difference = {c.activation_max[7],c.activation_max[7:0]} - {value[7],value};
    assign pool_lane_value[lane] = minimum_difference[8] ? c.activation_min[7:0] :
        maximum_difference[8] ? c.activation_max[7:0] : value;
  end
  for (genvar entry=0;entry<TILE;entry++) begin : g_result_write
    localparam int LANE_INDEX = entry % PE_COUNT;
    localparam int GROUP_BASE = entry - LANE_INDEX;
    logic write_enable;
    logic [7:0] write_value;
    logic byte_selected, pool_selected;
    logic [7:0] pool_value;
    assign byte_selected = result_byte_pending && result_byte_index == TILE_INDEX_W'(entry);
    assign pool_selected = state_pool_store && active_lane_mask[entry] &&
        compute_pool_group[GROUP_BASE/PE_COUNT];
    assign pool_value = pool_lane_value[LANE_INDEX];
    assign write_enable = byte_selected || pool_selected;
    assign write_value = ({8{result_byte_pending}} & result_byte_data) | ({8{pool_selected}} & pool_value);
    assign result_write_enable[entry] = write_enable;
    assign result_write_data[entry] = write_value;
  end

  // 已提交通道读取累加存储，当前返回的通道组直接读取 PE 结果。
  for (genvar entry=0;entry<TILE;entry++) begin : g_snapshot_value
    localparam int p_lane_index = entry % PE_COUNT;
    localparam int p_group_base = entry - p_lane_index;
    logic result_selected;
    assign result_selected = dw_commit_vld && active_lane_mask[entry] &&
        dw_commit_index == TILE_INDEX_W'(p_group_base);
    assign dw_snapshot_value[entry] = result_selected ? pe_result[p_lane_index] : acc_buf[entry];
  end
  // 完成的像素保存到独立存储行，同一边沿将累加存储初始化为下一像素的偏置。
  // 量化读取快照期间，PE 继续累加下一像素。
  if (SHARED_STORAGE_ENABLE) begin : g_shared_snapshot
    logic read_pending, data_valid;
    assign o_ps_write_en = rst_n && dw_snapshot_fire && !i_storage_error;
    assign o_ps_write_addr = '0;
    assign o_ps_read_en = read_pending && !state_failed && !i_storage_error;
    assign o_ps_read_addr = '0;
    assign dw_snapshot_data_ready = data_valid || i_ps_read_valid;
    for (genvar entry=0;entry<TILE;entry++) begin : g_channel
      assign o_ps_write_data[32*entry+:32] = dw_snapshot_value[entry];
      assign quant_req_accumulator[entry] = $signed(i_ps_read_data[32*entry+:32]);
    end
    // 写入和读取分处相邻周期；RAM 输出保持有效，直到该像素的量化输入全部接收。
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        read_pending <= 1'b0;
        data_valid <= 1'b0;
      end else if ((state==CHECK) || state_failed) begin
        read_pending <= 1'b0;
        data_valid <= 1'b0;
      end else begin
        if (o_ps_read_en) read_pending <= 1'b0;
        if (i_ps_read_valid) data_valid <= 1'b1;
        if (dw_snapshot_fire) begin
          read_pending <= 1'b1;
          data_valid <= 1'b0;
        end
        if (dw_quant_last_issue) data_valid <= 1'b0;
      end
    end
  end else begin : g_private_snapshot
    logic signed [31:0] dw_snapshot[TILE];
    assign dw_snapshot_data_ready = 1'b1;
    assign quant_req_accumulator = dw_snapshot;
    assign o_ps_read_en = 1'b0;
    assign o_ps_read_addr = '0;
    assign o_ps_write_en = 1'b0;
    assign o_ps_write_addr = '0;
    assign o_ps_write_data = '0;
    for (genvar entry=0;entry<TILE;entry++) begin : g_channel
      always_ff @(posedge clk) begin
        if (dw_snapshot_fire) dw_snapshot[entry] <= dw_snapshot_value[entry];
      end
    end
  end

  // 两组结果存储分别保存正在量化和等待写出的像素，写出接收后释放该组。
  for (genvar slot=0;slot<2;slot++) begin : g_dw_result_slot
    for (genvar entry=0;entry<TILE;entry++) begin : g_channel
      always_ff @(posedge clk) begin
        if (rst_n && depthwise && !state_failed) begin
          if (SHARED_QUANT_ENABLE && quant_rsp_valid && quant_rsp_tag==1'(slot) && entry<dw_result_count[slot])
            dw_result_bytes[slot][entry] <= quant_rsp_data[entry];
          else if (!SHARED_QUANT_ENABLE && q_valid[6] &&
                   dw_quant_slot_pipe[6]==1'(slot) && q_index[6]==TILE_INDEX_W'(entry))
            dw_result_bytes[slot][entry] <= q_clamped_q;
        end
      end
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      dw_commit_vld <= 1'b0;
      dw_commit_index <= '0;
      dw_snapshot_vld <= 1'b0;
      dw_snapshot_address <= '0;
      dw_snapshot_last <= 1'b0;
      dw_quant_input_active <= 1'b0;
      dw_quant_slot <= 1'b0;
      dw_quant_next_slot <= 1'b0;
      dw_quant_slot_pipe <= '0;
      dw_result_reserved <= '0;
      dw_result_ready <= '0;
      dw_result_last <= '0;
      dw_result_read_slot <= 1'b0;
      for (int slot=0;slot<2;slot++) begin
        dw_result_address[slot] <= '0;
        dw_result_count[slot] <= '0;
      end
    end else if ((state==CHECK) || state_failed) begin
      dw_commit_vld <= 1'b0;
      dw_snapshot_vld <= 1'b0;
      dw_quant_input_active <= 1'b0;
      dw_quant_slot <= 1'b0;
      dw_quant_next_slot <= 1'b0;
      dw_quant_slot_pipe <= '0;
      dw_result_reserved <= '0;
      dw_result_ready <= '0;
      dw_result_read_slot <= 1'b0;
    end else begin
      dw_commit_vld <= dw_issue_fire;
      if (dw_issue_fire) dw_commit_index <= compute_index;
      if (dw_snapshot_fire) begin
        dw_snapshot_vld <= 1'b1;
        dw_snapshot_address <= write_origin_next;
        dw_snapshot_last <= position_is_last;
      end
      if (dw_quant_last_issue) begin
        dw_quant_input_active <= 1'b0;
        dw_snapshot_vld <= 1'b0;
      end
      if (dw_quant_start) begin
        dw_quant_input_active <= !SHARED_QUANT_ENABLE;
        dw_quant_slot <= dw_quant_next_slot;
        dw_result_reserved[dw_quant_next_slot] <= 1'b1;
        dw_result_address[dw_quant_next_slot] <= dw_snapshot_address;
        dw_result_count[dw_quant_next_slot] <= active;
        dw_result_last[dw_quant_next_slot] <= dw_snapshot_last;
        dw_quant_next_slot <= !dw_quant_next_slot;
      end
      if (depthwise && !SHARED_QUANT_ENABLE) dw_quant_slot_pipe <= {dw_quant_slot_pipe[5:0],dw_quant_slot};
      if (dw_quant_complete)
        dw_result_ready[SHARED_QUANT_ENABLE ? quant_rsp_tag : dw_quant_slot_pipe[6]] <= 1'b1;
      if (dw_result_accept) begin
        dw_result_ready[dw_result_read_slot] <= 1'b0;
        dw_result_reserved[dw_result_read_slot] <= 1'b0;
        dw_result_read_slot <= !dw_result_read_slot;
      end
    end
  end

  // 错误处理仍等待共享流水中的已接收请求返回，随后才允许切换任务。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) dw_shared_inflight <= '0;
    else if (state==CHECK) dw_shared_inflight <= '0;
    else if (SHARED_QUANT_ENABLE) begin
      case ({dw_shared_fire,quant_rsp_valid})
        2'b10: dw_shared_inflight <= dw_shared_inflight+1'b1;
        2'b01: dw_shared_inflight <= dw_shared_inflight-1'b1;
        default: ;
      endcase
    end
  end

endmodule

`default_nettype wire
