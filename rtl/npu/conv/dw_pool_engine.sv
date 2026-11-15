// SPDX-License-Identifier: Apache-2.0
// DMA client for depthwise convolution, pooling and signed vector arithmetic.
module dw_pool_engine #(
  parameter int TILE = 16,
  parameter int DMA_SIZE = 4*TILE,
  parameter int PE_COUNT = (TILE < 8) ? TILE : 8,
  parameter int MAX_TAPS = 49
) (
  input logic clk, rst_n,
  input logic start,
  input dw_pool_pkg::dw_pool_cfg_t cfg,
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
  import dw_pool_pkg::*;
  typedef enum logic [5:0] {
    IDLE, CHECK, CONFIGURE, TILE_INIT, LOAD_REQ, LOAD_WAIT,
    OUTPUT_INIT, TAP_CHECK, WINDOW_REQ, WINDOW_WAIT, EXECUTE, TAP_NEXT,
    QUANT_INIT, Q_SHIFT, Q_MULT, Q_ROUND, Q_STORE, AVG_START, AVG_WAIT,
    POOL_STORE, WRITE_PREP, WRITE_REQ, WRITE_DATA, WRITE_WAIT,
    OUTPUT_NEXT, VECTOR_INIT, VECTOR_NEXT, VECTOR_REDUCE, FAILED, DONE
  } state_t;
  typedef enum logic [2:0] {LD_WEIGHT, LD_BIAS, LD_MULT, LD_SHIFT, LD_A, LD_B} load_t;
  state_t state;
  load_t load_kind;
  dw_pool_cfg_t c;
  logic spatial, depthwise, binary_vector;
  logic [31:0] channels, taps, active, channel_base, position;
  logic [31:0] ox, oy, kx, ky, tap, load_tap, valid_taps;
  logic [31:0] vector_offset, compute_index, quant_index, reduce_index;
  logic signed [15:0] input_buf [TILE], rhs_buf [TILE];
  logic signed [7:0] weight_buf [MAX_TAPS*TILE];
  logic signed [31:0] bias_buf [TILE], mult_buf [TILE], shift_buf [TILE];
  logic signed [31:0] acc_buf [TILE], result_buf [TILE];
  logic [2:0] pe_op;
  logic signed [15:0] pe_a [PE_COUNT], pe_b [PE_COUNT];
  logic signed [31:0] pe_acc [PE_COUNT], pe_result [PE_COUNT];
  logic signed [31:0] reduce_acc, reduce_next;
  logic signed [63:0] input_y, input_x;
  logic in_bounds, param_bad, param_bad_seen;
  logic cfg_ok;
  logic [63:0] input_bytes, output_bytes, weight_bytes, parameter_bytes;
  logic [63:0] kernel_count, position_count;
  logic [31:0] load_bytes;
  logic signed [31:0] q_scaled, q_rounded, q_with_offset;
  logic signed [63:0] q_product;
  logic [4:0] q_right;
  logic div_start, div_busy, div_done, div_zero, avg_negative;
  logic [31:0] div_numerator, div_quotient, div_remainder;
  logic [31:0] write_origin, write_total, write_index, write_count;
  logic [31:0] write_addr_q, write_data_q;
  logic [3:0] write_mask_q;
  logic [31:0] pack_addr, pack_count, pack_data;
  logic [3:0] pack_mask;

  assign spatial = c.op <= MINPOOL_S8;
  assign depthwise = c.op == DW_S8;
  assign binary_vector = c.op == VEC_DOT || c.op == VEC_HADAMARD;
  assign q_with_offset = q_rounded + c.output_offset;
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
  function automatic logic signed [31:0] round_high(input logic signed [63:0] product,
                                                      input logic [4:0] right_shift);
    logic signed [31:0] high, shifted;
    logic [31:0] mask, remainder, threshold;
    high = 32'((product + 64'sh4000_0000) >>> 31);
    mask = (32'd1 << right_shift)-1;
    remainder = $unsigned(high) & mask;
    threshold = (mask >> 1) + 32'(high < 0);
    shifted = high >>> right_shift;
    round_high = shifted + 32'(remainder > threshold);
  endfunction

  always_comb begin
    kernel_count = 64'(c.image.kernel_h)*64'(c.image.kernel_w);
    position_count = 64'(c.image.output_h)*64'(c.image.output_w);
    parameter_bytes = 64'(channels)*4;
    weight_bytes = kernel_count*64'(channels);
    input_bytes = spatial ? 64'(c.image.input_h)*64'(c.image.input_w)*64'(channels) :
                            64'(c.length)*(c.vector_s16 ? 2 : 1);
    output_bytes = spatial ? position_count*64'(channels) :
                     c.op==VEC_HADAMARD ? 64'(c.length)*4 : 64'd4;
    cfg_ok = c.op <= VEC_HADAMARD && range_ok(c.input_base,input_bytes) &&
             range_ok(c.output_base,output_bytes) &&
             separate_ranges(c.input_base,input_bytes,c.output_base,output_bytes);
    if (spatial) begin
      cfg_ok = cfg_ok && c.image.input_h!=0 && c.image.input_w!=0 && channels!=0 &&
        c.image.output_h!=0 && c.image.output_w!=0 && c.image.kernel_h!=0 && c.image.kernel_w!=0 &&
        kernel_count<=64'(MAX_TAPS) && c.image.stride_h!=0 && c.image.stride_w!=0 &&
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
      cfg_ok = cfg_ok && c.length!=0 && c.output_base[1:0]==0;
      if (c.vector_s16) cfg_ok = cfg_ok && c.input_base[0]==0;
      if (binary_vector) begin
        cfg_ok = cfg_ok && range_ok(c.rhs_base,input_bytes) &&
          separate_ranges(c.rhs_base,input_bytes,c.output_base,output_bytes);
        if (c.vector_s16) cfg_ok = cfg_ok && c.rhs_base[0]==0;
      end
    end
  end

  // All allocation intervals and the image geometry are immutable for a job.
  always_comb begin
    dma_cfg_valid = state==CONFIGURE && dma_cfg_ready;
    dma_conv_enable = spatial;
    dma_range_enable = 1'b1;
    dma_conv_cfg = c.image;
    dma_conv_cfg.input_base = c.input_base;
    dma_conv_cfg.group_c = c.image.input_c;
    dma_conv_cfg.group_offset = 0;
    dma_conv_cfg.input_s16 = 0;
    for (int i=0;i<4;i++) begin dma_range_base[i]=0; dma_range_end[i]=0; end
    if (depthwise) begin
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

  assign rd_req = state==LOAD_REQ || state==WINDOW_REQ;
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
    param_bad = state==LOAD_WAIT && rd_raw_valid &&
      ((load_kind==LD_SHIFT && ($signed(rd_raw_data)<-31 || $signed(rd_raw_data)>30)) ||
       (load_kind==LD_MULT && $signed(rd_raw_data)<0));
  end

  always_comb begin
    pe_op=PE_MADD;
    case (c.op)
      AVGPOOL_S8,VEC_SUM: pe_op=PE_SUM;
      MAXPOOL_S8,VEC_MAX: pe_op=PE_MAX;
      MINPOOL_S8,VEC_MIN: pe_op=PE_MIN;
      VEC_HADAMARD: pe_op=PE_MUL;
      default: ;
    endcase
    for (int l=0;l<PE_COUNT;l++) begin
      pe_a[l]=0; pe_b[l]=0; pe_acc[l]=0;
      if (compute_index+32'(l)<active) begin
        pe_a[l]=input_buf[compute_index+32'(l)];
        pe_b[l]=depthwise ? 16'($signed(weight_buf[tap*TILE+compute_index+32'(l)])) : rhs_buf[compute_index+32'(l)];
        pe_acc[l]=acc_buf[compute_index+32'(l)];
      end
    end
  end
  for (genvar l=0;l<PE_COUNT;l++) begin : g_pe
    dw_pool_pe u_pe(.op(pe_op),.a(pe_a[l]),.b(pe_b[l]),.acc(pe_acc[l]),.result(pe_result[l]));
  end

  always_comb begin
    reduce_next=reduce_acc+acc_buf[reduce_index];
    if (c.op==VEC_MAX) reduce_next=reduce_acc>acc_buf[reduce_index] ? reduce_acc : acc_buf[reduce_index];
    if (c.op==VEC_MIN) reduce_next=reduce_acc<acc_buf[reduce_index] ? reduce_acc : acc_buf[reduce_index];
  end
  assign div_start = state==AVG_START;
  assign div_numerator = (acc_buf[quant_index]<0 ? $unsigned(-acc_buf[quant_index]) :
                           $unsigned(acc_buf[quant_index])) + (valid_taps>>1);
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
        if (spatial) pack_data[b*8+:8]=8'(result_buf[write_index+32'(b)-32'(pack_addr[1:0])]);
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
      q_scaled<=0;q_rounded<=0;q_product<=0;q_right<=0;avg_negative<=0;
      write_origin<=0;write_total<=0;write_index<=0;write_count<=0;
      write_addr_q<=0;write_data_q<=0;write_mask_q<=0;
      stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;
    end else begin
      if (state!=IDLE && state!=DONE) stat_cycles<=stat_cycles+1;
      if (state==EXECUTE) stat_compute<=stat_compute+1;
      if (state==LOAD_WAIT || state==WINDOW_WAIT || state==WRITE_DATA || state==WRITE_WAIT ||
          ((state==LOAD_REQ || state==WINDOW_REQ) && !rd_granted) ||
          (state==WRITE_REQ && !wr_granted) || (state==CONFIGURE && !dma_cfg_ready))
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
      case (state)
        IDLE: if (start) begin
          c<=cfg; error<=0; state<=CHECK;
          stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;param_bad_seen<=0;
        end
        CHECK: if (!cfg_ok) begin error<=2'b01;state<=FAILED;end
          else begin taps<=32'(kernel_count);channel_base<=0;state<=CONFIGURE;end
        CONFIGURE: if (dma_cfg_ready) state<=spatial ? TILE_INIT : VECTOR_INIT;
        TILE_INIT: begin
          active<=channels-channel_base<TILE ? channels-channel_base : 32'(TILE);
          position<=0;ox<=0;oy<=0;load_tap<=0;load_kind<=LD_WEIGHT;
          for (int l=0;l<TILE;l++) bias_buf[l]<=0;
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
            LD_SHIFT: state<=OUTPUT_INIT;
            LD_A: if (binary_vector) begin load_kind<=LD_B;state<=LOAD_REQ;end
              else begin compute_index<=0;state<=EXECUTE;end
            LD_B: begin compute_index<=0;state<=EXECUTE;end
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
          tap<=0;kx<=0;ky<=0;valid_taps<=0;state<=TAP_CHECK;
        end
        TAP_CHECK: if (in_bounds) begin valid_taps<=valid_taps+1;state<=WINDOW_REQ;end
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
          else if (spatial) state<=TAP_NEXT;
          else if (c.op==VEC_HADAMARD) begin
            write_origin<=c.output_base+(vector_offset<<2);write_total<=active<<2;write_index<=0;state<=WRITE_PREP;
          end else state<=VECTOR_NEXT;
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
          q_scaled<=acc_buf[quant_index] <<< (shift_buf[quant_index]>0 ? 5'(shift_buf[quant_index]) : 5'd0);
          q_right<=shift_buf[quant_index]<0 ? 5'(-shift_buf[quant_index]) : 5'd0;
          state<=Q_MULT;
        end
        Q_MULT: begin q_product<=q_scaled*mult_buf[quant_index];state<=Q_ROUND;end
        Q_ROUND: begin q_rounded<=round_high(q_product,q_right);state<=Q_STORE;end
        Q_STORE: begin
          result_buf[quant_index]<=clamp_s8($signed(64'(q_with_offset)),c.activation_min,c.activation_max);
          if (quant_index+1<active) begin quant_index<=quant_index+1;state<=QUANT_INIT;end
          else begin
            write_origin<=c.output_base+position*channels+channel_base;
            write_total<=active;write_index<=0;state<=WRITE_PREP;
          end
        end
        AVG_START: begin avg_negative<=acc_buf[quant_index]<0;state<=AVG_WAIT;end
        AVG_WAIT: if (div_done) begin
          result_buf[quant_index]<=clamp_s8(avg_negative ? -$signed(64'(div_quotient)) : $signed(64'(div_quotient)),
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
          else if (c.op==VEC_HADAMARD) state<=VECTOR_NEXT;
          else state<=DONE;
        end
        OUTPUT_NEXT: begin
          if (position+1<32'(position_count)) begin
            position<=position+1;
            if (ox+1==32'(c.image.output_w)) begin ox<=0;oy<=oy+1;end else ox<=ox+1;
            state<=OUTPUT_INIT;
          end else if (channel_base+active<channels) begin channel_base<=channel_base+active;state<=TILE_INIT;end
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
        end else if (c.op==VEC_HADAMARD) state<=DONE;
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
  end
  always_ff @(posedge clk) if (rst_n) begin
    if (src_wvalid && !src_wready) begin
      assert(wr_busy);
    end
    if (state==EXECUTE) assert(active>0 && active<=TILE && compute_index<active);
    if (state==WINDOW_REQ) assert(in_bounds && tap<taps);
    if (state==WRITE_REQ) assert(write_count>0 && write_count<=4 && write_mask_q!=0);
  end
`endif
endmodule
