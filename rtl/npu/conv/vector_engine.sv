// SPDX-License-Identifier: Apache-2.0
// 根据描述符执行向量计算、量化 Add、深度卷积和池化。
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
  input logic clk, rst_n,
  input logic start,
  input vector_engine_pkg::vector_engine_cfg_t cfg,
  output logic ready, done_valid,
  input logic done_ready,
  output logic [1:0] error,

  output logic dma_cfg_valid,
  input logic dma_cfg_ready,
  output logic dma_conv_enable, dma_range_enable,
  output conv_im2col_pkg::conv_cfg_t dma_conv_cfg,
  output logic [31:0] dma_range_base [4],
  output logic [32:0] dma_range_end [4],

  output logic win_req_valid,
  input logic win_req_ready,
  output logic [31:0] win_req_p0,win_req_q0,win_req_cols,
  output logic [1:0] win_req_tag,
  input logic win_rsp_valid,
  output logic win_rsp_ready,
  input logic [1:0] win_rsp_tag,
  input logic [31:0] win_rsp_col,
  input logic signed [15:0] win_rsp_data[WINDOW_LANES],
  input logic [WINDOW_LANES-1:0] win_rsp_mask,
  input logic win_rsp_last,win_rsp_error,win_busy,

  // DW 请求预留结果缓冲，矩阵量化流水按标签返回全部有效通道。
  output logic quant_req_valid,
  input logic quant_req_ready = 1'b0,
  output logic quant_req_tag,
  output logic signed [31:0] quant_req_accumulator[TILE],
  output logic signed [31:0] quant_req_multiplier[TILE],
  output logic [5:0] quant_req_right[TILE],
  output logic [TILE-1:0] quant_req_mask,
  output logic signed [31:0] quant_req_offset, quant_req_minimum, quant_req_maximum,
  input logic quant_rsp_valid = 1'b0,
  input logic quant_rsp_tag = 1'b0,
  input logic signed [7:0] quant_rsp_data[TILE] = '{default:8'sd0},

  // 权重地址以 16 字节为单位，部分和地址以 64 字节为单位；读取在下一周期返回。
  output logic o_weight_read_en,
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_weight_read_addr,
  input logic i_weight_read_valid = 1'b0,
  input logic [127:0] i_weight_read_data = '0,
  output logic o_weight_write_en,
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_weight_write_addr,
  output logic [127:0] o_weight_write_data,
  output logic [15:0] o_weight_write_mask,
  output logic o_ps_read_en,
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_ps_read_addr,
  input logic i_ps_read_valid = 1'b0,
  input logic [511:0] i_ps_read_data = '0,
  output logic o_ps_write_en,
  output logic [SHARED_STORAGE_ADDR_WIDTH-1:0] o_ps_write_addr,
  output logic [511:0] o_ps_write_data,
  input logic i_storage_error = 1'b0,

  output logic rd_req, rd_start,
  input logic rd_granted,
  output logic rd_im2col,
  output logic [31:0] rd_p0, rd_q0, rd_base_addr, rd_row_stride,
  output logic [31:0] rd_rows_to_read, rd_valid_cols,
  output logic [7:0] rd_burst_len_m1,
  output logic rd_use_16bits,
  input logic rd_busy, rd_done, rd_error,
  input logic signed [15:0] rd_data [BUS_WIDTH/8],
  input logic rd_valid [BUS_WIDTH/8],
  input logic [$clog2(DMA_SIZE)-1:0] rd_col_base,
  input logic [BUS_WIDTH-1:0] rd_raw_data,
  input logic rd_raw_valid,

  output logic wr_req, wr_start,
  input logic wr_granted,
  output logic [31:0] wr_base_addr, wr_row_stride, wr_rows_to_write,
  output logic [7:0] wr_burst_len_m1,
  output logic [BUS_WIDTH-1:0] src_wdata,
  output logic [BUS_WIDTH/8-1:0] src_wmask,
  output logic src_wvalid,
  input logic src_wready, wr_busy, wr_done, wr_error
);
  import vector_engine_pkg::*;
  // 完成与错误在接口边界共同保存，数据仍在各自有效周期写入存储。
  logic read_done_q, read_error_q, write_response_done_q, write_response_error_q;
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

  localparam int BUS_BYTES=BUS_WIDTH/8;
  localparam int BUS_SHIFT=$clog2(BUS_BYTES);
  localparam int INPUT_BANKS=WINDOW_LANES>BUS_BYTES ? WINDOW_LANES : BUS_BYTES;
  typedef enum logic [5:0] {
    IDLE, CHECK, CONFIGURE, TILE_INIT, LOAD_REQ, LOAD_WAIT,
    OUTPUT_INIT, TAP_CHECK, WINDOW_WAIT, EXECUTE, TAP_NEXT,
    QUANT_INIT, AVG_START, AVG_WAIT, POOL_STORE, WRITE_PREP,
    OUTPUT_NEXT, VECTOR_INIT, VECTOR_NEXT, VECTOR_REDUCE, FAILED, DONE,
    ADD_MULT, ADD_DRAIN, ADD_ROUND, ADD_SUM, ADD_STORE,
    POOL_LOAD_PREP, POOL_LOAD_REQ, POOL_LOAD_WAIT,
    DRAIN, DRAIN_TILE, SOFT_START, SOFT_RUN, SOFT_LUT_REQ, SOFT_LUT_WAIT,
    CHECK_WAIT, QUANT_STREAM, EXECUTE_COMMIT, ADD_ROUND_WAIT, AVG_POWER_STORE, POOL_LOAD_DRAIN,
    DW_EXECUTE, DW_FINISH, ADD_CLAMP, AVG_POWER_DELAY, AVG_POWER_CLAMP, LOAD_VERIFY
  } state_t;
  typedef enum logic [2:0] {LD_WEIGHT, LD_BIAS, LD_MULT, LD_SHIFT, LD_A, LD_B, LD_LUT} load_t;
  // 对外握手标志与状态同时更新，状态保持时也保持这些寄存输出。
  function automatic logic [$bits(state_t)+4:0] state_control_value(input state_t next_state);
    state_control_value = {
        (next_state==OUTPUT_INIT || next_state==TAP_CHECK || next_state==WINDOW_WAIT || next_state==QUANT_STREAM || next_state==EXECUTE || next_state==EXECUTE_COMMIT || next_state==TAP_NEXT || next_state==QUANT_INIT || next_state==OUTPUT_NEXT || next_state==AVG_START || next_state==AVG_POWER_DELAY || next_state==AVG_POWER_CLAMP || next_state==AVG_POWER_STORE || next_state==AVG_WAIT || next_state==POOL_STORE || next_state==WRITE_PREP || next_state==DW_EXECUTE || next_state==DW_FINISH),
        next_state==CONFIGURE,
        next_state==LOAD_REQ || next_state==POOL_LOAD_REQ || next_state==SOFT_LUT_REQ,
        next_state==IDLE,
        next_state==DONE,
        next_state
    };
  endfunction
  state_t state;
  logic window_fetch_phase;
  load_t load_kind;
  vector_engine_cfg_t c;
  logic spatial, depthwise, binary_vector, add_s8, softmax_s8, byte_output;
  logic avg_pool, max_pool, min_pool, vector_max, vector_min, vector_hadamard;
  localparam int ACTIVE_COUNT_W = $clog2(TILE + 1);
  localparam int TAP_LIMIT = MAX_TAPS > POOL_MAX_TAPS ? MAX_TAPS : POOL_MAX_TAPS;
  localparam int TAP_COUNT_W = $clog2(TAP_LIMIT + 1);
  logic [31:0] channels, position;
  logic [15:0] channel_base;
  logic [ACTIVE_COUNT_W-1:0] active;
  logic [TAP_COUNT_W-1:0] taps;
  logic [15:0] ox, oy;
  (* use_dsp = "yes" *) logic [15:0] fetch_ox_next, ox_next, oy_next;
  assign ox_next = ox + 16'd1;
  assign oy_next = oy + 16'd1;
  logic [TAP_COUNT_W-1:0] kx,ky;
  logic [TAP_COUNT_W-1:0] kernel_last_column;
  logic [TAP_COUNT_W-1:0] tap, load_tap, valid_taps;
  localparam int TILE_INDEX_W = $clog2(TILE + PE_COUNT + 1);
  localparam int INPUT_INDEX_W = $clog2(DMA_SIZE);
  localparam int INPUT_STORED_ELEMENTS = PE_COUNT>=16 ? 4*TILE : 2*TILE;
  localparam bit p_input_bank_storage = TILE==16 && PE_COUNT==8 && DMA_SIZE==64 &&
      BUS_WIDTH==64 && WINDOW_LANES==8;
  localparam int p_input_bank_rows = (INPUT_STORED_ELEMENTS+INPUT_BANKS-1)/INPUT_BANKS;
  localparam int p_input_row_width = p_input_bank_rows>1 ? $clog2(p_input_bank_rows) : 1;
  logic [31:0] vector_offset;
  (* use_dsp = "yes" *) logic [16:0] channel_next_value;
  (* use_dsp = "yes" *) logic [31:0] channel_remaining;
  logic [15:0] channel_next;
  logic channel_has_more;
  logic [ACTIVE_COUNT_W:0] vector_low_sum;
  logic vector_high_equal, vector_high_less;
  logic vector_high_next_equal, vector_high_next_less;
  logic [ACTIVE_COUNT_W:0] vector_remaining_low;
  logic [ACTIVE_COUNT_W-1:0] vector_next_active, vector_next_active_comb;
  logic [31-ACTIVE_COUNT_W:0] vector_high_increment;
  logic [31-ACTIVE_COUNT_W:0] vector_remaining_carry_needed;
  logic [31-ACTIVE_COUNT_W:0] vector_remaining_carry_generated;
  logic [31-ACTIVE_COUNT_W:0] vector_remaining_carry_expected;
  logic vector_remaining_high_zero, unused_vector_remaining_carry;
  logic vector_has_more, vector_has_more_comb;
  logic [TILE_INDEX_W-1:0] compute_index, quant_index, reduce_index;
  logic compute_group_last_q;
  logic [31:0] fetch_tap_offset, position_offset, pool_byte_offset;
  (* use_dsp = "yes" *) logic [31:0] fetch_position_next, fetch_tap_offset_next;
  (* use_dsp = "yes" *) logic [31:0] position_offset_next, pool_byte_offset_next, vector_offset_next;
  (* use_dsp = "yes" *) logic [31:0] window_request_offset;
  (* use_dsp = "yes" *) logic signed [31:0] add_input_sum;
  logic signed [15:0] input_buf [DMA_SIZE], rhs_buf [TILE];
  logic signed [15:0] input_bank_data [INPUT_BANKS];
  logic signed [15:0] input_bank_read_data [INPUT_BANKS];
  logic [7:0] input_softmax_data;
  logic [7:0] add_input_saved;
  logic signed [15:0] input_bank_contents [INPUT_BANKS][p_input_bank_rows];
  logic [INPUT_INDEX_W:0] input_vector_base;
  logic [INPUT_INDEX_W-1:0] input_scalar_index;
  logic signed [15:0] input_scalar_data;
  logic [p_input_row_width-1:0] input_bank_read_row;
  logic weights_i_wr_en, weights_i_rd_en;
  logic weight_row_last_fire;
  logic parameter_row_last_fire;
  logic [1:0] parameter_rows_remaining;
  logic parameter_three_rows, parameter_two_rows;
  logic [31:0] parameter_row_stride;
  logic [31:0] weights_i_wr_tap, weights_i_rd_tap;
  logic [TILE-1:0] weights_i_wr_mask;
  logic [8*TILE-1:0] weights_i_wr_data, weights_o_rd_data;
  logic weight_data_ready;
  logic [SHARED_STORAGE_ADDR_WIDTH-1:0] weight_data_tap;
  logic weight_tap_advance;
  logic [TAP_COUNT_W-1:0] weight_tap_nxt;
  logic tap_last_wide, tap_last_modulo;
  logic unused_weight_tap_carry;

  wire signed [7:0] weight_tap_data [TILE];
  logic signed [31:0] bias_buf [TILE];
  logic signed [31:0] acc_buf [TILE];
  logic [TILE-1:0] result_write_enable;
  logic [7:0] result_write_data [TILE];
  logic [2:0] pe_op;
  logic [2:0] pe_op_q;
  logic pe_operand_en;
  logic signed [15:0] pe_a [PE_COUNT], pe_b [PE_COUNT];
  logic signed [31:0] pe_acc [PE_COUNT], pe_result [PE_COUNT];
  logic [1:0] add_stage;
  logic add_multiply_wait;
  logic [5:0] add_right;
  logic signed [31:0] add_multiplier, add_operand;
  logic signed [31:0] add_scaled_a;
  logic signed [63:0] add_rounded;
  logic signed [31:0] reduce_acc, reduce_next;
  logic signed [33:0] input_y, input_x, input_origin_x, input_origin_y;
  logic in_bounds, param_bad, param_bad_seen;
  logic input_column_in_bounds, input_row_in_bounds;
  logic dw_in_bounds;
  logic origin_column_in_bounds, origin_row_in_bounds;
  logic next_origin_column_valid, next_origin_row_valid;
  logic signed [16:0] dilation_x_min, dilation_x_max, dilation_y_min, dilation_y_max;
  logic signed [16:0] stride_x_min, stride_x_max, stride_y_min, stride_y_max;
  logic [15:0] output_last_column;
  logic [63:0] input_bytes,output_bytes,weight_bytes,parameter_bytes;
  logic [32:0] checked_range_end[4];
  logic global_pool;
  wire [31:0] checked_kernel_count,checked_position_count;
  wire [63:0] kernel_count={32'd0,checked_kernel_count};
  wire [63:0] position_count={32'd0,checked_position_count};
  logic config_check_ready,config_check_done,config_check_error;
  vector_config_check #(.TILE(TILE),.MAX_TAPS(MAX_TAPS),.POOL_MAX_TAPS(POOL_MAX_TAPS)) u_config_check (
    .clk,.rst_n,.start(state==CHECK),.cfg(c),.ready(config_check_ready),
    .i_input_range(global_pool),
    .done(config_check_done),.error(config_check_error),
    .kernel_count(checked_kernel_count),.position_count(checked_position_count),
    .input_bytes,.output_bytes,.weight_bytes,
    .o_read_end(checked_range_end));
  assign parameter_bytes=64'(channels)<<2;
  logic [31:0] load_bytes;
  logic load_completion_error;
  logic signed [31:0] q_accumulator, q_multiplier;
  logic signed [63:0] q_rounded;
  logic [8:0] q_offset_low;
  logic signed [8:0] q_minimum_before_offset, q_maximum_before_offset;
  logic q_rounded_fits_s9;
  logic q_before_offset_below, q_before_offset_above;
  logic q_offset_increment, q_offset_decrement;
  logic q_positive_overflow, q_negative_overflow;
  logic q_below_min, q_above_max;
  logic signed [31:0] q_clamped_data;
  logic [5:0] q_right_0, q_right_1, q_right_2;
  logic [6:0] q_valid;
  logic [7:0] q_clamped_q, serial_clamped_q;
  logic [TILE_INDEX_W-1:0] q_index_0, q_index_1, q_index_2, q_index_3, q_index_4, q_index_5, q_index_6, q_issue, q_count;
  logic q_active;
  // DW 前台每周期发射一组操作数，提交下标独立保存，连续卷积位置转发累加结果。
  logic dw_issue_fire, dw_commit_vld, dw_group_last, dw_tap_advance;
  logic [TILE_INDEX_W-1:0] dw_commit_index;
  logic dw_snapshot_fire, dw_snapshot_vld, dw_quant_start, dw_quant_last_issue;
  logic dw_snapshot_data_ready;
  logic [31:0] dw_snapshot_address;
  logic dw_snapshot_last;
  logic dw_quant_input_active, dw_quant_slot, dw_quant_next_slot;
  logic [6:0] dw_quant_slot_pipe;
  logic [1:0] dw_result_reserved, dw_result_ready;
  logic [7:0] dw_result_bytes [2][TILE];
  logic [31:0] dw_result_address [2];
  logic [ACTIVE_COUNT_W-1:0] dw_result_count [2];
  logic [1:0] dw_result_last;
  logic dw_result_read_slot, dw_result_accept;
  logic dw_quant_complete, dw_group_pending, dw_work_pending;
  logic dw_shared_fire;
  logic [1:0] dw_shared_inflight;
  logic writeback_request_valid, writeback_request_last;
  logic [31:0] writeback_request_address;
  logic [$clog2(4*TILE+1)-1:0] writeback_request_bytes;
  logic [31:0] write_origin, write_total;
  wire writeback_ready, writeback_busy_raw, writeback_done, writeback_error;
  logic writeback_sink_ready, writeback_metadata_valid, writeback_metadata_slot;
  logic writeback_metadata_coalesce, writeback_metadata_last;
  logic writeback_metadata_capture, writeback_sink_fire, writeback_accept_pending;
  logic [31:0] writeback_metadata_address;
  logic [$clog2(4*TILE+1)-1:0] writeback_metadata_bytes;
  logic writeback_busy;
  wire [32*TILE-1:0] writeback_words;
  for (genvar word_index=0;word_index<TILE;word_index++) begin : g_writeback_word
    wire [31:0] word_value = word_index==0 && !byte_output && !vector_hadamard ?
        reduce_acc : acc_buf[word_index];
    // 标量字节结果保存在已消费的累加项中，DW 使用独立的双组结果存储。
    assign writeback_words[32*word_index+:32] = {word_value[31:8],
        depthwise ? dw_result_bytes[dw_result_read_slot][word_index] : word_value[7:0]};
  end
  assign writeback_request_valid = depthwise ?
      (dw_result_ready[dw_result_read_slot] && state!=FAILED) : state==WRITE_PREP;
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
    else if (state==CHECK || state==FAILED || writeback_sink_fire)
      writeback_metadata_valid <= 1'b0;
    else if (writeback_metadata_capture) writeback_metadata_valid <= 1'b1;
  end
  always_ff @(posedge clk) begin
    if (writeback_metadata_capture) begin
      writeback_metadata_address <= writeback_request_address;
      writeback_metadata_bytes <= writeback_request_bytes;
      writeback_metadata_slot <= dw_result_read_slot;
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
    .flush(state==FAILED),
    .busy(writeback_busy_raw),.done(writeback_done),.error(writeback_error),
    .wr_req,.wr_start,.wr_granted,.wr_base_addr,.wr_row_stride,.wr_rows_to_write,
    .wr_burst_len_m1,.src_wdata,.src_wmask,.src_wvalid,.src_wready,.wr_done(write_response_done_q),.wr_error(write_response_error_q));
  logic avg_negative, avg_power_two, avg_power_two_next;
  logic avg_done;
  logic [5:0] avg_shift, avg_shift_next;
  localparam int AVG_SCALE_BITS = 8+$clog2(POOL_MAX_TAPS+1);
`ifdef ASIC_SYNTHESIS
  logic [AVG_SCALE_BITS:0] avg_reciprocal [0:POOL_MAX_TAPS];
`else
  (* rom_style = "block" *) logic [AVG_SCALE_BITS:0] avg_reciprocal [0:POOL_MAX_TAPS];
`endif
  logic [AVG_SCALE_BITS:0] avg_reciprocal_data;
  logic [AVG_SCALE_BITS-1:0] avg_numerator_q;
  logic [7:0] avg_estimate_q, avg_quotient_q, avg_magnitude_q;
  logic signed [8:0] avg_signed_q;
  logic [AVG_SCALE_BITS:0] avg_check_q;
  logic signed [AVG_SCALE_BITS+1:0] avg_residual_q;
  logic [TAP_COUNT_W-1:0] avg_remainder_q;
  logic [TAP_COUNT_W:0] avg_twice_remainder;
  logic [3:0] avg_phase;
  logic [31:0] avg_input_magnitude;
  logic avg_overestimate;
  // 倒数表保存完整精度常量，ASIC 分支使用静态连接表达同一内容。
`ifdef ASIC_SYNTHESIS
  assign avg_reciprocal[0]='0;
`else
  initial avg_reciprocal[0]='0;
`endif
  for (genvar denominator=1;denominator<=POOL_MAX_TAPS;denominator++) begin : g_avg_reciprocal
    localparam logic [AVG_SCALE_BITS:0] RECIPROCAL =
      (AVG_SCALE_BITS+1)'(((64'd1 << AVG_SCALE_BITS) + denominator - 1) / denominator);
`ifdef ASIC_SYNTHESIS
    assign avg_reciprocal[denominator]=RECIPROCAL;
`else
    initial avg_reciprocal[denominator]=RECIPROCAL;
`endif
  end
  // AVG_START 的前一拍已保持分母，同步读取结果在原乘法采样边沿消费。
  always_ff @(posedge clk) begin
    avg_reciprocal_data <= avg_reciprocal[valid_taps];
  end
  logic input_range_mode, cache_power_two;
  logic [5:0] cache_channel_shift;
  logic cache_power_two_next;
  logic [5:0] cache_channel_shift_next;
  logic [1:0] read_bank,wf_bank,input_bank_mask;
  logic input_slot_release;
  logic [3:0] input_ready,input_reserved;
  logic input_ready_clear_all, input_ready_release, input_drain_ready;
  logic window_slot_available, input_reservations_clear;
  logic [INPUT_INDEX_W-1:0] input_read_base,input_response_base;
  logic [31:0] window_received;
  logic [$clog2(WINDOW_LANES+1)-1:0] window_response_count;
  logic [31:0] window_count_i_value, window_count_i_increment, window_count_i_target;
  logic window_count_i_carry, window_count_o_equal;
  logic [31:0] window_count_o_sum;
  logic unused_window_count_carry;
  localparam int p_window_count_width = $clog2(WINDOW_LANES+1);
  localparam int p_window_count_leaves = 1 << $clog2(WINDOW_LANES);
  logic [p_window_count_width-1:0] window_count_tree [2*p_window_count_leaves];
  logic window_response_fire,window_request_fire;
  logic window_fetch_enabled, window_fetch_in_bounds, window_fetch_advance;
  logic window_response_last_q, window_response_error_q, window_response_fault;
  logic window_response_count_ok_q;
  logic [1:0] window_response_tag;
  logic input_response_pending;
  logic [WINDOW_LANES-1:0] window_bank_valid;
  logic [31:0] fetch_position;
  logic [TAP_COUNT_W-1:0] fetch_tap;
  logic [15:0] fetch_ox;
  assign fetch_ox_next = fetch_ox + 16'd1;
  logic [TAP_COUNT_W-1:0] fetch_kx;
  logic signed [33:0] fetch_x, fetch_y, fetch_origin_x, fetch_origin_y;
  logic [33:0] coordinate_step_i_value [8], coordinate_step_i_delta [8];
  logic [33:0] coordinate_step_o_value [8];
  logic [7:0] unused_coordinate_step_carry;
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
    parallel_prefix_add #(.p_width(34), .p_group_width(4)) u_step (
        .i_a(coordinate_step_i_value[coordinate]), .i_b(coordinate_step_i_delta[coordinate]),
        .i_carry(1'b0), .o_sum(coordinate_step_o_value[coordinate]),
        .o_carry(unused_coordinate_step_carry[coordinate])
    );
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
  // 接收累计值保留完整三十二位，FPGA 配置使用公共加法器的算术推断。
  parallel_prefix_add #(.p_width(32)) u_window_count_sum (
      .i_a(window_count_i_value), .i_b(window_count_i_increment), .i_carry(window_count_i_carry),
      .o_sum(window_count_o_sum), .o_carry(unused_window_count_carry)
  );
  logic next_window_valid, next_window_valid_q;
  logic signed [33:0] next_window_x, next_window_y;
  wire kernel_column_end=kx==kernel_last_column;
  wire signed [33:0] next_column_x=$signed(coordinate_step_o_value[0]);
  wire signed [33:0] next_row_y=$signed(coordinate_step_o_value[1]);
  logic input_x_fits_interval, input_y_fits_interval;
  logic origin_x_fits_interval, origin_y_fits_interval;
  logic next_column_valid, next_row_valid;

  // 配置阶段保存坐标增量对应的有效区间。运行时并行比较当前坐标与两个端点，
  // 十七位符号扩展检查覆盖完整三十四位坐标，范围判断不再依赖坐标加法的进位。
  assign input_x_fits_interval = input_x[33:17] == {17{input_x[16]}};
  assign input_y_fits_interval = input_y[33:17] == {17{input_y[16]}};
  assign origin_x_fits_interval = input_origin_x[33:17] == {17{input_origin_x[16]}};
  assign origin_y_fits_interval = input_origin_y[33:17] == {17{input_origin_y[16]}};
  assign next_column_valid = input_x_fits_interval &&
      ($signed(input_x[16:0]) >= dilation_x_min) && ($signed(input_x[16:0]) < dilation_x_max) &&
      input_row_in_bounds;
  assign next_row_valid = origin_column_in_bounds && input_y_fits_interval &&
      ($signed(input_y[16:0]) >= dilation_y_min) && ($signed(input_y[16:0]) < dilation_y_max);
  assign next_origin_column_valid = origin_x_fits_interval &&
      ($signed(input_origin_x[16:0]) >= stride_x_min) &&
      ($signed(input_origin_x[16:0]) < stride_x_max) && origin_row_in_bounds;
  assign next_origin_row_valid = (c.image.pad_left == 16'd0) && (c.image.input_w != 16'd0) &&
      origin_y_fits_interval &&
      ($signed(input_origin_y[16:0]) >= stride_y_min) &&
      ($signed(input_origin_y[16:0]) < stride_y_max);

  // 配置增量的完整差值先由普通算术表达，寄存边沿分别保存各有效区间。
  (* use_dsp = "yes" *) logic [15:0] dilation_x_negative;
  (* use_dsp = "yes" *) logic signed [16:0] dilation_x_maximum;
  (* use_dsp = "yes" *) logic [15:0] dilation_y_negative;
  (* use_dsp = "yes" *) logic signed [16:0] dilation_y_maximum;
  (* use_dsp = "yes" *) logic [15:0] stride_x_negative;
  (* use_dsp = "yes" *) logic signed [16:0] stride_x_maximum;
  (* use_dsp = "yes" *) logic [15:0] stride_y_negative;
  (* use_dsp = "yes" *) logic signed [16:0] stride_y_maximum;
  (* use_dsp = "yes" *) logic [15:0] output_last_column_next;
  (* use_dsp = "yes" *) logic [15:0] padding_x_negative, padding_y_negative;
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
    if (state == CHECK_WAIT && config_check_done) begin
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
  logic soft_ready, soft_done, soft_exp_we, soft_out_we;
  logic [1:0] soft_error;
  logic [$clog2(TILE)-1:0] soft_input_index, soft_exp_index, soft_out_index;
  logic soft_lut_req_valid, soft_lut_req_ready, soft_lut_rsp_valid;
  logic [7:0] soft_lut_index, soft_lut_index_q;
  logic [31:0] soft_lut_data;
  logic signed [31:0] soft_exp_data, soft_mul_a, soft_mul_b;
  logic signed [7:0] soft_out_data;
  logic soft_exp_write_valid, soft_out_write_valid;
  logic [$clog2(TILE)-1:0] soft_exp_write_index, soft_out_write_index;
  logic signed [31:0] multiplier_a, multiplier_b;
  logic signed [63:0] multiplier_product;
  logic [TAP_COUNT_W-1:0] pool_offset, pool_taps_remaining;
  logic [INPUT_INDEX_W:0] pool_pixels, pool_received, pool_pixel;
  logic [INPUT_INDEX_W:0] pool_elements, pool_next_elements, pool_next_pixels, pool_input_index;
  logic [INPUT_INDEX_W:0] pool_capacity;
  logic [INPUT_INDEX_W:0] pool_row_columns, pool_row_remaining;
  wire pool_response_fire=state==POOL_LOAD_WAIT && rd_valid[0];
  logic [BUS_SHIFT:0] pool_beat_count;
  logic [INPUT_INDEX_W:0] pool_count_i_a, pool_count_i_b, pool_count_i_target;
  logic pool_count_i_carry;
  (* keep = 1 *) logic pool_count_o_equal, pool_received_equal;
  logic pool_receive_complete, pool_read_complete_saved;

  // 单拍数量由已保存的行长度决定，完成条件在响应到达前并行计算。
  assign pool_beat_count = pool_row_remaining>BUS_BYTES ? (BUS_SHIFT+1)'(BUS_BYTES) :
      (BUS_SHIFT+1)'(pool_row_remaining);
  assign pool_count_i_a = pool_received;
  assign pool_count_i_b = (INPUT_INDEX_W+1)'(pool_beat_count);
  assign pool_count_i_target = pool_elements;
  assign pool_count_i_carry = 1'b0;
  assign pool_received_equal = pool_received == pool_elements;
  assign pool_receive_complete = rd_valid[0] ? pool_count_o_equal : pool_received_equal;
  always_ff @(posedge clk) begin
    if (rd_done) pool_read_complete_saved <= pool_receive_complete;
  end
  add_equal #(.p_width(INPUT_INDEX_W+1)) u_pool_count_equal (
      .i_a(pool_count_i_a), .i_b(pool_count_i_b), .i_target(pool_count_i_target),
      .i_carry_in(pool_count_i_carry), .o_equal(pool_count_o_equal)
  );
  localparam int POOL_ROW_W=INPUT_INDEX_W>BUS_SHIFT ? INPUT_INDEX_W-BUS_SHIFT : 1;
  logic [BUS_BYTES-1:0] pool_bank_valid;
  logic [POOL_ROW_W-1:0] pool_bank_row[BUS_BYTES];
  logic signed [15:0] pool_bank_data[BUS_BYTES];

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
      pe_op <= PE_MADD;
    end else if (state == IDLE && start) begin
      spatial <= cfg.op <= MINPOOL_S8;
      depthwise <= cfg.op == DW_S8;
      add_s8 <= cfg.op == ADD_S8;
      softmax_s8 <= cfg.op == SOFTMAX_S8;
      byte_output <= cfg.op <= MINPOOL_S8 || cfg.op == ADD_S8 || cfg.op == SOFTMAX_S8;
      binary_vector <= cfg.op == VEC_DOT || cfg.op == VEC_HADAMARD || cfg.op == ADD_S8;
      avg_pool <= cfg.op == AVGPOOL_S8;
      max_pool <= cfg.op == MAXPOOL_S8;
      min_pool <= cfg.op == MINPOOL_S8;
      vector_max <= cfg.op == VEC_MAX;
      vector_min <= cfg.op == VEC_MIN;
      vector_hadamard <= cfg.op == VEC_HADAMARD;
      case (cfg.op)
        AVGPOOL_S8, VEC_SUM: pe_op <= PE_SUM;
        MAXPOOL_S8, VEC_MAX: pe_op <= PE_MAX;
        MINPOOL_S8, VEC_MIN: pe_op <= PE_MIN;
        VEC_HADAMARD: pe_op <= PE_MUL;
        default: pe_op <= PE_MADD;
      endcase
    end
  end

  logic [31:0] position_next;
  logic unused_position_carry;
  // 像素位置的递增结果供完成判断和状态更新共同使用。
  parallel_prefix_add #(.p_width(32), .p_preserve_groups(1'b1)) u_position_next (
      .i_a(position), .i_b(32'd0), .i_carry(1'b1),
      .o_sum(position_next), .o_carry(unused_position_carry)
  );

  // 有效通道数只影响低位；高位比较与低位加法并行执行，保留三十二位回绕。
  assign vector_low_sum = {1'b0, vector_offset[ACTIVE_COUNT_W-1:0]} + {1'b0, active};
  unsigned_compare #(.p_width(32-ACTIVE_COUNT_W)) u_vector_length_compare (
      .i_a(vector_offset[31:ACTIVE_COUNT_W]), .i_b(c.length[31:ACTIVE_COUNT_W]),
      .o_less(vector_high_less), .o_equal(vector_high_equal)
  );
  assign vector_high_next_equal =
      ((vector_offset[31:ACTIVE_COUNT_W] ^ c.length[31:ACTIVE_COUNT_W]) ==
       {(vector_offset[30:ACTIVE_COUNT_W] & ~c.length[30:ACTIVE_COUNT_W]), 1'b1});
  assign vector_high_next_less = (vector_high_less && !vector_high_next_equal) ||
      ((&vector_offset[31:ACTIVE_COUNT_W]) && (|c.length[31:ACTIVE_COUNT_W]));
  assign vector_has_more_comb = vector_low_sum[ACTIVE_COUNT_W] ?
      (vector_high_next_less || (vector_high_next_equal &&
          (vector_low_sum[ACTIVE_COUNT_W-1:0] < c.length[ACTIVE_COUNT_W-1:0]))) :
      (vector_high_less || (vector_high_equal &&
          (vector_low_sum[ACTIVE_COUNT_W-1:0] < c.length[ACTIVE_COUNT_W-1:0])));
  // 剩余长度复用低位偏移加法；低位借位与加法进位共同决定高位的递增量。
  // 逐位检查高位差值是否为零，只保留下一批需要的有效通道数。
  assign vector_remaining_low = {1'b0, c.length[ACTIVE_COUNT_W-1:0]} -
      {1'b0, vector_low_sum[ACTIVE_COUNT_W-1:0]};
  assign vector_high_increment = (32-ACTIVE_COUNT_W)'({
      vector_low_sum[ACTIVE_COUNT_W] && vector_remaining_low[ACTIVE_COUNT_W],
      vector_low_sum[ACTIVE_COUNT_W] ^ vector_remaining_low[ACTIVE_COUNT_W]});
  assign vector_remaining_carry_needed = vector_offset[31:ACTIVE_COUNT_W] ^
      vector_high_increment ^ c.length[31:ACTIVE_COUNT_W];
  assign vector_remaining_carry_generated =
      (vector_offset[31:ACTIVE_COUNT_W] & vector_high_increment) |
      ((vector_offset[31:ACTIVE_COUNT_W] | vector_high_increment) & ~c.length[31:ACTIVE_COUNT_W]);
  assign {unused_vector_remaining_carry, vector_remaining_carry_expected} =
      {vector_remaining_carry_generated, 1'b0};
  assign vector_remaining_high_zero = vector_remaining_carry_needed == vector_remaining_carry_expected;
  assign vector_next_active_comb = vector_remaining_high_zero &&
      vector_remaining_low[ACTIVE_COUNT_W-1:0] < ACTIVE_COUNT_W'(TILE) ?
      vector_remaining_low[ACTIVE_COUNT_W-1:0] : ACTIVE_COUNT_W'(TILE);
  // 一个分块的偏移和有效通道数在计算期间保持稳定，转移周期使用准备好的条件。
  always_ff @(posedge clk) begin
    vector_has_more <= vector_has_more_comb;
    vector_next_active <= vector_next_active_comb;
  end
  // 配置检查保证量化偏移和激活范围为 S8，低八位加法保留输出字节。
  // 高五十六位并行检查进位、借位和符号，保留完整六十四位回绕行为。
  assign q_offset_low = {1'b0, q_rounded[7:0]} + {1'b0, c.output_offset[7:0]};
  assign q_offset_increment = q_offset_low[8] && !c.output_offset[7];
  assign q_offset_decrement = !q_offset_low[8] && c.output_offset[7];
  // 配置稳定期间先扣除输出偏移，限幅比较与低字节加法并行执行。
  always_ff @(posedge clk) begin
    q_minimum_before_offset <= $signed({c.activation_min[7],c.activation_min[7:0]}) -
        $signed({c.output_offset[7],c.output_offset[7:0]});
    q_maximum_before_offset <= $signed({c.activation_max[7],c.activation_max[7:0]}) -
        $signed({c.output_offset[7],c.output_offset[7:0]});
  end
  assign q_rounded_fits_s9 = q_rounded[63:9] == {55{q_rounded[8]}};
  assign q_before_offset_below = q_rounded_fits_s9 ?
      $signed(q_rounded[8:0]) < q_minimum_before_offset : q_rounded[63];
  assign q_before_offset_above = q_rounded_fits_s9 ?
      $signed(q_rounded[8:0]) > q_maximum_before_offset : !q_rounded[63];
  // 保留六十四位补码加法在两个符号边界处的回绕结果。
  assign q_positive_overflow = !q_rounded[63] && (&q_rounded[62:8]) && q_offset_increment;
  assign q_negative_overflow = q_rounded[63] && !(|q_rounded[62:8]) && q_offset_decrement;
  assign q_below_min = !q_negative_overflow && (q_positive_overflow || q_before_offset_below);
  assign q_above_max = !q_positive_overflow && (q_negative_overflow || q_before_offset_above);
  assign channels = {16'd0,c.image.input_c};
  assign channel_remaining = channels - 32'(channel_base);
  assign channel_next_value = {1'b0,channel_base} + 17'(active);
  always_ff @(posedge clk) begin
    channel_next <= channel_next_value[15:0];
    channel_has_more <= channel_next_value < 17'(channels);
  end
  vector_coordinate_bound u_input_column_bound (
      .i_coordinate(input_x), .i_limit(c.image.input_w), .o_in_bounds(input_column_in_bounds)
  );
  vector_coordinate_bound u_input_row_bound (
      .i_coordinate(input_y), .i_limit(c.image.input_h), .o_in_bounds(input_row_in_bounds)
  );
  vector_coordinate_bound u_origin_column_bound (
      .i_coordinate(input_origin_x), .i_limit(c.image.input_w), .o_in_bounds(origin_column_in_bounds)
  );
  vector_coordinate_bound u_origin_row_bound (
      .i_coordinate(input_origin_y), .i_limit(c.image.input_h), .o_in_bounds(origin_row_in_bounds)
  );
  assign in_bounds = input_column_in_bounds && input_row_in_bounds;
  // DW 发射读取与坐标同时保存的有效位；权重地址选择只经过寄存后的范围结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      dw_in_bounds <= 1'b0;
    end else if (state == OUTPUT_INIT) begin
      dw_in_bounds <= origin_column_in_bounds && origin_row_in_bounds;
    end else if (state == DW_EXECUTE && dw_tap_advance && !tap_last_modulo) begin
      dw_in_bounds <= kernel_column_end ? next_row_valid : next_column_valid;
    end else if (state == DW_FINISH && dw_snapshot_fire) begin
      dw_in_bounds <= (ox == output_last_column) ? next_origin_row_valid : next_origin_column_valid;
    end else if (state == TAP_NEXT) begin
      dw_in_bounds <= next_window_valid;
    end else if (state == EXECUTE_COMMIT && compute_group_last_q && spatial && !global_pool) begin
      dw_in_bounds <= next_window_valid_q;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) global_pool <= 1'b0;
    else if (state==IDLE && start)
      global_pool <= cfg.op <= MINPOOL_S8 && cfg.op != DW_S8 &&
                     cfg.image.output_h==1 && cfg.image.output_w==1 &&
                     cfg.image.kernel_h==cfg.image.input_h && cfg.image.kernel_w==cfg.image.input_w &&
                     cfg.image.pad_top==0 && cfg.image.pad_left==0 &&
                     cfg.image.dilation_h==1 && cfg.image.dilation_w==1;
  end
  // 十六路计算配置保存四个完整通道组；较窄配置保存两个完整组或四个半组。
  // 槽位预留允许 DMA 提前发出请求，并按顺序接收响应。
  assign window_fetch_enabled=spatial && !global_pool && window_fetch_phase;
  assign window_fetch_in_bounds=fetch_x>=0 && fetch_y>=0 &&
    fetch_x<$signed(34'(c.image.input_w)) && fetch_y<$signed(34'(c.image.input_h));
  assign input_bank_mask=PE_COUNT>=16 || active<=ACTIVE_COUNT_W'(TILE/2) ? 2'b11 : 2'b01;
  assign input_read_base=active<=ACTIVE_COUNT_W'(TILE/2) ?
      (INPUT_INDEX_W'(read_bank)<<($clog2(TILE)-1)) : (INPUT_INDEX_W'(read_bank)<<$clog2(TILE));
  assign input_response_base=active<=ACTIVE_COUNT_W'(TILE/2) ?
      (INPUT_INDEX_W'(win_rsp_tag)<<($clog2(TILE)-1)) : (INPUT_INDEX_W'(win_rsp_tag)<<$clog2(TILE));
  assign window_slot_available = window_fetch_enabled &&
      (fetch_position < 32'(position_count)) && window_fetch_in_bounds;
  // PE 在释放边沿保存旧槽操作数，新请求可以在同一边沿预留该槽。
  assign input_slot_release = dw_issue_fire && dw_group_last && wf_bank==read_bank;
  assign win_req_valid = window_slot_available && !window_response_fault &&
      (!input_ready[wf_bank] || input_slot_release) && !input_reserved[wf_bank];
  assign win_req_p0=fetch_position;
  assign win_req_q0=window_request_offset;
  assign win_req_cols=active;
  assign win_req_tag=wf_bank;
  assign win_rsp_ready=1'b1;
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
        window_response_tag <= win_rsp_tag;
        window_response_count_ok_q <= window_count_o_equal;
      end
    end
  end
  assign window_response_fault = window_response_last_q &&
      (window_response_error_q || !window_response_count_ok_q);
  assign window_response_fire=win_rsp_valid && win_rsp_ready;
  assign window_fetch_advance=window_request_fire ||
    (window_fetch_enabled && fetch_position<32'(position_count) && !window_fetch_in_bounds);
  assign input_reservations_clear = (state == CHECK) || (state == TILE_INIT) ||
      (state == FAILED && input_drain_ready);
  assign input_response_pending = p_input_bank_storage &&
      (window_response_last_q || (|window_bank_valid));
  assign input_drain_ready = !rd_busy && !read_done_q && !wr_busy && !win_busy &&
      !input_response_pending && !writeback_busy &&
      dw_shared_inflight == 0 && dma_cfg_ready &&
      (!SHARED_STORAGE_ENABLE || (!i_weight_read_valid && !i_ps_read_valid));
  assign input_ready_clear_all = (state == CHECK) || (state == TILE_INIT) ||
      (state == FAILED && input_drain_ready);
  assign input_ready_release = (dw_issue_fire && dw_group_last) ||
      (state == EXECUTE_COMMIT && compute_group_last_q && !global_pool && spatial);

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
        (!input_ready[bank] || input_slot_release);
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
    if (lane < WINDOW_LANES) begin : g_present
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
    if (pool_next_pixels>pool_taps_remaining) pool_next_pixels=(INPUT_INDEX_W+1)'(pool_taps_remaining);
    pool_next_elements=cache_power_two ? pool_next_pixels<<cache_channel_shift : active;
    next_window_x=kernel_column_end ? input_origin_x : next_column_x;
    next_window_y=kernel_column_end ? next_row_y : input_y;
    // 两组候选坐标先分别检查范围，再选择下一个卷积核位置。
    next_window_valid=spatial && !global_pool && tap+1<taps &&
      (kernel_column_end ? next_row_valid : next_column_valid);
    avg_power_two_next=valid_taps!=0 && (valid_taps&(valid_taps-1))==0;
    avg_shift_next=0;
    for (int bit_index=0;bit_index<TAP_COUNT_W;bit_index++) if (valid_taps[bit_index]) avg_shift_next=6'(bit_index);
  end

  // 通道数在分块初始化时保存，池化请求准备前完成容量和移位量译码。
  always_ff @(posedge clk) begin
    cache_power_two <= cache_power_two_next;
    cache_channel_shift <= cache_channel_shift_next;
    pool_capacity <= cache_power_two_next && active >= 4 ?
        (INPUT_INDEX_W+1)'(2*TILE) >> cache_channel_shift_next : (INPUT_INDEX_W+1)'(1);
    avg_power_two <= avg_power_two_next;
    avg_shift <= avg_shift_next;
  end

  // 执行阶段提前保存下一坐标的范围判断，提交阶段直接选择后续状态。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) next_window_valid_q <= 1'b0;
    else if (state == EXECUTE) next_window_valid_q <= next_window_valid;
  end

  // 执行周期保存通道组末项判断，提交周期直接使用该条件。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) compute_group_last_q <= 1'b0;
    else if (state == EXECUTE)
      compute_group_last_q <= compute_index + 32'(PE_COUNT) >= active;
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
  logic [31:0] read_address_base, read_address_offset;
  logic [15:0] read_address_channel;
  logic [1:0] unused_read_address_carry;
  logic [31:0] parameter_stride_i_b;
  logic unused_parameter_stride_carry, parameter_stride_equal;
  logic [31:0] parameter_row_stride_next;
  logic parameter_two_rows_next, parameter_three_rows_next;

  // 等距参数数组由二维 DMA 连续读取，接收端在每行结束后切换参数类型。
  assign parameter_stride_i_b = ~c.multiplier_base;
  parallel_prefix_add #(.p_width(32)) u_parameter_stride (
      .i_a(c.shift_base), .i_b(parameter_stride_i_b), .i_carry(1'b1),
      .o_sum(parameter_row_stride_next), .o_carry(unused_parameter_stride_carry)
  );
  add_equal #(.p_width(32)) u_parameter_stride_equal (
      .i_a(c.bias_base), .i_b(c.shift_base), .i_target({c.multiplier_base[30:0], 1'b0}),
      .i_carry_in(1'b0), .o_equal(parameter_stride_equal)
  );
  assign parameter_two_rows_next = c.shift_base>c.multiplier_base;
  assign parameter_three_rows_next = c.bias_base!=0 &&
      c.multiplier_base>c.bias_base && parameter_two_rows_next &&
      parameter_stride_equal;
  // 配置检查期间保存参数行描述符，随后各通道复用相同的步长与行数判断。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      parameter_row_stride <= '0;
      parameter_two_rows <= 1'b0;
      parameter_three_rows <= 1'b0;
    end else if (state == CHECK) begin
      parameter_row_stride <= parameter_row_stride_next;
      parameter_two_rows <= parameter_two_rows_next;
      parameter_three_rows <= parameter_three_rows_next;
    end
  end
  assign parameter_row_last_fire = state==LOAD_WAIT && rd_raw_valid &&
      (load_kind==LD_BIAS || load_kind==LD_MULT || load_kind==LD_SHIFT) &&
      32'(rd_col_base)+32'(BUS_BYTES)>=(32'(active)<<2);

  // 低八位突发编码直接判断减一的借位，避免先向上取整再减一。
  function automatic logic [7:0] burst_length_from_bytes(input logic [31:0] value);
    burst_length_from_bytes = 8'(((value+BUS_BYTES-1)>>BUS_SHIFT)-1);
    if (BUS_SHIFT <= 24) begin
      case (^value)
        1'b0, 1'b1: begin
          for (int bit_index = 0; bit_index < 8; bit_index++) begin
            burst_length_from_bytes[bit_index] = value[BUS_SHIFT+bit_index] ^
                ((value & ((32'd1 << (BUS_SHIFT+bit_index))-1)) == 32'd0);
          end
        end
        default: begin end
      endcase
    end
  endfunction

  // 普通读取与专用读取并行计算地址，状态信号只选择已算出的结果。
  logic [31:0] ordinary_read_address, pool_read_address, soft_read_address;
  logic [31:0] ordinary_sum, ordinary_four_state;
  logic unused_ordinary_carry;
  logic [1:0] unused_pool_read_carry, unused_soft_read_carry;
  always_comb begin
    read_address_base = 32'd0;
    read_address_offset = 32'd0;
    read_address_channel = 16'd0;
    case (load_kind)
      LD_WEIGHT: begin
        read_address_base = c.rhs_base;
        read_address_offset = {16'd0, channel_base};
      end
      LD_BIAS, LD_MULT, LD_SHIFT: begin
        case (load_kind)
          LD_BIAS: read_address_base = c.bias_base;
          LD_MULT: read_address_base = c.multiplier_base;
          default: read_address_base = c.shift_base;
        endcase
        read_address_offset = {14'd0, channel_base, 2'b00};
      end
      LD_A: begin
        read_address_base = c.input_base;
        read_address_offset = vector_offset << c.vector_s16;
      end
      LD_B: begin
        read_address_base = c.rhs_base;
        read_address_offset = vector_offset << c.vector_s16;
      end
      default: begin end
    endcase
  end
  vector_read_address_add #(.p_preserve_groups(1'b0)) u_read_address (
    .clk(clk), .i_base(read_address_base), .i_offset(read_address_offset),
    .i_channel(read_address_channel), .o_address(ordinary_four_state),
    .o_carry(unused_read_address_carry)
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(3), .p_preserve_groups(1'b1)) u_ordinary_sum (
    .i_a(read_address_base), .i_b(read_address_offset), .i_carry(1'b0),
    .o_sum(ordinary_sum), .o_carry(unused_ordinary_carry)
  );
  always_comb begin
    case (^{read_address_base, read_address_offset})
      1'b0, 1'b1: ordinary_read_address = ordinary_sum;
      default: ordinary_read_address = ordinary_four_state;
    endcase
  end
  vector_read_address_add u_pool_read_address (
    .clk(clk), .i_base(c.input_base), .i_offset(pool_byte_offset),
    .i_channel(channel_base), .o_address(pool_read_address), .o_carry(unused_pool_read_carry)
  );
  vector_read_address_add u_soft_read_address (
    .clk(clk), .i_base(c.rhs_base), .i_offset({22'd0, soft_lut_index_q, 2'b00}),
    .i_channel(16'd0), .o_address(soft_read_address), .o_carry(unused_soft_read_carry)
  );
  always_comb begin
    case (state)
      SOFT_LUT_REQ, SOFT_LUT_WAIT: rd_base_addr = soft_read_address;
      POOL_LOAD_REQ, POOL_LOAD_WAIT: rd_base_addr = pool_read_address;
      default: rd_base_addr = ordinary_read_address;
    endcase
  end
  always_comb begin
    rd_im2col = 1'b0;
    rd_p0 = 0;
    rd_q0 = 0;
    rd_row_stride = 0;
    rd_rows_to_read = 1;
    rd_valid_cols = active;
    rd_use_16bits = !spatial && c.vector_s16;
    load_bytes = active << rd_use_16bits;
    case (load_kind)
      LD_WEIGHT: begin
        rd_use_16bits = 1'b0;
        rd_rows_to_read = 32'(taps);
        rd_row_stride = channels;
        load_bytes = active;
      end
      LD_BIAS, LD_MULT, LD_SHIFT: begin
        rd_use_16bits = 1'b0;
        load_bytes = active << 2;
        rd_valid_cols = active << 2;
        if (load_kind==LD_BIAS && parameter_three_rows) begin
          rd_rows_to_read = 3;
          rd_row_stride = parameter_row_stride;
        end else if (load_kind==LD_MULT && parameter_two_rows) begin
          rd_rows_to_read = 2;
          rd_row_stride = parameter_row_stride;
        end
      end
      default: begin
      end
    endcase
    rd_burst_len_m1 = burst_length_from_bytes(load_bytes);
    if (state==SOFT_LUT_REQ || state==SOFT_LUT_WAIT) begin
      rd_use_16bits=0;rd_valid_cols=4;rd_burst_len_m1=0;
    end
    if (state==POOL_LOAD_REQ || state==POOL_LOAD_WAIT) begin
      rd_use_16bits = 1'b0;
      if (channels==active) begin
        rd_rows_to_read=1;rd_valid_cols=pool_elements;rd_row_stride=0;
        rd_burst_len_m1=burst_length_from_bytes(32'(pool_elements));
      end else begin
        rd_rows_to_read=pool_pixels;rd_valid_cols=active;rd_row_stride=channels;
        rd_burst_len_m1=burst_length_from_bytes(32'(active));
      end
    end
    param_bad = 1'b0;
    for(int word=0;word<BUS_WIDTH/32;word++) begin
      if(state==LOAD_WAIT && rd_raw_valid && ((32'(rd_col_base)>>2)+32'(word))<active)
        param_bad |= (load_kind==LD_SHIFT && ($signed(rd_raw_data[word*32+:32])<-31 ||
                     $signed(rd_raw_data[word*32+:32])>30)) ||
                     (load_kind==LD_MULT && $signed(rd_raw_data[word*32+:32])<0);
    end
  end

  // 写回状态选择完整偏移，公共加法器生成最终输出地址。
  logic [31:0] write_address_offset, write_origin_next;
  logic [31:0] write_main_offset;
  logic [15:0] write_channel_offset;
  logic [1:0] unused_write_origin_carry;
  always_comb begin
    write_address_offset = 32'd0;
    write_main_offset = 32'd0;
    write_channel_offset = 16'd0;
    case (state)
      EXECUTE_COMMIT: begin
        write_address_offset = vector_offset << 2;
        write_main_offset = vector_offset << 2;
      end
      ADD_STORE: begin
        write_address_offset = vector_offset;
        write_main_offset = vector_offset;
      end
      // 空间位置与通道号分别参与三操作数压缩，减少连续进位计算。
      QUANT_STREAM, AVG_POWER_STORE, AVG_WAIT, POOL_STORE, DW_FINISH: begin
        write_address_offset = position_offset + {16'd0, channel_base};
        write_main_offset = position_offset;
        write_channel_offset = channel_base;
      end
      default: begin end
    endcase
  end
  logic [31:0] write_origin_fast, write_origin_four_state;
  logic unused_write_origin_four_state_carry;
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

  wire signed [15:0] input_lane [PE_COUNT];
  wire signed [15:0] rhs_lane [PE_COUNT];
  wire signed [7:0] weight_lane [PE_COUNT];
  wire signed [31:0] accum_lane [PE_COUNT];
  generate if (TILE % PE_COUNT == 0) begin : g_compute_lane_banks
    for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_lane
      logic signed [15:0] rhs_value;
      logic signed [7:0] weight_value;
      logic signed [31:0] accum_value;
      always_comb begin
        rhs_value='0;weight_value='0;accum_value='0;
        for (int group=0;group<TILE/PE_COUNT;group++) begin
          if (compute_index==TILE_INDEX_W'(group*PE_COUNT)) begin
            rhs_value=rhs_buf[group*PE_COUNT+lane];
            weight_value=weight_tap_data[group*PE_COUNT+lane];
            accum_value=acc_buf[group*PE_COUNT+lane];
          end
        end
      end
      assign rhs_lane[lane]=rhs_value;
      assign weight_lane[lane]=weight_value;
      assign accum_lane[lane]=accum_value;
    end
  end else begin : g_compute_lane_fallback
    for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_lane
      assign rhs_lane[lane]=rhs_buf[compute_index+32'(lane)];
      assign weight_lane[lane]=weight_tap_data[compute_index+32'(lane)];
      assign accum_lane[lane]=acc_buf[compute_index+32'(lane)];
    end
  end endgenerate
  // 向量与标量运算共用每个银行的读取端口，标量字节在独立边沿保存。
  always_comb begin
    input_vector_base = (INPUT_INDEX_W+1)'(compute_index);
    if (state==EXECUTE && global_pool)
      input_vector_base = (INPUT_INDEX_W+1)'(pool_input_index) + (INPUT_INDEX_W+1)'(compute_index);
    else if (spatial && !global_pool)
      input_vector_base = (INPUT_INDEX_W+1)'(input_read_base) + (INPUT_INDEX_W+1)'(compute_index);
  end
  assign input_scalar_index = add_s8 ?
      (state==ADD_CLAMP || state==ADD_STORE ? INPUT_INDEX_W'(compute_index+1'b1) : '0) :
      INPUT_INDEX_W'(soft_input_index);
  assign input_bank_read_row = add_s8 || softmax_s8 ?
      p_input_row_width'(input_scalar_index>>$clog2(INPUT_BANKS)) :
      p_input_row_width'(input_vector_base>>$clog2(INPUT_BANKS));
  // Add 在结果限幅周期准备下一项，Softmax 在读取状态等待寄存数据。
  if (p_input_bank_storage) begin : g_add_input_prepare
    always_ff @(posedge clk) begin
      if (add_s8 || softmax_s8) add_input_saved <= input_scalar_data[7:0];
    end
  end
  generate if (p_input_bank_storage) begin : g_input_memory_read
    logic read_valid, half_group;
    assign half_group = state==EXECUTE && global_pool && active==4 && input_vector_base[2];
    always_comb begin
      read_valid = 1'b0;
      if ((input_vector_base>>$clog2(INPUT_BANKS)) < (INPUT_INDEX_W+1)'(p_input_bank_rows))
        read_valid = 1'b1;
    end
    assign input_scalar_data = {8'd0, input_bank_read_data[input_scalar_index[$clog2(INPUT_BANKS)-1:0]][7:0]};
    assign input_softmax_data = add_input_saved;
    for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_lane
      assign input_lane[lane] = read_valid ?
          (half_group ? input_bank_read_data[(lane+4)%PE_COUNT] : input_bank_read_data[lane]) : 16'sd0;
    end
  end else begin : g_input_general_read
    assign input_scalar_data = 16'sd0;
    assign input_softmax_data = 8'd0;
  if (PE_COUNT > 1 && (PE_COUNT & (PE_COUNT-1)) == 0 &&
               DMA_SIZE % PE_COUNT == 0) begin : g_input_lane_banks
    localparam int BANK_SHIFT = $clog2(PE_COUNT);
    localparam int BANK_ROWS = DMA_SIZE / PE_COUNT;
    logic [INPUT_INDEX_W:0] vector_base;
    logic signed [15:0] bank_current [PE_COUNT], bank_next [PE_COUNT];
    always_comb begin
      if (state==EXECUTE && global_pool)
        vector_base = (INPUT_INDEX_W+1)'(pool_input_index) + (INPUT_INDEX_W+1)'(compute_index);
      else if (spatial && !global_pool)
        vector_base = (INPUT_INDEX_W+1)'(input_read_base) + (INPUT_INDEX_W+1)'(compute_index);
      else vector_base = (INPUT_INDEX_W+1)'(compute_index);
    end
    for (genvar bank=0;bank<PE_COUNT;bank++) begin : g_bank
      always_comb begin
        bank_current[bank] = '0;
        bank_next[bank] = '0;
        for (int row=0;row<BANK_ROWS;row++) begin
          if ((vector_base >> BANK_SHIFT)==(INPUT_INDEX_W+1)'(row))
            bank_current[bank] = input_buf[row*PE_COUNT+bank];
          if ((vector_base >> BANK_SHIFT)+1==(INPUT_INDEX_W+1)'(row))
            bank_next[bank] = input_buf[row*PE_COUNT+bank];
        end
      end
    end
    if (TILE==16 && PE_COUNT==8 && DMA_SIZE==64) begin : g_aligned_lanes
      localparam int p_stored_rows = (2*TILE)/PE_COUNT;
      localparam int p_row_width = $clog2(p_stored_rows);
      logic [p_row_width-1:0] read_row;
      logic signed [15:0] read_data [PE_COUNT];
      logic read_valid;
      logic half_group;

      assign read_row = vector_base[BANK_SHIFT+:p_row_width];
      assign half_group = state==EXECUTE && global_pool && active==4 && vector_base[2];

      // 输入存储的前两个 TILE 保存数据，其余项由 g_unused 固定为零。
      // 银行内使用二进制行号选择数据，完整地址的有效条件在银行交换后统一处理。
      always_comb begin
        read_valid = 1'b0;
        if ((vector_base >> BANK_SHIFT) < (INPUT_INDEX_W+1)'(p_stored_rows))
          read_valid = 1'b1;
      end
      for (genvar bank=0;bank<PE_COUNT;bank++) begin : g_read_bank
        logic signed [15:0] rows [p_stored_rows];
        for (genvar row=0;row<p_stored_rows;row++) begin : g_row
          assign rows[row] = input_buf[row*PE_COUNT+bank];
        end
        assign read_data[bank] = rows[read_row];
      end
      for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_lane
        assign input_lane[lane] = read_valid ?
            (half_group ? read_data[(lane+4)%PE_COUNT] : read_data[lane]) : 16'sd0;
      end
    end else begin : g_general_lanes
      for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_lane
        wire [BANK_SHIFT:0] lane_sum = {1'b0,vector_base[BANK_SHIFT-1:0]} + (BANK_SHIFT+1)'(lane);
        logic signed [15:0] lane_value;
        always_comb begin
          lane_value = '0;
          for (int bank=0;bank<PE_COUNT;bank++)
            if (lane_sum[BANK_SHIFT-1:0]==BANK_SHIFT'(bank))
              lane_value = lane_sum[BANK_SHIFT] ? bank_next[bank] : bank_current[bank];
        end
        assign input_lane[lane] = lane_value;
      end
    end
  end else begin : g_input_lane_fallback
    for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_lane
      wire [31:0] base = state==EXECUTE && global_pool ? pool_input_index :
          spatial && !global_pool ? 32'(input_read_base) : 32'd0;
      assign input_lane[lane] = input_buf[base+32'(compute_index)+32'(lane)];
    end
  end

  end endgenerate

  always_comb begin
    add_multiplier = add_stage==0 ? c.add.input1_multiplier :
                     add_stage==1 ? c.add.input2_multiplier : c.add.output_multiplier;
    // 公共左移量合入输入除数，保留完整定点商，每级只执行一次最近偶数舍入。
    add_right = add_stage==0 ? 6'(31-c.add.input1_shift-c.add.left_shift) :
                add_stage==1 ? 6'(31-c.add.input2_shift-c.add.left_shift) :
                               6'(31-c.add.output_shift);
  end
  assign dw_group_last = compute_index + TILE_INDEX_W'(PE_COUNT) >= TILE_INDEX_W'(active);
  assign dw_issue_fire = state==DW_EXECUTE && !window_response_fault && dw_in_bounds && input_ready[read_bank] && weight_data_ready;
  assign dw_tap_advance = state==DW_EXECUTE && (!dw_in_bounds || (dw_issue_fire && dw_group_last));
  // 完成事件等待最后一次 PE 提交，整行快照由完整的累加存储提供。
  assign dw_snapshot_fire = state==DW_FINISH && !dw_snapshot_vld && !dw_commit_vld;
  assign quant_req_valid = SHARED_QUANT_ENABLE && dw_snapshot_vld && dw_snapshot_data_ready &&
      !dw_result_reserved[dw_quant_next_slot] && state!=FAILED;
  assign quant_req_tag = dw_quant_next_slot;
  assign quant_req_offset = c.output_offset;
  assign quant_req_minimum = c.activation_min;
  assign quant_req_maximum = c.activation_max;
  for (genvar lane=0;lane<TILE;lane++) begin : g_quant_request_mask
    assign quant_req_mask[lane] = lane<active;
  end
  assign dw_shared_fire = quant_req_valid && quant_req_ready;
  assign dw_quant_start = SHARED_QUANT_ENABLE ? dw_shared_fire :
      dw_snapshot_vld && dw_snapshot_data_ready && !dw_quant_input_active &&
      !dw_result_reserved[dw_quant_next_slot] && state!=FAILED;
  assign dw_quant_last_issue = SHARED_QUANT_ENABLE ? dw_shared_fire :
      dw_quant_input_active && q_issue+1'b1>=q_count;
  assign dw_quant_complete = SHARED_QUANT_ENABLE ? quant_rsp_valid :
      depthwise && q_valid[6] && q_index_6+1'b1>=q_count;
  assign dw_group_pending = dw_snapshot_vld || dw_quant_input_active || (|q_valid);
  assign dw_work_pending = dw_group_pending || (|dw_result_reserved) || (dw_shared_inflight!=0);
  assign pe_operand_en = dw_issue_fire || ((state == EXECUTE) && ((!vector_hadamard) || !writeback_busy));
  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_operand_select
    wire enabled=(TILE_INDEX_W+1)'(compute_index)+(TILE_INDEX_W+1)'(lane)<(TILE_INDEX_W+1)'(active);
    assign pe_a[lane]=enabled ? input_lane[lane] : 16'sd0;
    // 无效通道的 a 和 acc 已为零，各运算结果与 b 的取值无关。
    assign pe_b[lane]=depthwise ? 16'($signed(weight_lane[lane])) : rhs_lane[lane];
    // 同一通道连续发射时使用上一拍乘加结果，其余通道读取已提交的累加值。
    assign pe_acc[lane]=!enabled ? 32'sd0 :
        (depthwise && dw_commit_vld && dw_commit_index==compute_index) ? pe_result[lane] : accum_lane[lane];
  end
  always_ff @(posedge clk) if (pe_operand_en) pe_op_q<=pe_op;
  // 权重按卷积核位置整行保存，字节掩码允许每个通道独立接收 DMA 数据。
  // 提交当前计算结果时准备下一位置，使同步读取在下一次计算前完成。
  assign weights_i_wr_en = rst_n && (state == LOAD_WAIT) && !read_done_q && (load_kind == LD_WEIGHT);
  assign weights_i_wr_tap = 32'(load_tap);
  // 一个二维 DMA 描述符读取整组卷积核，各行末拍推进权重存储行号。
  assign weight_row_last_fire = weights_i_wr_en && (|weights_i_wr_mask) &&
      32'(rd_col_base)+32'(BUS_BYTES)>=32'(active);
  assign weight_tap_advance = ((state == EXECUTE_COMMIT) &&
      compute_group_last_q && !global_pool && spatial &&
      !tap_last_wide) || (dw_tap_advance && !tap_last_modulo);
  // 递增数据和末项条件并行计算，分别保留扩展比较与窄位回绕比较。
  parallel_prefix_add #(
      .p_width(TAP_COUNT_W), .p_group_width(3), .p_preserve_groups(1'b1)
  ) u_weight_tap_increment (
      .i_a(tap), .i_b(TAP_COUNT_W'(1)), .i_carry(1'b0),
      .o_sum(weight_tap_nxt), .o_carry(unused_weight_tap_carry)
  );
  add_equal #(.p_width(32)) u_tap_last_wide (
      .i_a(32'(tap)), .i_b(32'd1), .i_target(32'(taps)), .i_carry_in(1'b0),
      .o_equal(tap_last_wide)
  );
  add_equal #(.p_width(TAP_COUNT_W)) u_tap_last_modulo (
      .i_a(tap), .i_b(TAP_COUNT_W'(1)), .i_target(taps), .i_carry_in(1'b0),
      .o_equal(tap_last_modulo)
  );
  assign weights_i_rd_tap = (state == OUTPUT_INIT || state == DW_FINISH) ? 32'd0 :
      weight_tap_advance ? 32'(weight_tap_nxt) : 32'(tap);
  // 同步读取提前准备当前或下一卷积核位置；加载权重期间不发起共享 RAM 读取。
  assign weights_i_rd_en = !SHARED_STORAGE_ENABLE || (rst_n && depthwise && !i_storage_error &&
      (state==OUTPUT_INIT || state==DW_EXECUTE || state==DW_FINISH));
  for (genvar channel = 0; channel < TILE; channel++) begin : g_weight_channel
    localparam int p_dma_lane = channel % BUS_BYTES;
    assign weights_i_wr_mask[channel] = rd_valid[p_dma_lane] &&
        (32'(rd_col_base) + 32'(p_dma_lane) == 32'(channel)) && (32'(channel) < active);
    assign weights_i_wr_data[8*channel+:8] = rd_data[p_dma_lane][7:0];
    assign weight_tap_data[channel] = $signed(weights_o_rd_data[8*channel+:8]);
  end
  if (SHARED_STORAGE_ENABLE) begin : g_shared_weights
    logic [SHARED_STORAGE_ADDR_WIDTH-1:0] prefetch_tap, return_tap, saved_tap;
    logic [127:0] saved_data;
    logic saved_valid, return_matches, saved_matches;

    // 当前权重和下一核位置并行保留。预取地址只取决于已保存的核位置，
    // 当前输入是否就绪以及是否发射均不参与共享存储器的地址选择。
    assign prefetch_tap = (state == OUTPUT_INIT || state == DW_FINISH || tap_last_modulo) ?
        '0 : SHARED_STORAGE_ADDR_WIDTH'(weight_tap_nxt);
    assign return_matches = i_weight_read_valid && return_tap == SHARED_STORAGE_ADDR_WIDTH'(tap);
    assign saved_matches = saved_valid && saved_tap == SHARED_STORAGE_ADDR_WIDTH'(tap);
    assign weight_data_ready = return_matches || saved_matches;
    assign weight_data_tap = return_matches ? return_tap : saved_tap;
    assign o_weight_read_en = weights_i_rd_en;
    assign o_weight_read_addr = prefetch_tap;
    assign o_weight_write_en = weights_i_wr_en && !i_storage_error;
    assign o_weight_write_addr = SHARED_STORAGE_ADDR_WIDTH'(weights_i_wr_tap);
    assign o_weight_write_data = 128'(weights_i_wr_data);
    assign o_weight_write_mask = 16'(weights_i_wr_mask);
    assign weights_o_rd_data = (8*TILE)'(return_matches ? i_weight_read_data : saved_data);

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
      end else if ((state == CHECK) || state == TILE_INIT ||
                   state == OUTPUT_INIT || state == FAILED) begin
        saved_valid <= 1'b0;
      end else if (return_matches) begin
        saved_valid <= 1'b1;
      end
    end
  end else begin : g_private_weights
    vector_weight_store #(.p_channels(TILE), .p_depth(MAX_TAPS)) u_weights (
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
    assign weight_data_tap = '0;
  end

  // 操作码在 EXECUTE 更新；操作数独立等待写出允许后接收，下一周期提交结果。
  for (genvar lane = 0; lane < PE_COUNT; lane++) begin : g_pe
    logic pe_i_en;
    logic [2:0] pe_i_op;
    logic signed [15:0] pe_i_a;
    logic signed [15:0] pe_i_b;
    logic signed [31:0] pe_i_acc;
    logic signed [31:0] pe_o_result;

    assign pe_i_en = pe_operand_en;
    assign pe_i_op = pe_op_q;
    assign pe_i_a = pe_a[lane];
    assign pe_i_b = pe_b[lane];
    assign pe_i_acc = pe_acc[lane];
    assign pe_result[lane] = pe_o_result;
    registered_vector_pe u_pe (
      .clk(clk), .i_en(pe_i_en), .i_op(pe_i_op), .i_a(pe_i_a), .i_b(pe_i_b),
      .i_acc(pe_i_acc), .o_result(pe_o_result)
    );
  end

  localparam int ADD_INDEX_WIDTH=$clog2(TILE)>0 ? $clog2(TILE) : 1;
  wire signed [7:0] add_first_lhs=p_input_bank_storage ? add_input_saved : input_buf[0][7:0];
  wire signed [7:0] add_next_lhs=p_input_bank_storage ? add_input_saved :
      input_buf[ADD_INDEX_WIDTH'(compute_index)+ADD_INDEX_WIDTH'(1)][7:0];
  wire signed [7:0] add_rhs=rhs_buf[ADD_INDEX_WIDTH'(compute_index)][7:0];
  // 有效 S8 操作数加上 [-127,128] 内的偏移，结果范围为 [-255,255]。
  wire signed [8:0] add_first_lhs_offset=$signed({add_first_lhs[7],add_first_lhs})+$signed(c.add.input1_offset[8:0]);
  wire signed [8:0] add_next_lhs_offset=$signed({add_next_lhs[7],add_next_lhs})+$signed(c.add.input1_offset[8:0]);
  wire signed [8:0] add_rhs_offset=$signed({add_rhs[7],add_rhs})+$signed(c.add.input2_offset[8:0]);
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

  // 串行运算按任务操作码选择累加存储地址；归约使用独立的提前读取寄存器。
  logic [TILE_INDEX_W-1:0] serial_acc_read_index;
  logic signed [31:0] serial_acc_read_data;
  logic signed [31:0] softmax_i_exp_rdata;
  always_comb begin
    serial_acc_read_index = quant_index;
    if (depthwise) begin
      serial_acc_read_index = q_issue;
    end
  end
  assign serial_acc_read_data = acc_buf[serial_acc_read_index];
  // 指数值采用单写入、单读取的普通数组，计算通道保存独立的工作累加值。
  logic signed [31:0] soft_exp_memory [TILE];
  always_ff @(posedge clk) begin
    if (rst_n && soft_exp_write_valid) soft_exp_memory[soft_exp_write_index] <= soft_lut_data;
  end
  assign softmax_i_exp_rdata = soft_exp_memory[soft_exp_index];

  logic signed [31:0] reduce_alu_i_lhs, reduce_alu_i_rhs, reduce_rhs_q;
  logic reduce_alu_i_max, reduce_alu_i_min;
  assign reduce_alu_i_lhs = reduce_acc;
  // 归约期间缓冲区保持稳定，提前一拍读取下一项并保存完整 INT32 操作数。
  assign reduce_alu_i_rhs = reduce_rhs_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) reduce_rhs_q <= '0;
    else if (state == VECTOR_NEXT && !vector_has_more && !vector_hadamard && !add_s8)
      reduce_rhs_q <= acc_buf[0];
    else if (state == VECTOR_REDUCE && reduce_index + 1 < TILE)
      reduce_rhs_q <= acc_buf[reduce_index + TILE_INDEX_W'(1)];
  end
  assign reduce_alu_i_max = vector_max;
  assign reduce_alu_i_min = vector_min;
  // 当前索引在本周期提供操作数，加法与有符号极值比较共用归约单元。
  vector_reduce_alu u_reduce_alu (
    .clk(clk), .i_lhs(reduce_alu_i_lhs), .i_rhs(reduce_alu_i_rhs),
    .i_max(reduce_alu_i_max), .i_min(reduce_alu_i_min), .o_result(reduce_next)
  );
  localparam int POOL_SUM_WIDTH=8+$clog2(POOL_MAX_TAPS);
  wire signed [POOL_SUM_WIDTH-1:0] avg_pool_sum=serial_acc_read_data[POOL_SUM_WIDTH-1:0];
  (* use_dsp = "yes" *) logic [POOL_SUM_WIDTH-1:0] avg_negated_sum;
  (* use_dsp = "yes" *) logic signed [AVG_SCALE_BITS+1:0] avg_residual_next;
  assign avg_negated_sum = $unsigned(-avg_pool_sum);
  assign avg_residual_next = $signed({2'b00,avg_numerator_q}) - $signed({1'b0,avg_check_q});
  wire [POOL_SUM_WIDTH-1:0] avg_unsigned_magnitude=avg_pool_sum<0 ?
      avg_negated_sum : $unsigned(avg_pool_sum);
  assign avg_input_magnitude=32'(avg_unsigned_magnitude);
  assign avg_overestimate=avg_residual_q[AVG_SCALE_BITS+1];
  assign avg_twice_remainder={avg_remainder_q,1'b0};
  assign avg_done=state==AVG_WAIT && avg_phase==4'd10;
  always_ff @(posedge clk) begin
    // 倒数平均运算先经过 QUANT_INIT，累加器选择和绝对值计算在进入乘法器前完成。
    if (state==QUANT_INIT && avg_pool && !avg_power_two)
      avg_numerator_q<=AVG_SCALE_BITS'(avg_input_magnitude);
    if (state==AVG_START && !avg_power_two) begin
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
      (state==AVG_START ? $signed(32'(avg_numerator_q)) : $signed({24'd0,avg_estimate_q})) :
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
    .exp_we(soft_exp_we),.exp_index(soft_exp_index),.exp_wdata(soft_exp_data),.exp_rdata(softmax_i_exp_rdata),
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

  wire window_write_valid[WINDOW_LANES], dma_input_write_valid[BUS_BYTES];
  wire [INPUT_INDEX_W-1:0] window_write_index[WINDOW_LANES], dma_input_write_index[BUS_BYTES];
  for (genvar lane=0;lane<WINDOW_LANES;lane++) begin : g_window_write_address
    wire [INPUT_INDEX_W:0] column_sum={1'b0,win_rsp_col[INPUT_INDEX_W-1:0]}+(INPUT_INDEX_W+1)'(lane);
    assign window_write_valid[lane]=window_response_fire && win_rsp_mask[lane] &&
        win_rsp_col<32'(active) && column_sum<(INPUT_INDEX_W+1)'(active);
    assign window_write_index[lane]=input_response_base+INPUT_INDEX_W'(column_sum);
  end
  localparam int WINDOW_BANK_W=$clog2(WINDOW_LANES);
  logic [INPUT_INDEX_W-1:0] window_bank_index[WINDOW_LANES];
  wire signed [15:0] window_bank_data[WINDOW_LANES];
  wire [WINDOW_BANK_W-1:0] window_first_bank=WINDOW_BANK_W'(input_response_base)+WINDOW_BANK_W'(win_rsp_col);
  for (genvar bank=0;bank<WINDOW_LANES;bank++) begin : g_window_bank
    wire [WINDOW_BANK_W-1:0] source_lane=WINDOW_BANK_W'(bank)-window_first_bank;
    if (p_input_bank_storage) begin : g_registered_write
      always_ff @(posedge clk) begin
        if (!rst_n) window_bank_valid[bank] <= 1'b0;
        else begin
          window_bank_valid[bank] <= window_write_valid[source_lane];
          if (window_write_valid[source_lane]) window_bank_index[bank] <= window_write_index[source_lane];
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
  for (genvar lane=0;lane<BUS_BYTES;lane++) begin : g_dma_write_address
    wire [INPUT_INDEX_W:0] column_sum={1'b0,rd_col_base}+(INPUT_INDEX_W+1)'(lane);
    assign dma_input_write_valid[lane]=state==LOAD_WAIT && load_kind==LD_A && rd_valid[lane] &&
        column_sum<(INPUT_INDEX_W+1)'(active);
    assign dma_input_write_index[lane]=INPUT_INDEX_W'(column_sum);
  end
  // 线性 S8 响应包含按列顺序连续排列的有效数据。
  // 每次响应统一循环选择数据，写入对应的输入存储银行。
  wire [BUS_SHIFT-1:0] pool_first_bank=BUS_SHIFT'(pool_received);
  for (genvar bank=0;bank<BUS_BYTES;bank++) begin : g_pool_bank
    wire [BUS_SHIFT-1:0] source_lane=BUS_SHIFT'(bank)-pool_first_bank;
    wire [INPUT_INDEX_W:0] destination_index=pool_received+(INPUT_INDEX_W+1)'(source_lane);
    wire bank_receive=pool_response_fire && (BUS_SHIFT+1)'(source_lane)<pool_beat_count &&
        destination_index<pool_elements;
    wire [POOL_ROW_W-1:0] destination_row=POOL_ROW_W'(pool_received>>BUS_SHIFT)+
        POOL_ROW_W'(BUS_SHIFT'(bank)<pool_first_bank);
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
      always_ff @(posedge clk) begin
        if (rst_n && bank_receive) pool_bank_data[bank] <= rd_data[source_lane];
      end
    end
  end

  // 空间响应保存原始数据和起始银行，窗口与全局池化共用循环选择器。
  // 数据与写入行号同时进入寄存阶段，下一边沿写入输入存储并发布完成。
  if (p_input_bank_storage) begin : g_spatial_input_data
    logic [WINDOW_BANK_W-1:0] first_bank_saved, selected_first;
    logic signed [15:0] spatial_raw_data [INPUT_BANKS];
    logic signed [15:0] selected_data [INPUT_BANKS];

    always_ff @(posedge clk) begin
      if (pool_response_fire || window_response_fire) begin
        first_bank_saved <= global_pool ? pool_first_bank : window_first_bank;
        for (int lane=0;lane<INPUT_BANKS;lane++)
          spatial_raw_data[lane] <= global_pool ? rd_data[lane] : win_rsp_data[lane];
      end
    end
    assign selected_first = first_bank_saved;
    for (genvar bank=0;bank<INPUT_BANKS;bank++) begin : g_bank
      logic [WINDOW_BANK_W-1:0] source_lane;
      logic signed [15:0] bank_data;
      assign source_lane = WINDOW_BANK_W'(bank)-selected_first;
      assign selected_data[bank] = spatial_raw_data[bank];
      assign bank_data = selected_data[source_lane];
      assign window_bank_data[bank] = bank_data;
      assign pool_bank_data[bank] = bank_data;
    end
  end

  assign q_clamped_data = q_below_min ? c.activation_min :
      q_above_max ? c.activation_max : 32'($signed(q_offset_low[7:0]));

  // 每个总线银行共用一个数据选择器，存储项分别保留地址比较和写使能。
  // 已保存的运算模式确定普通向量、窗口和全局池化响应的数据来源。
  for (genvar bank=0;bank<INPUT_BANKS;bank++) begin : g_input_bank_data
    localparam int p_s16_lane = bank % (BUS_BYTES / 2);
    localparam int p_s8_lane = bank % BUS_BYTES;
    localparam int p_window_bank = bank % WINDOW_LANES;
    logic signed [15:0] dma_bank_data;

    assign dma_bank_data = c.vector_s16 ? rd_data[p_s16_lane] : rd_data[p_s8_lane];
    if (p_input_bank_storage) begin : g_shared_rotation
      assign input_bank_data[bank] = spatial ? window_bank_data[p_window_bank] : dma_bank_data;
    end else begin : g_separate_rotation
      assign input_bank_data[bank] = global_pool ? pool_bank_data[p_s8_lane] :
          spatial ? window_bank_data[p_window_bank] : dma_bank_data;
    end
  end

  // 一个银行每拍至多写入一行，完整数据字保存到普通数组并异步读取。
  if (p_input_bank_storage) begin : g_input_memory
    for (genvar bank=0;bank<INPUT_BANKS;bank++) begin : g_bank
      logic signed [15:0] mem [p_input_bank_rows];
      logic [p_input_row_width-1:0] write_row;
      logic [INPUT_INDEX_W-1:0] load_index;
      logic load_valid, write_valid;

      assign load_index = c.vector_s16 ? dma_input_write_index[bank%(BUS_BYTES/2)] :
          dma_input_write_index[bank%BUS_BYTES];
      assign load_valid = (c.vector_s16 ? dma_input_write_valid[bank%(BUS_BYTES/2)] :
          dma_input_write_valid[bank%BUS_BYTES]) &&
          load_index[$clog2(INPUT_BANKS)-1:0] == $clog2(INPUT_BANKS)'(bank);
      assign write_valid = pool_bank_valid[bank] || window_bank_valid[bank] || load_valid;
      assign write_row = global_pool ? pool_bank_row[bank] : spatial ?
          p_input_row_width'(window_bank_index[bank]>>$clog2(INPUT_BANKS)) :
          p_input_row_width'(load_index>>$clog2(INPUT_BANKS));

      always_ff @(posedge clk) begin
        if (rst_n && write_valid) mem[write_row] <= input_bank_data[bank];
      end
      assign input_bank_read_data[bank] = mem[input_bank_read_row];
      for (genvar row=0;row<p_input_bank_rows;row++) begin : g_row
        assign input_bank_contents[bank][row] = mem[row];
      end
    end
  end

  for (genvar entry=0;entry<DMA_SIZE;entry++) begin : g_input_write
    if (entry>=INPUT_STORED_ELEMENTS) begin : g_unused
      assign input_buf[entry]=16'sd0;
    end else begin : g_buffer
    localparam int S8_LANE=entry%BUS_BYTES;
    localparam int S16_LANE=entry%(BUS_BYTES/2);
    wire load_match=c.vector_s16 ?
        dma_input_write_valid[S16_LANE] && dma_input_write_index[S16_LANE]==INPUT_INDEX_W'(entry) :
        dma_input_write_valid[S8_LANE] && dma_input_write_index[S8_LANE]==INPUT_INDEX_W'(entry);
    logic write_enable;
    logic signed [15:0] write_value;
    localparam int WINDOW_BANK=entry%WINDOW_LANES;
    wire window_match=window_bank_valid[WINDOW_BANK] &&
        window_bank_index[WINDOW_BANK]==INPUT_INDEX_W'(entry);
    wire pool_match=pool_bank_valid[S8_LANE] &&
        pool_bank_row[S8_LANE]==POOL_ROW_W'(entry/BUS_BYTES);

    assign write_enable = window_match || load_match || pool_match;
    assign write_value = input_bank_data[entry%INPUT_BANKS];
    if (p_input_bank_storage) begin : g_memory_value
      assign input_buf[entry] = input_bank_contents[entry%INPUT_BANKS][entry/INPUT_BANKS];
    end else begin : g_register_value
      always_ff @(posedge clk) if (rst_n && write_enable) input_buf[entry] <= write_value;
    end
    end
  end

  // 每拍的连续偏置字分配到固定分组，同组存储项共用数据字选择。
  localparam int p_bias_words_per_beat = BUS_WIDTH / 32;
  logic bias_load_fire;
  logic [31:0] bias_word_index [p_bias_words_per_beat];
  logic bias_bank_valid [p_bias_words_per_beat];
  logic [31:0] bias_bank_index [p_bias_words_per_beat];
  logic [31:0] bias_bank_data [p_bias_words_per_beat];

  assign bias_load_fire = (state == LOAD_WAIT) && (load_kind == LD_BIAS) && rd_raw_valid;
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
      if (state == TILE_INIT) begin
        bias_bank_data[bank] = 32'd0;
      end
    end
  end
  // 深度为一的存储保留所有偏置的并行读取，初始化周期同时写入零值。
  for (genvar entry = 0; entry < TILE; entry++) begin : g_bias_storage
    localparam int p_bank = entry % p_bias_words_per_beat;
    logic bias_storage_i_wr_en;
    logic [0:0] bias_storage_i_wr_addr;
    logic [31:0] bias_storage_i_wr_data;
    logic [0:0] bias_storage_i_wr_mask;
    logic [0:0] bias_storage_i_rd_en;
    logic [0:0][0:0] bias_storage_i_rd_addr;
    logic [0:0][31:0] bias_storage_o_rd_data;

    assign bias_storage_i_wr_en = rst_n && ((state == TILE_INIT) ||
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
  logic params_i_wr_en;
  logic params_i_wr_multiplier, params_i_wr_shift;
  logic [INPUT_INDEX_W-1:0] params_i_wr_byte_index;
  logic [BUS_WIDTH-1:0] params_i_wr_data;
  logic [ACTIVE_COUNT_W-1:0] params_i_active;
  logic [TILE_INDEX_W-1:0] params_i_rd_index;
  logic signed [31:0] params_o_multiplier;
  logic [5:0] params_o_right_shift;
  assign params_i_wr_en = rst_n && state==LOAD_WAIT && rd_raw_valid;
  assign params_i_wr_multiplier = (load_kind==LD_MULT);
  assign params_i_wr_shift = (load_kind==LD_SHIFT);
  assign params_i_wr_byte_index = rd_col_base;
  assign params_i_wr_data = rd_raw_data;
  assign params_i_active = active;
  assign params_i_rd_index = q_issue;
  vector_quant_params #(
      .p_entries(TILE),
      .p_bus_width(BUS_WIDTH),
      .p_dma_index_width(INPUT_INDEX_W),
      .p_read_index_width(TILE_INDEX_W),
      .p_active_width(ACTIVE_COUNT_W),
      .p_parallel_output(SHARED_QUANT_ENABLE)
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

  logic accumulator_compute_fire;
  logic accumulator_init_fire, accumulator_bias_selected;
  logic signed [31:0] accumulator_init_data;
  assign accumulator_compute_fire = (state == EXECUTE_COMMIT && (!vector_hadamard || !writeback_busy)) ||
      (dw_commit_vld && state!=FAILED && !dw_snapshot_fire);
  assign accumulator_init_fire = state == OUTPUT_INIT || state == VECTOR_INIT || dw_snapshot_fire;
  assign accumulator_bias_selected = depthwise && (state == OUTPUT_INIT || dw_snapshot_fire);
  always_comb begin
    accumulator_init_data = 32'sd0;
    if (state == OUTPUT_INIT) begin
      if (max_pool) accumulator_init_data = -32'sd128;
      else if (min_pool) accumulator_init_data = 32'sd127;
    end else if (state == VECTOR_INIT) begin
      if (vector_max) accumulator_init_data = 32'sh8000_0000;
      else if (vector_min) accumulator_init_data = 32'sh7fff_ffff;
    end
  end
  for (genvar entry=0;entry<TILE;entry++) begin : g_accumulator_write
    localparam int LANE_INDEX = entry % PE_COUNT;
    localparam int GROUP_BASE = entry - LANE_INDEX;
    logic compute_write, bias_write, constant_write;
    logic write_enable;
    logic [31:0] write_value;
    assign compute_write = accumulator_compute_fire && 32'(entry) < active &&
        (depthwise ? dw_commit_index : compute_index) == TILE_INDEX_W'(GROUP_BASE);
    assign bias_write = accumulator_init_fire && accumulator_bias_selected;
    assign constant_write = accumulator_init_fire && !accumulator_bias_selected;
    assign write_enable = compute_write || accumulator_init_fire;
    assign write_value = ({32{accumulator_compute_fire}} & pe_result[LANE_INDEX]) |
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
    always_ff @(posedge clk) if (rst_n) begin
      if (state==LOAD_WAIT && load_kind==LD_B && 32'(entry)<active) begin
        if (c.vector_s16) begin
          if (rd_valid[entry%(BUS_BYTES/2)] &&
              32'(rd_col_base)+32'(entry%(BUS_BYTES/2))==32'(entry))
            rhs_buf[entry]<=rd_data[entry%(BUS_BYTES/2)];
        end else begin
          if (rd_valid[entry%BUS_BYTES] &&
              32'(rd_col_base)+32'(entry%BUS_BYTES)==32'(entry))
            rhs_buf[entry]<=rd_data[entry%BUS_BYTES];
        end
      end
    end
  end

  // 乘法器已完成的输出直接进入舍入输入寄存器，乘积与移位量同拍保存。
  wire signed [63:0] rounding_input = avg_pool ? $signed(64'(serial_acc_read_data)) : multiplier_product;
  wire [5:0] rounding_amount = add_s8 ? add_right : avg_pool ? avg_shift : q_right_2;
  wire signed [63:0] rounding_result,rounding_floor;
  vector_round_shift #(.REGISTER_MIDDLE(1'b1),.REGISTER_INPUT(1'b1)) u_rounding (
    .clk(clk),.value(rounding_input),.amount(rounding_amount),.result(rounding_result),.floor_value(rounding_floor));
  // 有效 S8 池化输入及激活范围使精确平均值保持在 [-128,127] 内。
  wire signed [8:0] pool_activation_min={c.activation_min[7],c.activation_min[7:0]};
  wire signed [8:0] pool_activation_max={c.activation_max[7],c.activation_max[7:0]};
  wire signed [7:0] avg_power_floor=rounding_floor[7:0];
  // 舍入在向下取整的商上增加零或一。激活上下限均为整数，
  // 范围检查可以与该递增运算并行执行。
  wire signed [31:0] avg_power_result=avg_power_floor<$signed(c.activation_min[7:0]) ? c.activation_min :
      avg_power_floor>=$signed(c.activation_max[7:0]) ? c.activation_max : 32'($signed(rounding_result[7:0]));
  wire signed [31:0] avg_div_result=avg_signed_q<pool_activation_min ? c.activation_min :
      avg_signed_q>pool_activation_max ? c.activation_max : 32'(avg_signed_q);
  wire signed [9:0] add_adjusted=$signed(add_rounded[9:0])+$signed({{2{c.output_offset[7]}},c.output_offset[7:0]});
  // 十位加法结果与完整激活上下限比较，高位范围和低位大小并行判断。
  logic add_below_min, add_above_max;
  logic add_min_high_zero, add_min_high_ones, add_max_high_zero, add_max_high_ones;
  assign add_min_high_zero = !(|c.activation_min[30:9]);
  assign add_min_high_ones = &c.activation_min[30:9];
  assign add_max_high_zero = !(|c.activation_max[30:9]);
  assign add_max_high_ones = &c.activation_max[30:9];
  assign add_below_min = c.activation_min[31] ?
      (add_min_high_ones && (add_adjusted < $signed(c.activation_min[9:0]))) :
      (!add_min_high_zero || (add_adjusted < $signed(c.activation_min[9:0])));
  assign add_above_max = c.activation_max[31] ?
      (!add_max_high_ones || (add_adjusted > $signed(c.activation_max[9:0]))) :
      (add_max_high_zero && (add_adjusted > $signed(c.activation_max[9:0])));
  wire signed [31:0] add_clamped=add_rounded>64'sd255 ? c.activation_max :
      add_rounded< -64'sd256 ? c.activation_min :
      add_below_min ? c.activation_min : add_above_max ? c.activation_max : 32'(add_adjusted);

  // 标量限幅先保存字节结果，存储写使能仅选择已经完成的数值。
  always_ff @(posedge clk) begin
    if (state == ADD_CLAMP) serial_clamped_q <= add_clamped[7:0];
    else if (state == AVG_POWER_CLAMP) serial_clamped_q <= avg_power_result[7:0];
    else if (state == AVG_WAIT && avg_phase == 4'd9) serial_clamped_q <= avg_div_result[7:0];
  end

  // 串行结果共用字节数据选择，每个存储项仅保留地址使能和并行结果选择。
  logic result_background_write;
  logic [TILE_INDEX_W-1:0] result_background_index;
  logic result_serial_write;
  logic [TILE_INDEX_W-1:0] result_serial_index;
  logic [7:0] result_serial_data;
  logic [7:0] result_common_data;
  logic result_byte_pending;
  logic [TILE_INDEX_W-1:0] result_byte_index;
  logic [7:0] result_byte_data;
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
    else if (state==FAILED) result_byte_pending <= 1'b0;
    else result_byte_pending <= result_background_write || result_serial_write;
  end
  always_ff @(posedge clk) begin
    result_byte_index <= result_serial_write ? result_serial_index : result_background_index;
    result_byte_data <= result_common_data;
  end
  // 极值池化按 PE 组提交，读取选择器与计算通道共用。
  // 每个通道保留一个八位限幅器，当前组全部字节在同一边沿写入。
  logic [7:0] pool_lane_value [PE_COUNT];
  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_pool_lane_clamp
    assign pool_lane_value[lane] = $signed(accum_lane[lane][7:0]) < $signed(c.activation_min[7:0]) ?
        c.activation_min[7:0] : $signed(accum_lane[lane][7:0]) > $signed(c.activation_max[7:0]) ?
        c.activation_max[7:0] : accum_lane[lane][7:0];
  end
  for (genvar entry=0;entry<TILE;entry++) begin : g_result_write
    localparam int LANE_INDEX = entry % PE_COUNT;
    localparam int GROUP_BASE = entry - LANE_INDEX;
    logic write_enable;
    logic [7:0] write_value;
    logic byte_selected, pool_selected;
    logic [7:0] pool_value;
    assign byte_selected = result_byte_pending && result_byte_index == TILE_INDEX_W'(entry);
    assign pool_selected = state == POOL_STORE && 32'(entry) < active &&
        compute_index == TILE_INDEX_W'(GROUP_BASE);
    assign pool_value = pool_lane_value[LANE_INDEX];
    assign write_enable = byte_selected || pool_selected;
    assign write_value = ({8{result_byte_pending}} & result_byte_data) | ({8{pool_selected}} & pool_value);
    assign result_write_enable[entry] = write_enable;
    assign result_write_data[entry] = write_value;
  end

  // 完成的像素保存到独立存储行，量化读取期间，PE 继续累加下一像素。
  // 最后一次计算先提交到累加存储，下一边沿读取整行并初始化下一像素。
  if (SHARED_STORAGE_ENABLE) begin : g_shared_snapshot
    logic read_pending, data_valid;
    assign o_ps_write_en = rst_n && dw_snapshot_fire && !i_storage_error;
    assign o_ps_write_addr = '0;
    assign o_ps_read_en = read_pending && state!=FAILED && !i_storage_error;
    assign o_ps_read_addr = '0;
    assign dw_snapshot_data_ready = data_valid || i_ps_read_valid;
    for (genvar entry=0;entry<TILE;entry++) begin : g_channel
      assign o_ps_write_data[32*entry+:32] = acc_buf[entry];
      assign quant_req_accumulator[entry] = $signed(i_ps_read_data[32*entry+:32]);
    end
    // 写入和读取分处相邻周期；RAM 输出保持有效，直到该像素的量化输入全部接收。
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        read_pending <= 1'b0;
        data_valid <= 1'b0;
      end else if ((state==CHECK) || state==FAILED) begin
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
        if (dw_snapshot_fire) dw_snapshot[entry] <= acc_buf[entry];
      end
    end
  end

  // 两组结果存储分别保存正在量化和等待写出的像素，写出接收后释放该组。
  for (genvar slot=0;slot<2;slot++) begin : g_dw_result_slot
    for (genvar entry=0;entry<TILE;entry++) begin : g_channel
      always_ff @(posedge clk) begin
        if (rst_n && depthwise && state!=FAILED) begin
          if (SHARED_QUANT_ENABLE && quant_rsp_valid && quant_rsp_tag==1'(slot) && entry<dw_result_count[slot])
            dw_result_bytes[slot][entry] <= quant_rsp_data[entry];
          else if (!SHARED_QUANT_ENABLE && q_valid[6] &&
                   dw_quant_slot_pipe[6]==1'(slot) && q_index_6==TILE_INDEX_W'(entry))
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
    end else if ((state==CHECK) || state==FAILED) begin
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
        dw_snapshot_last <= position_next==32'(position_count);
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

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(IDLE); c<='0; error<=0; load_kind<=LD_WEIGHT;
      parameter_rows_remaining<=0;
      taps<=0; active<=0; channel_base<=0; position<=0;
      ox<=0;oy<=0;kx<=0;ky<=0;tap<=0;load_tap<=0;valid_taps<=0;
      input_x<=0;input_y<=0;input_origin_x<=0;input_origin_y<=0;
      vector_offset<=0;compute_index<=0;quant_index<=0;reduce_index<=0;
      reduce_acc<=0; param_bad_seen<=0;load_completion_error<=1'b0;
      add_stage<=0;add_multiply_wait<=0;add_scaled_a<=0;add_rounded<=0;
      q_accumulator<=0;q_multiplier<=0;q_rounded<=0;q_right_0<=0;q_right_1<=0;q_right_2<=0;
      q_valid<=0;q_index_0<=0;q_index_1<=0;q_index_2<=0;q_index_3<=0;q_index_4<=0;q_index_5<=0;q_index_6<=0;q_clamped_q<=0;q_issue<=0;q_count<=0;
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
      if (depthwise && !SHARED_QUANT_ENABLE && state!=IDLE && state!=FAILED && state!=DONE) begin
        q_active <= dw_quant_input_active || (|q_valid) || dw_quant_start;
        q_valid <= {q_valid[5:0],dw_quant_input_active};
        if (dw_quant_start) begin
          q_count <= TILE_INDEX_W'(active);
          q_issue <= '0;
        end else if (dw_quant_input_active) begin
          q_accumulator <= quant_req_accumulator[$clog2(TILE)'(q_issue)];
          q_multiplier <= params_o_multiplier;
          q_right_0 <= params_o_right_shift;
          q_index_0 <= q_issue;
          q_issue <= q_issue+1'b1;
        end
        if (q_valid[0]) begin q_right_1<=q_right_0;q_index_1<=q_index_0;end
        if (q_valid[1]) begin q_right_2<=q_right_1;q_index_2<=q_index_1;end
        if (q_valid[2]) begin q_index_3<=q_index_2;end
        if (q_valid[3]) q_index_4<=q_index_3;
        if (q_valid[4]) begin q_rounded<=rounding_result;q_index_5<=q_index_4;end
        if (q_valid[5]) begin q_clamped_q<=q_clamped_data[7:0];q_index_6<=q_index_5;end
      end
      if (softmax_s8) begin
        if (state==SOFT_LUT_WAIT && rd_raw_valid) soft_lut_data<=rd_raw_data[31:0];
      end
      if (weight_row_last_fire) load_tap<=load_tap+1'b1;
      if (parameter_row_last_fire && parameter_rows_remaining!=0) begin
        parameter_rows_remaining<=parameter_rows_remaining-1'b1;
        load_kind<=load_kind==LD_BIAS ? LD_MULT : LD_SHIFT;
      end

      if (window_fetch_advance) begin
        if (fetch_tap+1==taps) begin
          fetch_position<=fetch_position_next;fetch_tap<=0;fetch_tap_offset<=0;fetch_kx<=0;
          if (fetch_ox==output_last_column) begin
            fetch_ox<=0;
            fetch_origin_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});
            fetch_origin_y<=$signed(coordinate_step_o_value[7]);
            fetch_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});
            fetch_y<=$signed(coordinate_step_o_value[7]);
          end else begin
            fetch_ox<=fetch_ox_next;
            fetch_origin_x<=$signed(coordinate_step_o_value[6]);
            fetch_x<=$signed(coordinate_step_o_value[6]);fetch_y<=fetch_origin_y;
          end
        end else begin
          fetch_tap<=fetch_tap+1;fetch_tap_offset<=fetch_tap_offset_next;
          if (fetch_kx==kernel_last_column) begin
            fetch_kx<=0;fetch_x<=fetch_origin_x;fetch_y<=$signed(coordinate_step_o_value[5]);
          end else begin
            fetch_kx<=fetch_kx+1;fetch_x<=$signed(coordinate_step_o_value[4]);
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
        pool_received<=pool_received+(INPUT_INDEX_W+1)'(pool_beat_count);
        if (pool_row_remaining<=BUS_BYTES) pool_row_remaining<=pool_row_columns;
        else pool_row_remaining<=pool_row_remaining-(INPUT_INDEX_W+1)'(BUS_BYTES);
      end
      case (state)
        IDLE: if (start) begin
          c<=cfg; error<=0; {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(CHECK);
          input_range_mode<=0;
        end
        CHECK: begin
          q_active<=0;q_valid<=0;
          read_bank<=0;wf_bank<=0;window_received<=0;
          param_bad_seen<=0;
          if (config_check_ready) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(CHECK_WAIT);
        end
        CHECK_WAIT: if (config_check_done) begin
          if (config_check_error) begin error<=2'b01;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);end
          else begin
            taps<=32'(kernel_count);channel_base<=0;input_range_mode<=global_pool;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(CONFIGURE);
            kernel_last_column<=TAP_COUNT_W'(c.image.kernel_w)-TAP_COUNT_W'(1);
          end
        end
        CONFIGURE: if (dma_cfg_ready) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(spatial ? TILE_INIT : VECTOR_INIT);
        TILE_INIT: begin
          active<=channel_remaining<TILE ? channel_remaining : 32'(TILE);
          position<=0;position_offset<=0;ox<=0;oy<=0;load_tap<=0;load_kind<=LD_WEIGHT;
          input_origin_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});input_origin_y<=$signed({{18{(|c.image.pad_top)}}, padding_y_negative});
          read_bank<=0;wf_bank<=0;window_received<=0;
          fetch_position<=0;fetch_tap<=0;fetch_tap_offset<=0;fetch_ox<=0;fetch_kx<=0;
          fetch_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});fetch_y<=$signed({{18{(|c.image.pad_top)}}, padding_y_negative});
          fetch_origin_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});fetch_origin_y<=$signed({{18{(|c.image.pad_top)}}, padding_y_negative});
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(depthwise ? LOAD_REQ : OUTPUT_INIT);
        end
        LOAD_REQ: if (rd_granted) begin
          parameter_rows_remaining<=
              load_kind==LD_BIAS && parameter_three_rows ? 2'd2 :
              load_kind==LD_MULT && parameter_two_rows ? 2'd1 : 2'd0;
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_WAIT);
        end
        LOAD_WAIT: if (read_done_q) begin
          load_completion_error<=read_error_q;
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_VERIFY);
        end
        LOAD_VERIFY: begin
          if (load_completion_error || param_bad_seen) begin error<=2'b10;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);end
          else case (load_kind)
            LD_WEIGHT: begin load_kind<=c.bias_base==0 ? LD_MULT : LD_BIAS;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_REQ);end
            LD_BIAS: begin load_kind<=LD_MULT;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_REQ);end
            LD_MULT: begin load_kind<=LD_SHIFT;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_REQ);end
            LD_SHIFT: {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(OUTPUT_INIT);
            LD_A: if (binary_vector) begin load_kind<=LD_B;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_REQ);end
              else begin compute_index<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(softmax_s8 ? SOFT_START : EXECUTE);end
            LD_B: begin
              compute_index<=0;add_stage<=0;
              {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(add_s8 ? ADD_MULT : EXECUTE);
            end
            default: begin error<=2'b10;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);end
          endcase
        end
        OUTPUT_INIT: begin
          tap<=0;kx<=0;ky<=0;valid_taps<=0;compute_index<=0;
          input_x<=input_origin_x;input_y<=input_origin_y;
          if (global_pool) begin
            valid_taps<=taps;pool_offset<=0;pool_taps_remaining<=taps;pool_byte_offset<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(POOL_LOAD_PREP);
          end else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(depthwise ? DW_EXECUTE : TAP_CHECK);
        end
        DW_EXECUTE: begin
          if (dw_issue_fire) begin
            if (!dw_group_last) compute_index<=compute_index+TILE_INDEX_W'(PE_COUNT);
            else begin
              compute_index<='0;
              read_bank<=(read_bank+1'b1)&input_bank_mask;
            end
          end
          if (dw_tap_advance) begin
            if (tap_last_modulo) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DW_FINISH);
            else begin
              tap<=weight_tap_nxt;
              input_x<=next_window_x;input_y<=next_window_y;
              if (kernel_column_end) begin kx<=0;ky<=ky+1'b1;end
              else kx<=kx+1'b1;
            end
          end
        end
        DW_FINISH: if (dw_snapshot_fire) begin
          compute_index<='0;tap<='0;kx<='0;ky<='0;
          if (position_next<32'(position_count)) begin
            position<=position_next;position_offset<=position_offset_next;
            if (ox==output_last_column) begin
              ox<=0;oy<=oy_next;
              input_origin_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});
              input_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});
              input_origin_y<=$signed(coordinate_step_o_value[3]);
              input_y<=$signed(coordinate_step_o_value[3]);
            end else begin
              ox<=ox_next;
              input_origin_x<=$signed(coordinate_step_o_value[2]);
              input_x<=$signed(coordinate_step_o_value[2]);
              input_y<=input_origin_y;
            end
            {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DW_EXECUTE);
          end else if (channel_has_more) begin
            channel_base<=channel_next;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DRAIN_TILE);
          end else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DRAIN);
        end
        POOL_LOAD_PREP: begin
          pool_pixels<=pool_next_pixels;pool_received<=0;pool_pixel<=0;pool_input_index<=0;
          pool_elements<=pool_next_elements;
          pool_row_columns<=channels==active ? pool_next_elements : (INPUT_INDEX_W+1)'(active);
          pool_row_remaining<=channels==active ? pool_next_elements : (INPUT_INDEX_W+1)'(active);
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(POOL_LOAD_REQ);
        end
        POOL_LOAD_REQ: if (rd_granted) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(POOL_LOAD_WAIT);
        POOL_LOAD_WAIT: if (read_done_q) begin
          if (read_error_q || !pool_read_complete_saved) begin error<=2'b10;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);end
          else begin compute_index<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(POOL_LOAD_DRAIN);end
        end
        POOL_LOAD_DRAIN: {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(EXECUTE);
        TAP_CHECK: if (dw_in_bounds) begin
            valid_taps<=valid_taps+1;compute_index<=0;
            {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(input_ready[read_bank] ? EXECUTE : WINDOW_WAIT);
          end
          else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(TAP_NEXT);
        WINDOW_WAIT: if (input_ready[read_bank]) begin compute_index<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(EXECUTE);end
        EXECUTE: if (!vector_hadamard || !writeback_busy) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(EXECUTE_COMMIT);
        EXECUTE_COMMIT: begin
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(EXECUTE);
          if (!compute_group_last_q) compute_index<=compute_index+32'(PE_COUNT);
          else if (global_pool) begin
            pool_byte_offset<=pool_byte_offset_next;
            if (pool_pixel+1<pool_pixels) begin
              pool_pixel<=pool_pixel+1;pool_input_index<=pool_input_index+(INPUT_INDEX_W+1)'(active);
              compute_index<=0;
            end
            else if (pool_taps_remaining>pool_pixels) begin
              pool_offset<=pool_offset+pool_pixels;
              pool_taps_remaining<=pool_taps_remaining-TAP_COUNT_W'(pool_pixels);
              {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(POOL_LOAD_PREP);
            end
            else begin quant_index<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(QUANT_INIT);end
          end
          else if (spatial) begin
            read_bank<=(read_bank+1'b1)&input_bank_mask;compute_index<=0;
            if (tap_last_wide) begin quant_index<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(QUANT_INIT);end
            else begin
              tap<=weight_tap_nxt;input_x<=next_window_x;input_y<=next_window_y;
              if (kernel_column_end) begin kx<=0;ky<=ky+1;end else kx<=kx+1;
              if (next_window_valid_q) begin
                valid_taps<=valid_taps+1;
                {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(input_ready[(read_bank+1'b1)&input_bank_mask] ? EXECUTE : WINDOW_WAIT);
              end else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(TAP_CHECK);
            end
          end
          else if (vector_hadamard) begin
            write_origin<=write_origin_next;write_total<=active<<2;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);
          end else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(VECTOR_NEXT);
        end
        ADD_MULT: begin
          add_multiply_wait<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_DRAIN);
        end
        ADD_DRAIN: if (add_multiply_wait) begin
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_ROUND);
        end else add_multiply_wait<=1;
        ADD_ROUND: {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_ROUND_WAIT);
        ADD_ROUND_WAIT: begin
          if (add_stage==0) begin
            add_scaled_a<=32'(rounding_result);
            add_stage<=1;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_MULT);
          end else if (add_stage==1) begin
            add_rounded<=rounding_result;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_SUM);
          end else begin
            add_rounded<=rounding_result;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_CLAMP);
          end
        end
        ADD_SUM: begin
          add_stage<=2;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_MULT);
        end
        ADD_CLAMP: {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_STORE);
        ADD_STORE: if (!writeback_busy) begin
          if (compute_index+1<active) begin
            compute_index<=compute_index+1'b1;add_stage<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(ADD_MULT);
          end else begin
            write_origin<=write_origin_next;write_total<=active;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);
          end
        end
        TAP_NEXT: if (tap_last_wide) begin quant_index<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(QUANT_INIT);end
          else begin
            tap<=weight_tap_nxt;input_x<=next_window_x;input_y<=next_window_y;
            if (kernel_column_end) begin kx<=0;ky<=ky+1;end else kx<=kx+1;
            {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(TAP_CHECK);
          end
        QUANT_INIT: begin
          if (depthwise) begin
            if (!writeback_busy) begin
              q_active<=1;q_count<=active;q_issue<=0;q_valid<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(QUANT_STREAM);
            end
          end else if (!writeback_busy) begin
            if (avg_pool) begin
              if (valid_taps==0) begin error<=2'b01;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);end else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(AVG_START);
            end else begin
              compute_index <= '0;
              {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(POOL_STORE);
            end
          end
        end
        QUANT_STREAM: begin
          q_valid<={q_valid[5:0],q_issue<q_count};
          if (q_issue<q_count) begin
            q_accumulator<=serial_acc_read_data;q_multiplier<=params_o_multiplier;
            q_right_0<=params_o_right_shift;q_index_0<=q_issue;q_issue<=q_issue+1'b1;
          end
          if (q_valid[0]) begin q_right_1<=q_right_0;q_index_1<=q_index_0;end
          if (q_valid[1]) begin q_right_2<=q_right_1;q_index_2<=q_index_1;end
          if (q_valid[2]) begin
            q_index_3<=q_index_2;
          end
          if (q_valid[3]) q_index_4<=q_index_3;
          if (q_valid[4]) begin q_rounded<=rounding_result;q_index_5<=q_index_4;end
          if (q_valid[5]) begin q_clamped_q<=q_clamped_data[7:0];q_index_6<=q_index_5;end
          if (q_valid[6] && q_index_6+1==q_count) begin
            q_active<=0;q_valid<=0;
            write_origin<=write_origin_next;write_total<=active;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);
          end
        end
        AVG_START: if (avg_power_two) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(AVG_POWER_DELAY);
          else begin avg_negative<=serial_acc_read_data<0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(AVG_WAIT);end
        AVG_POWER_DELAY: {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(AVG_POWER_CLAMP);
        AVG_POWER_CLAMP: {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(AVG_POWER_STORE);
        AVG_POWER_STORE: begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(AVG_START);end
          else begin write_origin<=write_origin_next;write_total<=active;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);end
        end
        AVG_WAIT: if (avg_done) begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(QUANT_INIT);end
          else begin write_origin<=write_origin_next;
            write_total<=active;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);end
        end
        POOL_STORE: begin
          if (32'(compute_index)+32'(PE_COUNT) < active) begin
            compute_index <= compute_index + TILE_INDEX_W'(PE_COUNT);
          end else begin
            write_origin <= write_origin_next;
            write_total <= active;
            {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);
          end
        end
        WRITE_PREP: if (writeback_ready) begin
          if (spatial) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(OUTPUT_NEXT);
          else if (vector_hadamard || add_s8) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(VECTOR_NEXT);
          else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DRAIN);
        end
        OUTPUT_NEXT: begin
          if (position_next<32'(position_count)) begin
            position<=position_next;position_offset<=position_offset_next;
            if (ox==output_last_column) begin
              ox<=0;oy<=oy_next;input_origin_x<=$signed({{18{(|c.image.pad_left)}}, padding_x_negative});
              input_origin_y<=$signed(coordinate_step_o_value[3]);
            end else begin
              ox<=ox_next;input_origin_x<=$signed(coordinate_step_o_value[2]);
            end
            {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(OUTPUT_INIT);
          end else if (channel_has_more) begin
            channel_base<=channel_next;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DRAIN_TILE);
          end
          else {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DRAIN);
        end
        // 每个结果槽保存所属通道数，共享量化与写回可跨通道组继续完成。
        DRAIN_TILE: if (!win_busy && input_reserved==0 && !q_active &&
                       (depthwise ? !dw_group_pending : !writeback_busy && !dw_work_pending))
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(TILE_INIT);
        DRAIN: if (!writeback_busy && !win_busy && input_reserved==0 && !q_active && !dw_work_pending && dma_cfg_ready)
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DONE);
        SOFT_START: if (soft_ready) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(SOFT_RUN);
        SOFT_RUN: if (soft_done) begin
          if (soft_error!=0) begin error<=soft_error;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);end
          else begin write_origin<=write_origin_next;write_total<=active;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);end
        end else if (soft_lut_req_valid) begin
          soft_lut_data<=0;soft_lut_index_q<=soft_lut_index;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(SOFT_LUT_REQ);
        end
        SOFT_LUT_REQ: if (rd_granted) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(SOFT_LUT_WAIT);
        SOFT_LUT_WAIT: if (read_done_q) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(SOFT_RUN);
        VECTOR_INIT: begin
          vector_offset<=0;active<=c.length<TILE ? c.length : 32'(TILE);
          load_kind<=LD_A;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_REQ);
        end
        VECTOR_NEXT: if (vector_has_more) begin
          vector_offset<=vector_offset_next;
          active<=vector_next_active;
          load_kind<=LD_A;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(LOAD_REQ);
        end else if (vector_hadamard || add_s8) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DRAIN);
        else begin
          reduce_acc<=vector_max ? 32'sh8000_0000 : vector_min ? 32'sh7fff_ffff : 32'sd0;
          reduce_index<=0;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(VECTOR_REDUCE);
        end
        VECTOR_REDUCE: begin
          reduce_acc<=reduce_next;
          if (reduce_index+1<TILE) reduce_index<=reduce_index+1;
          else begin write_origin<=write_origin_next;write_total<=4;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(WRITE_PREP);end
        end
        FAILED: if (input_drain_ready) begin
          q_active<=0;q_valid<=0;
          {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(DONE);
        end
        DONE: if (done_ready) {window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(IDLE);
        default: begin error<=2'b10;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);end
      endcase
      if ((writeback_done && writeback_error) ||
          window_response_fault) begin
        error<=2'b10;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);
      end
      if (SHARED_STORAGE_ENABLE && i_storage_error &&
          state!=IDLE && state!=FAILED && state!=DONE) begin
        error<=2'b10;{window_fetch_phase,dma_cfg_valid,rd_req,ready,done_valid,state}<=state_control_value(FAILED);
      end
    end
  end

`ifdef NPU_SIM_ASSERT
  logic signed [31:0] soft_exp_previous;
  logic signed [7:0] soft_out_previous;
  always_ff @(posedge clk) begin
    if (soft_exp_we) soft_exp_previous <= soft_exp_data;
    if (soft_out_we) soft_out_previous <= soft_out_data;
    if (rst_n && soft_exp_write_valid) assert(soft_lut_data === soft_exp_previous);
    if (rst_n && soft_out_write_valid) assert(soft_out_data === soft_out_previous);
  end
  logic [31:0] input_position[4],input_tap[4];
  logic writeback_metadata_stalled;
  logic writeback_metadata_match;
  logic previous_writeback_sink_fire;
  assign writeback_metadata_match = writeback_metadata_valid &&
      (!depthwise || writeback_metadata_slot == dw_result_read_slot);
  logic [31:0] previous_writeback_address;
  logic [$clog2(4*TILE+1)-1:0] previous_writeback_bytes;
  logic previous_writeback_last, previous_writeback_coalesce;
  logic [32*TILE-1:0] previous_writeback_words;
  always @(posedge clk) begin
    if (!rst_n) begin
      writeback_metadata_stalled <= 1'b0;
      previous_writeback_sink_fire <= 1'b0;
    end else begin
      if (state==AVG_WAIT && avg_phase==4'd9)
        assert(avg_signed_q === (avg_negative ? -$signed({1'b0,avg_magnitude_q}) :
            $signed({1'b0,avg_magnitude_q})));
      if (writeback_sink_fire && !depthwise) assert(!result_byte_pending);
      assert(!(result_background_write && result_serial_write));
      if (state==POOL_STORE) assert(!result_byte_pending);
      if (dw_snapshot_fire) assert(!dw_commit_vld);
      assert(writeback_accept_pending == previous_writeback_sink_fire);
      assert(!(writeback_metadata_valid && writeback_accept_pending));
      if (writeback_metadata_valid && state!=FAILED)
        assert(writeback_request_valid && writeback_metadata_match);
      if (state==TAP_CHECK) assert(dw_in_bounds == in_bounds);
      if (state==DW_FINISH || state==OUTPUT_NEXT) begin
        assert(channel_has_more == (channel_base+active<channels));
        assert(channel_next == 16'(channel_base+active));
      end
      assert(window_fetch_phase == (state==OUTPUT_INIT || state==TAP_CHECK || state==WINDOW_WAIT || state==QUANT_STREAM || state==EXECUTE || state==EXECUTE_COMMIT || state==TAP_NEXT || state==QUANT_INIT || state==OUTPUT_NEXT || state==AVG_START || state==AVG_POWER_DELAY || state==AVG_POWER_CLAMP || state==AVG_POWER_STORE || state==AVG_WAIT || state==POOL_STORE || state==WRITE_PREP || state==DW_EXECUTE || state==DW_FINISH));
      previous_writeback_sink_fire <= writeback_sink_fire;
      assert(ready == (state==IDLE));
      assert(done_valid == (state==DONE));
      assert(dma_cfg_valid == (state==CONFIGURE));
      assert(rd_req == (state==LOAD_REQ || state==POOL_LOAD_REQ || state==SOFT_LUT_REQ));
      if (writeback_request_valid && writeback_metadata_match) begin
        assert(writeback_metadata_address == writeback_request_address);
        assert(writeback_metadata_bytes == writeback_request_bytes);
        assert(writeback_metadata_last == writeback_request_last);
        assert(writeback_metadata_coalesce ==
            (depthwise && channels==32'(dw_result_count[dw_result_read_slot])));
      end
      if (writeback_metadata_stalled && state != FAILED) begin
        assert(writeback_request_valid && writeback_metadata_match);
        assert(writeback_metadata_address == previous_writeback_address);
        assert(writeback_metadata_bytes == previous_writeback_bytes);
        assert(writeback_metadata_last == previous_writeback_last);
        assert(writeback_metadata_coalesce == previous_writeback_coalesce);
        if (byte_output) begin
          for (int entry=0; entry<TILE; entry++)
            assert(writeback_words[32*entry+:8] == previous_writeback_words[32*entry+:8]);
        end else assert(writeback_words == previous_writeback_words);
      end
      if (window_response_fault) begin
        assert(!dw_issue_fire);
        assert(!win_req_valid);
      end
      writeback_metadata_stalled <= writeback_request_valid && writeback_metadata_match && !writeback_sink_ready;
      previous_writeback_address <= writeback_metadata_address;
      previous_writeback_bytes <= writeback_metadata_bytes;
      previous_writeback_last <= writeback_metadata_last;
      previous_writeback_coalesce <= writeback_metadata_coalesce;
      previous_writeback_words <= writeback_words;
    end
  end
  initial forever begin
    @(posedge clk or negedge rst_n);
    if (!rst_n) begin
      for (int bank=0;bank<4;bank++) begin
        input_position[bank]<=0;input_tap[bank]<=0;
      end
    end else if (window_request_fire) begin
      input_position[wf_bank]<=fetch_position;input_tap[wf_bank]<=fetch_tap;
    end
  end
  initial begin
    assert(TILE>=2 && TILE<=64 && (TILE&(TILE-1))==0);
    assert(PE_COUNT>=1 && PE_COUNT<=TILE && TILE%PE_COUNT==0);
    assert(DMA_SIZE>=4*TILE && MAX_TAPS>=1 && MAX_TAPS<=255);
    assert(POOL_MAX_TAPS>=1 && POOL_MAX_TAPS<=65535);
  end
  initial forever @(posedge clk) if (rst_n) begin
    if (writeback_busy_raw) assert(writeback_busy);
    assert(spatial == (c.op <= MINPOOL_S8) && depthwise == (c.op == DW_S8));
    assert(add_s8 == (c.op == ADD_S8) && softmax_s8 == (c.op == SOFTMAX_S8));
    assert(byte_output == (spatial || add_s8 || softmax_s8));
    assert(binary_vector == (c.op == VEC_DOT || c.op == VEC_HADAMARD || add_s8));
    assert(avg_pool == (c.op == AVGPOOL_S8) && max_pool == (c.op == MAXPOOL_S8));
    assert(min_pool == (c.op == MINPOOL_S8) && vector_hadamard == (c.op == VEC_HADAMARD));
    assert(vector_max == (c.op == VEC_MAX) && vector_min == (c.op == VEC_MIN));
    if (state == VECTOR_NEXT) begin
      assert(vector_has_more == vector_has_more_comb);
      assert(vector_next_active == vector_next_active_comb);
    end
    if (global_pool && (state == POOL_LOAD_PREP || state == EXECUTE || state == EXECUTE_COMMIT))
      assert(pool_taps_remaining == taps - pool_offset);
    if (state == POOL_LOAD_PREP) begin
      assert(cache_power_two == cache_power_two_next && cache_channel_shift == cache_channel_shift_next);
      assert(pool_capacity == (cache_power_two_next && active >= 4 ?
          (INPUT_INDEX_W+1)'(2*TILE) >> cache_channel_shift_next : (INPUT_INDEX_W+1)'(1)));
    end
    if (state == QUANT_INIT || state == AVG_START || state == AVG_POWER_STORE || state == AVG_WAIT)
      assert(avg_power_two == avg_power_two_next && avg_shift == avg_shift_next);
    if (q_valid[6]) begin
      assert(q_minimum_before_offset == $signed({c.activation_min[7],c.activation_min[7:0]}) -
          $signed({c.output_offset[7],c.output_offset[7:0]}));
      assert(q_maximum_before_offset == $signed({c.activation_max[7],c.activation_max[7:0]}) -
          $signed({c.output_offset[7],c.output_offset[7:0]}));
    end
    if (src_wvalid && !src_wready) begin
      assert(wr_busy);
    end
    if (state==EXECUTE) assert(active>0 && active<=TILE && compute_index<active);
    if (weight_row_last_fire) assert(load_tap<taps);
    if (state==LOAD_WAIT && load_kind==LD_WEIGHT && read_done_q && !read_error_q)
      assert(32'(load_tap)+32'(weight_row_last_fire)==32'(taps));
    if (state==LOAD_WAIT && read_done_q && !read_error_q &&
        (load_kind==LD_BIAS || load_kind==LD_MULT || load_kind==LD_SHIFT))
      assert(parameter_rows_remaining==0);
    if (state==ADD_MULT || state==ADD_DRAIN || state==ADD_ROUND || state==ADD_ROUND_WAIT || state==ADD_SUM || state==ADD_STORE) begin
      assert(add_s8 && active>0 && active<=TILE && compute_index<active);
      assert(add_stage<=2 && add_right>=1 && add_right<=62);
      if (state==ADD_SUM)
        assert($signed(64'(add_scaled_a))+$signed(add_rounded)>=-64'sd2147483648 &&
               $signed(64'(add_scaled_a))+$signed(add_rounded)<=64'sd2147483647);
    end
    if (window_request_fire) begin
      assert((!input_ready[wf_bank] || input_slot_release) && !input_reserved[wf_bank]);
      assert(win_req_cols>0 && win_req_cols<=TILE);
    end
    if (window_response_fire) begin
      assert(input_reserved[win_rsp_tag]);
      if(!win_rsp_error) begin
        assert(win_rsp_mask!=0 && win_rsp_col+32'(window_response_count)<=active);
        if(win_rsp_last) assert(window_received+32'(window_response_count)==active);
      end
    end
    if (state==WINDOW_WAIT) assert(in_bounds && tap<taps);
    if (state==POOL_LOAD_REQ) begin
      assert(global_pool && input_range_mode && pool_pixels>0 && pool_elements<=DMA_SIZE);
      assert(pool_offset+pool_pixels<=taps);
    end
    if (state==EXECUTE && global_pool) assert(pool_pixel<pool_pixels && pool_input_index+active<=pool_elements);
    if ((state==EXECUTE || dw_issue_fire) && spatial && !global_pool) begin
      assert(input_ready[read_bank]);
      assert(input_position[read_bank]==position && input_tap[read_bank]==tap);
    end
  end
`endif
endmodule

// 有符号坐标与十六位尺寸比较，三个相邻位组并行归并大小关系。
module vector_coordinate_bound (
  input  logic signed [33:0] i_coordinate,
  input  logic [15:0] i_limit,
  output logic o_in_bounds
);
  //! 0. 辅助定义
  //! -----------

  logic [15:0] bit_generate, bit_propagate;
  // 仅保存后级实际使用的分组边界，使十六位比较保持并行归并结构。
  (* keep = 1 *) logic [5:0] group_generate;
  logic [5:0] group_propagate;
  (* keep = 1 *) logic [1:0] half_generate;
  logic [1:0] half_propagate;
  logic coordinate_high_zero, coordinate_low_less;

  //! 1. 并行比较坐标与尺寸
  //! -----------------------

  assign bit_generate = ~i_coordinate[15:0] & i_limit;
  assign bit_propagate = ~i_coordinate[15:0] | i_limit;
  for (genvar group_index = 0; group_index < 6; group_index++) begin : g_group
    localparam int p_low = 3 * group_index;
    localparam int p_bits = group_index == 5 ? 1 : 3;
    logic [p_bits-1:0] generate_terms;

    for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
      if (bit_index == p_bits-1) begin : g_high
        assign generate_terms[bit_index] = bit_generate[p_low+bit_index];
      end else begin : g_low
        assign generate_terms[bit_index] = bit_generate[p_low+bit_index] &&
            (&bit_propagate[p_low+bit_index+1 +: p_bits-bit_index-1]);
      end
    end
    assign group_generate[group_index] = |generate_terms;
    if (group_index > 0) begin : g_propagate_boundary
      (* keep = 1 *) logic propagate_value;
      assign propagate_value = &bit_propagate[p_low +: p_bits];
      assign group_propagate[group_index] = propagate_value;
    end else begin : g_first_propagate
      assign group_propagate[group_index] = &bit_propagate[p_low +: p_bits];
    end
  end
  for (genvar half_index = 0; half_index < 2; half_index++) begin : g_half
    localparam int p_low = 3 * half_index;
    assign half_generate[half_index] = group_generate[p_low+2] ||
        (group_propagate[p_low+2] && group_generate[p_low+1]) ||
        (group_propagate[p_low+2] && group_propagate[p_low+1] && group_generate[p_low]);
    assign half_propagate[half_index] = &group_propagate[p_low +: 3];
  end
  assign coordinate_low_less = half_generate[1] || (half_propagate[1] && half_generate[0]);
  assign coordinate_high_zero = i_coordinate[33:16] == 18'd0;
  assign o_in_bounds = coordinate_high_zero && coordinate_low_less;
endmodule

// 三个无符号地址分量进行完整宽度组合加法。
module vector_read_address_add #(
`ifdef ASIC_SYNTHESIS
  parameter bit p_use_dsp = 1'b0,
`elsif XILINX_FPGA
  parameter bit p_use_dsp = 1'b1,
`elsif SYNTHESIS
  parameter bit p_use_dsp = 1'b1,
`else
  parameter bit p_use_dsp = 1'b0,
`endif
  parameter bit p_preserve_groups = 1'b1
) (
  input logic clk,
  input logic [31:0] i_base,
  input logic [31:0] i_offset,
  input logic [15:0] i_channel,
  output logic [31:0] o_address,
  output logic [1:0] o_carry
);
  logic [33:0] base_extended, offset_extended, channel_extended;
  logic [33:0] address_sum, address_carry, address_result;
  logic unused_address_carry;

  // 三项先压缩成两项，再以三位分组求和，保留两个地址进位位。
  assign base_extended = {2'b00, i_base};
  assign offset_extended = {2'b00, i_offset};
  assign channel_extended = {18'd0, i_channel};
  assign address_sum = base_extended ^ offset_extended ^ channel_extended;
  assign address_carry = ((base_extended & offset_extended) |
      (base_extended & channel_extended) | (offset_extended & channel_extended)) << 1;
  parallel_prefix_add #(.p_width(34), .p_group_width(3), .p_preserve_groups(p_preserve_groups)) u_address_sum (
      .i_a(address_sum), .i_b(address_carry), .i_carry(1'b0),
      .o_sum(address_result), .o_carry(unused_address_carry)
  );
  assign {o_carry, o_address} = address_result;
endmodule

// 权重采用异步读取，计算单元在原有发射周期接收当前卷积核位置的数据。
module vector_weight_bank #(
  parameter integer DEPTH=49,
  parameter integer ADDRESS_BITS=$clog2(DEPTH)>0 ? $clog2(DEPTH) : 1
) (
  input wire clk, write_enable,
  input wire [31:0] write_address, read_address,
  input wire signed [7:0] write_data,
  output wire signed [7:0] read_data
);
  reg signed [7:0] data [DEPTH];
  always @(posedge clk)
    if(write_enable && write_address<DEPTH)
      data[ADDRESS_BITS'(write_address)]<=write_data;
  assign read_data=read_address<DEPTH ? data[ADDRESS_BITS'(read_address)] : 8'sd0;
endmodule

// 每个卷积核位置保存全部通道，字节写入与整行同步读取共用存储数组。
module vector_weight_store #(
    parameter int p_channels = 16,
    parameter int p_depth = 49,
    parameter int p_address_width = (p_depth < 2) ? 1 : $clog2(p_depth)
) (
    input logic clk,
    input logic i_wr_en,
    input logic [31:0] i_wr_tap,
    input logic [p_channels-1:0] i_wr_mask,
    input logic [8*p_channels-1:0] i_wr_data,
    input logic [31:0] i_rd_tap,
    output logic [8*p_channels-1:0] o_rd_data
);
    //! 0. 存储端口和读取状态
    //! -----------------------

    logic storage_i_wr_en;
    logic [p_address_width-1:0] storage_i_wr_addr;
    logic [8*p_channels-1:0] storage_i_wr_data;
    logic [p_channels-1:0] storage_i_wr_mask;
    logic [0:0] storage_i_rd_en;
    logic [0:0][p_address_width-1:0] storage_i_rd_addr;
    logic [0:0][8*p_channels-1:0] storage_o_rd_data;
    logic read_in_range;

    //! 1. 生成存储地址和字节写入条件
    //! -------------------------------

    assign storage_i_wr_en = i_wr_en && (i_wr_tap < 32'(p_depth));
    assign storage_i_wr_addr = p_address_width'(i_wr_tap);
    assign storage_i_wr_data = i_wr_data;
    assign storage_i_wr_mask = i_wr_mask;
    assign storage_i_rd_en = 1'b1;
    assign storage_i_rd_addr[0] = p_address_width'(i_rd_tap);

    //! 2. 保存读取结果和地址有效状态
    //! -------------------------------

    regfile #(
        .p_data_width(8*p_channels), .p_depth(p_depth), .p_addr_width(p_address_width),
        .p_write_unit(8), .p_read_ports(1), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_storage (
        .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
        .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
        .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
    );
    always_ff @(posedge clk) begin
        read_in_range <= i_rd_tap < 32'(p_depth);
    end

    //! 3. 输出读取的权重行
    //! ---------------------

    assign o_rd_data = read_in_range ? storage_o_rd_data[0] : '0;
endmodule

// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按总线字接收结果，两个字节银行组分别保存待发数据与当前事务。
module vector_banked_writeback #(
  parameter int TILE = 16,
  parameter int BUS_WIDTH = 64,
  parameter int COUNT_WIDTH = $clog2(4*TILE+1),
  parameter bit p_coalesce_bytes_only = 1'b1,
`ifdef XILINX_FPGA
  parameter bit p_use_dsp = 1'b1
`else
  parameter bit p_use_dsp = 1'b0
`endif
) (
  input  logic clk, rst_n,
  input  logic request_valid,
  output logic request_ready,
  input  logic [31:0] request_address,
  input  logic [COUNT_WIDTH-1:0] request_bytes,
  input  logic request_byte_output,
  input  logic [32*TILE-1:0] result_words,
  input  logic request_coalesce,
  input  logic request_last,
  input  logic flush,
  output logic busy, done, error,
  output logic wr_req, wr_start,
  input  logic wr_granted,
  output logic [31:0] wr_base_addr, wr_row_stride, wr_rows_to_write,
  output logic [7:0] wr_burst_len_m1,
  output logic [BUS_WIDTH-1:0] src_wdata,
  output logic [BUS_WIDTH/8-1:0] src_wmask,
  output logic src_wvalid,
  input  logic src_wready, wr_done, wr_error
);
  //! 0. 内部定义
  //! ----------------

  localparam int BUS_BYTES = BUS_WIDTH/8;
  localparam int BUS_SHIFT = $clog2(BUS_BYTES);
  localparam int CAPACITY = 4*TILE;
  localparam int GROUP_COUNT = (CAPACITY+BUS_BYTES-1)/BUS_BYTES;
  localparam int ROW_WIDTH = GROUP_COUNT<=1 ? 1 : $clog2(GROUP_COUNT);
  localparam int BANK_DEPTH = 1 << (ROW_WIDTH+1);
  localparam int ARITH_WIDTH = COUNT_WIDTH>BUS_SHIFT ? COUNT_WIDTH+1 : BUS_SHIFT+2;
  typedef enum logic [1:0] {IDLE, REQUEST, DATA, RESPONSE} state_t;
  state_t c_st, n_st;
  logic pending_slot, payload_slot;
  logic [31:0] pending_address, payload_address;
  logic [32:0] pending_end_address;
  (* use_dsp = p_use_dsp ? "yes" : "no" *) logic [32:0] request_end_address;
  logic [COUNT_WIDTH-1:0] pending_bytes, total_bytes, written_bytes;
  logic pending_last;
  logic [7:0] payload_burst_length;
  logic [ROW_WIDTH:0] beats_remaining;
  logic [BUS_BYTES-1:0] first_mask, last_mask, final_mask;
  logic [BUS_SHIFT-1:0] final_count;
  logic [BUS_SHIFT-1:0] lane_offset, first_bank;
  logic [COUNT_WIDTH:0] appended_bytes;
  logic append_compatible, append_fits, append_allowed;
  logic request_prepared, prepared_compatible, prepared_fits;
  logic publish_fire, request_fire, data_fire;
  logic copy_active, copy_word_fire, copy_cancel, copy_last;
  logic [ROW_WIDTH-1:0] copy_source_q, copy_row_q;
  logic [BUS_SHIFT-1:0] copy_offset_q;
  logic [ROW_WIDTH-1:0] source_group, destination_row;
  logic [BUS_SHIFT-1:0] destination_offset;
  logic [ARITH_WIDTH-1:0] copy_remaining, remaining, available, beat_bytes, pending_span;
  logic [BUS_SHIFT:0] copy_count;
  logic [BUS_WIDTH-1:0] source_word, bank_word;
  logic [BUS_WIDTH-1:0] store_rotation [0:BUS_SHIFT];
  logic [BUS_WIDTH-1:0] output_rotation [0:BUS_SHIFT];
  logic [ROW_WIDTH-1:0] read_row [BUS_BYTES];
  logic read_enable;

  //! 1. 接收资格与传输数量
  //! ------------------------

  assign request_end_address = {1'b0, request_address} + 33'(request_bytes);
  assign appended_bytes = {1'b0, pending_bytes} + {1'b0, request_bytes};
  assign append_compatible = pending_bytes==0 ||
      (request_coalesce && (!p_coalesce_bytes_only || request_byte_output) &&
       !pending_end_address[32] && request_address==pending_end_address[31:0]);
  assign append_fits = appended_bytes <= (COUNT_WIDTH+1)'(CAPACITY);
  assign copy_cancel = copy_active && (!request_valid || flush);
  assign publish_fire = (c_st==IDLE || (c_st==RESPONSE && wr_done && !wr_error)) &&
      pending_bytes!=0 && (!copy_active || copy_cancel) &&
      (pending_last || flush || pending_bytes==COUNT_WIDTH'(CAPACITY) ||
       (request_valid && request_prepared && (!prepared_compatible || !prepared_fits)));
  assign append_allowed = request_prepared && !flush && !pending_last &&
      prepared_compatible && prepared_fits && !publish_fire;
  assign source_group = copy_active ? copy_source_q : '0;
  assign destination_row = copy_active ? copy_row_q : ROW_WIDTH'(pending_bytes >> BUS_SHIFT);
  assign destination_offset = copy_active ? copy_offset_q : BUS_SHIFT'(pending_bytes);
  assign copy_remaining = ARITH_WIDTH'(request_bytes) -
      (ARITH_WIDTH'(source_group) << BUS_SHIFT);
  assign copy_count = copy_remaining > ARITH_WIDTH'(BUS_BYTES) ?
      (BUS_SHIFT+1)'(BUS_BYTES) : (BUS_SHIFT+1)'(copy_remaining);
  assign copy_last = copy_remaining <= ARITH_WIDTH'(BUS_BYTES);
  assign copy_word_fire = request_valid && append_allowed;
  // 最后一个总线字存入银行时确认请求，生产方在此之前保存地址、长度和数据。
  assign request_ready = append_allowed && copy_last;
  assign request_fire = request_valid && request_ready;
  assign data_fire = c_st==DATA && src_wready;
  assign remaining = ARITH_WIDTH'(total_bytes) - ARITH_WIDTH'(written_bytes);
  assign available = ARITH_WIDTH'(BUS_BYTES) - ARITH_WIDTH'(lane_offset);
  assign beat_bytes = remaining<available ? remaining : available;
  assign pending_span = ARITH_WIDTH'(pending_address[BUS_SHIFT-1:0]) +
      ARITH_WIDTH'(pending_bytes) + ARITH_WIDTH'(BUS_BYTES-1);
  assign read_enable = publish_fire || (data_fire && remaining>available);

  //! 2. 按银行保存与读取数据
  //! --------------------------

  // 源地址的低位为固定通道号，每个银行只选择当前组中的一个字节。
  for (genvar bank=0; bank<BUS_BYTES; bank++) begin : g_source_bank
    logic [7:0] word_group [1<<ROW_WIDTH];
    logic [7:0] byte_group [1<<ROW_WIDTH];
    for (genvar group=0; group<(1<<ROW_WIDTH); group++) begin : g_group
      localparam int INDEX = group*BUS_BYTES+bank;
      if (INDEX<CAPACITY) begin : g_word
        assign word_group[group] = result_words[8*INDEX+:8];
      end else begin : g_word_padding
        assign word_group[group] = '0;
      end
      if (INDEX<TILE) begin : g_byte
        assign byte_group[group] = result_words[32*INDEX+:8];
      end else begin : g_byte_padding
        assign byte_group[group] = '0;
      end
    end
    assign source_word[8*bank+:8] = request_byte_output ? byte_group[source_group] : word_group[source_group];
  end
  assign store_rotation[0] = source_word;
  for (genvar stage=0; stage<BUS_SHIFT; stage++) begin : g_store_rotation
    localparam int SHIFT_BITS = 8*(1<<stage);
    assign store_rotation[stage+1] = destination_offset[stage] ?
        {store_rotation[stage][BUS_WIDTH-SHIFT_BITS-1:0],
         store_rotation[stage][BUS_WIDTH-1:BUS_WIDTH-SHIFT_BITS]} : store_rotation[stage];
  end
  for (genvar bank=0; bank<BUS_BYTES; bank++) begin : g_storage_bank
    logic [BUS_SHIFT-1:0] source_lane;
    logic [ROW_WIDTH-1:0] write_row, next_read_row;
    logic [ROW_WIDTH:0] write_address, read_address;
    logic write_enable;
    logic [7:0] read_data;
    (* ram_style = "block" *) logic [7:0] memory [0:BANK_DEPTH-1];

    assign source_lane = BUS_SHIFT'(bank) - destination_offset;
    assign write_row = destination_row + ROW_WIDTH'(BUS_SHIFT'(bank)<destination_offset);
    assign write_address = {pending_slot, write_row};
    assign write_enable = copy_word_fire && {1'b0, source_lane}<copy_count;
    assign next_read_row = written_bytes==0 && first_bank!=0 ?
        ROW_WIDTH'(BUS_SHIFT'(bank)<first_bank) : read_row[bank]+ROW_WIDTH'(1);
    assign read_address = publish_fire ? {pending_slot, {ROW_WIDTH{1'b0}}} :
        {payload_slot, next_read_row};
    always_ff @(posedge clk) begin
      if (write_enable) memory[write_address] <= store_rotation[BUS_SHIFT][8*bank+:8];
      if (read_enable) read_data <= memory[read_address];
    end
    assign bank_word[8*bank+:8] = read_data;
    always_ff @(posedge clk) begin
      if (publish_fire) read_row[bank] <= '0;
      else if (data_fire && remaining>available) read_row[bank] <= next_read_row;
    end
  end

  //! 3. 更新接收与事务状态
  //! ------------------------

  // 请求保持有效期间先保存地址连续性与容量检查，复制循环只使用寄存结果。
  // 提交或发布会改变待发缓冲的边界，随后为下一项请求重新计算接收资格。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) request_prepared <= 1'b0;
    else if (flush || !request_valid || request_fire || publish_fire)
      request_prepared <= 1'b0;
    else if (!request_prepared) request_prepared <= 1'b1;
  end
  always_ff @(posedge clk) begin
    if (!request_prepared && request_valid && !flush && !publish_fire) begin
      prepared_compatible <= append_compatible;
      prepared_fits <= append_fits;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      copy_active <= 1'b0;
      copy_source_q <= '0;
      copy_row_q <= '0;
      copy_offset_q <= '0;
    end else if (copy_cancel || publish_fire) begin
      copy_active <= 1'b0;
    end else if (copy_word_fire) begin
      copy_active <= !copy_last;
      copy_source_q <= source_group + ROW_WIDTH'(1);
      copy_row_q <= destination_row + ROW_WIDTH'(1);
      copy_offset_q <= destination_offset;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pending_slot <= 1'b0;
      pending_address <= '0;
      pending_end_address <= '0;
      pending_bytes <= '0;
      pending_last <= 1'b0;
    end else if (publish_fire) begin
      pending_slot <= !pending_slot;
      pending_bytes <= '0;
      pending_last <= 1'b0;
    end else if (request_fire) begin
      if (pending_bytes==0) pending_address <= request_address;
      pending_end_address <= request_end_address;
      pending_bytes <= appended_bytes[COUNT_WIDTH-1:0];
      pending_last <= request_last || !request_coalesce || (p_coalesce_bytes_only && !request_byte_output);
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) c_st <= IDLE;
    else c_st <= n_st;
  end
  always_comb begin
    n_st = c_st;
    case (c_st)
      IDLE: if (publish_fire) n_st = REQUEST;
      REQUEST: if (wr_granted) n_st = DATA;
      DATA: if (data_fire && remaining<=available) n_st = RESPONSE;
      RESPONSE: if (wr_done) n_st = publish_fire ? REQUEST : IDLE;
      default: n_st = IDLE;
    endcase
  end
  always_ff @(posedge clk) begin
    if (publish_fire) begin
      payload_slot <= pending_slot;
      payload_address <= {pending_address[31:BUS_SHIFT], {BUS_SHIFT{1'b0}}};
      payload_burst_length <= 8'((pending_span >> BUS_SHIFT)-1'b1);
      beats_remaining <= (ROW_WIDTH+1)'(pending_span >> BUS_SHIFT);
      src_wmask <= first_mask;
      last_mask <= final_mask;
      total_bytes <= pending_bytes;
      written_bytes <= '0;
      lane_offset <= pending_address[BUS_SHIFT-1:0];
      first_bank <= BUS_SHIFT'(0)-pending_address[BUS_SHIFT-1:0];
    end else if (data_fire) begin
      written_bytes <= written_bytes + COUNT_WIDTH'(beat_bytes);
      lane_offset <= '0;
      beats_remaining <= beats_remaining - (ROW_WIDTH+1)'(1);
      src_wmask <= beats_remaining==(ROW_WIDTH+1)'(2) ? last_mask : '1;
    end
  end

  //! 4. 输出与握手
  //! ----------------

  assign output_rotation[0] = bank_word;
  for (genvar stage=0; stage<BUS_SHIFT; stage++) begin : g_output_rotation
    localparam int SHIFT_BITS = 8*(1<<stage);
    assign output_rotation[stage+1] = first_bank[stage] ?
        {output_rotation[stage][SHIFT_BITS-1:0], output_rotation[stage][BUS_WIDTH-1:SHIFT_BITS]} :
        output_rotation[stage];
  end
  assign src_wdata = output_rotation[BUS_SHIFT];
  assign src_wvalid = c_st==DATA;
  assign final_count = pending_address[BUS_SHIFT-1:0] + BUS_SHIFT'(pending_bytes);
  for (genvar lane=0; lane<BUS_BYTES; lane++) begin : g_byte_mask
    logic [BUS_SHIFT-1:0] distance;
    assign distance = BUS_SHIFT'(lane)-pending_address[BUS_SHIFT-1:0];
    assign first_mask[lane] = BUS_SHIFT'(lane)>=pending_address[BUS_SHIFT-1:0] &&
        ARITH_WIDTH'(pending_bytes)>ARITH_WIDTH'(distance);
    assign final_mask[lane] = final_count==0 || BUS_SHIFT'(lane)<final_count;
  end
  assign busy = c_st!=IDLE || pending_bytes!=0 || copy_active || request_prepared;
  assign done = c_st==RESPONSE && wr_done;
  assign error = done && wr_error;
  assign wr_req = c_st==REQUEST;
  assign wr_start = wr_req && wr_granted;
  assign wr_base_addr = payload_address;
  assign wr_row_stride = 32'd0;
  assign wr_rows_to_write = 32'd1;
  assign wr_burst_len_m1 = payload_burst_length;

`ifdef NPU_SIM_ASSERT
  initial begin
    assert(TILE>=1 && BUS_BYTES>=4 && (BUS_BYTES&(BUS_BYTES-1))==0);
    assert(COUNT_WIDTH>0 && COUNT_WIDTH<=16);
  end
  always @(posedge clk) if (rst_n) begin
    assert(!(publish_fire && copy_word_fire));
    if (copy_word_fire) assert(appended_bytes<=(COUNT_WIDTH+1)'(CAPACITY));
    if (request_fire) assert(request_prepared && copy_last);
    if (request_prepared && request_valid && !flush) begin
      assert(prepared_compatible == append_compatible);
      assert(prepared_fits == append_fits);
    end
    if (c_st!=IDLE && pending_bytes!=0) assert(payload_slot!=pending_slot);
    if (data_fire) begin
      assert(beat_bytes!=0);
      assert(beats_remaining!=0);
      for (int lane=0;lane<BUS_BYTES;lane++) begin
        assert(src_wmask[lane] == (BUS_SHIFT'(lane)>=lane_offset &&
            remaining>ARITH_WIDTH'(BUS_SHIFT'(lane)-lane_offset)));
      end
    end
  end
`endif
endmodule

`default_nettype wire
