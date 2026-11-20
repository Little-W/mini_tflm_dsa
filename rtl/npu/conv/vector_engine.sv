// SPDX-License-Identifier: Apache-2.0
// 根据描述符执行向量计算、量化 Add、深度卷积和池化。
module vector_engine #(
  parameter int TILE = 16,
  parameter int BUS_WIDTH = 32,
  parameter int DMA_SIZE = 4*TILE,
  parameter int PE_COUNT = (TILE < 8) ? TILE : 8,
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
  input logic signed [15:0] win_rsp_data[4],
  input logic [3:0] win_rsp_mask,
  input logic win_rsp_last,win_rsp_error,win_busy,

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
  localparam int BUS_BYTES=BUS_WIDTH/8;
  localparam int BUS_SHIFT=$clog2(BUS_BYTES);
  typedef enum logic [5:0] {
    IDLE, CHECK, CONFIGURE, TILE_INIT, LOAD_REQ, LOAD_WAIT,
    OUTPUT_INIT, TAP_CHECK, WINDOW_WAIT, EXECUTE, TAP_NEXT,
    QUANT_INIT, AVG_START, AVG_WAIT, POOL_STORE, WRITE_PREP,
    OUTPUT_NEXT, VECTOR_INIT, VECTOR_NEXT, VECTOR_REDUCE, FAILED, DONE,
    ADD_MULT, ADD_DRAIN, ADD_ROUND, ADD_SUM, ADD_STORE,
    POOL_LOAD_PREP, POOL_LOAD_REQ, POOL_LOAD_WAIT,
    DRAIN, DRAIN_TILE, SOFT_START, SOFT_RUN, SOFT_LUT_REQ, SOFT_LUT_WAIT,
    CHECK_WAIT, QUANT_STREAM, EXECUTE_COMMIT, ADD_ROUND_WAIT, AVG_POWER_STORE, POOL_LOAD_DRAIN
  } state_t;
  typedef enum logic [2:0] {LD_WEIGHT, LD_BIAS, LD_MULT, LD_SHIFT, LD_A, LD_B, LD_LUT} load_t;
  state_t state;
  load_t load_kind;
  vector_engine_cfg_t c;
  logic spatial, depthwise, binary_vector, add_s8, softmax_s8, byte_output;
  localparam int ACTIVE_COUNT_W = $clog2(TILE + 1);
  localparam int TAP_LIMIT = MAX_TAPS > POOL_MAX_TAPS ? MAX_TAPS : POOL_MAX_TAPS;
  localparam int TAP_COUNT_W = $clog2(TAP_LIMIT + 1);
  logic [31:0] channels, position;
  logic [15:0] channel_base;
  logic [ACTIVE_COUNT_W-1:0] active;
  logic [TAP_COUNT_W-1:0] taps;
  logic [15:0] ox, oy;
  logic [TAP_COUNT_W-1:0] kx,ky;
  logic [TAP_COUNT_W-1:0] kernel_last_column;
  logic [TAP_COUNT_W-1:0] tap, load_tap, valid_taps;
  localparam int TILE_INDEX_W = $clog2(TILE + PE_COUNT + 1);
  localparam int INPUT_INDEX_W = $clog2(DMA_SIZE);
  logic [31:0] vector_offset;
  logic [ACTIVE_COUNT_W:0] vector_low_sum;
  logic vector_high_equal, vector_high_less;
  logic vector_high_next_equal, vector_high_next_less;
  logic [ACTIVE_COUNT_W:0] vector_remaining_low;
  logic [ACTIVE_COUNT_W-1:0] vector_next_active;
  logic [31-ACTIVE_COUNT_W:0] vector_high_increment;
  logic [31-ACTIVE_COUNT_W:0] vector_remaining_carry_needed;
  logic [31-ACTIVE_COUNT_W:0] vector_remaining_carry_generated;
  logic [31-ACTIVE_COUNT_W:0] vector_remaining_carry_expected;
  logic vector_remaining_high_zero, unused_vector_remaining_carry;
  logic vector_has_more;
  logic [TILE_INDEX_W-1:0] compute_index, quant_index, reduce_index;
  logic [31:0] fetch_tap_offset, load_tap_offset, position_offset, pool_byte_offset;
  logic signed [15:0] input_buf [DMA_SIZE], rhs_buf [TILE];
  logic signed [15:0] input_bank_data [BUS_BYTES];
  logic weights_i_wr_en;
  logic [31:0] weights_i_wr_tap, weights_i_rd_tap;
  logic [TILE-1:0] weights_i_wr_mask;
  logic [8*TILE-1:0] weights_i_wr_data, weights_o_rd_data;
  logic weight_tap_advance;
  logic [TAP_COUNT_W-1:0] weight_tap_nxt;
  logic unused_weight_tap_carry;

  wire signed [7:0] weight_tap_data [TILE];
  logic signed [31:0] bias_buf [TILE];
  logic signed [31:0] acc_buf [TILE], result_buf [TILE];
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
  logic signed [63:0] add_product, add_rounded;
  logic signed [31:0] reduce_acc, reduce_next;
  logic signed [33:0] input_y, input_x, input_origin_x, input_origin_y;
  logic in_bounds, param_bad, param_bad_seen;
  logic [63:0] input_bytes,output_bytes,weight_bytes,parameter_bytes;
  wire [31:0] checked_kernel_count,checked_position_count;
  wire [63:0] kernel_count={32'd0,checked_kernel_count};
  wire [63:0] position_count={32'd0,checked_position_count};
  logic config_check_ready,config_check_done,config_check_error;
  vector_config_check #(.TILE(TILE),.MAX_TAPS(MAX_TAPS),.POOL_MAX_TAPS(POOL_MAX_TAPS)) u_config_check (
    .clk,.rst_n,.start(state==CHECK),.cfg(c),.ready(config_check_ready),
    .done(config_check_done),.error(config_check_error),
    .kernel_count(checked_kernel_count),.position_count(checked_position_count),
    .input_bytes,.output_bytes,.weight_bytes);
  assign parameter_bytes=64'(channels)<<2;
  logic [31:0] load_bytes;
  logic signed [31:0] q_accumulator, q_multiplier;
  logic signed [63:0] q_product, q_rounded;
  logic [8:0] q_offset_low;
  logic q_offset_high_zero, q_offset_high_ones, q_offset_high_negative;
  logic q_offset_increment, q_offset_decrement, q_offset_keep_high;
  logic q_offset_fits_s8;
  logic q_offset_below_s8, q_offset_above_s8;
  logic q_below_min, q_above_max;
  logic signed [31:0] q_clamped_data;
  logic [5:0] q_right_0, q_right_1, q_right_2, q_right_3;
  logic [5:0] q_valid;
  logic [TILE_INDEX_W-1:0] q_index_0, q_index_1, q_index_2, q_index_3, q_index_4, q_index_5, q_issue, q_count;
  logic q_active;
  logic [31:0] write_origin, write_total;
  wire writeback_ready, writeback_busy, writeback_done, writeback_error;
  wire [32*TILE-1:0] writeback_words;
  for (genvar word_index=0;word_index<TILE;word_index++) begin : g_writeback_word
    assign writeback_words[32*word_index+:32]=result_buf[word_index];
  end
  vector_writeback #(.TILE(TILE),.BUS_WIDTH(BUS_WIDTH)) u_writeback (
    .clk,.rst_n,.request_valid(state==WRITE_PREP),.request_ready(writeback_ready),
    .request_address(write_origin),.request_bytes($clog2(4*TILE+1)'(write_total)),
    .request_byte_output(byte_output),.result_words(writeback_words),
    .busy(writeback_busy),.done(writeback_done),.error(writeback_error),
    .wr_req,.wr_start,.wr_granted,.wr_base_addr,.wr_row_stride,.wr_rows_to_write,
    .wr_burst_len_m1,.src_wdata,.src_wmask,.src_wvalid,.src_wready,.wr_done,.wr_error);
  logic avg_negative, avg_power_two;
  logic avg_done;
  logic [5:0] avg_shift;
  localparam int AVG_SCALE_BITS = 8+$clog2(POOL_MAX_TAPS+1);
`ifdef ASIC_SYNTHESIS
  logic [AVG_SCALE_BITS:0] avg_reciprocal [0:POOL_MAX_TAPS];
`else
  (* rom_style = "block" *) logic [AVG_SCALE_BITS:0] avg_reciprocal [0:POOL_MAX_TAPS];
`endif
  logic [AVG_SCALE_BITS:0] avg_reciprocal_data;
  logic [AVG_SCALE_BITS-1:0] avg_numerator_q;
  logic [7:0] avg_estimate_q, avg_quotient_q, avg_magnitude_q;
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
  logic [1:0] read_bank,wf_bank,input_bank_mask;
  logic [3:0] input_ready,input_reserved;
  logic window_slot_available, input_reservations_clear;
  logic [INPUT_INDEX_W-1:0] input_read_base,input_response_base;
  logic [31:0] window_received;
  logic [2:0] window_response_count;
  logic [31:0] window_count_i_value, window_count_i_increment, window_count_i_target;
  logic window_count_i_carry, window_count_o_equal;
  logic window_response_fire,window_request_fire;
  logic window_fetch_enabled, window_fetch_in_bounds, window_fetch_advance;
  logic [31:0] fetch_position;
  logic [TAP_COUNT_W-1:0] fetch_tap;
  logic [15:0] fetch_ox;
  logic [TAP_COUNT_W-1:0] fetch_kx;
  logic signed [33:0] fetch_x, fetch_y, fetch_origin_x, fetch_origin_y;
  // 完成条件逐位检查所需进位，保留接收计数的三十二位回绕行为。
  assign window_count_i_value = window_received;
  assign window_count_i_increment = {29'd0, window_response_count};
  assign window_count_i_target = 32'(active);
  assign window_count_i_carry = 1'b0;
  add_equal #(.p_width(32)) u_window_count_equal (
      .i_a(window_count_i_value), .i_b(window_count_i_increment),
      .i_target(window_count_i_target), .i_carry_in(window_count_i_carry),
      .o_equal(window_count_o_equal)
  );
  logic next_window_valid;
  logic signed [33:0] next_window_x, next_window_y;
  wire kernel_column_end=kx==kernel_last_column;
  wire signed [33:0] next_column_x=input_x+$signed(34'(c.image.dilation_w));
  wire signed [33:0] next_row_y=input_y+$signed(34'(c.image.dilation_h));
  logic [16:0] next_column_low, next_row_low;
  logic next_column_high_zero, next_row_high_zero;
  logic next_column_valid, next_row_valid;

  // 图像尺寸为十六位，坐标范围由低位和高位条件并行检查。
  // 低位加法进位只选择原坐标高位的零值或全一值，保留完整坐标回绕行为。
  assign next_column_low = {1'b0, input_x[15:0]} + {1'b0, c.image.dilation_w};
  assign next_row_low = {1'b0, input_y[15:0]} + {1'b0, c.image.dilation_h};
  assign next_column_high_zero = next_column_low[16] ? (&input_x[33:16]) : !(|input_x[33:16]);
  assign next_row_high_zero = next_row_low[16] ? (&input_y[33:16]) : !(|input_y[33:16]);
  assign next_column_valid = next_column_high_zero && (next_column_low[15:0] < c.image.input_w) &&
      !(|input_y[33:16]) && (input_y[15:0] < c.image.input_h);
  assign next_row_valid = !(|input_origin_x[33:16]) && (input_origin_x[15:0] < c.image.input_w) &&
      next_row_high_zero && (next_row_low[15:0] < c.image.input_h);
  logic soft_ready, soft_done, soft_exp_we, soft_out_we;
  logic [1:0] soft_error;
  logic [$clog2(TILE)-1:0] soft_input_index, soft_exp_index, soft_out_index;
  logic soft_lut_req_valid, soft_lut_req_ready, soft_lut_rsp_valid;
  logic [7:0] soft_lut_index;
  logic [31:0] soft_lut_data;
  logic signed [31:0] soft_exp_data, soft_mul_a, soft_mul_b;
  logic signed [7:0] soft_out_data;
  logic signed [31:0] multiplier_a, multiplier_b;
  logic signed [63:0] multiplier_product;
  logic global_pool;
  logic [TAP_COUNT_W-1:0] pool_offset;
  logic [INPUT_INDEX_W:0] pool_pixels, pool_received, pool_pixel;
  logic [INPUT_INDEX_W:0] pool_elements, pool_next_elements, pool_next_pixels, pool_input_index;
  logic [INPUT_INDEX_W:0] pool_row_columns, pool_row_remaining;
  wire pool_response_fire=state==POOL_LOAD_WAIT && rd_valid[0];
  logic [BUS_SHIFT:0] pool_beat_count;
  logic [INPUT_INDEX_W:0] pool_count_i_a, pool_count_i_b, pool_count_i_target;
  logic pool_count_i_carry;
  (* keep = 1 *) logic pool_count_o_equal, pool_received_equal;
  logic pool_receive_complete;

  // 单拍数量由已保存的行长度决定，完成条件在响应到达前并行计算。
  assign pool_beat_count = pool_row_remaining>BUS_BYTES ? (BUS_SHIFT+1)'(BUS_BYTES) :
      (BUS_SHIFT+1)'(pool_row_remaining);
  assign pool_count_i_a = pool_received;
  assign pool_count_i_b = (INPUT_INDEX_W+1)'(pool_beat_count);
  assign pool_count_i_target = pool_elements;
  assign pool_count_i_carry = 1'b0;
  assign pool_received_equal = pool_received == pool_elements;
  assign pool_receive_complete = rd_valid[0] ? pool_count_o_equal : pool_received_equal;
  add_equal #(.p_width(INPUT_INDEX_W+1)) u_pool_count_equal (
      .i_a(pool_count_i_a), .i_b(pool_count_i_b), .i_target(pool_count_i_target),
      .i_carry_in(pool_count_i_carry), .o_equal(pool_count_o_equal)
  );
  localparam int POOL_ROW_W=INPUT_INDEX_W>BUS_SHIFT ? INPUT_INDEX_W-BUS_SHIFT : 1;
  logic [BUS_BYTES-1:0] pool_bank_valid;
  logic [POOL_ROW_W-1:0] pool_bank_row[BUS_BYTES];
  logic signed [15:0] pool_bank_data[BUS_BYTES];

  assign spatial = c.op <= MINPOOL_S8;
  assign depthwise = c.op == DW_S8;
  assign add_s8 = c.op == ADD_S8;
  assign softmax_s8 = c.op == SOFTMAX_S8;
  assign byte_output = spatial || add_s8 || softmax_s8;
  assign binary_vector = c.op == VEC_DOT || c.op == VEC_HADAMARD || add_s8;

  // 有效通道数只影响低位；高位比较与低位加法并行执行，保留三十二位回绕。
  assign vector_low_sum = {1'b0, vector_offset[ACTIVE_COUNT_W-1:0]} + {1'b0, active};
  assign vector_high_equal = vector_offset[31:ACTIVE_COUNT_W] == c.length[31:ACTIVE_COUNT_W];
  assign vector_high_less = vector_offset[31:ACTIVE_COUNT_W] < c.length[31:ACTIVE_COUNT_W];
  assign vector_high_next_equal =
      ((vector_offset[31:ACTIVE_COUNT_W] ^ c.length[31:ACTIVE_COUNT_W]) ==
       {(vector_offset[30:ACTIVE_COUNT_W] & ~c.length[30:ACTIVE_COUNT_W]), 1'b1});
  assign vector_high_next_less = (vector_high_less && !vector_high_next_equal) ||
      ((&vector_offset[31:ACTIVE_COUNT_W]) && (|c.length[31:ACTIVE_COUNT_W]));
  assign vector_has_more = vector_low_sum[ACTIVE_COUNT_W] ?
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
  assign vector_next_active = vector_remaining_high_zero &&
      vector_remaining_low[ACTIVE_COUNT_W-1:0] < ACTIVE_COUNT_W'(TILE) ?
      vector_remaining_low[ACTIVE_COUNT_W-1:0] : ACTIVE_COUNT_W'(TILE);
  // 配置检查保证量化偏移和激活范围为 S8，低八位加法保留输出字节。
  // 高五十六位并行检查进位、借位和符号，保留完整六十四位回绕行为。
  assign q_offset_low = {1'b0, q_rounded[7:0]} + {1'b0, c.output_offset[7:0]};
  assign q_offset_increment = q_offset_low[8] && !c.output_offset[7];
  assign q_offset_decrement = !q_offset_low[8] && c.output_offset[7];
  assign q_offset_keep_high = q_offset_low[8] == c.output_offset[7];
  assign q_offset_high_zero =
      (q_offset_keep_high && q_rounded[63:8] == 56'd0) ||
      (q_offset_increment && q_rounded[63:8] == 56'hff_ffff_ffff_ffff) ||
      (q_offset_decrement && q_rounded[63:8] == 56'd1);
  assign q_offset_high_ones =
      (q_offset_keep_high && q_rounded[63:8] == 56'hff_ffff_ffff_ffff) ||
      (q_offset_increment && q_rounded[63:8] == 56'hff_ffff_ffff_fffe) ||
      (q_offset_decrement && q_rounded[63:8] == 56'd0);
  assign q_offset_high_negative = q_rounded[63] ^
      ((q_offset_increment && (&q_rounded[62:8])) ||
       (q_offset_decrement && !(|q_rounded[62:8])));
  assign q_offset_below_s8 = $signed(q_offset_low[7:0]) < $signed(c.activation_min[7:0]);
  assign q_offset_above_s8 = $signed(q_offset_low[7:0]) > $signed(c.activation_max[7:0]);
  assign q_offset_fits_s8 = q_offset_low[7] ? q_offset_high_ones : q_offset_high_zero;
  assign q_below_min = q_offset_fits_s8 ? q_offset_below_s8 : q_offset_high_negative;
  assign q_above_max = q_offset_fits_s8 ? q_offset_above_s8 : !q_offset_high_negative;
  assign ready = state == IDLE;
  assign done_valid = state == DONE;
  assign channels = {16'd0,c.image.input_c};
  assign in_bounds = input_y >= 0 && input_x >= 0 &&
                     input_y < $signed(34'(c.image.input_h)) &&
                     input_x < $signed(34'(c.image.input_w));
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) global_pool <= 1'b0;
    else if (state==IDLE && start)
      global_pool <= cfg.op <= MINPOOL_S8 && cfg.op != DW_S8 &&
                     cfg.image.output_h==1 && cfg.image.output_w==1 &&
                     cfg.image.kernel_h==cfg.image.input_h && cfg.image.kernel_w==cfg.image.input_w &&
                     cfg.image.pad_top==0 && cfg.image.pad_left==0 &&
                     cfg.image.dilation_h==1 && cfg.image.dilation_w==1;
  end
  // 输入存储容纳两个完整通道组或四个半通道组。
  // 槽位预留允许 DMA 提前发出请求，并按顺序接收响应。
  assign window_fetch_enabled=spatial && !global_pool &&
    (state==OUTPUT_INIT || state==TAP_CHECK || state==WINDOW_WAIT || state==QUANT_STREAM ||
     state==EXECUTE || state==EXECUTE_COMMIT || state==TAP_NEXT || state==QUANT_INIT || state==OUTPUT_NEXT ||
     state==AVG_START || state==AVG_POWER_STORE || state==AVG_WAIT || state==POOL_STORE || state==WRITE_PREP);
  assign window_fetch_in_bounds=fetch_x>=0 && fetch_y>=0 &&
    fetch_x<$signed(34'(c.image.input_w)) && fetch_y<$signed(34'(c.image.input_h));
  assign input_bank_mask=active<=TILE/2 ? 2'b11 : 2'b01;
  assign input_read_base=active<=TILE/2 ? (32'(read_bank)<<($clog2(TILE)-1)) : (32'(read_bank)<<$clog2(TILE));
  assign input_response_base=active<=TILE/2 ? (32'(win_rsp_tag)<<($clog2(TILE)-1)) : (32'(win_rsp_tag)<<$clog2(TILE));
  assign window_slot_available = window_fetch_enabled &&
      (fetch_position < 32'(position_count)) && window_fetch_in_bounds;
  assign win_req_valid = window_slot_available && !input_ready[wf_bank] && !input_reserved[wf_bank];
  assign win_req_p0=fetch_position;
  assign win_req_q0=fetch_tap_offset+channel_base;
  assign win_req_cols=active;
  assign win_req_tag=wf_bank;
  assign win_rsp_ready=1'b1;
  assign window_request_fire=win_req_valid && win_req_ready;
  assign window_response_fire=win_rsp_valid && win_rsp_ready;
  assign window_fetch_advance=window_request_fire ||
    (window_fetch_enabled && fetch_position<32'(position_count) &&
     !input_ready[wf_bank] && !input_reserved[wf_bank] && !window_fetch_in_bounds);
  assign input_reservations_clear = (state == IDLE && start) || (state == TILE_INIT) ||
      (state == FAILED && !rd_busy && !wr_busy && !win_busy && !writeback_busy && dma_cfg_ready);

  // 每个槽位并行生成接收和释放条件，就绪信号只参与最后的数据选择。
  // 同周期返回完成优先释放对应槽位，初始化和错误恢复同时清空全部槽位。
  for (genvar bank = 0; bank < 4; bank++) begin : g_input_reservation
    (* keep = 1 *) logic request_selected, release_selected;
    assign request_selected = window_slot_available && (wf_bank == 2'(bank)) && !input_ready[bank];
    assign release_selected = input_reservations_clear ||
        (window_response_fire && win_rsp_last && win_rsp_tag == 2'(bank));
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) input_reserved[bank] <= 1'b0;
      else input_reserved[bank] <= !release_selected &&
          (input_reserved[bank] || (win_req_ready && request_selected));
    end
  end
  always_comb begin
    window_response_count=0;
    for(int lane=0;lane<4;lane++) if(win_rsp_mask[lane])
      window_response_count=window_response_count+1'b1;
  end
  always_comb begin
    cache_power_two=1'b1;
    case (active)
      32'd1: cache_channel_shift=0;
      32'd2: cache_channel_shift=1;
      32'd4: cache_channel_shift=2;
      32'd8: cache_channel_shift=3;
      32'd16: cache_channel_shift=4;
      32'd32: cache_channel_shift=5;
      32'd64: cache_channel_shift=6;
      default: begin cache_channel_shift=0;cache_power_two=1'b0;end
    endcase
    pool_next_pixels=cache_power_two && active>=4 ? 32'(2*TILE)>>cache_channel_shift : 32'd1;
    if (pool_next_pixels>taps-pool_offset) pool_next_pixels=taps-pool_offset;
    pool_next_elements=cache_power_two ? pool_next_pixels<<cache_channel_shift : active;
    next_window_x=kernel_column_end ? input_origin_x : next_column_x;
    next_window_y=kernel_column_end ? next_row_y : input_y;
    // 两组候选坐标先分别检查范围，再选择下一个卷积核位置。
    next_window_valid=spatial && !global_pool && tap+1<taps &&
      (kernel_column_end ? next_row_valid : next_column_valid);
    avg_power_two=valid_taps!=0 && (valid_taps&(valid_taps-1))==0;
    avg_shift=0;
    for (int bit_index=0;bit_index<TAP_COUNT_W;bit_index++) if (valid_taps[bit_index]) avg_shift=6'(bit_index);
  end

  logic [32:0] dma_range_size [4];
  logic [3:0] unused_dma_range_carry;

  // 每个范围先选择起点和字节数，再使用一个加法器生成末端。
  for (genvar range_index = 0; range_index < 4; range_index++) begin : g_dma_range_end
    assign {unused_dma_range_carry[range_index], dma_range_end[range_index]} =
        {2'b00, dma_range_base[range_index]} + {1'b0, dma_range_size[range_index]};
  end
  always_comb begin
    // 配置等待期间持续提供描述符，接收边沿由就绪信号决定。
    dma_cfg_valid = state==CONFIGURE;
    dma_conv_enable = spatial;
    dma_range_enable = 1'b1;
    dma_conv_cfg = c.image;
    dma_conv_cfg.input_base = c.input_base;
    dma_conv_cfg.group_c = c.image.input_c;
    dma_conv_cfg.group_offset = 0;
    dma_conv_cfg.input_s16 = 0;
    dma_conv_cfg.windowed = spatial;
    dma_conv_cfg.prefetch_enable = 1;
    for (int i=0;i<4;i++) begin dma_range_base[i]=0; dma_range_size[i]=0; end
    if (global_pool && input_range_mode) begin
      dma_range_base[0]=c.input_base;dma_range_size[0]=input_bytes[32:0];
    end else if (depthwise) begin
      dma_range_base[0]=c.rhs_base; dma_range_size[0]=weight_bytes[32:0];
      if (c.bias_base!=0) begin
        dma_range_base[1]=c.bias_base; dma_range_size[1]=parameter_bytes[32:0];
      end
      dma_range_base[2]=c.multiplier_base; dma_range_size[2]=parameter_bytes[32:0];
      dma_range_base[3]=c.shift_base; dma_range_size[3]=parameter_bytes[32:0];
    end else if (!spatial) begin
      dma_range_base[0]=c.input_base; dma_range_size[0]=input_bytes[32:0];
      if (binary_vector || softmax_s8) begin
        dma_range_base[1]=c.rhs_base;
        dma_range_size[1]=softmax_s8 ? 33'd1024 : input_bytes[32:0];
      end
    end
  end

  assign rd_req = state==LOAD_REQ || state==POOL_LOAD_REQ || state==SOFT_LUT_REQ;
  assign rd_start = rd_req && rd_granted;
  logic [31:0] read_address_base, read_address_offset;
  logic [15:0] read_address_channel;
  logic [1:0] unused_read_address_carry;

  // 状态译码选择读取起点、偏移和通道号，各类读取共用地址加法器。
  vector_read_address_add u_read_address (
    .clk(clk), .i_base(read_address_base), .i_offset(read_address_offset),
    .i_channel(read_address_channel), .o_address(rd_base_addr),
    .o_carry(unused_read_address_carry)
  );
  always_comb begin
    rd_im2col = 1'b0;
    rd_p0 = 0;
    rd_q0 = 0;
    read_address_base = 32'd0;
    read_address_offset = 32'd0;
    read_address_channel = 16'd0;
    rd_row_stride = 0;
    rd_rows_to_read = 1;
    rd_valid_cols = active;
    rd_use_16bits = !spatial && c.vector_s16;
    load_bytes = active << rd_use_16bits;
    case (load_kind)
      LD_WEIGHT: begin
        read_address_base = c.rhs_base;
        read_address_offset = load_tap_offset;
        read_address_channel = channel_base;
        rd_use_16bits = 1'b0;
        load_bytes = active;
      end
      LD_BIAS, LD_MULT, LD_SHIFT: begin
        case (load_kind)
          LD_BIAS: read_address_base = c.bias_base;
          LD_MULT: read_address_base = c.multiplier_base;
          default: read_address_base = c.shift_base;
        endcase
        read_address_offset = {14'd0, channel_base, 2'b00};
        rd_use_16bits = 1'b0;
        load_bytes = active << 2;
        rd_valid_cols = active << 2;
      end
      LD_A: begin
        read_address_base = c.input_base;
        read_address_offset = vector_offset << c.vector_s16;
      end
      LD_B: begin
        read_address_base = c.rhs_base;
        read_address_offset = vector_offset << c.vector_s16;
      end
      default: begin
      end
    endcase
    rd_burst_len_m1 = 8'(((load_bytes+BUS_BYTES-1)>>BUS_SHIFT)-1);
    if (state==SOFT_LUT_REQ || state==SOFT_LUT_WAIT) begin
      read_address_base = c.rhs_base;
      read_address_offset = {22'd0, soft_lut_index, 2'b00};
      read_address_channel = 16'd0;
      rd_use_16bits=0;rd_valid_cols=4;rd_burst_len_m1=0;
    end
    if (state==POOL_LOAD_REQ || state==POOL_LOAD_WAIT) begin
      read_address_base = c.input_base;
      read_address_offset = pool_byte_offset;
      read_address_channel = channel_base;
      rd_use_16bits = 1'b0;
      if (channels==active) begin
        rd_rows_to_read=1;rd_valid_cols=pool_elements;rd_row_stride=0;
        rd_burst_len_m1=8'(((pool_elements+BUS_BYTES-1)>>BUS_SHIFT)-1);
      end else begin
        rd_rows_to_read=pool_pixels;rd_valid_cols=active;rd_row_stride=channels;
        rd_burst_len_m1=8'(((active+BUS_BYTES-1)>>BUS_SHIFT)-1);
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
  always_comb begin
    write_address_offset = 32'd0;
    case (state)
      EXECUTE_COMMIT: write_address_offset = vector_offset << 2;
      ADD_STORE: write_address_offset = vector_offset;
      // 空间位置与通道号共同组成行偏移。
      QUANT_STREAM, AVG_POWER_STORE, AVG_WAIT, POOL_STORE:
        write_address_offset = position_offset + {16'd0, channel_base};
      default: begin end
    endcase
  end
  assign write_origin_next = c.output_base + write_address_offset;

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
  generate if (PE_COUNT > 1 && (PE_COUNT & (PE_COUNT-1)) == 0 &&
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
  end endgenerate

  always_comb begin
    add_multiplier = add_stage==0 ? c.add.input1_multiplier :
                     add_stage==1 ? c.add.input2_multiplier : c.add.output_multiplier;
    // 公共左移量合入输入除数，保留完整定点商，每级只执行一次最近偶数舍入。
    add_right = add_stage==0 ? 6'(31-c.add.input1_shift-c.add.left_shift) :
                add_stage==1 ? 6'(31-c.add.input2_shift-c.add.left_shift) :
                               6'(31-c.add.output_shift);
    pe_op=PE_MADD;
    case (c.op)
      AVGPOOL_S8,VEC_SUM: pe_op=PE_SUM;
      MAXPOOL_S8,VEC_MAX: pe_op=PE_MAX;
      MINPOOL_S8,VEC_MIN: pe_op=PE_MIN;
      VEC_HADAMARD: pe_op=PE_MUL;
      default: ;
    endcase
  end
  assign pe_operand_en = (state == EXECUTE) && ((c.op != VEC_HADAMARD) || !writeback_busy);
  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_operand_select
    wire enabled=(TILE_INDEX_W+1)'(compute_index)+(TILE_INDEX_W+1)'(lane)<(TILE_INDEX_W+1)'(active);
    assign pe_a[lane]=enabled ? input_lane[lane] : 16'sd0;
    // 无效通道的 a 和 acc 已为零，各运算结果与 b 的取值无关。
    assign pe_b[lane]=depthwise ? 16'($signed(weight_lane[lane])) : rhs_lane[lane];
    assign pe_acc[lane]=enabled ? accum_lane[lane] : 32'sd0;
  end
  always_ff @(posedge clk) if (state==EXECUTE) pe_op_q<=pe_op;
  // 权重按卷积核位置整行保存，字节掩码允许每个通道独立接收 DMA 数据。
  // 提交当前计算结果时准备下一位置，使同步读取在下一次计算前完成。
  assign weights_i_wr_en = rst_n && (state == LOAD_WAIT) && (load_kind == LD_WEIGHT);
  assign weights_i_wr_tap = 32'(load_tap);
  assign weight_tap_advance = (state == EXECUTE_COMMIT) &&
      (compute_index + 32'(PE_COUNT) >= active) && !global_pool && spatial &&
      (32'(tap) + 32'd1 != 32'(taps));
  assign {unused_weight_tap_carry, weight_tap_nxt} = {1'b0, tap} + (TAP_COUNT_W+1)'(1);
  assign weights_i_rd_tap = (state == OUTPUT_INIT) ? 32'd0 :
      weight_tap_advance ? 32'(weight_tap_nxt) : 32'(tap);
  for (genvar channel = 0; channel < TILE; channel++) begin : g_weight_channel
    localparam int p_dma_lane = channel % BUS_BYTES;
    assign weights_i_wr_mask[channel] = rd_valid[p_dma_lane] &&
        (32'(rd_col_base) + 32'(p_dma_lane) == 32'(channel)) && (32'(channel) < active);
    assign weights_i_wr_data[8*channel+:8] = rd_data[p_dma_lane][7:0];
    assign weight_tap_data[channel] = $signed(weights_o_rd_data[8*channel+:8]);
  end
  vector_weight_store #(.p_channels(TILE), .p_depth(MAX_TAPS)) u_weights (
      .clk(clk), .i_wr_en(weights_i_wr_en), .i_wr_tap(weights_i_wr_tap),
      .i_wr_mask(weights_i_wr_mask), .i_wr_data(weights_i_wr_data),
      .i_rd_tap(weights_i_rd_tap), .o_rd_data(weights_o_rd_data)
  );

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
  wire signed [7:0] add_first_lhs=input_buf[0][7:0];
  wire signed [7:0] add_next_lhs=input_buf[ADD_INDEX_WIDTH'(compute_index)+ADD_INDEX_WIDTH'(1)][7:0];
  wire signed [7:0] add_rhs=rhs_buf[ADD_INDEX_WIDTH'(compute_index)][7:0];
  // 有效 S8 操作数加上 [-127,128] 内的偏移，结果范围为 [-255,255]。
  wire signed [8:0] add_first_lhs_offset=$signed({add_first_lhs[7],add_first_lhs})+$signed(c.add.input1_offset[8:0]);
  wire signed [8:0] add_next_lhs_offset=$signed({add_next_lhs[7],add_next_lhs})+$signed(c.add.input1_offset[8:0]);
  wire signed [8:0] add_rhs_offset=$signed({add_rhs[7],add_rhs})+$signed(c.add.input2_offset[8:0]);
  // 加载、舍入和求和周期分别准备下一次乘法操作数。
  // 输出缩放阶段所需的和也保存在同一个寄存器中。
  always_ff @(posedge clk) begin
    if(state==LOAD_WAIT && load_kind==LD_B && rd_done && add_s8)
      add_operand<=32'(add_first_lhs_offset);
    else if(state==ADD_ROUND_WAIT && add_stage==0)
      add_operand<=32'(add_rhs_offset);
    else if(state==ADD_SUM)
      add_operand<=add_scaled_a+32'(add_rounded);
    else if(state==ADD_STORE && !writeback_busy && compute_index+1<active)
      add_operand<=32'(add_next_lhs_offset);
  end

  // 串行运算在各自消费周期选择地址，共用一个累加存储读取端口。
  // 量化和归约由当前状态选择，其余周期服务 Softmax 或平均池化。
  logic [TILE_INDEX_W-1:0] serial_acc_read_index;
  logic signed [31:0] serial_acc_read_data;
  logic signed [31:0] softmax_i_exp_rdata;
  always_comb begin
    serial_acc_read_index = quant_index;
    if (state==QUANT_STREAM) begin
      serial_acc_read_index = q_issue;
    end else if (state==VECTOR_REDUCE) begin
      serial_acc_read_index = reduce_index;
    end else if (softmax_s8) begin
      serial_acc_read_index = TILE_INDEX_W'(soft_exp_index);
    end
  end
  assign serial_acc_read_data = acc_buf[serial_acc_read_index];
  assign softmax_i_exp_rdata = serial_acc_read_data;

  logic signed [31:0] reduce_alu_i_lhs, reduce_alu_i_rhs;
  logic reduce_alu_i_max, reduce_alu_i_min;
  assign reduce_alu_i_lhs = reduce_acc;
  assign reduce_alu_i_rhs = serial_acc_read_data;
  assign reduce_alu_i_max = c.op == VEC_MAX;
  assign reduce_alu_i_min = c.op == VEC_MIN;
  // 共享串行读端口在本周期提供操作数，加法与有符号极值比较共用归约单元。
  vector_reduce_alu u_reduce_alu (
    .clk(clk), .i_lhs(reduce_alu_i_lhs), .i_rhs(reduce_alu_i_rhs),
    .i_max(reduce_alu_i_max), .i_min(reduce_alu_i_min), .o_result(reduce_next)
  );
  localparam int POOL_SUM_WIDTH=8+$clog2(POOL_MAX_TAPS);
  wire signed [POOL_SUM_WIDTH-1:0] avg_pool_sum=serial_acc_read_data[POOL_SUM_WIDTH-1:0];
  wire [POOL_SUM_WIDTH-1:0] avg_unsigned_magnitude=avg_pool_sum<0 ?
      $unsigned(-avg_pool_sum) : $unsigned(avg_pool_sum);
  assign avg_input_magnitude=32'(avg_unsigned_magnitude);
  assign avg_overestimate=avg_residual_q[AVG_SCALE_BITS+1];
  assign avg_twice_remainder={avg_remainder_q,1'b0};
  assign avg_done=state==AVG_WAIT && avg_phase==4'd8;
  always_ff @(posedge clk) begin
    // 倒数平均运算先经过 QUANT_INIT，累加器选择和绝对值计算在进入乘法器前完成。
    if (state==QUANT_INIT && c.op==AVGPOOL_S8 && !avg_power_two)
      avg_numerator_q<=AVG_SCALE_BITS'(avg_input_magnitude);
    if (state==AVG_START && !avg_power_two) begin
      avg_phase<=0;
    end else if (state==AVG_WAIT) begin
      if (avg_phase==1) avg_estimate_q<=8'(multiplier_product >> AVG_SCALE_BITS);
      if (avg_phase==4) avg_check_q<=(AVG_SCALE_BITS+1)'(multiplier_product);
      if (avg_phase==5) avg_residual_q<=
          $signed({2'b00,avg_numerator_q})-$signed({1'b0,avg_check_q});
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
      avg_phase<=avg_phase+1'b1;
    end
  end

  assign multiplier_a=c.op==AVGPOOL_S8 ?
      (state==AVG_START ? $signed(32'(avg_numerator_q)) : $signed({24'd0,avg_estimate_q})) :
      add_s8 ? add_operand : softmax_s8 ? soft_mul_a : q_accumulator;
  assign multiplier_b=c.op==AVGPOOL_S8 ?
      (state==AVG_START ? $signed(32'(avg_reciprocal_data)) : $signed(32'(valid_taps))) :
      add_s8 ? add_multiplier : softmax_s8 ? soft_mul_b : q_multiplier;
  vector_scalar_multiplier u_scalar_multiplier (
    .clk(clk),.a(multiplier_a),.b(multiplier_b),.product(multiplier_product));
  assign soft_lut_req_ready=state==SOFT_LUT_REQ && rd_granted;
  assign soft_lut_rsp_valid=state==SOFT_LUT_WAIT && rd_done;
  vector_softmax #(.MAX_DEPTH(TILE),.MULTIPLIER_LATENCY(2)) u_softmax (
    .clk,.rst_n,.start(state==SOFT_START),.depth(c.length),.ready(soft_ready),.done(soft_done),.error(soft_error),
    .input_index(soft_input_index),.input_data(8'(input_buf[32'(soft_input_index)])),
    .lut_req_valid(soft_lut_req_valid),.lut_req_ready(soft_lut_req_ready),.lut_index(soft_lut_index),
    .lut_rsp_valid(soft_lut_rsp_valid),.lut_rsp_data(rd_raw_valid ? rd_raw_data[31:0] : soft_lut_data),.lut_rsp_error(rd_error),
    .exp_we(soft_exp_we),.exp_index(soft_exp_index),.exp_wdata(soft_exp_data),.exp_rdata(softmax_i_exp_rdata),
    .out_we(soft_out_we),.out_index(soft_out_index),.out_data(soft_out_data),
    .mul_a(soft_mul_a),.mul_b(soft_mul_b),.mul_product(multiplier_product)
  );

  wire window_write_valid[4], dma_input_write_valid[BUS_BYTES];
  wire [INPUT_INDEX_W-1:0] window_write_index[4], dma_input_write_index[BUS_BYTES];
  for (genvar lane=0;lane<4;lane++) begin : g_window_write_address
    wire [INPUT_INDEX_W:0] column_sum={1'b0,win_rsp_col[INPUT_INDEX_W-1:0]}+(INPUT_INDEX_W+1)'(lane);
    assign window_write_valid[lane]=window_response_fire && win_rsp_mask[lane] &&
        win_rsp_col<32'(active) && column_sum<(INPUT_INDEX_W+1)'(active);
    assign window_write_index[lane]=input_response_base+INPUT_INDEX_W'(column_sum);
  end
  wire [3:0] window_bank_valid;
  wire [INPUT_INDEX_W-1:0] window_bank_index[4];
  wire signed [15:0] window_bank_data[4];
  wire [1:0] window_first_bank=2'(input_response_base)+2'(win_rsp_col);
  for (genvar bank=0;bank<4;bank++) begin : g_window_bank
    wire [1:0] source_lane=2'(bank)-window_first_bank;
    assign window_bank_valid[bank]=window_write_valid[source_lane];
    assign window_bank_index[bank]=window_write_index[source_lane];
    assign window_bank_data[bank]=win_rsp_data[source_lane];
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
          pool_bank_data[bank]<=rd_data[source_lane];
        end
      end
    end
  end

  assign q_clamped_data = q_below_min ? c.activation_min :
      q_above_max ? c.activation_max : 32'($signed(q_offset_low[7:0]));

  // 每个总线银行共用一个数据选择器，存储项分别保留地址比较和写使能。
  // 已保存的运算模式确定普通向量、窗口和全局池化响应的数据来源。
  for (genvar bank=0;bank<BUS_BYTES;bank++) begin : g_input_bank_data
    localparam int p_s16_lane = bank % (BUS_BYTES / 2);
    localparam int p_window_bank = bank % 4;
    logic signed [15:0] dma_bank_data;

    assign dma_bank_data = c.vector_s16 ? rd_data[p_s16_lane] : rd_data[bank];
    assign input_bank_data[bank] = global_pool ? pool_bank_data[bank] :
        spatial ? window_bank_data[p_window_bank] : dma_bank_data;
  end

  for (genvar entry=0;entry<DMA_SIZE;entry++) begin : g_input_write
    if (entry>=2*TILE) begin : g_unused
      assign input_buf[entry]=16'sd0;
    end else begin : g_buffer
    localparam int S8_LANE=entry%BUS_BYTES;
    localparam int S16_LANE=entry%(BUS_BYTES/2);
    wire load_match=c.vector_s16 ?
        dma_input_write_valid[S16_LANE] && dma_input_write_index[S16_LANE]==INPUT_INDEX_W'(entry) :
        dma_input_write_valid[S8_LANE] && dma_input_write_index[S8_LANE]==INPUT_INDEX_W'(entry);
    logic write_enable;
    logic signed [15:0] write_value;
    localparam int WINDOW_BANK=entry%4;
    wire window_match=window_bank_valid[WINDOW_BANK] &&
        window_bank_index[WINDOW_BANK]==INPUT_INDEX_W'(entry);
    wire pool_match=pool_bank_valid[S8_LANE] &&
        pool_bank_row[S8_LANE]==POOL_ROW_W'(entry/BUS_BYTES);

    assign write_enable = window_match || load_match || pool_match;
    assign write_value = input_bank_data[S8_LANE];
    always_ff @(posedge clk) if (rst_n && write_enable) input_buf[entry] <= write_value;
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
      .p_active_width(ACTIVE_COUNT_W)
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
      .o_right_shift(params_o_right_shift)
  );

  logic signed [31:0] acc_common_write_data [PE_COUNT];
  logic accumulator_compute_fire, accumulator_soft_fire;
  logic accumulator_init_fire, accumulator_bias_selected;
  logic signed [31:0] accumulator_init_data;
  assign accumulator_compute_fire = state == EXECUTE_COMMIT && c.op != VEC_HADAMARD;
  assign accumulator_soft_fire = softmax_s8 && soft_exp_we;
  // 计算提交与 Softmax 指数接收处于独立状态，各 PE 通道共用写入数据。
  for (genvar lane = 0; lane < PE_COUNT; lane++) begin : g_accumulator_write_data
    assign acc_common_write_data[lane] =
        ({32{accumulator_compute_fire}} & pe_result[lane]) |
        ({32{accumulator_soft_fire}} & soft_exp_data);
  end
  assign accumulator_init_fire = state == OUTPUT_INIT || state == VECTOR_INIT;
  assign accumulator_bias_selected = state == OUTPUT_INIT && depthwise;
  always_comb begin
    accumulator_init_data = 32'sd0;
    if (state == OUTPUT_INIT) begin
      if (c.op == MAXPOOL_S8) accumulator_init_data = -32'sd128;
      else if (c.op == MINPOOL_S8) accumulator_init_data = 32'sd127;
    end else if (state == VECTOR_INIT) begin
      if (c.op == VEC_MAX) accumulator_init_data = 32'sh8000_0000;
      else if (c.op == VEC_MIN) accumulator_init_data = 32'sh7fff_ffff;
    end
  end
  for (genvar entry=0;entry<TILE;entry++) begin : g_accumulator_write
    localparam int LANE_INDEX = entry % PE_COUNT;
    localparam int GROUP_BASE = entry - LANE_INDEX;
    (* keep = 1 *) logic soft_selected;
    // 下标和模式先行检查，指数接收条件直接参与当前项的写入选择。
    assign soft_selected = softmax_s8 && soft_exp_index==$bits(soft_exp_index)'(entry);
    logic soft_write, compute_write, bias_write, constant_write;
    logic write_enable, shared_write;
    logic [31:0] write_value;
    assign soft_write = soft_selected && soft_exp_we;
    assign compute_write = !soft_write && accumulator_compute_fire && 32'(entry) < active && compute_index == TILE_INDEX_W'(GROUP_BASE);
    assign bias_write = !soft_write && accumulator_init_fire && accumulator_bias_selected;
    assign constant_write = !soft_write && accumulator_init_fire && !accumulator_bias_selected;
    assign shared_write = soft_write || compute_write;
    assign write_enable = shared_write || accumulator_init_fire;
    assign write_value = acc_common_write_data[LANE_INDEX] |
        ({32{bias_write}} & bias_buf[entry]) |
        ({32{constant_write}} & accumulator_init_data);
    always_ff @(posedge clk) begin
      if (rst_n && write_enable) acc_buf[entry] <= write_value;
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

  wire signed [63:0] rounding_input = add_s8 ? add_product :
      c.op==AVGPOOL_S8 ? $signed(64'(serial_acc_read_data)) : q_product;
  wire [5:0] rounding_amount = add_s8 ? add_right : c.op==AVGPOOL_S8 ? avg_shift : q_right_3;
  wire signed [63:0] rounding_result,rounding_floor;
  vector_round_shift #(.REGISTER_MIDDLE(1'b1)) u_rounding (
    .clk(clk),.value(rounding_input),.amount(rounding_amount),.result(rounding_result),.floor_value(rounding_floor));
  // 有效 S8 池化输入及激活范围使精确平均值保持在 [-128,127] 内。
  wire signed [8:0] pool_activation_min={c.activation_min[7],c.activation_min[7:0]};
  wire signed [8:0] pool_activation_max={c.activation_max[7],c.activation_max[7:0]};
  wire signed [7:0] avg_power_floor=rounding_floor[7:0];
  // 舍入在向下取整的商上增加零或一。激活上下限均为整数，
  // 范围检查可以与该递增运算并行执行。
  wire signed [31:0] avg_power_result=avg_power_floor<$signed(c.activation_min[7:0]) ? c.activation_min :
      avg_power_floor>=$signed(c.activation_max[7:0]) ? c.activation_max : 32'($signed(rounding_result[7:0]));
  wire signed [8:0] avg_signed=avg_negative ? -$signed({1'b0,avg_magnitude_q}) : $signed({1'b0,avg_magnitude_q});
  wire signed [31:0] avg_div_result=avg_signed<pool_activation_min ? c.activation_min :
      avg_signed>pool_activation_max ? c.activation_max : 32'(avg_signed);
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

  // 串行结果共用字节数据选择，每个存储项仅保留地址使能和并行结果选择。
  logic result_background_write;
  logic result_quant_write;
  logic [TILE_INDEX_W-1:0] result_background_index;
  logic result_serial_write;
  logic [TILE_INDEX_W-1:0] result_serial_index;
  logic [7:0] result_serial_data;
  logic [7:0] result_common_data;
  assign result_quant_write = depthwise && state!=IDLE && state!=FAILED && state!=DONE &&
      q_active && q_valid[5];
  assign result_background_write = result_quant_write || (softmax_s8 && soft_out_we);
  assign result_background_index = result_quant_write ? q_index_5 : TILE_INDEX_W'(soft_out_index);
  always_comb begin
    result_serial_write = 1'b0;
    result_serial_index = '0;
    result_serial_data = '0;
    case (state)
      ADD_STORE: begin
        result_serial_write = !writeback_busy && compute_index<TILE_INDEX_W'(active);
        result_serial_index = compute_index;
        result_serial_data = add_clamped[7:0];
      end
      AVG_POWER_STORE: begin
        result_serial_write = 1'b1;
        result_serial_index = quant_index;
        result_serial_data = avg_power_result[7:0];
      end
      AVG_WAIT: begin
        result_serial_write = avg_done;
        result_serial_index = quant_index;
        result_serial_data = avg_div_result[7:0];
      end
      VECTOR_REDUCE: begin
        result_serial_write = reduce_index+1>=TILE;
        result_serial_data = reduce_next[7:0];
      end
      default: ;
    endcase
  end
  // 字节写入来源互斥，各存储项共用已按写使能选择的数据。
  assign result_common_data = ({8{result_quant_write}} & q_clamped_data[7:0]) |
      ({8{softmax_s8 && soft_out_we}} & soft_out_data) |
      ({8{result_serial_write}} & result_serial_data);
  for (genvar entry=0;entry<TILE;entry++) begin : g_result_write
    localparam int LANE_INDEX = entry % PE_COUNT;
    localparam int GROUP_BASE = entry - LANE_INDEX;
    logic write_enable;
    logic [7:0] write_value;
    logic background_selected, serial_selected, multiply_selected, pool_selected;
    logic [7:0] pool_value;
    assign background_selected = result_background_write && result_background_index == TILE_INDEX_W'(entry);
    assign serial_selected = result_serial_write && result_serial_index == TILE_INDEX_W'(entry);
    assign multiply_selected = state == EXECUTE_COMMIT && c.op == VEC_HADAMARD && !writeback_busy &&
        32'(entry) < active && compute_index == TILE_INDEX_W'(GROUP_BASE);
    assign pool_selected = state == POOL_STORE && 32'(entry) < active;
    assign pool_value = $signed(acc_buf[entry][7:0]) < $signed(c.activation_min[7:0]) ? c.activation_min[7:0] :
        $signed(acc_buf[entry][7:0]) > $signed(c.activation_max[7:0]) ? c.activation_max[7:0] : acc_buf[entry][7:0];
    assign write_enable = background_selected || serial_selected || multiply_selected || pool_selected;
    assign write_value = result_common_data | ({8{multiply_selected}} & pe_result[LANE_INDEX][7:0]) |
        ({8{pool_selected}} & pool_value);
    // 字节运算只更新字节写回模式使用的低八位。
    always_ff @(posedge clk) if (rst_n && write_enable) result_buf[entry][7:0] <= write_value;
    always_ff @(posedge clk) begin
      if(rst_n) begin
        if(state==EXECUTE_COMMIT && c.op==VEC_HADAMARD && !writeback_busy &&
            32'(entry)<active && compute_index==TILE_INDEX_W'(GROUP_BASE))
          result_buf[entry][31:8]<=pe_result[LANE_INDEX][31:8];
        if(entry==0 && state==VECTOR_REDUCE && reduce_index+1>=TILE)
          result_buf[entry][31:8]<=reduce_next[31:8];
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE; c<='0; error<=0; load_kind<=LD_WEIGHT;
      taps<=0; active<=0; channel_base<=0; position<=0;
      ox<=0;oy<=0;kx<=0;ky<=0;tap<=0;load_tap<=0;valid_taps<=0;
      input_x<=0;input_y<=0;input_origin_x<=0;input_origin_y<=0;
      vector_offset<=0;compute_index<=0;quant_index<=0;reduce_index<=0;
      reduce_acc<=0; param_bad_seen<=0;
      add_stage<=0;add_multiply_wait<=0;add_product<=0;add_scaled_a<=0;add_rounded<=0;
      q_accumulator<=0;q_multiplier<=0;q_rounded<=0;q_product<=0;q_right_0<=0;q_right_1<=0;q_right_2<=0;q_right_3<=0;
      q_valid<=0;q_index_0<=0;q_index_1<=0;q_index_2<=0;q_index_3<=0;q_index_4<=0;q_index_5<=0;q_issue<=0;q_count<=0;
      q_active<=0;
      read_bank<=0;wf_bank<=0;input_ready<=0;
      window_received<=0;soft_lut_data<=0;avg_negative<=0;
      fetch_position<=0;fetch_tap<=0;fetch_ox<=0;fetch_kx<=0;
      fetch_x<=0;fetch_y<=0;fetch_origin_x<=0;fetch_origin_y<=0;
      write_origin<=0;write_total<=0;
      input_range_mode<=0;
      pool_offset<=0;pool_pixels<=0;pool_received<=0;pool_pixel<=0;
      pool_elements<=0;pool_row_columns<=0;pool_row_remaining<=0;pool_input_index<=0;
      fetch_tap_offset<=0;load_tap_offset<=0;position_offset<=0;pool_byte_offset<=0;
    end else begin
      if (softmax_s8) begin
        if (state==SOFT_LUT_WAIT && rd_raw_valid) soft_lut_data<=rd_raw_data[31:0];
      end

      if (window_fetch_advance) begin
        if (fetch_tap+1==taps) begin
          fetch_position<=fetch_position+1;fetch_tap<=0;fetch_tap_offset<=0;fetch_kx<=0;
          if (fetch_ox+1==32'(c.image.output_w)) begin
            fetch_ox<=0;
            fetch_origin_x<=-$signed(34'(c.image.pad_left));
            fetch_origin_y<=fetch_origin_y+$signed(34'(c.image.stride_h));
            fetch_x<=-$signed(34'(c.image.pad_left));
            fetch_y<=fetch_origin_y+$signed(34'(c.image.stride_h));
          end else begin
            fetch_ox<=fetch_ox+1;
            fetch_origin_x<=fetch_origin_x+$signed(34'(c.image.stride_w));
            fetch_x<=fetch_origin_x+$signed(34'(c.image.stride_w));fetch_y<=fetch_origin_y;
          end
        end else begin
          fetch_tap<=fetch_tap+1;fetch_tap_offset<=fetch_tap_offset+channels;
          if (fetch_kx==kernel_last_column) begin
            fetch_kx<=0;fetch_x<=fetch_origin_x;fetch_y<=fetch_y+$signed(34'(c.image.dilation_h));
          end else begin
            fetch_kx<=fetch_kx+1;fetch_x<=fetch_x+$signed(34'(c.image.dilation_w));
          end
        end
      end
      if (window_request_fire) begin
        wf_bank<=(wf_bank+1'b1)&input_bank_mask;
      end
      if (window_response_fire) begin
        window_received<=window_received+32'(window_response_count);
        if(win_rsp_last) begin
          input_ready[win_rsp_tag]<=!win_rsp_error;
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
          c<=cfg; error<=0; state<=CHECK;
          input_range_mode<=0;
          q_active<=0;q_valid<=0;
          input_ready<=0;read_bank<=0;wf_bank<=0;window_received<=0;
          param_bad_seen<=0;
        end
        CHECK: if (config_check_ready) state<=CHECK_WAIT;
        CHECK_WAIT: if (config_check_done) begin
          if (config_check_error) begin error<=2'b01;state<=FAILED;end
          else begin
            taps<=32'(kernel_count);channel_base<=0;input_range_mode<=global_pool;state<=CONFIGURE;
            kernel_last_column<=TAP_COUNT_W'(c.image.kernel_w)-TAP_COUNT_W'(1);
          end
        end
        CONFIGURE: if (dma_cfg_ready) state<=spatial ? TILE_INIT : VECTOR_INIT;
        TILE_INIT: begin
          active<=channels-channel_base<TILE ? channels-channel_base : 32'(TILE);
          position<=0;position_offset<=0;ox<=0;oy<=0;load_tap<=0;load_tap_offset<=0;load_kind<=LD_WEIGHT;
          input_origin_x<=-$signed(34'(c.image.pad_left));input_origin_y<=-$signed(34'(c.image.pad_top));
          input_ready<=0;read_bank<=0;wf_bank<=0;window_received<=0;
          fetch_position<=0;fetch_tap<=0;fetch_tap_offset<=0;fetch_ox<=0;fetch_kx<=0;
          fetch_x<=-$signed(34'(c.image.pad_left));fetch_y<=-$signed(34'(c.image.pad_top));
          fetch_origin_x<=-$signed(34'(c.image.pad_left));fetch_origin_y<=-$signed(34'(c.image.pad_top));
          state<=depthwise ? LOAD_REQ : OUTPUT_INIT;
        end
        LOAD_REQ: if (rd_granted) state<=LOAD_WAIT;
        LOAD_WAIT: if (rd_done) begin
          if (rd_error || param_bad || param_bad_seen) begin error<=2'b10;state<=FAILED;end
          else case (load_kind)
            LD_WEIGHT: if (load_tap+1<taps) begin
              load_tap<=load_tap+1;load_tap_offset<=load_tap_offset+channels;state<=LOAD_REQ;end
              else begin load_kind<=c.bias_base==0 ? LD_MULT : LD_BIAS;state<=LOAD_REQ;end
            LD_BIAS: begin load_kind<=LD_MULT;state<=LOAD_REQ;end
            LD_MULT: begin load_kind<=LD_SHIFT;state<=LOAD_REQ;end
            LD_SHIFT: state<=OUTPUT_INIT;
            LD_A: if (binary_vector) begin load_kind<=LD_B;state<=LOAD_REQ;end
              else begin compute_index<=0;state<=softmax_s8 ? SOFT_START : EXECUTE;end
            LD_B: begin
              compute_index<=0;add_stage<=0;
              state<=add_s8 ? ADD_MULT : EXECUTE;
            end
            default: begin error<=2'b10;state<=FAILED;end
          endcase
        end
        OUTPUT_INIT: begin
          tap<=0;kx<=0;ky<=0;valid_taps<=0;
          input_x<=input_origin_x;input_y<=input_origin_y;
          if (global_pool) begin
            valid_taps<=taps;pool_offset<=0;pool_byte_offset<=0;state<=POOL_LOAD_PREP;
          end else state<=TAP_CHECK;
        end
        POOL_LOAD_PREP: begin
          pool_pixels<=pool_next_pixels;pool_received<=0;pool_pixel<=0;pool_input_index<=0;
          pool_elements<=pool_next_elements;
          pool_row_columns<=channels==active ? pool_next_elements : (INPUT_INDEX_W+1)'(active);
          pool_row_remaining<=channels==active ? pool_next_elements : (INPUT_INDEX_W+1)'(active);
          state<=POOL_LOAD_REQ;
        end
        POOL_LOAD_REQ: if (rd_granted) state<=POOL_LOAD_WAIT;
        POOL_LOAD_WAIT: if (rd_done) begin
          if (rd_error || !pool_receive_complete) begin error<=2'b10;state<=FAILED;end
          else begin compute_index<=0;state<=POOL_LOAD_DRAIN;end
        end
        POOL_LOAD_DRAIN: state<=EXECUTE;
        TAP_CHECK: if (in_bounds) begin
            valid_taps<=valid_taps+1;compute_index<=0;
            state<=input_ready[read_bank] ? EXECUTE : WINDOW_WAIT;
          end
          else state<=TAP_NEXT;
        WINDOW_WAIT: if (input_ready[read_bank]) begin compute_index<=0;state<=EXECUTE;end
        EXECUTE: if (c.op!=VEC_HADAMARD || !writeback_busy) state<=EXECUTE_COMMIT;
        EXECUTE_COMMIT: begin
          state<=EXECUTE;
          if (compute_index+32'(PE_COUNT)<active) compute_index<=compute_index+32'(PE_COUNT);
          else if (global_pool) begin
            pool_byte_offset<=pool_byte_offset+channels;
            if (pool_pixel+1<pool_pixels) begin
              pool_pixel<=pool_pixel+1;pool_input_index<=pool_input_index+(INPUT_INDEX_W+1)'(active);
              compute_index<=0;
            end
            else if (pool_offset+pool_pixels<taps) begin pool_offset<=pool_offset+pool_pixels;state<=POOL_LOAD_PREP;end
            else begin quant_index<=0;state<=QUANT_INIT;end
          end
          else if (spatial) begin
            input_ready[read_bank]<=0;read_bank<=(read_bank+1'b1)&input_bank_mask;compute_index<=0;
            if (tap+1==taps) begin quant_index<=0;state<=QUANT_INIT;end
            else begin
              tap<=tap+1;input_x<=next_window_x;input_y<=next_window_y;
              if (kernel_column_end) begin kx<=0;ky<=ky+1;end else kx<=kx+1;
              if (next_window_valid) begin
                valid_taps<=valid_taps+1;
                state<=input_ready[(read_bank+1'b1)&input_bank_mask] ? EXECUTE : WINDOW_WAIT;
              end else state<=TAP_CHECK;
            end
          end
          else if (c.op==VEC_HADAMARD) begin
            write_origin<=write_origin_next;write_total<=active<<2;state<=WRITE_PREP;
          end else state<=VECTOR_NEXT;
        end
        ADD_MULT: begin
          add_multiply_wait<=0;state<=ADD_DRAIN;
        end
        ADD_DRAIN: if (add_multiply_wait) begin
          add_product<=multiplier_product;state<=ADD_ROUND;
        end else add_multiply_wait<=1;
        ADD_ROUND: state<=ADD_ROUND_WAIT;
        ADD_ROUND_WAIT: begin
          if (add_stage==0) begin
            add_scaled_a<=32'(rounding_result);
            add_stage<=1;state<=ADD_MULT;
          end else if (add_stage==1) begin
            add_rounded<=rounding_result;state<=ADD_SUM;
          end else begin
            add_rounded<=rounding_result;state<=ADD_STORE;
          end
        end
        ADD_SUM: begin
          add_stage<=2;state<=ADD_MULT;
        end
        ADD_STORE: if (!writeback_busy) begin
          if (compute_index+1<active) begin
            compute_index<=compute_index+1'b1;add_stage<=0;state<=ADD_MULT;
          end else begin
            write_origin<=write_origin_next;write_total<=active;state<=WRITE_PREP;
          end
        end
        TAP_NEXT: if (tap+1==taps) begin quant_index<=0;state<=QUANT_INIT;end
          else begin
            tap<=tap+1;input_x<=next_window_x;input_y<=next_window_y;
            if (kernel_column_end) begin kx<=0;ky<=ky+1;end else kx<=kx+1;
            state<=TAP_CHECK;
          end
        QUANT_INIT: begin
          if (depthwise) begin
            if (!writeback_busy) begin
              q_active<=1;q_count<=active;q_issue<=0;q_valid<=0;state<=QUANT_STREAM;
            end
          end else if (!writeback_busy) begin
            if (c.op==AVGPOOL_S8) begin
              if (valid_taps==0) begin error<=2'b01;state<=FAILED;end else state<=AVG_START;
            end else state<=POOL_STORE;
          end
        end
        QUANT_STREAM: begin
          q_valid<={q_valid[4:0],q_issue<q_count};
          if (q_issue<q_count) begin
            q_accumulator<=serial_acc_read_data;q_multiplier<=params_o_multiplier;
            q_right_0<=params_o_right_shift;q_index_0<=q_issue;q_issue<=q_issue+1'b1;
          end
          if (q_valid[0]) begin q_right_1<=q_right_0;q_index_1<=q_index_0;end
          if (q_valid[1]) begin q_right_2<=q_right_1;q_index_2<=q_index_1;end
          if (q_valid[2]) begin
            q_product<=multiplier_product;q_right_3<=q_right_2;q_index_3<=q_index_2;
          end
          if (q_valid[3]) q_index_4<=q_index_3;
          if (q_valid[4]) begin q_rounded<=rounding_result;q_index_5<=q_index_4;end
          if (q_valid[5] && q_index_5+1==q_count) begin
            q_active<=0;q_valid<=0;
            write_origin<=write_origin_next;write_total<=active;state<=WRITE_PREP;
          end
        end
        AVG_START: if (avg_power_two) state<=AVG_POWER_STORE;
          else begin avg_negative<=serial_acc_read_data<0;state<=AVG_WAIT;end
        AVG_POWER_STORE: begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=AVG_START;end
          else begin write_origin<=write_origin_next;write_total<=active;state<=WRITE_PREP;end
        end
        AVG_WAIT: if (avg_done) begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=QUANT_INIT;end
          else begin write_origin<=write_origin_next;
            write_total<=active;state<=WRITE_PREP;end
        end
        POOL_STORE: begin
          write_origin<=write_origin_next;
          write_total<=active;state<=WRITE_PREP;
        end
        WRITE_PREP: if (writeback_ready) begin
          if (spatial) state<=OUTPUT_NEXT;
          else if (c.op==VEC_HADAMARD || add_s8) state<=VECTOR_NEXT;
          else state<=DRAIN;
        end
        OUTPUT_NEXT: begin
          if (position+1<32'(position_count)) begin
            position<=position+1;position_offset<=position_offset+channels;
            if (ox+1==32'(c.image.output_w)) begin
              ox<=0;oy<=oy+1;input_origin_x<=-$signed(34'(c.image.pad_left));
              input_origin_y<=input_origin_y+$signed(34'(c.image.stride_h));
            end else begin
              ox<=ox+1;input_origin_x<=input_origin_x+$signed(34'(c.image.stride_w));
            end
            state<=OUTPUT_INIT;
          end else if (channel_base+active<channels) begin
            channel_base<=channel_base+active;state<=DRAIN_TILE;
          end
          else state<=DRAIN;
        end
        DRAIN_TILE: if (!writeback_busy && !win_busy && input_reserved==0 && !q_active)
          state<=TILE_INIT;
        DRAIN: if (!writeback_busy && !win_busy && input_reserved==0 && !q_active && dma_cfg_ready)
          state<=DONE;
        SOFT_START: if (soft_ready) state<=SOFT_RUN;
        SOFT_RUN: if (soft_done) begin
          if (soft_error!=0) begin error<=soft_error;state<=FAILED;end
          else begin write_origin<=write_origin_next;write_total<=active;state<=WRITE_PREP;end
        end else if (soft_lut_req_valid) begin soft_lut_data<=0;state<=SOFT_LUT_REQ;end
        SOFT_LUT_REQ: if (rd_granted) state<=SOFT_LUT_WAIT;
        SOFT_LUT_WAIT: if (rd_done) state<=SOFT_RUN;
        VECTOR_INIT: begin
          vector_offset<=0;active<=c.length<TILE ? c.length : 32'(TILE);
          load_kind<=LD_A;state<=LOAD_REQ;
        end
        VECTOR_NEXT: if (vector_has_more) begin
          vector_offset<=vector_offset+active;
          active<=vector_next_active;
          load_kind<=LD_A;state<=LOAD_REQ;
        end else if (c.op==VEC_HADAMARD || add_s8) state<=DRAIN;
        else begin
          reduce_acc<=c.op==VEC_MAX ? 32'sh8000_0000 : c.op==VEC_MIN ? 32'sh7fff_ffff : 32'sd0;
          reduce_index<=0;state<=VECTOR_REDUCE;
        end
        VECTOR_REDUCE: begin
          reduce_acc<=reduce_next;
          if (reduce_index+1<TILE) reduce_index<=reduce_index+1;
          else begin write_origin<=write_origin_next;write_total<=4;state<=WRITE_PREP;end
        end
        FAILED: if (!rd_busy && !wr_busy && !win_busy && !writeback_busy && dma_cfg_ready) begin
          q_active<=0;q_valid<=0;
          input_ready<=0;state<=DONE;
        end
        DONE: if (done_ready) state<=IDLE;
        default: begin error<=2'b10;state<=FAILED;end
      endcase
      if ((writeback_done && writeback_error) ||
          (window_response_fire && win_rsp_last && (win_rsp_error || !window_count_o_equal))) begin
        error<=2'b10;state<=FAILED;
      end
    end
  end

`ifdef NPU_SIM_ASSERT
  logic [31:0] input_position[4],input_tap[4];
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
    if (src_wvalid && !src_wready) begin
      assert(wr_busy);
    end
    if (state==EXECUTE) assert(active>0 && active<=TILE && compute_index<active);
    if (state==ADD_MULT || state==ADD_DRAIN || state==ADD_ROUND || state==ADD_ROUND_WAIT || state==ADD_SUM || state==ADD_STORE) begin
      assert(add_s8 && active>0 && active<=TILE && compute_index<active);
      assert(add_stage<=2 && add_right>=1 && add_right<=62);
      if (state==ADD_SUM)
        assert($signed(64'(add_scaled_a))+$signed(add_rounded)>=-64'sd2147483648 &&
               $signed(64'(add_scaled_a))+$signed(add_rounded)<=64'sd2147483647);
    end
    if (window_request_fire) begin
      assert(!input_ready[wf_bank] && !input_reserved[wf_bank]);
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
    if (state==EXECUTE && spatial && !global_pool) begin
      assert(input_ready[read_bank]);
      assert(input_position[read_bank]==position && input_tap[read_bank]==tap);
    end
  end
`endif
endmodule

// 三个无符号地址分量先保存逐位进位，再由 DSP 完成完整宽度加法。
module vector_read_address_add #(
`ifdef ASIC_SYNTHESIS
  parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
  parameter bit p_use_dsp = 1'b1
`elsif SYNTHESIS
  parameter bit p_use_dsp = 1'b1
`else
  parameter bit p_use_dsp = 1'b0
`endif
) (
  input logic clk,
  input logic [31:0] i_base,
  input logic [31:0] i_offset,
  input logic [15:0] i_channel,
  output logic [31:0] o_address,
  output logic [1:0] o_carry
);
  if (p_use_dsp) begin : g_dsp
    logic [31:0] extended_channel, sum_bits, carry_bits;
    logic [47:0] extended_sum;
    logic [29:0] dsp_i_a, dsp_i_acin;
    logic [17:0] dsp_i_b, dsp_i_bcin;
    logic [47:0] dsp_i_c, dsp_i_pcin;
    logic [24:0] dsp_i_d;
    logic [6:0] dsp_i_opmode;
    logic [4:0] dsp_i_inmode;
    logic [3:0] dsp_i_alumode;
    logic [2:0] dsp_i_carry_select;
    logic dsp_i_zero;
    logic [47:0] dsp_o_p;
    logic [29:0] unused_acout;
    logic [17:0] unused_bcout;
    logic [47:0] unused_pcout;
    logic [3:0] unused_carryout;
    logic unused_carrycascout, unused_multsignout;
    logic unused_overflow, unused_underflow;
    logic unused_patterndetect, unused_patternbdetect;

    assign extended_channel = {16'd0, i_channel};
    // 三个地址分量逐位产生和位及进位，进位在下一步统一左移。
    assign sum_bits = i_base ^ i_offset ^ extended_channel;
    assign carry_bits = (i_base & i_offset) | (i_base & extended_channel) |
        (i_offset & extended_channel);
    assign extended_sum = {16'd0, sum_bits};
    assign dsp_i_a = extended_sum[47:18];
    assign dsp_i_b = extended_sum[17:0];
    assign dsp_i_c = {15'd0, carry_bits, 1'b0};
    assign dsp_i_acin = '0;
    assign dsp_i_bcin = '0;
    assign dsp_i_pcin = '0;
    assign dsp_i_d = '0;
    assign dsp_i_opmode = 7'b0110011;
    assign dsp_i_inmode = '0;
    assign dsp_i_alumode = '0;
    assign dsp_i_carry_select = '0;
    assign dsp_i_zero = 1'b0;

    // 所有内部寄存器均旁路，读请求仍在原来的周期提供地址。
    // 保留两位溢出，覆盖两个三十二位分量与十六位通道号的完整和。
    DSP48E1 #(
      .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .ADREG(0),
      .CREG(0), .DREG(0), .MREG(0), .PREG(0), .CARRYINREG(0),
      .CARRYINSELREG(0), .INMODEREG(0), .OPMODEREG(0), .ALUMODEREG(0),
      .USE_DPORT("FALSE"), .USE_MULT("NONE"), .USE_SIMD("ONE48")
    ) u_dsp (
      .CLK(clk), .A(dsp_i_a), .ACIN(dsp_i_acin), .B(dsp_i_b), .BCIN(dsp_i_bcin),
      .C(dsp_i_c), .D(dsp_i_d), .PCIN(dsp_i_pcin),
      .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode), .ALUMODE(dsp_i_alumode),
      .CARRYIN(dsp_i_zero), .CARRYINSEL(dsp_i_carry_select),
      .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero),
      .CEA1(dsp_i_zero), .CEA2(dsp_i_zero), .CEAD(dsp_i_zero),
      .CEB1(dsp_i_zero), .CEB2(dsp_i_zero), .CEC(dsp_i_zero),
      .CECARRYIN(dsp_i_zero), .CED(dsp_i_zero), .CEM(dsp_i_zero), .CEP(dsp_i_zero),
      .CECTRL(dsp_i_zero), .CEINMODE(dsp_i_zero), .CEALUMODE(dsp_i_zero),
      .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
      .RSTM(dsp_i_zero), .RSTP(dsp_i_zero), .RSTALLCARRYIN(dsp_i_zero),
      .RSTCTRL(dsp_i_zero), .RSTINMODE(dsp_i_zero), .RSTALUMODE(dsp_i_zero),
      .P(dsp_o_p), .ACOUT(unused_acout), .BCOUT(unused_bcout), .PCOUT(unused_pcout),
      .CARRYOUT(unused_carryout), .CARRYCASCOUT(unused_carrycascout),
      .MULTSIGNOUT(unused_multsignout), .OVERFLOW(unused_overflow),
      .UNDERFLOW(unused_underflow), .PATTERNDETECT(unused_patterndetect),
      .PATTERNBDETECT(unused_patternbdetect)
    );
    assign {o_carry, o_address} = dsp_o_p[33:0];
  end else begin : g_generic
    assign {o_carry, o_address} = {2'b00, i_base} + {2'b00, i_offset} + {18'd0, i_channel};
  end
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
