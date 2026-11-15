// SPDX-License-Identifier: Apache-2.0
// Descriptor-driven vector arithmetic, quantized Add, depthwise and pooling.
module vector_engine #(
  parameter int TILE = 16,
  parameter int DMA_SIZE = 4*TILE,
  parameter int PE_COUNT = (TILE < 8) ? TILE : 8,
  parameter int MAX_TAPS = 49,
  parameter int POOL_MAX_TAPS = 256,
  parameter int LINE_CACHE_MAX_WIDTH = 64
) (
  input logic clk, rst_n,
  input logic start,
  input vector_engine_pkg::vector_engine_cfg_t cfg,
  output logic ready, done_valid,
  input logic done_ready,
  output logic [1:0] error,
  output logic [31:0] stat_cycles, stat_compute, stat_dma_wait,

  output logic dma_cfg_valid,
  input logic dma_cfg_ready,
  output logic dma_conv_enable, dma_range_enable,
  output conv_im2col_pkg::conv_cfg_t dma_conv_cfg,
  output logic [31:0] dma_range_base [4],
  output logic [32:0] dma_range_end [4],

  output logic rd_req, rd_start,
  input logic rd_granted,
  output logic rd_im2col,
  output logic [31:0] rd_p0, rd_q0, rd_base_addr, rd_row_stride,
  output logic [31:0] rd_rows_to_read, rd_valid_cols,
  output logic [7:0] rd_burst_len_m1,
  output logic rd_use_16bits,
  input logic rd_busy, rd_done, rd_error,
  input logic signed [15:0] rd_data [4],
  input logic rd_valid [4],
  input logic [$clog2(DMA_SIZE)-1:0] rd_col_base,
  input logic [31:0] rd_raw_data,
  input logic rd_raw_valid,

  output logic wr_req, wr_start,
  input logic wr_granted,
  output logic [31:0] wr_base_addr, wr_row_stride, wr_rows_to_write,
  output logic [7:0] wr_burst_len_m1,
  output logic [31:0] src_wdata,
  output logic [3:0] src_wmask,
  output logic src_wvalid,
  input logic src_wready, wr_busy, wr_done, wr_error
);
  import vector_engine_pkg::*;
  typedef enum logic [5:0] {
    IDLE, CHECK, CONFIGURE, TILE_INIT, LOAD_REQ, LOAD_WAIT,
    OUTPUT_INIT, TAP_CHECK, WINDOW_REQ, WINDOW_WAIT, EXECUTE, TAP_NEXT,
    QUANT_INIT, Q_SHIFT, Q_MULT, Q_ROUND, Q_STORE, AVG_START, AVG_WAIT,
    POOL_STORE, WRITE_PREP, WRITE_REQ, WRITE_DATA, WRITE_WAIT,
    OUTPUT_NEXT, VECTOR_INIT, VECTOR_NEXT, VECTOR_REDUCE, FAILED, DONE,
    ADD_MULT, ADD_ROUND, ADD_SUM, ADD_STORE,
    CACHE_CONFIGURE, CACHE_CHECK, CACHE_LOAD_PREP, CACHE_LOAD_REQ, CACHE_LOAD_WAIT,
    POOL_LOAD_PREP, POOL_LOAD_REQ, POOL_LOAD_WAIT
  } state_t;
  typedef enum logic [2:0] {LD_WEIGHT, LD_BIAS, LD_MULT, LD_SHIFT, LD_A, LD_B} load_t;
  state_t state;
  load_t load_kind;
  vector_engine_cfg_t c;
  logic spatial, depthwise, binary_vector, add_s8, byte_output;
  logic [31:0] channels, taps, active, channel_base, position;
  logic [31:0] ox, oy, kx, ky, tap, load_tap, valid_taps;
  logic [31:0] vector_offset, compute_index, quant_index, reduce_index;
  logic signed [15:0] input_buf [DMA_SIZE], rhs_buf [TILE];
  logic signed [7:0] weight_buf [MAX_TAPS*TILE];
  logic signed [31:0] bias_buf [TILE], mult_buf [TILE], shift_buf [TILE];
  logic signed [31:0] acc_buf [TILE], result_buf [TILE];
  logic [2:0] pe_op;
  logic signed [15:0] pe_a [PE_COUNT], pe_b [PE_COUNT];
  logic signed [31:0] pe_acc [PE_COUNT], pe_result [PE_COUNT];
  logic [1:0] add_stage, add_part;
  logic [5:0] add_right;
  logic signed [31:0] add_multiplier;
  logic signed [31:0] add_operand [PE_COUNT];
  logic signed [31:0] add_scaled_a [PE_COUNT], add_scaled_b [PE_COUNT];
  logic signed [31:0] add_sum [PE_COUNT];
  logic signed [63:0] add_product [PE_COUNT], add_rounded [PE_COUNT];
  logic signed [63:0] add_acc_base [PE_COUNT], add_acc_term [PE_COUNT];
  logic signed [63:0] add_acc_next [PE_COUNT];
  logic signed [31:0] reduce_acc, reduce_next;
  logic signed [63:0] input_y, input_x;
  logic in_bounds, param_bad, param_bad_seen;
  logic cfg_ok;
  logic [63:0] input_bytes, output_bytes, weight_bytes, parameter_bytes;
  logic [63:0] kernel_count, position_count;
  logic [31:0] load_bytes;
  logic signed [31:0] q_accumulator;
  logic signed [63:0] q_product, q_rounded, q_with_offset;
  logic [5:0] q_right;
  logic div_start, div_busy, div_done, div_zero, avg_negative;
  logic [31:0] div_numerator, div_quotient, div_remainder, avg_magnitude;
  logic [31:0] write_origin, write_total, write_index, write_count;
  logic [31:0] write_addr_q, write_data_q;
  logic [3:0] write_mask_q;
  logic [31:0] pack_addr, pack_count, pack_data;
  logic [3:0] pack_mask;
  localparam int CACHE_BANKS = (PE_COUNT < 4) ? 4 : PE_COUNT;
  localparam int CACHE_WIDTH = (LINE_CACHE_MAX_WIDTH < 1) ? 1 : LINE_CACHE_MAX_WIDTH;
  localparam int CACHE_GROUPS = (TILE+CACHE_BANKS-1)/CACHE_BANKS;
  localparam int CACHE_ROW_SIZE = CACHE_WIDTH*CACHE_GROUPS;
  logic signed [7:0] line_buf [CACHE_BANKS][3*CACHE_ROW_SIZE];
  logic cache_enabled, input_range_mode, cache_power_two;
  logic [2:0] line_valid;
  logic [15:0] line_y [3];
  logic [1:0] line_slots [3], cache_scan, cache_slot, cache_requested_slot;
  logic signed [63:0] cache_requested_y;
  logic [31:0] cache_y, cache_x, cache_pixels, cache_received;
  logic [31:0] cache_next_pixels, cache_elements, cache_store_pixel [4], cache_store_channel [4];
  logic [5:0] cache_channel_shift;
  logic [2:0] cache_received_count;
  logic cache_lane_valid [4];
  logic [2:0] cache_lane_prefix [4];
  logic global_pool;
  logic [31:0] pool_offset, pool_pixels, pool_received, pool_pixel;
  logic [31:0] pool_elements, pool_next_pixels, pool_input_index;

  assign spatial = c.op <= MINPOOL_S8;
  assign depthwise = c.op == DW_S8;
  assign add_s8 = c.op == ADD_S8;
  assign byte_output = spatial || add_s8;
  assign binary_vector = c.op == VEC_DOT || c.op == VEC_HADAMARD || add_s8;
  assign q_with_offset = q_rounded + $signed(64'(c.output_offset));
  assign ready = state == IDLE;
  assign done_valid = state == DONE;
  assign channels = {16'd0,c.image.input_c};
  assign input_y = $signed(64'(oy)*64'(c.image.stride_h)) - $signed(64'(c.image.pad_top))
                 + $signed(64'(ky)*64'(c.image.dilation_h));
  assign input_x = $signed(64'(ox)*64'(c.image.stride_w)) - $signed(64'(c.image.pad_left))
                 + $signed(64'(kx)*64'(c.image.dilation_w));
  assign in_bounds = input_y >= 0 && input_x >= 0 &&
                     input_y < $signed(64'(c.image.input_h)) &&
                     input_x < $signed(64'(c.image.input_w));
  assign global_pool = spatial && !depthwise && c.image.output_h==1 && c.image.output_w==1 &&
                       c.image.kernel_h==c.image.input_h && c.image.kernel_w==c.image.input_w &&
                       c.image.pad_top==0 && c.image.pad_left==0 &&
                       c.image.dilation_h==1 && c.image.dilation_w==1;
  assign cache_enabled = LINE_CACHE_MAX_WIDTH!=0 && spatial && !global_pool && !c.image.bypass_cache &&
                         ((depthwise && c.image.kernel_h==3 && c.image.kernel_w==3) ||
                          (!depthwise && c.image.kernel_h<=3 && c.image.kernel_w<=3)) &&
                         c.image.dilation_h==1 && c.image.dilation_w==1 &&
                         32'(c.image.input_w)<=32'(LINE_CACHE_MAX_WIDTH);
  assign cache_requested_y = $signed(64'(oy)*64'(c.image.stride_h)) -
                            $signed(64'(c.image.pad_top)) + $signed(64'(cache_scan));
  assign cache_requested_slot = 2'(32'(cache_requested_y)%32'd3);

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
    cache_next_pixels = cache_power_two && active>=4 ? 32'(DMA_SIZE)>>cache_channel_shift : 32'd1;
    if (cache_next_pixels>32'(c.image.input_w)-cache_x)
      cache_next_pixels=32'(c.image.input_w)-cache_x;
    cache_elements=cache_power_two ? cache_pixels<<cache_channel_shift : active;
    pool_next_pixels=cache_power_two && active>=4 ? 32'(DMA_SIZE)>>cache_channel_shift : 32'd1;
    if (pool_next_pixels>taps-pool_offset) pool_next_pixels=taps-pool_offset;
    pool_elements=cache_power_two ? pool_pixels<<cache_channel_shift : active;
    pool_input_index=cache_power_two ? pool_pixel<<cache_channel_shift : 32'd0;
    cache_received_count=0;
    for (int l=0;l<4;l++) begin
      cache_lane_valid[l]=rd_valid[l] && 32'(rd_col_base)+32'(l)<rd_valid_cols;
      cache_lane_prefix[l]=cache_received_count;
      if (cache_lane_valid[l]) cache_received_count=cache_received_count+1'b1;
      cache_store_pixel[l]=cache_x;
      cache_store_channel[l]=cache_received+32'(cache_lane_prefix[l]);
      if (cache_power_two) begin
        cache_store_pixel[l]=cache_x+((cache_received+32'(cache_lane_prefix[l]))>>cache_channel_shift);
        cache_store_channel[l]=(cache_received+32'(cache_lane_prefix[l]))&(active-1);
      end
    end
  end

  function automatic logic range_ok(input logic [31:0] base, input logic [63:0] bytes);
    range_ok = bytes != 0 && (64'(base)+bytes < 64'h1_0000_0000);
  endfunction
  function automatic logic separate_ranges(input logic [31:0] a, input logic [63:0] an,
                                            input logic [31:0] b, input logic [63:0] bn);
    separate_ranges = (64'(a)+an <= 64'(b)) || (64'(b)+bn <= 64'(a));
  endfunction
  function automatic logic signed [31:0] clamp_s8(input logic signed [63:0] value,
                                                   input logic signed [31:0] lo, hi);
    if (value < $signed(64'(lo))) clamp_s8 = lo;
    else if (value > $signed(64'(hi))) clamp_s8 = hi;
    else clamp_s8 = 32'(value);
  endfunction
  function automatic logic signed [63:0] round_shift_even(input logic signed [63:0] product,
                                                         input logic [5:0] right_shift);
    logic signed [63:0] quotient;
    logic [63:0] mask, remainder, half;
    quotient = product >>> right_shift;
    mask = (64'd1 << right_shift)-1;
    remainder = $unsigned(product) & mask;
    half = 64'd1 << (right_shift-1'b1);
    if (right_shift == 0) round_shift_even = product;
    else round_shift_even = quotient + 64'(remainder > half ||
                                          (remainder == half && quotient[0]));
  endfunction

  always_comb begin
    kernel_count = 64'(c.image.kernel_h)*64'(c.image.kernel_w);
    position_count = 64'(c.image.output_h)*64'(c.image.output_w);
    parameter_bytes = 64'(channels)*4;
    weight_bytes = kernel_count*64'(channels);
    input_bytes = spatial ? 64'(c.image.input_h)*64'(c.image.input_w)*64'(channels) :
                            64'(c.length)*(c.vector_s16 ? 2 : 1);
    output_bytes = spatial ? position_count*64'(channels) :
                     add_s8 ? 64'(c.length) : c.op==VEC_HADAMARD ? 64'(c.length)*4 : 64'd4;
    cfg_ok = c.op <= ADD_S8 && range_ok(c.input_base,input_bytes) &&
             range_ok(c.output_base,output_bytes) &&
             separate_ranges(c.input_base,input_bytes,c.output_base,output_bytes);
    if (spatial) begin
      cfg_ok = cfg_ok && c.image.input_h!=0 && c.image.input_w!=0 && channels!=0 &&
        c.image.output_h!=0 && c.image.output_w!=0 && c.image.kernel_h!=0 && c.image.kernel_w!=0 &&
        kernel_count<=64'(depthwise ? MAX_TAPS : POOL_MAX_TAPS) && c.image.stride_h!=0 && c.image.stride_w!=0 &&
        c.image.dilation_h!=0 && c.image.dilation_w!=0 && !c.image.input_s16 && !c.vector_s16 &&
        weight_bytes<=64'hffff_ffff && position_count<=64'hffff_ffff &&
        c.activation_min>=-128 && c.activation_max<=127 && c.activation_min<=c.activation_max;
      if (depthwise) begin
        cfg_ok = cfg_ok && c.image.input_offset>=-127 && c.image.input_offset<=128 &&
          c.output_offset>=-128 && c.output_offset<=127 &&
          range_ok(c.rhs_base,weight_bytes) && range_ok(c.multiplier_base,parameter_bytes) &&
          range_ok(c.shift_base,parameter_bytes) && c.multiplier_base[1:0]==0 && c.shift_base[1:0]==0 &&
          separate_ranges(c.rhs_base,weight_bytes,c.output_base,output_bytes) &&
          separate_ranges(c.multiplier_base,parameter_bytes,c.output_base,output_bytes) &&
          separate_ranges(c.shift_base,parameter_bytes,c.output_base,output_bytes);
        if (c.bias_base!=0) cfg_ok = cfg_ok && c.bias_base[1:0]==0 &&
          range_ok(c.bias_base,parameter_bytes) && separate_ranges(c.bias_base,parameter_bytes,c.output_base,output_bytes);
      end else begin
        cfg_ok = cfg_ok && c.image.input_offset==0 && c.output_offset==0 &&
          c.image.dilation_h==1 && c.image.dilation_w==1 &&
          c.image.pad_top<c.image.kernel_h && c.image.pad_left<c.image.kernel_w &&
          ((64'(c.image.output_h)-1)*64'(c.image.stride_h) < 64'(c.image.input_h)+64'(c.image.pad_top)) &&
          ((64'(c.image.output_w)-1)*64'(c.image.stride_w) < 64'(c.image.input_w)+64'(c.image.pad_left));
      end
    end else begin
      cfg_ok = cfg_ok && c.length!=0 && (add_s8 || c.output_base[1:0]==0);
      if (c.vector_s16) cfg_ok = cfg_ok && c.input_base[0]==0;
      if (binary_vector) begin
        cfg_ok = cfg_ok && range_ok(c.rhs_base,input_bytes) &&
          separate_ranges(c.rhs_base,input_bytes,c.output_base,output_bytes);
        if (c.vector_s16) cfg_ok = cfg_ok && c.rhs_base[0]==0;
      end
      if (add_s8) cfg_ok = cfg_ok && !c.vector_s16 &&
        c.add.input1_offset>=-127 && c.add.input1_offset<=128 &&
        c.add.input2_offset>=-127 && c.add.input2_offset<=128 &&
        c.add.input1_multiplier>=0 && c.add.input2_multiplier>=0 && c.add.output_multiplier>=0 &&
        c.add.input1_shift>=-31 && c.add.input1_shift<=0 &&
        c.add.input2_shift>=-31 && c.add.input2_shift<=0 &&
        c.add.left_shift>=0 && c.add.left_shift<=22 &&
        c.add.output_shift>=-31 && c.add.output_shift<=30 &&
        c.output_offset>=-128 && c.output_offset<=127 &&
        c.activation_min>=-128 && c.activation_max<=127 && c.activation_min<=c.activation_max;
    end
  end

  // Parameter and cached-input phases configure their exact allocation ranges
  // after the preceding transfers have completed. The descriptor stays fixed.
  always_comb begin
    dma_cfg_valid = (state==CONFIGURE || state==CACHE_CONFIGURE) && dma_cfg_ready;
    dma_conv_enable = spatial;
    dma_range_enable = 1'b1;
    dma_conv_cfg = c.image;
    dma_conv_cfg.input_base = c.input_base;
    dma_conv_cfg.group_c = c.image.input_c;
    dma_conv_cfg.group_offset = 0;
    dma_conv_cfg.input_s16 = 0;
    for (int i=0;i<4;i++) begin dma_range_base[i]=0; dma_range_end[i]=0; end
    if ((cache_enabled || global_pool) && input_range_mode) begin
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
      if (binary_vector) begin
        dma_range_base[1]=c.rhs_base; dma_range_end[1]=33'(64'(c.rhs_base)+input_bytes);
      end
    end
  end

  assign rd_req = state==LOAD_REQ || state==WINDOW_REQ || state==CACHE_LOAD_REQ || state==POOL_LOAD_REQ;
  assign rd_start = rd_req && rd_granted;
  always_comb begin
    rd_im2col = state==WINDOW_REQ;
    rd_p0 = position;
    rd_q0 = tap*channels+channel_base;
    rd_base_addr = 0;
    rd_row_stride = 0;
    rd_rows_to_read = 1;
    rd_valid_cols = active;
    rd_use_16bits = !spatial && c.vector_s16;
    load_bytes = active << rd_use_16bits;
    case (load_kind)
      LD_WEIGHT: begin rd_base_addr=c.rhs_base+load_tap*channels+channel_base;
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
    rd_burst_len_m1 = 8'(((load_bytes+3)>>2)-1);
    if (state==WINDOW_REQ) begin rd_use_16bits=1; rd_valid_cols=active; end
    if (state==CACHE_LOAD_REQ || state==CACHE_LOAD_WAIT) begin
      rd_base_addr=c.input_base+(cache_y*32'(c.image.input_w)+cache_x)*channels+channel_base;
      rd_use_16bits=0;
      if (channels==active) begin
        rd_rows_to_read=1;rd_valid_cols=cache_elements;rd_row_stride=0;
        rd_burst_len_m1=8'(((cache_elements+3)>>2)-1);
      end else begin
        rd_rows_to_read=cache_pixels;rd_valid_cols=active;rd_row_stride=channels;
        rd_burst_len_m1=8'(((active+3)>>2)-1);
      end
    end
    if (state==POOL_LOAD_REQ || state==POOL_LOAD_WAIT) begin
      rd_base_addr=c.input_base+pool_offset*channels+channel_base;rd_use_16bits=0;
      if (channels==active) begin
        rd_rows_to_read=1;rd_valid_cols=pool_elements;rd_row_stride=0;
        rd_burst_len_m1=8'(((pool_elements+3)>>2)-1);
      end else begin
        rd_rows_to_read=pool_pixels;rd_valid_cols=active;rd_row_stride=channels;
        rd_burst_len_m1=8'(((active+3)>>2)-1);
      end
    end
    param_bad = state==LOAD_WAIT && rd_raw_valid &&
      ((load_kind==LD_SHIFT && ($signed(rd_raw_data)<-31 || $signed(rd_raw_data)>30)) ||
       (load_kind==LD_MULT && $signed(rd_raw_data)<0));
  end

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
    if (state==ADD_MULT) pe_op=add_part[1] ? PE_MUL_SU : PE_MUL_UU;
    for (int l=0;l<PE_COUNT;l++) begin
      pe_a[l]=0; pe_b[l]=0; pe_acc[l]=0;
      add_operand[l]=add_sum[l];
      if (compute_index+32'(l)<active) begin
        pe_a[l]=input_buf[compute_index+32'(l)];
        if (state==EXECUTE && global_pool)
          pe_a[l]=input_buf[pool_input_index+compute_index+32'(l)];
        if (state==EXECUTE && cache_enabled)
          pe_a[l]=16'($signed(line_buf[(compute_index+32'(l))%CACHE_BANKS]
                     [32'(line_slots[ky])*CACHE_ROW_SIZE+32'(input_x)*CACHE_GROUPS+
                      (compute_index+32'(l))/CACHE_BANKS])) + c.image.input_offset;
        pe_b[l]=depthwise ? 16'($signed(weight_buf[tap*TILE+compute_index+32'(l)])) : rhs_buf[compute_index+32'(l)];
        pe_acc[l]=acc_buf[compute_index+32'(l)];
        if (add_stage==0) add_operand[l]=32'($signed(input_buf[compute_index+32'(l)]))+c.add.input1_offset;
        else if (add_stage==1) add_operand[l]=32'($signed(rhs_buf[compute_index+32'(l)]))+c.add.input2_offset;
        if (state==ADD_MULT) begin
          pe_a[l]=add_part[1] ? add_operand[l][31:16] : add_operand[l][15:0];
          pe_b[l]=add_part[0] ? add_multiplier[31:16] : add_multiplier[15:0];
          pe_acc[l]=0;
        end
      end
    end
  end
  for (genvar l=0;l<PE_COUNT;l++) begin : g_pe
    vector_pe u_pe(.op(pe_op),.a(pe_a[l]),.b(pe_b[l]),.acc(pe_acc[l]),.result(pe_result[l]));
  end

  always_comb begin
    for (int l=0;l<PE_COUNT;l++) begin
      add_acc_base[l]=add_part==0 ? 64'sd0 : add_product[l];
      case (add_part)
        2'd0: add_acc_term[l]=$signed({32'd0,pe_result[l]});
        2'd1: add_acc_term[l]=$signed({16'd0,pe_result[l],16'd0});
        2'd2: add_acc_term[l]=$signed({{16{pe_result[l][31]}},pe_result[l],16'd0});
        default: add_acc_term[l]=$signed({pe_result[l],32'd0});
      endcase
      if (state==ADD_SUM) begin
        add_acc_base[l]=$signed(64'(add_scaled_a[l]));
        add_acc_term[l]=$signed(64'(add_scaled_b[l]));
      end
      add_acc_next[l]=add_acc_base[l]+add_acc_term[l];
    end
  end

  always_comb begin
    reduce_next=reduce_acc+acc_buf[reduce_index];
    if (c.op==VEC_MAX) reduce_next=reduce_acc>acc_buf[reduce_index] ? reduce_acc : acc_buf[reduce_index];
    if (c.op==VEC_MIN) reduce_next=reduce_acc<acc_buf[reduce_index] ? reduce_acc : acc_buf[reduce_index];
  end
  assign div_start = state==AVG_START;
  assign div_numerator = acc_buf[quant_index]<0 ? $unsigned(-acc_buf[quant_index]) :
                           $unsigned(acc_buf[quant_index]);
  assign avg_magnitude = div_quotient + 32'(div_remainder > valid_taps-div_remainder ||
                            (div_remainder == valid_taps-div_remainder && div_quotient[0]));
  conv_udiv32 u_average_divider(.clk,.rst_n,.start(div_start),.dividend(div_numerator),
    .divisor(valid_taps),.busy(div_busy),.done(div_done),.div_zero,
    .quotient(div_quotient),.remainder(div_remainder));

  assign wr_req = state==WRITE_REQ;
  assign wr_start = wr_req && wr_granted;
  // A single aligned write beat never crosses 4 KiB. Byte strobes preserve
  // neighbours of an unaligned NHWC output or a partial channel group.
  always_comb begin
    pack_addr = write_origin+write_index;
    pack_count = 4-{30'd0,pack_addr[1:0]};
    if (pack_count>write_total-write_index) pack_count=write_total-write_index;
    pack_data=0; pack_mask=0;
    for (int b=0;b<4;b++) begin
      if (32'(b)>=32'(pack_addr[1:0]) && 32'(b)<32'(pack_addr[1:0])+pack_count) begin
        pack_mask[b]=1;
        if (byte_output) pack_data[b*8+:8]=8'(result_buf[write_index+32'(b)-32'(pack_addr[1:0])]);
        else pack_data[b*8+:8]=8'(result_buf[(write_index+32'(b)-32'(pack_addr[1:0]))>>2] >>
          (((write_index+32'(b)-32'(pack_addr[1:0]))&3)*8));
      end
    end

    wr_base_addr = write_addr_q;
    wr_row_stride=0; wr_rows_to_write=1; wr_burst_len_m1=0;
    src_wdata=write_data_q; src_wmask=write_mask_q;
    src_wvalid=state==WRITE_DATA;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE; c<='0; error<=0; load_kind<=LD_WEIGHT;
      taps<=0; active<=0; channel_base<=0; position<=0;
      ox<=0;oy<=0;kx<=0;ky<=0;tap<=0;load_tap<=0;valid_taps<=0;
      vector_offset<=0;compute_index<=0;quant_index<=0;reduce_index<=0;
      reduce_acc<=0; param_bad_seen<=0;
      add_stage<=0;add_part<=0;
      for (int l=0;l<PE_COUNT;l++) begin
        add_product[l]<=0;add_scaled_a[l]<=0;add_scaled_b[l]<=0;
        add_sum[l]<=0;add_rounded[l]<=0;
      end
      q_accumulator<=0;q_rounded<=0;q_product<=0;q_right<=0;avg_negative<=0;
      write_origin<=0;write_total<=0;write_index<=0;write_count<=0;
      write_addr_q<=0;write_data_q<=0;write_mask_q<=0;
      stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;
      input_range_mode<=0;line_valid<=0;cache_scan<=0;cache_slot<=0;
      cache_y<=0;cache_x<=0;cache_pixels<=0;cache_received<=0;
      pool_offset<=0;pool_pixels<=0;pool_received<=0;pool_pixel<=0;
      for (int i=0;i<3;i++) begin line_y[i]<=0;line_slots[i]<=0;end
    end else begin
      if (state!=IDLE && state!=DONE) stat_cycles<=stat_cycles+1;
      if (state==EXECUTE || state==ADD_MULT || state==ADD_ROUND ||
          state==ADD_SUM || state==ADD_STORE) stat_compute<=stat_compute+1;
      if (state==LOAD_WAIT || state==WINDOW_WAIT || state==CACHE_LOAD_WAIT || state==POOL_LOAD_WAIT || state==WRITE_DATA || state==WRITE_WAIT ||
          ((state==LOAD_REQ || state==WINDOW_REQ || state==CACHE_LOAD_REQ || state==POOL_LOAD_REQ) && !rd_granted) ||
          (state==WRITE_REQ && !wr_granted) ||
          ((state==CONFIGURE || state==CACHE_CONFIGURE) && !dma_cfg_ready))
        stat_dma_wait<=stat_dma_wait+1;
      if (param_bad) param_bad_seen<=1;
      if (state==LOAD_WAIT) begin
        for (int l=0;l<4;l++) if (rd_valid[l] && 32'(rd_col_base)+32'(l)<active) begin
          case (load_kind)
            LD_WEIGHT: weight_buf[load_tap*TILE+32'(rd_col_base)+32'(l)]<=8'(rd_data[l]);
            LD_A: input_buf[32'(rd_col_base)+32'(l)]<=rd_data[l];
            LD_B: rhs_buf[32'(rd_col_base)+32'(l)]<=rd_data[l];
            default: ;
          endcase
        end
        if (rd_raw_valid && (32'(rd_col_base)>>2)<active) begin
          case (load_kind)
            LD_BIAS: bias_buf[32'(rd_col_base)>>2]<=$signed(rd_raw_data);
            LD_MULT: mult_buf[32'(rd_col_base)>>2]<=$signed(rd_raw_data);
            LD_SHIFT: shift_buf[32'(rd_col_base)>>2]<=$signed(rd_raw_data);
            default: ;
          endcase
        end
      end
      if (state==WINDOW_WAIT) begin
        for (int l=0;l<4;l++) if (rd_valid[l] && 32'(rd_col_base)+32'(l)<active)
          input_buf[32'(rd_col_base)+32'(l)]<=rd_data[l];
      end
      if (state==CACHE_LOAD_WAIT) begin
        cache_received<=cache_received+32'(cache_received_count);
        for (int l=0;l<4;l++) if (cache_lane_valid[l] && cache_received+32'(cache_lane_prefix[l])<cache_elements)
          line_buf[cache_store_channel[l]%CACHE_BANKS]
                  [32'(cache_slot)*CACHE_ROW_SIZE+cache_store_pixel[l]*CACHE_GROUPS+
                   cache_store_channel[l]/CACHE_BANKS]<=8'(rd_data[l]);
      end
      if (state==POOL_LOAD_WAIT) begin
        pool_received<=pool_received+32'(cache_received_count);
        for (int l=0;l<4;l++) if (cache_lane_valid[l] && pool_received+32'(cache_lane_prefix[l])<pool_elements)
          input_buf[pool_received+32'(cache_lane_prefix[l])]<=rd_data[l];
      end
      case (state)
        IDLE: if (start) begin
          c<=cfg; error<=0; state<=CHECK;
          input_range_mode<=0;
          stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;param_bad_seen<=0;
        end
        CHECK: if (!cfg_ok) begin error<=2'b01;state<=FAILED;end
          else begin
            taps<=32'(kernel_count);channel_base<=0;input_range_mode<=(cache_enabled || global_pool) && !depthwise;
            state<=CONFIGURE;
          end
        CONFIGURE: if (dma_cfg_ready) state<=spatial ? TILE_INIT : VECTOR_INIT;
        TILE_INIT: begin
          active<=channels-channel_base<TILE ? channels-channel_base : 32'(TILE);
          position<=0;ox<=0;oy<=0;load_tap<=0;load_kind<=LD_WEIGHT;
          for (int l=0;l<TILE;l++) bias_buf[l]<=0;
          line_valid<=0;cache_scan<=0;
          state<=depthwise ? LOAD_REQ : OUTPUT_INIT;
        end
        LOAD_REQ: if (rd_granted) state<=LOAD_WAIT;
        LOAD_WAIT: if (rd_done) begin
          if (rd_error || param_bad || param_bad_seen) begin error<=2'b10;state<=FAILED;end
          else case (load_kind)
            LD_WEIGHT: if (load_tap+1<taps) begin load_tap<=load_tap+1;state<=LOAD_REQ;end
              else begin load_kind<=c.bias_base==0 ? LD_MULT : LD_BIAS;state<=LOAD_REQ;end
            LD_BIAS: begin load_kind<=LD_MULT;state<=LOAD_REQ;end
            LD_MULT: begin load_kind<=LD_SHIFT;state<=LOAD_REQ;end
            LD_SHIFT: if (cache_enabled) begin input_range_mode<=1;state<=CACHE_CONFIGURE;end
              else state<=OUTPUT_INIT;
            LD_A: if (binary_vector) begin load_kind<=LD_B;state<=LOAD_REQ;end
              else begin compute_index<=0;state<=EXECUTE;end
            LD_B: begin
              compute_index<=0;add_stage<=0;add_part<=0;
              state<=add_s8 ? ADD_MULT : EXECUTE;
            end
            default: begin error<=2'b10;state<=FAILED;end
          endcase
        end
        OUTPUT_INIT: begin
          for (int l=0;l<TILE;l++) begin
            if (depthwise) acc_buf[l]<=bias_buf[l];
            else if (c.op==MAXPOOL_S8) acc_buf[l]<=-32'sd128;
            else if (c.op==MINPOOL_S8) acc_buf[l]<=32'sd127;
            else acc_buf[l]<=0;
          end
          tap<=0;kx<=0;ky<=0;valid_taps<=0;
          if (global_pool) begin
            valid_taps<=taps;pool_offset<=0;state<=POOL_LOAD_PREP;
          end else if (cache_enabled && ox==0) begin cache_scan<=0;state<=CACHE_CHECK;end
          else state<=TAP_CHECK;
        end
        CACHE_CONFIGURE: if (dma_cfg_ready) state<=OUTPUT_INIT;
        CACHE_CHECK: if (32'(cache_scan)==32'(c.image.kernel_h)) state<=TAP_CHECK;
          else if (cache_requested_y<0 || cache_requested_y>=$signed(64'(c.image.input_h)))
            cache_scan<=cache_scan+1'b1;
          else begin
            line_slots[cache_scan]<=cache_requested_slot;
            if (line_valid[cache_requested_slot] && line_y[cache_requested_slot]==16'(cache_requested_y))
              cache_scan<=cache_scan+1'b1;
            else begin
              cache_y<=32'(cache_requested_y);cache_slot<=cache_requested_slot;cache_x<=0;
              line_valid[cache_requested_slot]<=0;state<=CACHE_LOAD_PREP;
            end
          end
        CACHE_LOAD_PREP: begin
          cache_pixels<=cache_next_pixels;cache_received<=0;state<=CACHE_LOAD_REQ;
        end
        CACHE_LOAD_REQ: if (rd_granted) state<=CACHE_LOAD_WAIT;
        CACHE_LOAD_WAIT: if (rd_done) begin
          if (rd_error || cache_received+32'(cache_received_count)!=cache_elements) begin error<=2'b10;state<=FAILED;end
          else if (cache_x+cache_pixels<32'(c.image.input_w)) begin
            cache_x<=cache_x+cache_pixels;state<=CACHE_LOAD_PREP;
          end else begin
            line_valid[cache_slot]<=1;line_y[cache_slot]<=16'(cache_y);
            cache_scan<=cache_scan+1'b1;state<=CACHE_CHECK;
          end
        end
        POOL_LOAD_PREP: begin
          pool_pixels<=pool_next_pixels;pool_received<=0;pool_pixel<=0;state<=POOL_LOAD_REQ;
        end
        POOL_LOAD_REQ: if (rd_granted) state<=POOL_LOAD_WAIT;
        POOL_LOAD_WAIT: if (rd_done) begin
          if (rd_error || pool_received+32'(cache_received_count)!=pool_elements) begin error<=2'b10;state<=FAILED;end
          else begin compute_index<=0;state<=EXECUTE;end
        end
        TAP_CHECK: if (in_bounds) begin
            valid_taps<=valid_taps+1;compute_index<=0;state<=cache_enabled ? EXECUTE : WINDOW_REQ;
          end
          else state<=TAP_NEXT;
        WINDOW_REQ: if (rd_granted) state<=WINDOW_WAIT;
        WINDOW_WAIT: if (rd_done) begin
          if (rd_error) begin error<=2'b10;state<=FAILED;end
          else begin compute_index<=0;state<=EXECUTE;end
        end
        EXECUTE: begin
          for (int l=0;l<PE_COUNT;l++) if (compute_index+32'(l)<active) begin
            if (c.op==VEC_HADAMARD) result_buf[compute_index+32'(l)]<=pe_result[l];
            else acc_buf[compute_index+32'(l)]<=pe_result[l];
          end
          if (compute_index+32'(PE_COUNT)<active) compute_index<=compute_index+32'(PE_COUNT);
          else if (global_pool) begin
            if (pool_pixel+1<pool_pixels) begin pool_pixel<=pool_pixel+1;compute_index<=0;end
            else if (pool_offset+pool_pixels<taps) begin pool_offset<=pool_offset+pool_pixels;state<=POOL_LOAD_PREP;end
            else begin quant_index<=0;state<=QUANT_INIT;end
          end
          else if (spatial) state<=TAP_NEXT;
          else if (c.op==VEC_HADAMARD) begin
            write_origin<=c.output_base+(vector_offset<<2);write_total<=active<<2;write_index<=0;state<=WRITE_PREP;
          end else state<=VECTOR_NEXT;
        end
        ADD_MULT: begin
          for (int l=0;l<PE_COUNT;l++) if (compute_index+32'(l)<active)
            add_product[l]<=add_acc_next[l];
          if (add_part==3) state<=ADD_ROUND;
          else add_part<=add_part+1'b1;
        end
        ADD_ROUND: begin
          for (int l=0;l<PE_COUNT;l++) if (compute_index+32'(l)<active) begin
            if (add_stage==0) add_scaled_a[l]<=32'(round_shift_even(add_product[l],add_right));
            else if (add_stage==1) add_scaled_b[l]<=32'(round_shift_even(add_product[l],add_right));
            else add_rounded[l]<=round_shift_even(add_product[l],add_right);
          end
          add_part<=0;
          if (add_stage==0) begin add_stage<=1;state<=ADD_MULT;end
          else if (add_stage==1) state<=ADD_SUM;
          else state<=ADD_STORE;
        end
        ADD_SUM: begin
          for (int l=0;l<PE_COUNT;l++) if (compute_index+32'(l)<active)
            add_sum[l]<=32'(add_acc_next[l]);
          add_stage<=2;state<=ADD_MULT;
        end
        ADD_STORE: begin
          for (int l=0;l<PE_COUNT;l++) if (compute_index+32'(l)<active)
            result_buf[compute_index+32'(l)]<=clamp_s8(add_rounded[l]+$signed(64'(c.output_offset)),
                                                      c.activation_min,c.activation_max);
          if (compute_index+32'(PE_COUNT)<active) begin
            compute_index<=compute_index+32'(PE_COUNT);add_stage<=0;add_part<=0;state<=ADD_MULT;
          end else begin
            write_origin<=c.output_base+vector_offset;write_total<=active;write_index<=0;state<=WRITE_PREP;
          end
        end
        TAP_NEXT: if (tap+1==taps) begin quant_index<=0;state<=QUANT_INIT;end
          else begin
            tap<=tap+1;
            if (kx+1==32'(c.image.kernel_w)) begin kx<=0;ky<=ky+1;end else kx<=kx+1;
            state<=TAP_CHECK;
          end
        QUANT_INIT: begin
          if (depthwise) state<=Q_SHIFT;
          else if (c.op==AVGPOOL_S8) begin
            if (valid_taps==0) begin error<=2'b01;state<=FAILED;end else state<=AVG_START;
          end else state<=POOL_STORE;
        end
        Q_SHIFT: begin
          q_accumulator<=acc_buf[quant_index];
          q_right<=6'(31-shift_buf[quant_index]);
          state<=Q_MULT;
        end
        Q_MULT: begin q_product<=q_accumulator*mult_buf[quant_index];state<=Q_ROUND;end
        Q_ROUND: begin q_rounded<=round_shift_even(q_product,q_right);state<=Q_STORE;end
        Q_STORE: begin
          result_buf[quant_index]<=clamp_s8(q_with_offset,c.activation_min,c.activation_max);
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=QUANT_INIT;end
          else begin
            write_origin<=c.output_base+position*channels+channel_base;
            write_total<=active;write_index<=0;state<=WRITE_PREP;
          end
        end
        AVG_START: begin avg_negative<=acc_buf[quant_index]<0;state<=AVG_WAIT;end
        AVG_WAIT: if (div_done) begin
          result_buf[quant_index]<=clamp_s8(avg_negative ? -$signed(64'(avg_magnitude)) : $signed(64'(avg_magnitude)),
                                           c.activation_min,c.activation_max);
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=QUANT_INIT;end
          else begin write_origin<=c.output_base+position*channels+channel_base;
            write_total<=active;write_index<=0;state<=WRITE_PREP;end
        end
        POOL_STORE: begin
          result_buf[quant_index]<=clamp_s8($signed(64'(acc_buf[quant_index])),c.activation_min,c.activation_max);
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=QUANT_INIT;end
          else begin write_origin<=c.output_base+position*channels+channel_base;
            write_total<=active;write_index<=0;state<=WRITE_PREP;end
        end
        WRITE_PREP: begin
          write_addr_q<={pack_addr[31:2],2'b00};write_data_q<=pack_data;write_mask_q<=pack_mask;
          write_count<=pack_count;state<=WRITE_REQ;
        end
        WRITE_REQ: if (wr_granted) state<=WRITE_DATA;
        WRITE_DATA: if (src_wready) state<=WRITE_WAIT;
        WRITE_WAIT: if (wr_done) begin
          if (wr_error) begin error<=2'b10;state<=FAILED;end
          else if (write_index+write_count<write_total) begin write_index<=write_index+write_count;state<=WRITE_PREP;end
          else if (spatial) state<=OUTPUT_NEXT;
          else if (c.op==VEC_HADAMARD || add_s8) state<=VECTOR_NEXT;
          else state<=DONE;
        end
        OUTPUT_NEXT: begin
          if (position+1<32'(position_count)) begin
            position<=position+1;
            if (ox+1==32'(c.image.output_w)) begin ox<=0;oy<=oy+1;end else ox<=ox+1;
            state<=OUTPUT_INIT;
          end else if (channel_base+active<channels) begin
            channel_base<=channel_base+active;input_range_mode<=!depthwise;
            state<=cache_enabled || global_pool ? CONFIGURE : TILE_INIT;
          end
          else state<=DONE;
        end
        VECTOR_INIT: begin
          for (int l=0;l<TILE;l++) begin
            if (c.op==VEC_MAX) acc_buf[l]<=32'sh8000_0000;
            else if (c.op==VEC_MIN) acc_buf[l]<=32'sh7fff_ffff;
            else acc_buf[l]<=0;
          end
          vector_offset<=0;active<=c.length<TILE ? c.length : 32'(TILE);
          load_kind<=LD_A;state<=LOAD_REQ;
        end
        VECTOR_NEXT: if (vector_offset+active<c.length) begin
          vector_offset<=vector_offset+active;
          active<=c.length-vector_offset-active<TILE ? c.length-vector_offset-active : 32'(TILE);
          load_kind<=LD_A;state<=LOAD_REQ;
        end else if (c.op==VEC_HADAMARD || add_s8) state<=DONE;
        else begin
          reduce_acc<=c.op==VEC_MAX ? 32'sh8000_0000 : c.op==VEC_MIN ? 32'sh7fff_ffff : 32'sd0;
          reduce_index<=0;state<=VECTOR_REDUCE;
        end
        VECTOR_REDUCE: begin
          reduce_acc<=reduce_next;
          if (reduce_index+1<TILE) reduce_index<=reduce_index+1;
          else begin result_buf[0]<=reduce_next;write_origin<=c.output_base;write_index<=0;write_total<=4;state<=WRITE_PREP;end
        end
        FAILED: if (!rd_busy && !wr_busy && dma_cfg_ready) state<=DONE;
        DONE: if (done_ready) state<=IDLE;
        default: begin error<=2'b10;state<=FAILED;end
      endcase
    end
  end

`ifndef SYNTHESIS
  initial begin
    assert(TILE>=2 && TILE<=64 && (TILE&(TILE-1))==0);
    assert(PE_COUNT>=1 && PE_COUNT<=TILE && TILE%PE_COUNT==0);
    assert(DMA_SIZE>=4*TILE && MAX_TAPS>=1 && MAX_TAPS<=255);
    assert(POOL_MAX_TAPS>=1 && POOL_MAX_TAPS<=65535);
    assert(LINE_CACHE_MAX_WIDTH>=0 && LINE_CACHE_MAX_WIDTH<=65535);
  end
  always_ff @(posedge clk) if (rst_n) begin
    if (src_wvalid && !src_wready) begin
      assert(wr_busy);
    end
    if (state==EXECUTE) assert(active>0 && active<=TILE && compute_index<active);
    if (state==ADD_MULT || state==ADD_ROUND || state==ADD_SUM || state==ADD_STORE) begin
      assert(add_s8 && active>0 && active<=TILE && compute_index<active);
      assert(add_stage<=2 && add_right>=1 && add_right<=62);
      if (state==ADD_SUM) for (int l=0;l<PE_COUNT;l++) if (compute_index+32'(l)<active)
        assert(add_acc_next[l]>=-64'sd2147483648 && add_acc_next[l]<=64'sd2147483647);
    end
    if (state==WINDOW_REQ) assert(in_bounds && tap<taps);
    if (state==CACHE_LOAD_REQ) begin
      assert(cache_enabled && input_range_mode && cache_pixels>0 && cache_elements<=DMA_SIZE);
      assert(cache_x+cache_pixels<=32'(c.image.input_w) && cache_y<32'(c.image.input_h));
    end
    if (state==EXECUTE && cache_enabled) begin
      assert(in_bounds && ky<3 && line_valid[line_slots[ky]]);
      assert(line_y[line_slots[ky]]==16'(input_y));
    end
    if (state==POOL_LOAD_REQ) begin
      assert(global_pool && input_range_mode && pool_pixels>0 && pool_elements<=DMA_SIZE);
      assert(pool_offset+pool_pixels<=taps);
    end
    if (state==EXECUTE && global_pool) assert(pool_pixel<pool_pixels && pool_input_index+active<=pool_elements);
    if (state==WRITE_REQ) assert(write_count>0 && write_count<=4 && write_mask_q!=0);
  end
`endif
endmodule
