// SPDX-License-Identifier: Apache-2.0
// Descriptor-driven vector arithmetic, quantized Add, depthwise and pooling.
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
  logic [TILE_INDEX_W-1:0] compute_index, quant_index, reduce_index;
  logic [31:0] fetch_tap_offset, load_tap_offset, position_offset, pool_byte_offset;
  logic signed [15:0] input_buf [DMA_SIZE], rhs_buf [TILE];
  wire signed [7:0] weight_tap_data [TILE];
  logic signed [31:0] bias_buf [TILE], mult_buf [TILE];
  logic [5:0] right_shift_buf [TILE];
  logic signed [31:0] acc_buf [TILE], result_buf [TILE];
  logic [2:0] pe_op;
  logic [2:0] pe_op_q;
  logic signed [15:0] pe_a_q [PE_COUNT],pe_b_q [PE_COUNT];
  logic signed [31:0] pe_acc_q [PE_COUNT];
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
  logic signed [63:0] q_product, q_rounded, q_with_offset;
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
  logic [AVG_SCALE_BITS:0] avg_reciprocal [0:POOL_MAX_TAPS];
  logic [AVG_SCALE_BITS-1:0] avg_numerator_q;
  logic [7:0] avg_estimate_q, avg_quotient_q, avg_magnitude_q;
  logic [AVG_SCALE_BITS:0] avg_check_q;
  logic signed [AVG_SCALE_BITS+1:0] avg_residual_q;
  logic [TAP_COUNT_W-1:0] avg_remainder_q;
  logic [TAP_COUNT_W:0] avg_twice_remainder;
  logic [3:0] avg_phase;
  logic [31:0] avg_input_magnitude;
  logic avg_overestimate;
  assign avg_reciprocal[0]='0;
  for (genvar denominator=1;denominator<=POOL_MAX_TAPS;denominator++) begin : g_avg_reciprocal
    localparam logic [AVG_SCALE_BITS:0] RECIPROCAL =
      (AVG_SCALE_BITS+1)'(((64'd1 << AVG_SCALE_BITS) + denominator - 1) / denominator);
    assign avg_reciprocal[denominator]=RECIPROCAL;
  end
  logic input_range_mode, cache_power_two;
  logic [5:0] cache_channel_shift;
  logic [1:0] read_bank,wf_bank,input_bank_mask;
  logic [3:0] input_ready,input_reserved;
  logic [INPUT_INDEX_W-1:0] input_read_base,input_response_base;
  logic [31:0] window_received;
  logic [2:0] window_response_count;
  logic window_response_fire,window_request_fire;
  logic window_fetch_enabled, window_fetch_in_bounds, window_fetch_advance;
  logic [31:0] fetch_position;
  logic [TAP_COUNT_W-1:0] fetch_tap;
  logic [15:0] fetch_ox;
  logic [TAP_COUNT_W-1:0] fetch_kx;
  logic signed [33:0] fetch_x, fetch_y, fetch_origin_x, fetch_origin_y;
  logic next_window_valid;
  logic signed [33:0] next_window_x, next_window_y;
  wire kernel_column_end=kx==kernel_last_column;
  wire signed [33:0] next_column_x=input_x+$signed(34'(c.image.dilation_w));
  wire signed [33:0] next_row_y=input_y+$signed(34'(c.image.dilation_h));
  wire next_column_valid=next_column_x>=0 && next_column_x<$signed(34'(c.image.input_w)) &&
      input_y>=0 && input_y<$signed(34'(c.image.input_h));
  wire next_row_valid=input_origin_x>=0 && input_origin_x<$signed(34'(c.image.input_w)) &&
      next_row_y>=0 && next_row_y<$signed(34'(c.image.input_h));
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
  wire [BUS_SHIFT:0] pool_received_count=pool_response_fire ?
      (pool_row_remaining>BUS_BYTES ? (BUS_SHIFT+1)'(BUS_BYTES) :
       (BUS_SHIFT+1)'(pool_row_remaining)) : '0;
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
  assign q_with_offset = q_rounded + $signed(64'(c.output_offset));
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
  // The existing input storage holds two full channel groups or four half
  // groups. Reserved slots allow DMA requests to precede ordered responses.
  assign window_fetch_enabled=spatial && !global_pool &&
    (state==OUTPUT_INIT || state==TAP_CHECK || state==WINDOW_WAIT || state==QUANT_STREAM ||
     state==EXECUTE || state==EXECUTE_COMMIT || state==TAP_NEXT || state==QUANT_INIT || state==OUTPUT_NEXT ||
     state==AVG_START || state==AVG_POWER_STORE || state==AVG_WAIT || state==POOL_STORE || state==WRITE_PREP);
  assign window_fetch_in_bounds=fetch_x>=0 && fetch_y>=0 &&
    fetch_x<$signed(34'(c.image.input_w)) && fetch_y<$signed(34'(c.image.input_h));
  assign input_bank_mask=active<=TILE/2 ? 2'b11 : 2'b01;
  assign input_read_base=active<=TILE/2 ? (32'(read_bank)<<($clog2(TILE)-1)) : (32'(read_bank)<<$clog2(TILE));
  assign input_response_base=active<=TILE/2 ? (32'(win_rsp_tag)<<($clog2(TILE)-1)) : (32'(win_rsp_tag)<<$clog2(TILE));
  assign win_req_valid=window_fetch_enabled && fetch_position<32'(position_count) &&
    !input_ready[wf_bank] && !input_reserved[wf_bank] && window_fetch_in_bounds;
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
    // Compare the two coordinate candidates before selecting the next tap.
    next_window_valid=spatial && !global_pool && tap+1<taps &&
      (kernel_column_end ? next_row_valid : next_column_valid);
    avg_power_two=valid_taps!=0 && (valid_taps&(valid_taps-1))==0;
    avg_shift=0;
    for (int bit_index=0;bit_index<TAP_COUNT_W;bit_index++) if (valid_taps[bit_index]) avg_shift=6'(bit_index);
  end

  // Parameter and cached-input phases configure their exact allocation ranges
  // after the preceding transfers have completed. The descriptor stays fixed.
  always_comb begin
    dma_cfg_valid = state==CONFIGURE && dma_cfg_ready;
    dma_conv_enable = spatial;
    dma_range_enable = 1'b1;
    dma_conv_cfg = c.image;
    dma_conv_cfg.input_base = c.input_base;
    dma_conv_cfg.group_c = c.image.input_c;
    dma_conv_cfg.group_offset = 0;
    dma_conv_cfg.input_s16 = 0;
    dma_conv_cfg.windowed = spatial;
    dma_conv_cfg.prefetch_enable = 1;
    for (int i=0;i<4;i++) begin dma_range_base[i]=0; dma_range_end[i]=0; end
    if (global_pool && input_range_mode) begin
      dma_range_base[0]=c.input_base;dma_range_end[0]=33'(64'(c.input_base)+input_bytes);
    end else if (depthwise) begin
      dma_range_base[0]=c.rhs_base; dma_range_end[0]=33'(64'(c.rhs_base)+weight_bytes);
      if (c.bias_base!=0) begin
        dma_range_base[1]=c.bias_base; dma_range_end[1]=33'(64'(c.bias_base)+parameter_bytes);
      end
      dma_range_base[2]=c.multiplier_base; dma_range_end[2]=33'(64'(c.multiplier_base)+parameter_bytes);
      dma_range_base[3]=c.shift_base; dma_range_end[3]=33'(64'(c.shift_base)+parameter_bytes);
    end else if (!spatial) begin
      dma_range_base[0]=c.input_base; dma_range_end[0]=33'(64'(c.input_base)+input_bytes);
      if (binary_vector || softmax_s8) begin
        dma_range_base[1]=c.rhs_base;
        dma_range_end[1]=33'(64'(c.rhs_base)+(softmax_s8 ? 64'd1024 : input_bytes));
      end
    end
  end

  assign rd_req = state==LOAD_REQ || state==POOL_LOAD_REQ || state==SOFT_LUT_REQ;
  assign rd_start = rd_req && rd_granted;
  always_comb begin
    rd_im2col = 1'b0;
    rd_p0 = 0;
    rd_q0 = 0;
    rd_base_addr = 0;
    rd_row_stride = 0;
    rd_rows_to_read = 1;
    rd_valid_cols = active;
    rd_use_16bits = !spatial && c.vector_s16;
    load_bytes = active << rd_use_16bits;
    case (load_kind)
      LD_WEIGHT: begin rd_base_addr=c.rhs_base+load_tap_offset+channel_base;
        rd_use_16bits=0; load_bytes=active; end
      LD_BIAS: begin rd_base_addr=c.bias_base+(channel_base<<2);
        rd_use_16bits=0; load_bytes=active<<2; rd_valid_cols=active<<2; end
      LD_MULT: begin rd_base_addr=c.multiplier_base+(channel_base<<2);
        rd_use_16bits=0; load_bytes=active<<2; rd_valid_cols=active<<2; end
      LD_SHIFT: begin rd_base_addr=c.shift_base+(channel_base<<2);
        rd_use_16bits=0; load_bytes=active<<2; rd_valid_cols=active<<2; end
      LD_A: rd_base_addr=c.input_base+(vector_offset<<c.vector_s16);
      LD_B: rd_base_addr=c.rhs_base+(vector_offset<<c.vector_s16);
      default: ;
    endcase
    rd_burst_len_m1 = 8'(((load_bytes+BUS_BYTES-1)>>BUS_SHIFT)-1);
    if (state==SOFT_LUT_REQ || state==SOFT_LUT_WAIT) begin
      rd_base_addr=c.rhs_base+({24'd0,soft_lut_index}<<2);
      rd_use_16bits=0;rd_valid_cols=4;rd_burst_len_m1=0;
    end
    if (state==POOL_LOAD_REQ || state==POOL_LOAD_WAIT) begin
      rd_base_addr=c.input_base+pool_byte_offset+channel_base;rd_use_16bits=0;
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
      wire half_group = state==EXECUTE && global_pool && active==4 && vector_base[2];
      for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_lane
        assign input_lane[lane] = half_group ? bank_current[(lane+4)%PE_COUNT] : bank_current[lane];
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
    // Folding the common left shift into the input divisor preserves the
    // complete fixed-point quotient and performs exactly one RNE per stage.
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
  for (genvar lane=0;lane<PE_COUNT;lane++) begin : g_operand_register
    wire enabled=(TILE_INDEX_W+1)'(compute_index)+(TILE_INDEX_W+1)'(lane)<(TILE_INDEX_W+1)'(active);
    assign pe_a[lane]=enabled ? input_lane[lane] : 16'sd0;
    assign pe_b[lane]=enabled ? (depthwise ? 16'($signed(weight_lane[lane])) : rhs_lane[lane]) : 16'sd0;
    assign pe_acc[lane]=enabled ? accum_lane[lane] : 32'sd0;
    always_ff @(posedge clk) if (state==EXECUTE && (c.op!=VEC_HADAMARD || !writeback_busy)) begin
      pe_a_q[lane]<=pe_a[lane];
      pe_b_q[lane]<=pe_b[lane];
      pe_acc_q[lane]<=pe_acc[lane];
    end
  end
  always_ff @(posedge clk) if (state==EXECUTE) pe_op_q<=pe_op;
  // Channel banks provide a complete tap without a flattened channel/tap mux.
  for (genvar channel=0;channel<TILE;channel++) begin : g_weight_channel
    localparam int DMA_LANE=channel%BUS_BYTES;
    wire write_enable=state==LOAD_WAIT && load_kind==LD_WEIGHT && rd_valid[DMA_LANE] &&
        32'(rd_col_base)+32'(DMA_LANE)==32'(channel) && 32'(channel)<active;
    wire signed [7:0] write_value=8'(rd_data[DMA_LANE]);
    vector_weight_bank #(.DEPTH(MAX_TAPS)) u_bank (
      .clk, .write_enable(rst_n && write_enable),
      .write_address(load_tap), .write_data(write_value),
      .read_address(tap), .read_data(weight_tap_data[channel])
    );
  end

  for (genvar l=0;l<PE_COUNT;l++) begin : g_pe
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(1'b0)) u_pe(.op(pe_op_q),.a(pe_a_q[l]),.b(pe_b_q[l]),.acc(pe_acc_q[l]),.result(pe_result[l]));
  end

  localparam int ADD_INDEX_WIDTH=$clog2(TILE)>0 ? $clog2(TILE) : 1;
  wire signed [7:0] add_first_lhs=input_buf[0][7:0];
  wire signed [7:0] add_next_lhs=input_buf[ADD_INDEX_WIDTH'(compute_index)+ADD_INDEX_WIDTH'(1)][7:0];
  wire signed [7:0] add_rhs=rhs_buf[ADD_INDEX_WIDTH'(compute_index)][7:0];
  // Validated S8 operands plus offsets in [-127,128] produce [-255,255].
  wire signed [8:0] add_first_lhs_offset=$signed({add_first_lhs[7],add_first_lhs})+$signed(c.add.input1_offset[8:0]);
  wire signed [8:0] add_next_lhs_offset=$signed({add_next_lhs[7],add_next_lhs})+$signed(c.add.input1_offset[8:0]);
  wire signed [8:0] add_rhs_offset=$signed({add_rhs[7],add_rhs})+$signed(c.add.input2_offset[8:0]);
  // Existing load, round and sum cycles prepare the next multiply operand.
  // This register also holds the sum for the output scaling stage.
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

  always_comb begin
    reduce_next=reduce_acc+acc_buf[reduce_index];
    if (c.op==VEC_MAX) reduce_next=reduce_acc>acc_buf[reduce_index] ? reduce_acc : acc_buf[reduce_index];
    if (c.op==VEC_MIN) reduce_next=reduce_acc<acc_buf[reduce_index] ? reduce_acc : acc_buf[reduce_index];
  end
  localparam int POOL_SUM_WIDTH=8+$clog2(POOL_MAX_TAPS);
  wire signed [POOL_SUM_WIDTH-1:0] avg_pool_sum=acc_buf[quant_index][POOL_SUM_WIDTH-1:0];
  wire [POOL_SUM_WIDTH-1:0] avg_unsigned_magnitude=avg_pool_sum<0 ?
      $unsigned(-avg_pool_sum) : $unsigned(avg_pool_sum);
  assign avg_input_magnitude=32'(avg_unsigned_magnitude);
  assign avg_overestimate=avg_residual_q[AVG_SCALE_BITS+1];
  assign avg_twice_remainder={avg_remainder_q,1'b0};
  assign avg_done=state==AVG_WAIT && avg_phase==4'd8;
  always_ff @(posedge clk) begin
    // QUANT_INIT precedes every reciprocal-based average and isolates the
    // accumulator selection and absolute value from the shared multiplier.
    if (state==QUANT_INIT && c.op==AVGPOOL_S8 && !avg_power_two)
      avg_numerator_q<=AVG_SCALE_BITS'(avg_input_magnitude);
    if (state==AVG_START && !avg_power_two) begin
      avg_phase<=0;
    end else if (state==AVG_WAIT) begin
      if (avg_phase==1) avg_estimate_q<=8'(multiplier_product >> AVG_SCALE_BITS);
      if (avg_phase==4) avg_check_q<=(AVG_SCALE_BITS+1)'(multiplier_product);
      if (avg_phase==5) avg_residual_q<=
          $signed({2'b00,avg_numerator_q})-$signed({1'b0,avg_check_q});
      // A ceiling reciprocal can overestimate the quotient by one. The
      // corrected remainder is smaller than valid_taps and fits TAP_COUNT_W.
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
      (state==AVG_START ? $signed(32'(avg_reciprocal[valid_taps])) : $signed(32'(valid_taps))) :
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
    .exp_we(soft_exp_we),.exp_index(soft_exp_index),.exp_wdata(soft_exp_data),.exp_rdata(acc_buf[soft_exp_index]),
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
  // Linear S8 responses contain a contiguous prefix in logical column order.
  // Rotate each response once into the fixed banks of the existing input store.
  wire [BUS_SHIFT-1:0] pool_first_bank=BUS_SHIFT'(pool_received);
  for (genvar bank=0;bank<BUS_BYTES;bank++) begin : g_pool_bank
    wire [BUS_SHIFT-1:0] source_lane=BUS_SHIFT'(bank)-pool_first_bank;
    wire [INPUT_INDEX_W:0] destination_index=pool_received+(INPUT_INDEX_W+1)'(source_lane);
    wire bank_receive=pool_response_fire && (BUS_SHIFT+1)'(source_lane)<pool_received_count &&
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

  wire signed [31:0] q_clamped_data=q_with_offset<$signed(64'(c.activation_min)) ? c.activation_min :
      q_with_offset>$signed(64'(c.activation_max)) ? c.activation_max : q_with_offset[31:0];
  for (genvar entry=0;entry<DMA_SIZE;entry++) begin : g_input_write
    if (entry>=2*TILE) begin : g_unused
      assign input_buf[entry]=16'sd0;
    end else begin : g_buffer
    localparam int S8_LANE=entry%BUS_BYTES;
    localparam int S16_LANE=entry%(BUS_BYTES/2);
    wire load_match=c.vector_s16 ?
        dma_input_write_valid[S16_LANE] && dma_input_write_index[S16_LANE]==INPUT_INDEX_W'(entry) :
        dma_input_write_valid[S8_LANE] && dma_input_write_index[S8_LANE]==INPUT_INDEX_W'(entry);
    wire signed [15:0] load_value=c.vector_s16 ? rd_data[S16_LANE] : rd_data[S8_LANE];
    logic write_enable;
    logic signed [15:0] write_value;
    localparam int WINDOW_BANK=entry%4;
    wire window_match=window_bank_valid[WINDOW_BANK] &&
        window_bank_index[WINDOW_BANK]==INPUT_INDEX_W'(entry);
    wire signed [15:0] window_value=window_bank_data[WINDOW_BANK];
    wire pool_match=pool_bank_valid[S8_LANE] &&
        pool_bank_row[S8_LANE]==POOL_ROW_W'(entry/BUS_BYTES);
    // DMA, window and pool responses share fixed write ports in each bank.
    always_comb begin
      write_enable=window_match || load_match;
      write_value=load_match ? load_value : window_value;
      if (pool_match) begin
        write_enable=1'b1;write_value=pool_bank_data[S8_LANE];
      end
    end
    always_ff @(posedge clk) if (rst_n && write_enable) input_buf[entry] <= write_value;
    end
  end

  for (genvar entry=0;entry<TILE;entry++) begin : g_parameter_write
    always_ff @(posedge clk) begin
      if (rst_n && state==TILE_INIT) bias_buf[entry]<=0;
      if (rst_n && state==LOAD_WAIT && rd_raw_valid && 32'(entry)<active) begin
        for (int word=0;word<BUS_WIDTH/32;word++) begin
          if ((32'(rd_col_base)>>2)+32'(word)==32'(entry)) begin
            case (load_kind)
              LD_BIAS: bias_buf[entry]<=$signed(rd_raw_data[word*32+:32]);
              LD_MULT: mult_buf[entry]<=$signed(rd_raw_data[word*32+:32]);
              LD_SHIFT: right_shift_buf[entry]<=6'd31-rd_raw_data[word*32+:6];
              default: ;
            endcase
          end
        end
      end
    end
  end

  for (genvar entry=0;entry<TILE;entry++) begin : g_accumulator_write
    localparam int LANE_INDEX = entry % PE_COUNT;
    localparam int GROUP_BASE = entry - LANE_INDEX;
    always_ff @(posedge clk) if (rst_n) begin
      if (state==EXECUTE_COMMIT && c.op!=VEC_HADAMARD && 32'(entry)<active &&
          compute_index==TILE_INDEX_W'(GROUP_BASE)) acc_buf[entry]<=pe_result[LANE_INDEX];
      if (state==OUTPUT_INIT) begin
        if (depthwise) acc_buf[entry]<=bias_buf[entry];
        else if (c.op==MAXPOOL_S8) acc_buf[entry]<=-32'sd128;
        else if (c.op==MINPOOL_S8) acc_buf[entry]<=32'sd127;
        else acc_buf[entry]<=0;
      end
      if (state==VECTOR_INIT) begin
        if (c.op==VEC_MAX) acc_buf[entry]<=32'sh8000_0000;
        else if (c.op==VEC_MIN) acc_buf[entry]<=32'sh7fff_ffff;
        else acc_buf[entry]<=0;
      end
      if (softmax_s8 && soft_exp_we && soft_exp_index==$bits(soft_exp_index)'(entry))
        acc_buf[entry]<=soft_exp_data;
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
      c.op==AVGPOOL_S8 ? $signed(64'(acc_buf[quant_index])) : q_product;
  wire [5:0] rounding_amount = add_s8 ? add_right : c.op==AVGPOOL_S8 ? avg_shift : q_right_3;
  wire signed [63:0] rounding_result,rounding_floor;
  vector_round_shift #(.REGISTER_MIDDLE(1'b1)) u_rounding (
    .clk(clk),.value(rounding_input),.amount(rounding_amount),.result(rounding_result),.floor_value(rounding_floor));
  // Validated S8 pooling inputs and limits keep the exact mean in [-128,127].
  wire signed [8:0] pool_activation_min={c.activation_min[7],c.activation_min[7:0]};
  wire signed [8:0] pool_activation_max={c.activation_max[7],c.activation_max[7:0]};
  wire signed [7:0] avg_power_floor=rounding_floor[7:0];
  // Rounding adds zero or one to the floor quotient. Bounds can be checked
  // in parallel with that addition because both activation limits are integers.
  wire signed [31:0] avg_power_result=avg_power_floor<$signed(c.activation_min[7:0]) ? c.activation_min :
      avg_power_floor>=$signed(c.activation_max[7:0]) ? c.activation_max : 32'($signed(rounding_result[7:0]));
  wire signed [8:0] avg_signed=avg_negative ? -$signed({1'b0,avg_magnitude_q}) : $signed({1'b0,avg_magnitude_q});
  wire signed [31:0] avg_div_result=avg_signed<pool_activation_min ? c.activation_min :
      avg_signed>pool_activation_max ? c.activation_max : 32'(avg_signed);
  wire signed [9:0] add_adjusted=$signed(add_rounded[9:0])+$signed({{2{c.output_offset[7]}},c.output_offset[7:0]});
  wire signed [31:0] add_clamped=add_rounded>64'sd255 ? c.activation_max :
      add_rounded< -64'sd256 ? c.activation_min :
      add_adjusted<$signed(c.activation_min) ? c.activation_min :
      add_adjusted>$signed(c.activation_max) ? c.activation_max : 32'(add_adjusted);
  for (genvar entry=0;entry<TILE;entry++) begin : g_result_write
    localparam int LANE_INDEX = entry % PE_COUNT;
    localparam int GROUP_BASE = entry - LANE_INDEX;
    logic write_enable;
    logic [7:0] write_value;
    always_comb begin
      write_enable = 1'b0;
      write_value = '0;
      if (softmax_s8 && soft_out_we && soft_out_index==$bits(soft_out_index)'(entry)) begin
        write_enable = 1'b1;write_value = soft_out_data;
      end
      if (depthwise && state!=IDLE && state!=FAILED && state!=DONE &&
          q_active && q_valid[5] && q_index_5==TILE_INDEX_W'(entry)) begin
        write_enable = 1'b1;write_value = q_clamped_data[7:0];
      end
      if (state==EXECUTE_COMMIT && c.op==VEC_HADAMARD && !writeback_busy &&
          32'(entry)<active && compute_index==TILE_INDEX_W'(GROUP_BASE)) begin
        write_enable = 1'b1;write_value = pe_result[LANE_INDEX][7:0];
      end
      if (state==ADD_STORE && !writeback_busy &&
          32'(entry)<active && compute_index==TILE_INDEX_W'(entry)) begin
        write_enable = 1'b1;write_value = add_clamped[7:0];
      end
      if (state==AVG_POWER_STORE && quant_index==TILE_INDEX_W'(entry)) begin
        write_enable = 1'b1;write_value = avg_power_result[7:0];
      end
      if (state==AVG_WAIT && avg_done && quant_index==TILE_INDEX_W'(entry)) begin
        write_enable = 1'b1;write_value = avg_div_result[7:0];
      end
      if (state==POOL_STORE && 32'(entry)<active) begin
        write_enable = 1'b1;
        write_value = $signed(acc_buf[entry][7:0])<$signed(c.activation_min[7:0]) ? c.activation_min[7:0] :
            $signed(acc_buf[entry][7:0])>$signed(c.activation_max[7:0]) ? c.activation_max[7:0] :
            acc_buf[entry][7:0];
      end
      if (entry==0 && state==VECTOR_REDUCE && reduce_index+1>=TILE) begin
        write_enable = 1'b1;write_value = reduce_next[7:0];
      end
    end
    // Byte results update only the byte consumed by byte-mode writeback.
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
      read_bank<=0;wf_bank<=0;input_ready<=0;input_reserved<=0;
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
        input_reserved[wf_bank]<=1;
        wf_bank<=(wf_bank+1'b1)&input_bank_mask;
      end
      if (window_response_fire) begin
        window_received<=window_received+32'(window_response_count);
        if(win_rsp_last) begin
          input_reserved[win_rsp_tag]<=0;input_ready[win_rsp_tag]<=!win_rsp_error;
          window_received<=0;
        end
      end
      if (param_bad) param_bad_seen<=1;
      if (pool_response_fire) begin
        pool_received<=pool_received+(INPUT_INDEX_W+1)'(pool_received_count);
        if (pool_row_remaining<=BUS_BYTES) pool_row_remaining<=pool_row_columns;
        else pool_row_remaining<=pool_row_remaining-(INPUT_INDEX_W+1)'(BUS_BYTES);
      end
      case (state)
        IDLE: if (start) begin
          c<=cfg; error<=0; state<=CHECK;
          input_range_mode<=0;
          q_active<=0;q_valid<=0;
          input_ready<=0;input_reserved<=0;read_bank<=0;wf_bank<=0;window_received<=0;
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
          input_ready<=0;input_reserved<=0;read_bank<=0;wf_bank<=0;window_received<=0;
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
          if (rd_error || pool_received+(INPUT_INDEX_W+1)'(pool_received_count)!=pool_elements) begin error<=2'b10;state<=FAILED;end
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
            write_origin<=c.output_base+(vector_offset<<2);write_total<=active<<2;state<=WRITE_PREP;
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
            write_origin<=c.output_base+vector_offset;write_total<=active;state<=WRITE_PREP;
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
            q_accumulator<=acc_buf[q_issue];q_multiplier<=mult_buf[q_issue];
            q_right_0<=right_shift_buf[q_issue];q_index_0<=q_issue;q_issue<=q_issue+1'b1;
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
            write_origin<=c.output_base+position_offset+channel_base;write_total<=active;state<=WRITE_PREP;
          end
        end
        AVG_START: if (avg_power_two) state<=AVG_POWER_STORE;
          else begin avg_negative<=acc_buf[quant_index]<0;state<=AVG_WAIT;end
        AVG_POWER_STORE: begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=AVG_START;end
          else begin write_origin<=c.output_base+position_offset+channel_base;write_total<=active;state<=WRITE_PREP;end
        end
        AVG_WAIT: if (avg_done) begin
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=QUANT_INIT;end
          else begin write_origin<=c.output_base+position_offset+channel_base;
            write_total<=active;state<=WRITE_PREP;end
        end
        POOL_STORE: begin
          write_origin<=c.output_base+position_offset+channel_base;
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
          else begin write_origin<=c.output_base;write_total<=active;state<=WRITE_PREP;end
        end else if (soft_lut_req_valid) begin soft_lut_data<=0;state<=SOFT_LUT_REQ;end
        SOFT_LUT_REQ: if (rd_granted) state<=SOFT_LUT_WAIT;
        SOFT_LUT_WAIT: if (rd_done) state<=SOFT_RUN;
        VECTOR_INIT: begin
          vector_offset<=0;active<=c.length<TILE ? c.length : 32'(TILE);
          load_kind<=LD_A;state<=LOAD_REQ;
        end
        VECTOR_NEXT: if (vector_offset+active<c.length) begin
          vector_offset<=vector_offset+active;
          active<=c.length-vector_offset-active<TILE ? c.length-vector_offset-active : 32'(TILE);
          load_kind<=LD_A;state<=LOAD_REQ;
        end else if (c.op==VEC_HADAMARD || add_s8) state<=DRAIN;
        else begin
          reduce_acc<=c.op==VEC_MAX ? 32'sh8000_0000 : c.op==VEC_MIN ? 32'sh7fff_ffff : 32'sd0;
          reduce_index<=0;state<=VECTOR_REDUCE;
        end
        VECTOR_REDUCE: begin
          reduce_acc<=reduce_next;
          if (reduce_index+1<TILE) reduce_index<=reduce_index+1;
          else begin write_origin<=c.output_base;write_total<=4;state<=WRITE_PREP;end
        end
        FAILED: if (!rd_busy && !wr_busy && !win_busy && !writeback_busy && dma_cfg_ready) begin
          q_active<=0;q_valid<=0;
          input_reserved<=0;input_ready<=0;state<=DONE;
        end
        DONE: if (done_ready) state<=IDLE;
        default: begin error<=2'b10;state<=FAILED;end
      endcase
      if ((writeback_done && writeback_error) ||
          (window_response_fire && win_rsp_last && (win_rsp_error || window_received+32'(window_response_count)!=active))) begin
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

// Asynchronous tap reads preserve the vector issue schedule.
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
