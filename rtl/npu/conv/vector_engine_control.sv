// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 保存任务状态、循环位置和计算阶段，处理完成、错误与排空。
module vector_engine_control #(
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
  localparam int p_active_count_w = $clog2(p_tile + 1),
  localparam int p_tap_limit = p_max_taps > p_pool_max_taps ? p_max_taps : p_pool_max_taps,
  localparam int p_tap_count_w = $clog2(p_tap_limit + 1),
  localparam int p_tile_index_w = $clog2(p_tile + p_pe_count + 1),
  localparam int p_input_index_w = $clog2(p_dma_size),
  localparam int p_pool_group_count=(p_tile+p_pe_count-1)/p_pe_count
) (
  input wire logic clk,
  input wire logic rst_n,
  input wire logic i_start,
  input wire vector_engine_pkg::vector_engine_cfg_t i_cfg,
  output logic o_ready,
  output logic o_done_valid,
  input wire logic i_done_ready,
  output logic [1:0] o_error,
  output logic o_dma_cfg_valid,
  input wire logic i_dma_cfg_ready,
  input wire logic i_win_rsp_last,
  input wire logic i_win_busy,
  input wire logic signed [31:0] i_quant_req_accumulator [p_tile],
  input wire logic i_storage_error,
  output logic o_rd_req,
  input wire logic i_rd_granted,
  input wire logic i_rd_done,
  input wire logic i_rd_error,
  input wire logic [p_bus_width-1:0] i_rd_raw_data,
  input wire logic i_rd_raw_valid,
  input wire logic i_wr_done,
  input wire logic i_wr_error,
  output logic o_read_done_q,
  output logic o_read_error_q,
  output logic o_write_response_done_q,
  output logic o_write_response_error_q,
  output vector_engine_control_pkg::state_t o_state,
  output logic o_state_failed,
  output logic o_state_compute_commit,
  output logic o_state_pool_store,
  output logic o_state_dw_execute,
  output logic o_state_weight_read_phase,
  output logic o_state_weight_zero_address,
  output logic o_state_output_init,
  output logic o_state_vector_init,
  output logic o_state_dw_finish,
  output logic o_window_fetch_phase,
  output vector_engine_control_pkg::load_t o_load_kind,
  output vector_engine_pkg::vector_engine_cfg_t o_c,
  output logic o_spatial,
  output logic o_depthwise,
  output logic o_binary_vector,
  output logic o_add_s8,
  output logic o_softmax_s8,
  output logic o_byte_output,
  output logic o_avg_pool,
  output logic o_max_pool,
  output logic o_min_pool,
  output logic o_vector_max,
  output logic o_vector_min,
  output logic o_vector_hadamard,
  input wire logic [31:0] i_channels,
  output logic [31:0] o_position,
  output logic [15:0] o_channel_base,
  output logic [p_active_count_w-1:0] o_active,
  output logic [p_tile-1:0] o_active_lane_mask,
  output logic [p_tap_count_w-1:0] o_taps,
  output logic [15:0] o_ox,
  output logic [15:0] o_oy,
  input wire logic [15:0] i_fetch_ox_next,
  input wire logic [15:0] i_ox_next,
  input wire logic [15:0] i_oy_next,
  output logic [p_tap_count_w-1:0] o_kx,
  output logic [p_tap_count_w-1:0] o_kernel_last_column,
  output logic [p_tap_count_w-1:0] o_tap,
  output logic [p_tap_count_w-1:0] o_load_tap,
  output logic [p_tap_count_w-1:0] o_valid_taps,
  output logic [31:0] o_vector_offset,
  input wire logic [31:0] i_channel_remaining,
  input wire logic [15:0] i_channel_next,
  input wire logic i_channel_has_more,
  input wire logic [p_active_count_w-1:0] i_vector_next_active,
  input wire logic i_vector_has_more,
  output logic [p_tile_index_w-1:0] o_compute_index,
  output logic [p_tile_index_w-1:0] o_quant_index,
  output logic [p_tile_index_w-1:0] o_reduce_index,
  output logic [p_pool_group_count-1:0] o_compute_pool_group,
  input wire logic i_compute_group_last_q,
  input wire logic i_pool_pixel_has_more_q,
  output logic [31:0] o_fetch_tap_offset,
  output logic [31:0] o_position_offset,
  output logic [31:0] o_pool_byte_offset,
  input wire logic [31:0] i_fetch_position_next,
  input wire logic [31:0] i_fetch_tap_offset_next,
  input wire logic [31:0] i_position_offset_next,
  input wire logic [31:0] i_pool_byte_offset_next,
  input wire logic [31:0] i_vector_offset_next,
  input wire logic i_weight_row_last_fire,
  input wire logic i_parameter_row_last_fire,
  input wire logic i_parameter_three_rows,
  input wire logic i_parameter_two_rows,
  input wire logic [p_tap_count_w-1:0] i_weight_tap_nxt,
  input wire logic [p_tap_count_w-1:0] i_weight_tap_after_next,
  output logic [p_tap_count_w-1:0] o_weight_prefetch_q,
  input wire logic i_tap_last_wide,
  output logic o_tap_last_modulo,
  input wire logic i_tap_last_config,
  input wire logic i_tap_last_zero,
  input wire logic i_tap_last_increment,
  output logic [2:0] o_pe_op,
  output logic [1:0] o_add_stage,
  output logic signed [31:0] o_add_scaled_a,
  output logic signed [63:0] o_add_rounded,
  output logic signed [31:0] o_reduce_acc,
  input wire logic signed [31:0] i_reduce_next,
  output logic signed [33:0] o_input_y,
  output logic signed [33:0] o_input_x,
  output logic signed [33:0] o_input_origin_x,
  output logic signed [33:0] o_input_origin_y,
  input wire logic i_param_bad,
  input wire logic i_dw_in_bounds,
  input wire logic [15:0] i_output_last_column,
  input wire logic i_global_pool,
  input wire logic [63:0] i_kernel_count,
  input wire logic [63:0] i_position_count,
  input wire logic i_config_check_ready,
  input wire logic i_config_check_done,
  input wire logic i_config_check_error,
  output logic signed [31:0] o_q_accumulator,
  output logic signed [31:0] o_q_multiplier,
  output logic signed [63:0] o_q_rounded,
  input wire logic signed [31:0] i_q_clamped_data,
  output logic [6:0] o_q_valid,
  output logic [7:0] o_q_clamped_q,
  output logic [p_tile_index_w-1:0] o_q_issue,
  output logic [p_tile_index_w-1:0] o_q_count,
  input wire logic i_dw_issue_fire,
  input wire logic i_dw_group_last,
  input wire logic i_dw_tap_advance,
  input wire logic i_dw_snapshot_fire,
  input wire logic i_dw_quant_start,
  input wire logic i_dw_quant_input_active,
  input wire logic i_dw_group_pending,
  input wire logic i_dw_work_pending,
  output logic [31:0] o_write_origin,
  output logic [31:0] o_write_total,
  input wire logic i_writeback_ready,
  input wire logic i_writeback_done,
  input wire logic i_writeback_error,
  input wire logic i_writeback_busy,
  output logic o_avg_negative,
  input wire logic i_avg_power_two,
  input wire logic i_avg_done,
  output logic o_input_range_mode,
  output logic [1:0] o_read_bank,
  output logic [1:0] o_wf_bank,
  input wire logic [1:0] i_input_bank_mask,
  input wire logic [3:0] i_input_ready,
  input wire logic [3:0] i_input_reserved,
  input wire logic i_input_drain_ready,
  output logic [31:0] o_window_received,
  input wire logic [31:0] i_window_count_o_sum,
  input wire logic i_window_response_fire,
  input wire logic i_window_request_fire,
  input wire logic i_window_fetch_advance,
  input wire logic i_window_response_fault,
  output logic [31:0] o_fetch_position,
  output logic [15:0] o_fetch_ox,
  output logic signed [33:0] o_fetch_x,
  output logic signed [33:0] o_fetch_y,
  output logic signed [33:0] o_fetch_origin_x,
  output logic signed [33:0] o_fetch_origin_y,
  input wire logic [33:0] i_coordinate_step_o_value [8],
  input wire logic i_next_window_valid_q,
  input wire logic signed [33:0] i_next_window_x,
  input wire logic signed [33:0] i_next_window_y,
  input wire logic i_kernel_column_end,
  input wire logic [15:0] i_padding_x_negative,
  input wire logic [15:0] i_padding_y_negative,
  input wire logic i_soft_ready,
  input wire logic i_soft_done,
  input wire logic [1:0] i_soft_error,
  input wire logic i_soft_lut_req_valid,
  input wire logic [7:0] i_soft_lut_index,
  output logic [7:0] o_soft_lut_index_q,
  output logic [31:0] o_soft_lut_data,
  output logic [p_tap_count_w-1:0] o_pool_taps_remaining,
  output logic [p_input_index_w:0] o_pool_pixels,
  output logic [p_input_index_w:0] o_pool_received,
  output logic [p_input_index_w:0] o_pool_pixel,
  output logic [p_input_index_w:0] o_pool_elements,
  input wire logic [p_input_index_w:0] i_pool_next_elements,
  input wire logic [p_input_index_w:0] i_pool_next_pixels,
  output logic [p_input_index_w:0] o_pool_input_index,
  output logic [p_input_index_w:0] o_pool_row_remaining,
  input wire logic i_pool_response_fire,
  input wire logic [p_bus_shift:0] i_pool_beat_count,
  input wire logic i_pool_read_complete_saved,
  input wire logic [31:0] i_position_next,
  input wire logic [31:0] i_write_origin_next,
  input wire logic signed [31:0] i_serial_acc_read_data,
  input wire logic signed [31:0] i_params_o_multiplier,
  input wire logic [5:0] i_params_o_right_shift,
  input wire logic signed [63:0] i_rounding_result,
  output logic [5:0] o_q_right [3],
  output logic [p_tile_index_w-1:0] o_q_index [7]
);

  logic start;
  vector_engine_pkg::vector_engine_cfg_t cfg;
  logic ready;
  logic done_valid;
  logic done_ready;
  logic [1:0] error;
  logic dma_cfg_valid;
  logic dma_cfg_ready;
  logic win_rsp_last;
  logic win_busy;
  logic signed [31:0] quant_req_accumulator [p_tile];
  logic rd_req;
  logic rd_granted;
  logic rd_done;
  logic rd_error;
  logic [p_bus_width-1:0] rd_raw_data;
  logic rd_raw_valid;
  logic wr_done;
  logic wr_error;
  logic read_done_q;
  logic read_error_q;
  logic write_response_done_q;
  logic write_response_error_q;
  vector_engine_control_pkg::state_t state;
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
  vector_engine_control_pkg::load_t load_kind;
  vector_engine_pkg::vector_engine_cfg_t c;
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
  logic [15:0] channel_base;
  logic [p_active_count_w-1:0] active;
  logic [p_tile-1:0] active_lane_mask;
  logic [p_tap_count_w-1:0] taps;
  logic [15:0] ox;
  logic [15:0] oy;
  logic [15:0] fetch_ox_next;
  logic [15:0] ox_next;
  logic [15:0] oy_next;
  logic [p_tap_count_w-1:0] kx;
  logic [p_tap_count_w-1:0] kernel_last_column;
  logic [p_tap_count_w-1:0] tap;
  logic [p_tap_count_w-1:0] load_tap;
  logic [p_tap_count_w-1:0] valid_taps;
  logic [31:0] vector_offset;
  logic [31:0] channel_remaining;
  logic [15:0] channel_next;
  logic channel_has_more;
  logic [p_active_count_w-1:0] vector_next_active;
  logic vector_has_more;
  logic [p_tile_index_w-1:0] compute_index;
  logic [p_tile_index_w-1:0] quant_index;
  logic [p_tile_index_w-1:0] reduce_index;
  logic [p_pool_group_count-1:0] compute_pool_group;
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
  logic weight_row_last_fire;
  logic parameter_row_last_fire;
  logic parameter_three_rows;
  logic parameter_two_rows;
  logic [p_tap_count_w-1:0] weight_tap_nxt;
  logic [p_tap_count_w-1:0] weight_tap_after_next;
  logic [p_tap_count_w-1:0] weight_prefetch_q;
  logic tap_last_wide;
  logic tap_last_modulo;
  logic tap_last_config;
  logic tap_last_zero;
  logic tap_last_increment;
  logic [2:0] pe_op;
  logic [1:0] add_stage;
  logic signed [31:0] add_scaled_a;
  logic signed [63:0] add_rounded;
  logic signed [31:0] reduce_acc;
  logic signed [31:0] reduce_next;
  logic signed [17:0] input_y;
  logic signed [17:0] input_x;
  logic signed [17:0] input_origin_x;
  logic signed [17:0] input_origin_y;
  logic param_bad;
  logic dw_in_bounds;
  logic [15:0] output_last_column;
  logic global_pool;
  logic [63:0] kernel_count;
  logic [63:0] position_count;
  logic config_check_ready;
  logic config_check_done;
  logic config_check_error;
  logic signed [31:0] q_accumulator;
  logic signed [31:0] q_multiplier;
  logic signed [63:0] q_rounded;
  logic signed [31:0] q_clamped_data;
  logic [6:0] q_valid;
  logic [7:0] q_clamped_q;
  logic [p_tile_index_w-1:0] q_issue;
  logic [p_tile_index_w-1:0] q_count;
  logic dw_issue_fire;
  logic dw_group_last;
  logic dw_tap_advance;
  logic dw_snapshot_fire;
  logic dw_quant_start;
  logic dw_quant_input_active;
  logic dw_group_pending;
  logic dw_work_pending;
  logic [31:0] write_origin;
  logic [31:0] write_total;
  logic writeback_ready;
  logic writeback_done;
  logic writeback_error;
  logic writeback_busy;
  logic avg_negative;
  logic avg_power_two;
  logic avg_done;
  logic input_range_mode;
  logic [1:0] read_bank;
  logic [1:0] wf_bank;
  logic [1:0] input_bank_mask;
  logic [3:0] input_ready;
  logic [3:0] input_reserved;
  (* keep = 1 *) logic input_drain_ready;
  logic [31:0] window_received;
  logic [31:0] window_count_o_sum;
  logic window_response_fire;
  logic window_request_fire;
  logic window_fetch_advance;
  logic window_response_fault;
  logic [31:0] fetch_position;
  logic [15:0] fetch_ox;
  logic signed [17:0] fetch_x;
  logic signed [17:0] fetch_y;
  logic signed [17:0] fetch_origin_x;
  logic signed [17:0] fetch_origin_y;
  logic [33:0] coordinate_step_o_value [8];
  logic next_window_valid_q;
  logic signed [33:0] next_window_x;
  logic signed [33:0] next_window_y;
  logic kernel_column_end;
  logic [15:0] padding_x_negative;
  logic [15:0] padding_y_negative;
  logic soft_ready;
  logic soft_done;
  logic [1:0] soft_error;
  logic soft_lut_req_valid;
  logic [7:0] soft_lut_index;
  logic [7:0] soft_lut_index_q;
  logic [31:0] soft_lut_data;
  logic [p_tap_count_w-1:0] pool_taps_remaining;
  logic [p_input_index_w:0] pool_pixels;
  logic [p_input_index_w:0] pool_received;
  logic [p_input_index_w:0] pool_pixel;
  logic [p_input_index_w:0] pool_elements;
  logic [p_input_index_w:0] pool_next_elements;
  logic [p_input_index_w:0] pool_next_pixels;
  logic [p_input_index_w:0] pool_input_index;
  logic [p_input_index_w:0] pool_row_remaining;
  logic pool_response_fire;
  logic [p_bus_shift:0] pool_beat_count;
  logic pool_read_complete_saved;
  logic [31:0] position_next;
  logic [31:0] write_origin_next;
  logic signed [31:0] serial_acc_read_data;
  logic signed [31:0] params_o_multiplier;
  logic [5:0] params_o_right_shift;
  logic signed [63:0] rounding_result;
  logic [5:0] q_right [3];
  logic [p_tile_index_w-1:0] q_index [7];

  // 端口与内部保存值之间使用显式连续连接。
  assign start = i_start;
  assign cfg = i_cfg;
  assign o_ready = ready;
  assign o_done_valid = done_valid;
  assign done_ready = i_done_ready;
  assign o_error = error;
  assign o_dma_cfg_valid = dma_cfg_valid;
  assign dma_cfg_ready = i_dma_cfg_ready;
  assign win_rsp_last = i_win_rsp_last;
  assign win_busy = i_win_busy;
  assign quant_req_accumulator = i_quant_req_accumulator;
  assign o_rd_req = rd_req;
  assign rd_granted = i_rd_granted;
  assign rd_done = i_rd_done;
  assign rd_error = i_rd_error;
  assign rd_raw_data = i_rd_raw_data;
  assign rd_raw_valid = i_rd_raw_valid;
  assign wr_done = i_wr_done;
  assign wr_error = i_wr_error;
  assign o_read_done_q = read_done_q;
  assign o_read_error_q = read_error_q;
  assign o_write_response_done_q = write_response_done_q;
  assign o_write_response_error_q = write_response_error_q;
  assign o_state = state;
  assign o_state_failed = state_failed;
  assign o_state_compute_commit = state_compute_commit;
  assign o_state_pool_store = state_pool_store;
  assign o_state_dw_execute = state_dw_execute;
  assign o_state_weight_read_phase = state_weight_read_phase;
  assign o_state_weight_zero_address = state_weight_zero_address;
  assign o_state_output_init = state_output_init;
  assign o_state_vector_init = state_vector_init;
  assign o_state_dw_finish = state_dw_finish;
  assign o_window_fetch_phase = window_fetch_phase;
  assign o_load_kind = load_kind;
  assign o_c = c;
  assign o_spatial = spatial;
  assign o_depthwise = depthwise;
  assign o_binary_vector = binary_vector;
  assign o_add_s8 = add_s8;
  assign o_softmax_s8 = softmax_s8;
  assign o_byte_output = byte_output;
  assign o_avg_pool = avg_pool;
  assign o_max_pool = max_pool;
  assign o_min_pool = min_pool;
  assign o_vector_max = vector_max;
  assign o_vector_min = vector_min;
  assign o_vector_hadamard = vector_hadamard;
  assign channels = i_channels;
  assign o_position = position;
  assign o_channel_base = channel_base;
  assign o_active = active;
  assign o_active_lane_mask = active_lane_mask;
  assign o_taps = taps;
  assign o_ox = ox;
  assign o_oy = oy;
  assign fetch_ox_next = i_fetch_ox_next;
  assign ox_next = i_ox_next;
  assign oy_next = i_oy_next;
  assign o_kx = kx;
  assign o_kernel_last_column = kernel_last_column;
  assign o_tap = tap;
  assign o_load_tap = load_tap;
  assign o_valid_taps = valid_taps;
  assign o_vector_offset = vector_offset;
  assign channel_remaining = i_channel_remaining;
  assign channel_next = i_channel_next;
  assign channel_has_more = i_channel_has_more;
  assign vector_next_active = i_vector_next_active;
  assign vector_has_more = i_vector_has_more;
  assign o_compute_index = compute_index;
  assign o_quant_index = quant_index;
  assign o_reduce_index = reduce_index;
  assign o_compute_pool_group = compute_pool_group;
  assign compute_group_last_q = i_compute_group_last_q;
  assign pool_pixel_has_more_q = i_pool_pixel_has_more_q;
  assign o_fetch_tap_offset = fetch_tap_offset;
  assign o_position_offset = position_offset;
  assign o_pool_byte_offset = pool_byte_offset;
  assign fetch_position_next = i_fetch_position_next;
  assign fetch_tap_offset_next = i_fetch_tap_offset_next;
  assign position_offset_next = i_position_offset_next;
  assign pool_byte_offset_next = i_pool_byte_offset_next;
  assign vector_offset_next = i_vector_offset_next;
  assign weight_row_last_fire = i_weight_row_last_fire;
  assign parameter_row_last_fire = i_parameter_row_last_fire;
  assign parameter_three_rows = i_parameter_three_rows;
  assign parameter_two_rows = i_parameter_two_rows;
  assign weight_tap_nxt = i_weight_tap_nxt;
  assign weight_tap_after_next = i_weight_tap_after_next;
  assign o_weight_prefetch_q = weight_prefetch_q;
  assign tap_last_wide = i_tap_last_wide;
  assign o_tap_last_modulo = tap_last_modulo;
  assign tap_last_config = i_tap_last_config;
  assign tap_last_zero = i_tap_last_zero;
  assign tap_last_increment = i_tap_last_increment;
  assign o_pe_op = pe_op;
  assign o_add_stage = add_stage;
  assign o_add_scaled_a = add_scaled_a;
  assign o_add_rounded = add_rounded;
  assign o_reduce_acc = reduce_acc;
  assign reduce_next = i_reduce_next;
  assign o_input_y = 34'(input_y);
  assign o_input_x = 34'(input_x);
  assign o_input_origin_x = 34'(input_origin_x);
  assign o_input_origin_y = 34'(input_origin_y);
  assign param_bad = i_param_bad;
  assign dw_in_bounds = i_dw_in_bounds;
  assign output_last_column = i_output_last_column;
  assign global_pool = i_global_pool;
  assign kernel_count = i_kernel_count;
  assign position_count = i_position_count;
  assign config_check_ready = i_config_check_ready;
  assign config_check_done = i_config_check_done;
  assign config_check_error = i_config_check_error;
  assign o_q_accumulator = q_accumulator;
  assign o_q_multiplier = q_multiplier;
  assign o_q_rounded = q_rounded;
  assign q_clamped_data = i_q_clamped_data;
  assign o_q_valid = q_valid;
  assign o_q_clamped_q = q_clamped_q;
  assign o_q_issue = q_issue;
  assign o_q_count = q_count;
  assign dw_issue_fire = i_dw_issue_fire;
  assign dw_group_last = i_dw_group_last;
  assign dw_tap_advance = i_dw_tap_advance;
  assign dw_snapshot_fire = i_dw_snapshot_fire;
  assign dw_quant_start = i_dw_quant_start;
  assign dw_quant_input_active = i_dw_quant_input_active;
  assign dw_group_pending = i_dw_group_pending;
  assign dw_work_pending = i_dw_work_pending;
  assign o_write_origin = write_origin;
  assign o_write_total = write_total;
  assign writeback_ready = i_writeback_ready;
  assign writeback_done = i_writeback_done;
  assign writeback_error = i_writeback_error;
  assign writeback_busy = i_writeback_busy;
  assign o_avg_negative = avg_negative;
  assign avg_power_two = i_avg_power_two;
  assign avg_done = i_avg_done;
  assign o_input_range_mode = input_range_mode;
  assign o_read_bank = read_bank;
  assign o_wf_bank = wf_bank;
  assign input_bank_mask = i_input_bank_mask;
  assign input_ready = i_input_ready;
  assign input_reserved = i_input_reserved;
  assign input_drain_ready = i_input_drain_ready;
  assign o_window_received = window_received;
  assign window_count_o_sum = i_window_count_o_sum;
  assign window_response_fire = i_window_response_fire;
  assign window_request_fire = i_window_request_fire;
  assign window_fetch_advance = i_window_fetch_advance;
  assign window_response_fault = i_window_response_fault;
  assign o_fetch_position = fetch_position;
  assign o_fetch_ox = fetch_ox;
  assign o_fetch_x = 34'(fetch_x);
  assign o_fetch_y = 34'(fetch_y);
  assign o_fetch_origin_x = 34'(fetch_origin_x);
  assign o_fetch_origin_y = 34'(fetch_origin_y);
  assign coordinate_step_o_value = i_coordinate_step_o_value;
  assign next_window_valid_q = i_next_window_valid_q;
  assign next_window_x = i_next_window_x;
  assign next_window_y = i_next_window_y;
  assign kernel_column_end = i_kernel_column_end;
  assign padding_x_negative = i_padding_x_negative;
  assign padding_y_negative = i_padding_y_negative;
  assign soft_ready = i_soft_ready;
  assign soft_done = i_soft_done;
  assign soft_error = i_soft_error;
  assign soft_lut_req_valid = i_soft_lut_req_valid;
  assign soft_lut_index = i_soft_lut_index;
  assign o_soft_lut_index_q = soft_lut_index_q;
  assign o_soft_lut_data = soft_lut_data;
  assign o_pool_taps_remaining = pool_taps_remaining;
  assign o_pool_pixels = pool_pixels;
  assign o_pool_received = pool_received;
  assign o_pool_pixel = pool_pixel;
  assign o_pool_elements = pool_elements;
  assign pool_next_elements = i_pool_next_elements;
  assign pool_next_pixels = i_pool_next_pixels;
  assign o_pool_input_index = pool_input_index;
  assign o_pool_row_remaining = pool_row_remaining;
  assign pool_response_fire = i_pool_response_fire;
  assign pool_beat_count = i_pool_beat_count;
  assign pool_read_complete_saved = i_pool_read_complete_saved;
  assign position_next = i_position_next;
  assign write_origin_next = i_write_origin_next;
  assign serial_acc_read_data = i_serial_acc_read_data;
  assign params_o_multiplier = i_params_o_multiplier;
  assign params_o_right_shift = i_params_o_right_shift;
  assign rounding_result = i_rounding_result;
  assign o_q_right = q_right;
  assign o_q_index = q_index;


  logic [p_tap_count_w-1:0] ky;
  logic [1:0] parameter_rows_remaining;
  logic add_multiply_wait;
  logic param_bad_seen;
  logic load_completion_error;
  logic q_active;
  logic [p_tap_count_w-1:0] fetch_tap;
  logic [p_tap_count_w-1:0] fetch_kx;
  logic [p_tap_count_w-1:0] pool_offset;
  logic [p_input_index_w:0] pool_row_columns;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      read_done_q <= 1'b0;
      read_error_q <= 1'b0;
      write_response_done_q <= 1'b0;
      write_response_error_q <= 1'b0;
    end else begin
      read_done_q <= rd_done;
      write_response_done_q <= wr_done;
      if (rd_done) read_error_q <= rd_error;
      if (wr_done) write_response_error_q <= wr_error;
    end
  end

  function automatic logic [p_active_count_w+p_tile-1:0] active_count_value(
      input logic [p_active_count_w-1:0] next_active);
    active_count_value[p_active_count_w-1:0]=next_active;
    for (int lane=0;lane<p_tile;lane++) begin
      active_count_value[p_active_count_w+lane]=(32'(lane)<next_active);
    end
  endfunction
  function automatic logic [p_tile_index_w+p_pool_group_count-1:0] compute_index_value(
      input logic [p_tile_index_w-1:0] next_index);
    compute_index_value[p_tile_index_w-1:0]=next_index;
    for (int group=0;group<p_pool_group_count;group++) begin
      compute_index_value[p_tile_index_w+group]=(next_index==p_tile_index_w'(group*p_pe_count));
    end
  endfunction
  // 运算类型和描述符同时保存，数据通路直接使用已寄存的选择信号。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      spatial <= 1'b1;
      depthwise <= 1'b1;
      byte_output <= 1'b1;
      add_s8 <= 1'b0;
      softmax_s8 <= 1'b0;
      binary_vector <= 1'b0;
      avg_pool <= 1'b0;
      max_pool <= 1'b0;
      min_pool <= 1'b0;
      vector_max <= 1'b0;
      vector_min <= 1'b0;
      vector_hadamard <= 1'b0;
      pe_op <= vector_engine_pkg::PE_MADD;
    end else if (state == vector_engine_control_pkg::IDLE && start) begin
      spatial <= cfg.op <= vector_engine_pkg::MINPOOL_S8;
      depthwise <= cfg.op == vector_engine_pkg::DW_S8;
      add_s8 <= cfg.op == vector_engine_pkg::ADD_S8;
      softmax_s8 <= cfg.op == vector_engine_pkg::SOFTMAX_S8;
      byte_output <= cfg.op <= vector_engine_pkg::MINPOOL_S8 || cfg.op == vector_engine_pkg::ADD_S8 || cfg.op == vector_engine_pkg::SOFTMAX_S8;
      binary_vector <= cfg.op == vector_engine_pkg::VEC_DOT || cfg.op == vector_engine_pkg::VEC_HADAMARD || cfg.op == vector_engine_pkg::ADD_S8;
      avg_pool <= cfg.op == vector_engine_pkg::AVGPOOL_S8;
      max_pool <= cfg.op == vector_engine_pkg::MAXPOOL_S8;
      min_pool <= cfg.op == vector_engine_pkg::MINPOOL_S8;
      vector_max <= cfg.op == vector_engine_pkg::VEC_MAX;
      vector_min <= cfg.op == vector_engine_pkg::VEC_MIN;
      vector_hadamard <= cfg.op == vector_engine_pkg::VEC_HADAMARD;
      case (cfg.op)
        vector_engine_pkg::AVGPOOL_S8, vector_engine_pkg::VEC_SUM: pe_op <= vector_engine_pkg::PE_SUM;
        vector_engine_pkg::MAXPOOL_S8, vector_engine_pkg::VEC_MAX: pe_op <= vector_engine_pkg::PE_MAX;
        vector_engine_pkg::MINPOOL_S8, vector_engine_pkg::VEC_MIN: pe_op <= vector_engine_pkg::PE_MIN;
        vector_engine_pkg::VEC_HADAMARD: pe_op <= vector_engine_pkg::PE_MUL;
        default: pe_op <= vector_engine_pkg::PE_MADD;
      endcase
    end
  end
  // 核列上界在配置检查成功的边沿保存，运行状态保护其有效期。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else begin
      case (state)
        vector_engine_control_pkg::CHECK_WAIT: begin
          if (config_check_done) begin
            if (config_check_error) begin
            end else begin
              kernel_last_column <= p_tap_count_w'(c.image.kernel_w) - p_tap_count_w'(1);
            end
          end
        end
        default: begin end
      endcase
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::IDLE); c<='0; error<=0; load_kind<=vector_engine_control_pkg::LD_WEIGHT;
      parameter_rows_remaining<=0;
      taps<=0; tap_last_modulo<=1'b0;weight_prefetch_q<=p_tap_count_w'(1); {active_lane_mask,active}<=active_count_value(0); channel_base<=0; position<=0;
      ox<=0;oy<=0;kx<=0;ky<=0;tap<=0;load_tap<=0;valid_taps<=0;
      input_x<=0;input_y<=0;input_origin_x<=0;input_origin_y<=0;
      vector_offset<=0;{compute_pool_group,compute_index}<=compute_index_value(0);quant_index<=0;reduce_index<=0;
      reduce_acc<=0; param_bad_seen<=0;load_completion_error<=1'b0;
      add_stage<=0;add_multiply_wait<=0;add_scaled_a<=0;add_rounded<=0;
      q_accumulator<=0;
      q_multiplier<=0;
      q_rounded<=0;
      for (int stage=0; stage<3; stage++) begin
        q_right[stage]<='0;
      end
      q_valid<=0;
      for (int stage=0; stage<7; stage++) begin
        q_index[stage]<='0;
      end
      q_clamped_q<=0;
      q_issue<=0;
      q_count<=0;
      q_active<=0;
      read_bank<=0;wf_bank<=0;
      window_received<=0;soft_lut_data<=0;soft_lut_index_q<=0;avg_negative<=0;
      fetch_position<=0;fetch_tap<=0;fetch_ox<=0;fetch_kx<=0;
      fetch_x<=0;fetch_y<=0;fetch_origin_x<=0;fetch_origin_y<=0;
      write_origin<=0;write_total<=0;
      input_range_mode<=0;
      pool_offset<=0;pool_taps_remaining<=0;pool_pixels<=0;pool_received<=0;pool_pixel<=0;
      pool_elements<=0;pool_row_columns<=0;pool_row_remaining<=0;pool_input_index<=0;
      fetch_tap_offset<=0;position_offset<=0;pool_byte_offset<=0;
    end else begin
      // 量化流水独立于空间位置状态运行，连续像素可在同一流水内交叠。
      if (depthwise && !p_shared_quant_enable && state!=vector_engine_control_pkg::IDLE && !state_failed && state!=vector_engine_control_pkg::DONE) begin
        q_active <= dw_quant_input_active || (|q_valid) || dw_quant_start;
        q_valid <= {q_valid[5:0],dw_quant_input_active};
        if (dw_quant_start) begin
          q_count <= p_tile_index_w'(active);
          q_issue <= '0;
        end else if (dw_quant_input_active) begin
          q_accumulator <= quant_req_accumulator[$clog2(p_tile)'(q_issue)];
          q_multiplier <= params_o_multiplier;
          q_right[0] <= params_o_right_shift;
          q_index[0] <= q_issue;
          q_issue <= q_issue+1'b1;
        end
        for (int stage=1; stage<3; stage++) begin
          if (q_valid[stage-1]) q_right[stage] <= q_right[stage-1];
        end
        for (int stage=1; stage<7; stage++) begin
          if (q_valid[stage-1]) q_index[stage] <= q_index[stage-1];
        end
        if (q_valid[4]) q_rounded <= rounding_result;
        if (q_valid[5]) q_clamped_q <= q_clamped_data[7:0];
      end
      if (softmax_s8) begin
        if (state==vector_engine_control_pkg::SOFT_LUT_WAIT && rd_raw_valid) soft_lut_data<=rd_raw_data[31:0];
      end
      if (weight_row_last_fire) load_tap<=load_tap+1'b1;
      if (parameter_row_last_fire && parameter_rows_remaining!=0) begin
        parameter_rows_remaining<=parameter_rows_remaining-1'b1;
        load_kind<=load_kind==vector_engine_control_pkg::LD_BIAS ? vector_engine_control_pkg::LD_MULT : vector_engine_control_pkg::LD_SHIFT;
      end

      if (window_fetch_advance) begin
        if (fetch_tap+1==taps) begin
          fetch_position<=fetch_position_next;fetch_tap<=0;fetch_tap_offset<=0;fetch_kx<=0;
          if (fetch_ox==output_last_column) begin
            fetch_ox<=0;
            fetch_origin_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});
            fetch_origin_y<=18'($signed(coordinate_step_o_value[7]));
            fetch_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});
            fetch_y<=18'($signed(coordinate_step_o_value[7]));
          end else begin
            fetch_ox<=fetch_ox_next;
            fetch_origin_x<=18'($signed(coordinate_step_o_value[6]));
            fetch_x<=18'($signed(coordinate_step_o_value[6]));fetch_y<=fetch_origin_y;
          end
        end else begin
          fetch_tap<=fetch_tap+1;fetch_tap_offset<=fetch_tap_offset_next;
          if (fetch_kx==kernel_last_column) begin
            fetch_kx<=0;fetch_x<=fetch_origin_x;fetch_y<=18'($signed(coordinate_step_o_value[5]));
          end else begin
            fetch_kx<=fetch_kx+1;fetch_x<=18'($signed(coordinate_step_o_value[4]));
          end
        end
      end
      if (window_request_fire) begin
        wf_bank<=(wf_bank+1'b1)&input_bank_mask;
      end
      if (window_response_fire) begin
        window_received<=window_count_o_sum;
        if(win_rsp_last) begin
          window_received<=0;
        end
      end
      if (param_bad) param_bad_seen<=1;
      if (pool_response_fire) begin
        pool_received<=pool_received+(p_input_index_w+1)'(pool_beat_count);
        if (pool_row_remaining<=p_bus_bytes) pool_row_remaining<=pool_row_columns;
        else pool_row_remaining<=pool_row_remaining-(p_input_index_w+1)'(p_bus_bytes);
      end
      case (state)
        vector_engine_control_pkg::IDLE: if (start) begin
          c<=cfg; error<=0; {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::CHECK);
          input_range_mode<=0;
        end
        vector_engine_control_pkg::CHECK: begin
          q_active<=0;q_valid<=0;
          read_bank<=0;wf_bank<=0;window_received<=0;
          param_bad_seen<=0;
          if (config_check_ready) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::CHECK_WAIT);
        end
        vector_engine_control_pkg::CHECK_WAIT: if (config_check_done) begin
          if (config_check_error) begin error<=2'b01;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);end
          else begin
            taps<=32'(kernel_count);tap_last_modulo<=tap_last_config;
            weight_prefetch_q<=tap_last_config ? '0 : weight_tap_nxt;channel_base<=0;input_range_mode<=global_pool;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::CONFIGURE);
          end
        end
        vector_engine_control_pkg::CONFIGURE: if (dma_cfg_ready) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(spatial ? vector_engine_control_pkg::TILE_INIT : vector_engine_control_pkg::VECTOR_INIT);
        vector_engine_control_pkg::TILE_INIT: begin
          {active_lane_mask,active}<=active_count_value(p_active_count_w'(channel_remaining<p_tile ? channel_remaining : 32'(p_tile)));
          position<=0;position_offset<=0;ox<=0;oy<=0;load_tap<=0;load_kind<=vector_engine_control_pkg::LD_WEIGHT;
          input_origin_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});input_origin_y<=$signed({{2{(|c.image.pad_top)}}, padding_y_negative});
          read_bank<=0;wf_bank<=0;window_received<=0;
          fetch_position<=0;fetch_tap<=0;fetch_tap_offset<=0;fetch_ox<=0;fetch_kx<=0;
          fetch_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});fetch_y<=$signed({{2{(|c.image.pad_top)}}, padding_y_negative});
          fetch_origin_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});fetch_origin_y<=$signed({{2{(|c.image.pad_top)}}, padding_y_negative});
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(depthwise ? vector_engine_control_pkg::LOAD_REQ : vector_engine_control_pkg::OUTPUT_INIT);
        end
        vector_engine_control_pkg::LOAD_REQ: if (rd_granted) begin
          parameter_rows_remaining<=
              load_kind==vector_engine_control_pkg::LD_BIAS && parameter_three_rows ? 2'd2 :
              load_kind==vector_engine_control_pkg::LD_MULT && parameter_two_rows ? 2'd1 : 2'd0;
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_WAIT);
        end
        vector_engine_control_pkg::LOAD_WAIT: if (read_done_q) begin
          load_completion_error<=read_error_q;
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_VERIFY);
        end
        vector_engine_control_pkg::LOAD_VERIFY: begin
          if (load_completion_error || param_bad_seen) begin error<=2'b10;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);end
          else case (load_kind)
            vector_engine_control_pkg::LD_WEIGHT: begin load_kind<=c.bias_base==0 ? vector_engine_control_pkg::LD_MULT : vector_engine_control_pkg::LD_BIAS;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_REQ);end
            vector_engine_control_pkg::LD_BIAS: begin load_kind<=vector_engine_control_pkg::LD_MULT;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_REQ);end
            vector_engine_control_pkg::LD_MULT: begin load_kind<=vector_engine_control_pkg::LD_SHIFT;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_REQ);end
            vector_engine_control_pkg::LD_SHIFT: {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::OUTPUT_INIT);
            vector_engine_control_pkg::LD_A: if (binary_vector) begin load_kind<=vector_engine_control_pkg::LD_B;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_REQ);end
              else begin {compute_pool_group,compute_index}<=compute_index_value(0);{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(softmax_s8 ? vector_engine_control_pkg::SOFT_START : vector_engine_control_pkg::EXECUTE);end
            vector_engine_control_pkg::LD_B: begin
              {compute_pool_group,compute_index}<=compute_index_value(0);add_stage<=0;
              {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(add_s8 ? vector_engine_control_pkg::ADD_MULT : vector_engine_control_pkg::EXECUTE);
            end
            default: begin error<=2'b10;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);end
          endcase
        end
        vector_engine_control_pkg::OUTPUT_INIT: begin
          tap<=0;tap_last_modulo<=tap_last_zero;weight_prefetch_q<=tap_last_zero ? '0 : p_tap_count_w'(1);kx<=0;ky<=0;valid_taps<=0;{compute_pool_group,compute_index}<=compute_index_value(0);
          input_x<=input_origin_x;input_y<=input_origin_y;
          if (global_pool) begin
            valid_taps<=taps;pool_offset<=0;pool_taps_remaining<=taps;pool_byte_offset<=0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::POOL_LOAD_PREP);
          end else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(depthwise ? vector_engine_control_pkg::DW_EXECUTE : vector_engine_control_pkg::TAP_CHECK);
        end
        vector_engine_control_pkg::DW_EXECUTE: begin
          if (dw_issue_fire) begin
            if (!dw_group_last) {compute_pool_group,compute_index}<=compute_index_value(compute_index+p_tile_index_w'(p_pe_count));
            else begin
              {compute_pool_group,compute_index}<=compute_index_value('0);
              read_bank<=(read_bank+1'b1)&input_bank_mask;
            end
          end
          if (dw_tap_advance) begin
            if (tap_last_modulo) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DW_FINISH);
            else begin
              tap<=weight_tap_nxt;tap_last_modulo<=tap_last_increment;weight_prefetch_q<=tap_last_increment ? '0 : weight_tap_after_next;
              input_x<=18'(next_window_x);input_y<=18'(next_window_y);
              if (kernel_column_end) begin kx<=0;ky<=ky+1'b1;end
              else kx<=kx+1'b1;
            end
          end
        end
        vector_engine_control_pkg::DW_FINISH: if (dw_snapshot_fire) begin
          {compute_pool_group,compute_index}<=compute_index_value('0);tap<='0;tap_last_modulo<=tap_last_zero;weight_prefetch_q<=tap_last_zero ? '0 : p_tap_count_w'(1);kx<='0;ky<='0;
          if (position_next<32'(position_count)) begin
            position<=position_next;position_offset<=position_offset_next;
            if (ox==output_last_column) begin
              ox<=0;oy<=oy_next;
              input_origin_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});
              input_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});
              input_origin_y<=18'($signed(coordinate_step_o_value[3]));
              input_y<=18'($signed(coordinate_step_o_value[3]));
            end else begin
              ox<=ox_next;
              input_origin_x<=18'($signed(coordinate_step_o_value[2]));
              input_x<=18'($signed(coordinate_step_o_value[2]));
              input_y<=input_origin_y;
            end
            {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DW_EXECUTE);
          end else if (channel_has_more) begin
            channel_base<=channel_next;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DRAIN_TILE);
          end else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DRAIN);
        end
        vector_engine_control_pkg::POOL_LOAD_PREP: begin
          pool_pixels<=pool_next_pixels;pool_received<=0;pool_pixel<=0;pool_input_index<=0;
          pool_elements<=pool_next_elements;
          pool_row_columns<=channels==active ? pool_next_elements : (p_input_index_w+1)'(active);
          pool_row_remaining<=channels==active ? pool_next_elements : (p_input_index_w+1)'(active);
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::POOL_LOAD_REQ);
        end
        vector_engine_control_pkg::POOL_LOAD_REQ: if (rd_granted) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::POOL_LOAD_WAIT);
        vector_engine_control_pkg::POOL_LOAD_WAIT: if (read_done_q) begin
          if (read_error_q || !pool_read_complete_saved) begin error<=2'b10;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);end
          else begin {compute_pool_group,compute_index}<=compute_index_value(0);{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::POOL_LOAD_DRAIN);end
        end
        vector_engine_control_pkg::POOL_LOAD_DRAIN: {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::EXECUTE);
        vector_engine_control_pkg::TAP_CHECK: if (dw_in_bounds) begin
            valid_taps<=valid_taps+1;{compute_pool_group,compute_index}<=compute_index_value(0);
            {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(input_ready[read_bank] ? vector_engine_control_pkg::EXECUTE : vector_engine_control_pkg::WINDOW_WAIT);
          end
          else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::TAP_NEXT);
        vector_engine_control_pkg::WINDOW_WAIT: if (input_ready[read_bank]) begin {compute_pool_group,compute_index}<=compute_index_value(0);{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::EXECUTE);end
        vector_engine_control_pkg::EXECUTE: if (!vector_hadamard || !writeback_busy) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::EXECUTE_COMMIT);
        vector_engine_control_pkg::EXECUTE_COMMIT: begin
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::EXECUTE);
          if (!compute_group_last_q) {compute_pool_group,compute_index}<=compute_index_value(compute_index+32'(p_pe_count));
          else if (global_pool) begin
            pool_byte_offset<=pool_byte_offset_next;
            if (pool_pixel_has_more_q) begin
              pool_pixel<=pool_pixel+1;pool_input_index<=pool_input_index+(p_input_index_w+1)'(active);
              {compute_pool_group,compute_index}<=compute_index_value(0);
            end
            else if (pool_taps_remaining>pool_pixels) begin
              pool_offset<=pool_offset+pool_pixels;
              pool_taps_remaining<=pool_taps_remaining-p_tap_count_w'(pool_pixels);
              {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::POOL_LOAD_PREP);
            end
            else begin quant_index<=0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::QUANT_INIT);end
          end
          else if (spatial) begin
            read_bank<=(read_bank+1'b1)&input_bank_mask;{compute_pool_group,compute_index}<=compute_index_value(0);
            if (tap_last_wide) begin quant_index<=0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::QUANT_INIT);end
            else begin
              tap<=weight_tap_nxt;tap_last_modulo<=tap_last_increment;weight_prefetch_q<=tap_last_increment ? '0 : weight_tap_after_next;input_x<=18'(next_window_x);input_y<=18'(next_window_y);
              if (kernel_column_end) begin kx<=0;ky<=ky+1;end else kx<=kx+1;
              if (next_window_valid_q) begin
                valid_taps<=valid_taps+1;
                {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(input_ready[(read_bank+1'b1)&input_bank_mask] ? vector_engine_control_pkg::EXECUTE : vector_engine_control_pkg::WINDOW_WAIT);
              end else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::TAP_CHECK);
            end
          end
          else if (vector_hadamard) begin
            write_origin<=write_origin_next;write_total<=active<<2;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::WRITE_PREP);
          end else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::VECTOR_NEXT);
        end
        vector_engine_control_pkg::ADD_MULT: begin
          add_multiply_wait<=0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_DRAIN);
        end
        vector_engine_control_pkg::ADD_DRAIN: if (add_multiply_wait) begin
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_ROUND);
        end else add_multiply_wait<=1;
        vector_engine_control_pkg::ADD_ROUND: {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_ROUND_WAIT);
        vector_engine_control_pkg::ADD_ROUND_WAIT: begin
          if (add_stage==0) begin
            add_scaled_a<=32'(rounding_result);
            add_stage<=1;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_MULT);
          end else if (add_stage==1) begin
            add_rounded<=rounding_result;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_SUM);
          end else begin
            add_rounded<=rounding_result;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_CLAMP);
          end
        end
        vector_engine_control_pkg::ADD_SUM: begin
          add_stage<=2;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_MULT);
        end
        vector_engine_control_pkg::ADD_CLAMP: {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_STORE);
        vector_engine_control_pkg::ADD_STORE: if (!writeback_busy) begin
          if (compute_index+1<active) begin
            {compute_pool_group,compute_index}<=compute_index_value(compute_index+1'b1);add_stage<=0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::ADD_MULT);
          end else begin
            write_origin<=write_origin_next;write_total<=active;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::WRITE_PREP);
          end
        end
        vector_engine_control_pkg::TAP_NEXT: if (tap_last_wide) begin quant_index<=0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::QUANT_INIT);end
          else begin
            tap<=weight_tap_nxt;tap_last_modulo<=tap_last_increment;weight_prefetch_q<=tap_last_increment ? '0 : weight_tap_after_next;input_x<=18'(next_window_x);input_y<=18'(next_window_y);
            if (kernel_column_end) begin kx<=0;ky<=ky+1;end else kx<=kx+1;
            {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::TAP_CHECK);
          end
        vector_engine_control_pkg::QUANT_INIT: begin
          if (!writeback_busy) begin
            if (avg_pool) begin
              if (valid_taps==0) begin error<=2'b01;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);end else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::AVG_START);
            end else begin
              {compute_pool_group,compute_index}<=compute_index_value('0);
              {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::POOL_STORE);
            end
          end
        end
        vector_engine_control_pkg::AVG_START: if (avg_power_two) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::AVG_POWER_DELAY);
          else begin avg_negative<=serial_acc_read_data<0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::AVG_WAIT);end
        vector_engine_control_pkg::AVG_POWER_DELAY: {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::AVG_POWER_CLAMP);
        vector_engine_control_pkg::AVG_POWER_CLAMP: {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::AVG_POWER_STORE);
        vector_engine_control_pkg::AVG_POWER_STORE: begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::AVG_START);end
          else begin write_origin<=write_origin_next;write_total<=active;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::WRITE_PREP);end
        end
        vector_engine_control_pkg::AVG_WAIT: if (avg_done) begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::QUANT_INIT);end
          else begin write_origin<=write_origin_next;
            write_total<=active;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::WRITE_PREP);end
        end
        vector_engine_control_pkg::POOL_STORE: begin
          if (32'(compute_index)+32'(p_pe_count) < active) begin
            {compute_pool_group,compute_index}<=compute_index_value(compute_index + p_tile_index_w'(p_pe_count));
          end else begin
            write_origin <= write_origin_next;
            write_total <= active;
            {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::WRITE_PREP);
          end
        end
        vector_engine_control_pkg::WRITE_PREP: if (writeback_ready) begin
          if (spatial) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::OUTPUT_NEXT);
          else if (vector_hadamard || add_s8) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::VECTOR_NEXT);
          else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DRAIN);
        end
        vector_engine_control_pkg::OUTPUT_NEXT: begin
          if (position_next<32'(position_count)) begin
            position<=position_next;position_offset<=position_offset_next;
            if (ox==output_last_column) begin
              ox<=0;oy<=oy_next;input_origin_x<=$signed({{2{(|c.image.pad_left)}}, padding_x_negative});
              input_origin_y<=18'($signed(coordinate_step_o_value[3]));
            end else begin
              ox<=ox_next;input_origin_x<=18'($signed(coordinate_step_o_value[2]));
            end
            {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::OUTPUT_INIT);
          end else if (channel_has_more) begin
            channel_base<=channel_next;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DRAIN_TILE);
          end
          else {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DRAIN);
        end
        // 每个结果槽保存所属通道数，共享量化与写回可跨通道组继续完成。
        vector_engine_control_pkg::DRAIN_TILE: if (!win_busy && input_reserved==0 && !q_active &&
                       (depthwise ? !dw_group_pending : !writeback_busy && !dw_work_pending))
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::TILE_INIT);
        vector_engine_control_pkg::DRAIN: if (!writeback_busy && !win_busy && input_reserved==0 && !q_active && !dw_work_pending && dma_cfg_ready)
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DONE);
        vector_engine_control_pkg::SOFT_START: if (soft_ready) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::SOFT_RUN);
        vector_engine_control_pkg::SOFT_RUN: if (soft_done) begin
          if (soft_error!=0) begin error<=soft_error;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);end
          else begin write_origin<=write_origin_next;write_total<=active;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::WRITE_PREP);end
        end else if (soft_lut_req_valid) begin
          soft_lut_data<=0;soft_lut_index_q<=soft_lut_index;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::SOFT_LUT_REQ);
        end
        vector_engine_control_pkg::SOFT_LUT_REQ: if (rd_granted) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::SOFT_LUT_WAIT);
        vector_engine_control_pkg::SOFT_LUT_WAIT: if (read_done_q) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::SOFT_RUN);
        vector_engine_control_pkg::VECTOR_INIT: begin
          vector_offset<=0;{active_lane_mask,active}<=active_count_value(p_active_count_w'(c.length<p_tile ? c.length : 32'(p_tile)));
          load_kind<=vector_engine_control_pkg::LD_A;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_REQ);
        end
        vector_engine_control_pkg::VECTOR_NEXT: if (vector_has_more) begin
          vector_offset<=vector_offset_next;
          {active_lane_mask,active}<=active_count_value(vector_next_active);
          load_kind<=vector_engine_control_pkg::LD_A;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::LOAD_REQ);
        end else if (vector_hadamard || add_s8) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DRAIN);
        else begin
          reduce_acc<=vector_max ? 32'sh8000_0000 : vector_min ? 32'sh7fff_ffff : 32'sd0;
          reduce_index<=0;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::VECTOR_REDUCE);
        end
        vector_engine_control_pkg::VECTOR_REDUCE: begin
          reduce_acc<=reduce_next;
          if (reduce_index+1<p_tile) reduce_index<=reduce_index+1;
          else begin write_origin<=write_origin_next;write_total<=4;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::WRITE_PREP);end
        end
        vector_engine_control_pkg::FAILED: if (input_drain_ready) begin
          q_active<=0;q_valid<=0;
          {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::DONE);
        end
        vector_engine_control_pkg::DONE: if (done_ready) {state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::IDLE);
        default: begin error<=2'b10;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);end
      endcase
      if ((writeback_done && writeback_error) ||
          window_response_fault) begin
        error<=2'b10;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);
      end
      if (p_shared_storage_enable && i_storage_error &&
          state!=vector_engine_control_pkg::IDLE && !state_failed && state!=vector_engine_control_pkg::DONE) begin
        error<=2'b10;{state_weight_zero_address,state_weight_read_phase,state_dw_execute,state_pool_store,state_output_init,state_vector_init,state_dw_finish,state_compute_commit,state_failed,window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=vector_engine_control_pkg::state_control_value(vector_engine_control_pkg::FAILED);
      end
    end
  end
endmodule

`default_nettype wire
