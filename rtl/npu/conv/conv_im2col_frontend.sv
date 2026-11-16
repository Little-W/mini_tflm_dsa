// SPDX-License-Identifier: Apache-2.0
// Implicit im2col frontend. Does not change the PE array or allocate an expanded
// activation matrix in external memory. Feed tile descriptors from IA scheduling.
// Emits corrected signed-16 values to the existing IA tile RAM write interface.
module conv_im2col_frontend #(
  parameter int SIZE=16,
  parameter int SLOT_W=3,
  parameter int LANES=2,       // Corrected values written into independent IA banks
  parameter int CACHE_SETS=128,
  parameter int CACHE_WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int CACHE_POLICY=3,
  parameter int CW=$clog2(SIZE),
  parameter int RW=$clog2(SIZE+1)
) (
  input logic clk, rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input conv_im2col_pkg::conv_cfg_t cfg,
  // Native IA scheduler context. Zero groups disables the geometry policy for
  // standalone clients that do not promise the native descriptor order.
  input logic [31:0] cfg_sched_r = 32'd0,
  input logic [31:0] cfg_sched_groups = 32'd0,
  input logic tile_valid,
  output logic tile_ready,
  input logic [31:0] tile_p0, tile_q0,
  input logic [RW-1:0] tile_rows,
  input logic [RW-1:0] tile_cols = '0, // Zero selects the full SIZE columns.
  input logic [SLOT_W-1:0] tile_slot,
  input logic [31:0] tile_group = 32'd0,
  output logic wr_valid,
  input logic wr_ready,
  output logic [SLOT_W-1:0] wr_slot,
  output logic [CW-1:0] wr_row, wr_col,
  output logic signed [15:0] wr_data [LANES],
  output logic [LANES-1:0] wr_mask,
  output logic tile_done, tile_error, error, busy,
  output logic wr_last,
  output logic [31:0] stat_hits, stat_misses, stat_read_bytes,
  output logic [31:0] stat_prefetch_lines, stat_prefetch_used, stat_prefetch_wasted,
  output logic [31:0] stat_prefetch_unused, stat_prefetch_bytes, stat_prefetch_late,
  output logic arvalid,
  input logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input logic rvalid,
  output logic rready,
  input logic [31:0] rdata,
  input logic [1:0] rresp,
  input logic rlast
);
  import conv_im2col_pkg::*;
  typedef enum logic [4:0] {IDLE, P_DECODE, P_START, P_WAIT, Q_DECODE, Q_START, Q_WAIT,
    K_DECODE, K_START, K_WAIT, COORD, ADDRESS, ADDRESS_CHANNEL, FETCH, WAIT_WORD, STREAM, ZERO_STREAM} st_t;
  st_t state;
  conv_cfg_t c;
  logic configured, cfg_ok;
  logic [63:0] cfg_input_bytes, cfg_red;
  logic [31:0] cfg_positions;
  logic [31:0] reduction_len, position_count, tensor_bytes;
  logic [31:0] p0, q0, tap0, row_idx, col_idx, rows_q, cols_q;
  logic [31:0] ox, oy, ky, kx, ch, ky0, kx0, ch0;
  logic [32:0] q_current;
  logic signed [63:0] ix, iy;
  logic [63:0] pixel_index;
  logic pad_q;
  logic [31:0] addr;
  logic [31:0] word_buf, word_addr;
  logic word_valid;
  logic [31:0] chunk_count;
  logic [31:0] word_available;
  logic [SLOT_W-1:0] slot_q;
  logic div_start, div_busy, div_done, div_zero;
  logic [31:0] div_num, div_den, div_quot, div_rem;
  logic cache_cfg_ready, cache_req_ready, cache_rsp_valid, cache_rsp_error;
  logic cache_req_valid, cache_rsp_ready, stream_next_request;
  logic incoming_request, incoming_word_hit, finishing_tile;
  logic [31:0] cache_req_addr;
  logic [31:0] cache_rsp_data;
  logic [31:0] selected_word;
  logic pred_cfg_eligible, pred_enabled, pred_busy, pred_done, pred_start;
  logic [31:0] pred_rank, group_q, groups_q;
  logic geometry_tile, line_hint_valid, cache_hint_pending;
  logic [31:0] line_hint_rank;

  logic [3:0] p_cache_valid;
  logic [31:0] p_cache_key[4], p_cache_y[4], p_cache_x[4];
  logic last_p_valid;
  logic [31:0] last_p, last_y, last_x;
  logic p_fast_valid;
  logic [31:0] p_fast_y, p_fast_x, p_delta, p_sum, p_decode;
  logic incoming_fast, incoming_q_fast, incoming_k_fast, incoming_padding;
  logic [31:0] incoming_tap,incoming_ch,incoming_ky,incoming_kx,incoming_addr;
  logic signed [63:0] incoming_ix,incoming_iy;
  logic [63:0] incoming_pixel;
  logic [1:0] p_cache_select;
  logic [31:0] req_index, req_epoch, req_retire;
  logic req_index_valid;
  logic pf_valid, pf_ready;
  logic [31:0] pf_addr, pf_index, pf_epoch, pf_retire;
  logic pf_index_valid;
  logic [31:0] pf_x, pf_y, pf_step, pf_pixel, pf_channel, pf_distance;
  logic [31:0] pixel_bytes, line_pixels;
  logic pf_coordinate_valid;
  logic fragment_image_fits, pf_next_fragment;
  logic signed [63:0] request_x, request_y;
  logic [63:0] request_pixel;
  logic [31:0] request_channel, request_origin_channel, request_output_y;
  logic [31:0] request_kernel_x, request_rows, request_cols;
  logic signed [63:0] pf_wrap_x;
  logic pf_window_ahead;
  logic [31:0] pf_output_ahead,pf_output_x,pf_output_y;
  logic signed [63:0] pf_window_x,pf_window_y;
  logic [31:0] next_byte_addr;
  logic [1:0] address_step_phase;
  logic signed [63:0] row_wrap_dx, tap_wrap_dx;
  logic signed [63:0] row_y_pixels, tap_y_pixels, row_wrap_pixels, tap_wrap_pixels;
  logic [31:0] row_step_bytes, tap_step_bytes, row_wrap_bytes, tap_wrap_bytes, group_bytes;
  logic row_base_valid, coordinate_address_valid;
  logic signed [63:0] row_base_ix, row_base_iy;
  logic [63:0] row_base_pixel;
  logic [31:0] row_base_addr;
  logic row_wrap, tap_wrap, next_row_padding, next_tap_padding;
  logic signed [63:0] next_row_ix, next_row_iy, next_tap_ix, next_tap_iy;
  logic [63:0] next_row_pixel, next_tap_pixel;
  logic [31:0] next_row_addr, next_tap_addr;

  // Configuration-time products leave only additions and bounds checks at
  // row and tap boundaries while the current word is being transferred.
  always_comb begin
    row_wrap=ox+1==32'(c.output_w);
    next_row_ix=row_base_ix+(row_wrap ? row_wrap_dx : $signed(64'(c.stride_w)));
    next_row_iy=row_base_iy+(row_wrap ? $signed(64'(c.stride_h)) : 64'sd0);
    next_row_pixel=row_base_pixel+$unsigned(row_wrap ? row_wrap_pixels : $signed(64'(c.stride_w)));
    next_row_addr=row_base_addr+(row_wrap ? row_wrap_bytes : row_step_bytes);
    next_row_padding=next_row_ix<0 || next_row_iy<0 ||
      next_row_ix>=$signed(64'(c.input_w)) || next_row_iy>=$signed(64'(c.input_h));
    tap_wrap=kx+1==32'(c.kernel_w);
    next_tap_ix=ix+(tap_wrap ? tap_wrap_dx : $signed(64'(c.dilation_w)));
    next_tap_iy=iy+(tap_wrap ? $signed(64'(c.dilation_h)) : 64'sd0);
    next_tap_pixel=pixel_index+$unsigned(tap_wrap ? tap_wrap_pixels : $signed(64'(c.dilation_w)));
    next_tap_addr=next_byte_addr-group_bytes+(tap_wrap ? tap_wrap_bytes : tap_step_bytes);
    next_tap_padding=next_tap_ix<0 || next_tap_iy<0 ||
      next_tap_ix>=$signed(64'(c.input_w)) || next_tap_iy>=$signed(64'(c.input_h));
  end

  function automatic logic is_power_two(input logic [31:0] value);
    return value!=0 && (value & (value-1))==0;
  endfunction
  function automatic logic [4:0] power_shift(input logic [31:0] value);
    logic [4:0] result;
    result=0;
    for (int b=0;b<32;b++) if (value[b]) result=5'(b);
    return result;
  endfunction
  always_comb begin
    p_decode=tile_ready ? tile_p0 : p0;
    p_cache_select=2'(p_decode>>CW);
    p_delta=p_decode-last_p;
    p_sum=last_x+p_delta;
    p_fast_valid=0;p_fast_y=0;p_fast_x=0;
    if (p_decode==0) p_fast_valid=1;
    else if (p_cache_valid[p_cache_select] && p_cache_key[p_cache_select]==p_decode) begin
      p_fast_valid=1;p_fast_y=p_cache_y[p_cache_select];p_fast_x=p_cache_x[p_cache_select];
    end else if (last_p_valid && p_decode>=last_p && p_delta<=32'(c.output_w)) begin
      p_fast_valid=1;p_fast_y=last_y;p_fast_x=p_sum;
      if (p_sum>=32'(c.output_w)) begin p_fast_x=p_sum-32'(c.output_w);p_fast_y=last_y+1;end
    end
  end

  always_comb begin
    incoming_q_fast=1;incoming_tap=0;incoming_ch=0;
    if (tile_q0==0) begin incoming_tap=0;incoming_ch=0;end
    else if (is_power_two(32'(c.group_c))) begin
      incoming_tap=tile_q0>>power_shift(32'(c.group_c));incoming_ch=tile_q0&(32'(c.group_c)-1);
    end else if(c.group_c==3) begin incoming_tap=tile_q0/32'd3;incoming_ch=tile_q0%32'd3;end
    else incoming_q_fast=0;
    incoming_k_fast=1;incoming_ky=0;incoming_kx=0;
    if(is_power_two(32'(c.kernel_w))) begin
      incoming_ky=incoming_tap>>power_shift(32'(c.kernel_w));incoming_kx=incoming_tap&(32'(c.kernel_w)-1);
    end else if(c.kernel_w==3) begin incoming_ky=incoming_tap/32'd3;incoming_kx=incoming_tap%32'd3;end
    else incoming_k_fast=0;
    incoming_fast=CACHE_POLICY==3 && c.windowed && p_fast_valid && incoming_q_fast && incoming_k_fast;
    incoming_ix=$signed(64'(p_fast_x)*64'(c.stride_w))-$signed(64'(c.pad_left))+
                $signed(64'(incoming_kx)*64'(c.dilation_w));
    incoming_iy=$signed(64'(p_fast_y)*64'(c.stride_h))-$signed(64'(c.pad_top))+
                $signed(64'(incoming_ky)*64'(c.dilation_h));
    incoming_padding=incoming_ix<0 || incoming_iy<0 || incoming_ix>=$signed(64'(c.input_w)) ||
                     incoming_iy>=$signed(64'(c.input_h));
    incoming_pixel=64'(incoming_iy)*64'(c.input_w)+64'(incoming_ix);
    incoming_addr=c.input_base+32'((incoming_pixel*64'(c.input_c)+64'(c.group_offset)+
                                   64'(incoming_ch))<<c.input_s16);
  end

  always_comb begin
    cfg_input_bytes = 64'(cfg.input_h) * 64'(cfg.input_w) * 64'(cfg.input_c)
                      * (cfg.input_s16 ? 64'd2 : 64'd1);
    cfg_red = 64'(cfg.kernel_h) * 64'(cfg.kernel_w) * 64'(cfg.group_c);
    cfg_positions = 32'(cfg.output_h) * 32'(cfg.output_w);
    cfg_ok = cfg.input_h!=0 && cfg.input_w!=0 && cfg.input_c!=0 &&
             cfg.group_c!=0 && cfg.kernel_h!=0 && cfg.kernel_w!=0 &&
             cfg.output_h!=0 && cfg.output_w!=0 &&
             cfg.stride_h!=0 && cfg.stride_w!=0 &&
             cfg.dilation_h!=0 && cfg.dilation_w!=0 &&
             (32'(cfg.group_offset)+32'(cfg.group_c) <= 32'(cfg.input_c)) &&
             cfg_red <= 64'hffff_ffff &&
             cfg_input_bytes <= 64'hffff_ffff &&
             (64'(cfg.input_base)+cfg_input_bytes < 64'h1_0000_0000);
    if (cfg.input_s16)
      cfg_ok = cfg_ok && cfg.input_offset==0 && cfg.input_base[0]==0;
    else
      cfg_ok = cfg_ok && $signed(cfg.input_offset)>=-127 && $signed(cfg.input_offset)<=128;
  end
  assign cfg_ready = state==IDLE && cache_cfg_ready && !pred_busy && !cache_hint_pending && address_step_phase==0;
  assign finishing_tile=wr_valid && wr_ready && wr_last;
  assign tile_ready = (state==IDLE || finishing_tile) && configured && !error && !cfg_valid &&
                      !pred_busy && !cache_hint_pending && address_step_phase==0;
  assign busy = state!=IDLE || pred_busy || cache_hint_pending || !cache_cfg_ready || address_step_phase!=0;
  assign wr_valid = state==STREAM || state==ZERO_STREAM ||
                    (state==WAIT_WORD && cache_rsp_valid && !cache_rsp_error);
  assign wr_slot = slot_q;
  assign wr_row = CW'(row_idx);
  assign wr_col = CW'(col_idx);
  assign wr_last=row_idx+1==rows_q && col_idx+chunk_count==cols_q;

  assign div_start = state==P_START || state==Q_START || state==K_START;
  always_comb begin
    div_num = 0; div_den = 1;
    case (state)
      P_START: begin div_num=p0; div_den=32'(c.output_w); end
      Q_START: begin div_num=q0; div_den=32'(c.group_c); end
      K_START: begin div_num=tap0; div_den=32'(c.kernel_w); end
      default: ;
    endcase
  end
  conv_udiv32 u_div (.clk,.rst_n,.start(div_start),.dividend(div_num),.divisor(div_den),
    .busy(div_busy),.done(div_done),.div_zero,.quotient(div_quot),.remainder(div_rem));

  assign pred_start = state==ADDRESS && geometry_tile && col_idx==0 &&
    q_current<{1'b0,reduction_len} && ix>=0 && iy>=0 &&
    ix<$signed(64'(c.input_w)) && iy<$signed(64'(c.input_h)) &&
    !pred_busy && !cache_hint_pending;
  generate if (SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0) begin : g_next_use
    conv_next_use_predictor u_predictor (
      .clk,.rst_n,.cfg_valid(cfg_valid && cfg_ready && cfg_ok),.cfg,
      .cfg_r(cfg_sched_r),.cfg_groups(cfg_sched_groups),
      .cfg_eligible(pred_cfg_eligible),.enabled(pred_enabled),.start(pred_start),
      .input_y(32'(iy)),.input_x(32'(ix)),.channel(ch),
      .current_p(p0+row_idx),.current_q(32'(q_current)),.current_group(group_q),
      .busy(pred_busy),.done(pred_done),.next_rank(pred_rank)
    );
  end else begin : g_no_next_use
    assign pred_cfg_eligible=0;assign pred_enabled=0;assign pred_busy=0;
    assign pred_done=0;assign pred_rank=32'hffff_ffff;
  end endgenerate

  assign stream_next_request=wr_valid && wr_ready && state!=ZERO_STREAM &&
    col_idx+chunk_count<cols_q && q_current+33'(chunk_count)<{1'b0,reduction_len} &&
    ch+chunk_count<32'(c.group_c) && next_byte_addr[31:2]!=addr[31:2];
  assign incoming_word_hit=(finishing_tile && state==WAIT_WORD) ?
    addr[31:2]==incoming_addr[31:2] :
    word_valid && word_addr=={incoming_addr[31:2],2'b0};
  assign incoming_request=tile_valid && tile_ready && incoming_fast && !incoming_padding &&
    !incoming_word_hit && tile_rows!=0 && 32'(tile_rows)<=SIZE && 32'(tile_cols)<=SIZE &&
    tile_q0<reduction_len && {1'b0,tile_p0}+33'(tile_rows)<={1'b0,position_count};
  assign cache_req_valid = incoming_request ||
                           (state==FETCH && !(word_valid && word_addr=={addr[31:2],2'b0})) ||
                           stream_next_request;
  assign cache_req_addr=incoming_request ? incoming_addr : stream_next_request ? next_byte_addr : addr;
  assign cache_rsp_ready = state==WAIT_WORD && (wr_ready || cache_rsp_error);
  conv_read_cache #(.SETS(CACHE_SETS),.WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES),
    .CACHE_POLICY(CACHE_POLICY)) u_cache (
    .clk,.rst_n,
    .cfg_valid(cfg_valid && cfg_ready && cfg_ok),.cfg_ready(cache_cfg_ready),
    .cfg_base(cfg.input_base),.cfg_bytes(32'(cfg_input_bytes)),.cfg_bypass(cfg.bypass_cache),
    .cfg_geometry(pred_cfg_eligible),
    .cfg_windowed(cfg.windowed),.cfg_prefetch_enable(cfg.prefetch_enable),
    .req_valid(cache_req_valid),.req_ready(cache_req_ready),.req_addr(cache_req_addr),
    .req_geometry(geometry_tile),.req_event_first(geometry_tile && cache_req_addr[3:0]==0),
    .hint_valid(line_hint_valid),.hint_next(line_hint_rank),.hint_pending(cache_hint_pending),
    .req_window_index_valid(req_index_valid),.req_window_index(req_index),
    .req_window_epoch(req_epoch),.req_window_retire(req_retire),.req_window_progress(request_output_y),
    .prefetch_valid(pf_valid),.prefetch_ready(pf_ready),.prefetch_addr(pf_addr),
    .prefetch_window_index_valid(pf_index_valid),.prefetch_window_index(pf_index),
    .prefetch_window_epoch(pf_epoch),.prefetch_window_retire(pf_retire),
    .prefetch_next_fragment(pf_next_fragment),
    .rsp_valid(cache_rsp_valid),.rsp_ready(cache_rsp_ready),
    .rsp_data(cache_rsp_data),.rsp_error(cache_rsp_error),
    .stat_hits,.stat_misses,.stat_read_bytes,
    .stat_prefetch_lines,.stat_prefetch_used,.stat_prefetch_wasted,
    .stat_prefetch_unused,.stat_prefetch_bytes,.stat_prefetch_late,
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
  );
  always_comb begin
    chunk_count = LANES;
    if (chunk_count > cols_q-col_idx) chunk_count = cols_q-col_idx;
    if (q_current < {1'b0,reduction_len}) begin
      if (chunk_count > 32'(c.group_c)-ch) chunk_count = 32'(c.group_c)-ch;
      if (33'(chunk_count) > ({1'b0,reduction_len}-q_current))
        chunk_count = 32'({1'b0,reduction_len}-q_current);
    end
    word_available = (32'd4-{30'd0,addr[1:0]}) >> c.input_s16;
    if ((state==STREAM || state==WAIT_WORD) && chunk_count > word_available) chunk_count = word_available;
    selected_word = (state==WAIT_WORD ? cache_rsp_data : word_buf) >> (addr[1:0]*8);
    next_byte_addr=addr+(chunk_count<<c.input_s16);
    for (int l=0;l<LANES;l++) begin
      wr_mask[l]=32'(l)<chunk_count;
      wr_data[l]=0;
      if ((state==STREAM || state==WAIT_WORD) && 32'(l)<chunk_count) begin
        if (c.input_s16) wr_data[l]=$signed(16'(selected_word>>(l*16)));
        else wr_data[l]=$signed(16'($signed(8'(selected_word>>(l*8)))))+c.input_offset;
      end
    end
  end

  // Spatial indexing retains a channel fragment across the moving window.
  // The physical line tag preserves correctness for every tensor alignment.
  always_comb begin
    request_x=incoming_request ? incoming_ix : ix;
    request_y=incoming_request ? incoming_iy : iy;
    request_pixel=incoming_request ? incoming_pixel : pixel_index;
    request_channel=incoming_request ? incoming_ch : ch;
    request_origin_channel=incoming_request ? incoming_ch : ch0;
    request_output_y=incoming_request ? p_fast_y : oy;
    request_kernel_x=incoming_request ? incoming_kx : kx;
    request_rows=incoming_request ? 32'(tile_rows) : rows_q;
    request_cols=incoming_request ? (tile_cols==0 ? 32'(SIZE) : 32'(tile_cols)) : cols_q;
    pixel_bytes=32'(c.input_c)<<c.input_s16;
    line_pixels=1;
    for (int n=1;n<=LINE_BYTES;n++)
      if (32'(n)*pixel_bytes<32'(LINE_BYTES)) line_pixels=32'(n)+1;
    req_index_valid=c.windowed && c.input_base[$clog2(LINE_BYTES)-1:0]==0 &&
      ((pixel_bytes>=LINE_BYTES && (pixel_bytes&(LINE_BYTES-1))==0) ||
       (is_power_two(pixel_bytes) && pixel_bytes<LINE_BYTES));
    req_index=32'(request_pixel);
    req_epoch=(32'(c.group_offset)+request_channel)<<c.input_s16;
    req_epoch=req_epoch>>$clog2(LINE_BYTES);
    if (pixel_bytes<LINE_BYTES) begin
      req_index=32'(request_pixel)>>(power_shift(LINE_BYTES)-power_shift(pixel_bytes));
      req_epoch=0;
    end
    req_retire=32'hffff_ffff;
    if (is_power_two(32'(c.stride_h))) begin
      req_retire=(32'(request_y)+32'(c.pad_top))>>power_shift(32'(c.stride_h));
      if (req_retire>=32'(c.output_h)) req_retire=32'(c.output_h)-1;
      // A line shared by adjacent rows remains live through both rows.
      if (pixel_bytes<LINE_BYTES && req_retire+1<32'(c.output_h)) req_retire=req_retire+1;
    end
    pf_step=c.kernel_w==1 ? 32'(c.stride_w) : 32'(c.dilation_w);
    if (pf_step<line_pixels) pf_step=line_pixels;
    pf_distance=1;
    if (c.windowed) pf_distance=1+(((request_channel-request_origin_channel+
                              (stream_next_request ? chunk_count : 0))<<c.input_s16)>>2);
    pf_step=pf_step*pf_distance;
    pf_x=32'(request_x)+pf_step;pf_y=32'(request_y);
    if (pf_x>=32'(c.input_w)) begin
      pf_x=0;
      pf_y=32'(request_y)+(c.kernel_h==1 ? 32'(c.stride_h) : 32'(c.dilation_h));
    end
    // A single-position channel fragment follows the kernel rows. Keep its
    // lookahead inside the next kernel row before advancing along the image.
    pf_wrap_x=request_x+$signed(64'(pf_distance))+tap_wrap_dx-64'sd1;
    if (c.windowed && request_rows==1 && request_cols<=32'(c.group_c) &&
        c.kernel_w>1 && c.kernel_h>1 && c.dilation_w==1 && c.dilation_h==1 &&
        request_kernel_x+pf_distance>=32'(c.kernel_w) &&
        request_kernel_x+pf_distance<2*32'(c.kernel_w)) begin
      pf_x=pf_wrap_x<0 ? 0 : 32'(pf_wrap_x);
      pf_y=32'(request_y)+1;
    end
    // Strided windows prefetch the same kernel coordinate in the following
    // two output positions. Word offsets distribute requests across both
    // positions, including the next output row.
    pf_window_ahead=c.windowed && request_rows==1 && request_cols<=32'(c.group_c) &&
      (c.stride_h>1 || c.stride_w>1);
    pf_output_ahead=1+((pf_distance-1)&1);
    pf_output_x=(incoming_request ? p_fast_x : ox)+pf_output_ahead;
    pf_output_y=request_output_y;
    pf_window_x=request_x+$signed(64'(c.stride_w)<<pf_output_ahead[1]);
    pf_window_y=request_y;
    for(int step=0;step<2;step++) begin
      if(pf_output_x>=32'(c.output_w)) begin
        pf_output_x=pf_output_x-32'(c.output_w);
        pf_output_y=pf_output_y+1;
        pf_window_x=pf_window_x+row_wrap_dx-$signed(64'(c.stride_w));
        pf_window_y=pf_window_y+$signed(64'(c.stride_h));
      end
    end
    if(pf_window_ahead) begin pf_x=32'(pf_window_x);pf_y=32'(pf_window_y);end
    pf_coordinate_valid=request_x>=0 && request_y>=0 && request_x<$signed(64'(c.input_w)) &&
      request_y<$signed(64'(c.input_h)) && pf_x<32'(c.input_w) && pf_y<32'(c.input_h) &&
      (!pf_window_ahead || pf_output_y<32'(c.output_h));
    pf_pixel=pf_y*32'(c.input_w)+pf_x;
    pf_channel=32'(c.group_offset)+request_channel;
    pf_addr=c.input_base+((pf_pixel*32'(c.input_c)+pf_channel)<<c.input_s16);
    pf_index_valid=req_index_valid;pf_index=pf_pixel;pf_epoch=req_epoch;
    if (pixel_bytes<LINE_BYTES)
      pf_index=pf_pixel>>(power_shift(LINE_BYTES)-power_shift(pixel_bytes));
    pf_retire=32'hffff_ffff;
    if (is_power_two(32'(c.stride_h))) begin
      pf_retire=(pf_y+32'(c.pad_top))>>power_shift(32'(c.stride_h));
      if (pf_retire>=32'(c.output_h)) pf_retire=32'(c.output_h)-1;
      if (pixel_bytes<LINE_BYTES && pf_retire+1<32'(c.output_h)) pf_retire=pf_retire+1;
    end
    // Two ways retain the active and following channel fragments when each
    // spatial pixel has a distinct set. Both fragments use physical tags.
    pf_next_fragment=fragment_image_fits && req_index_valid && request_rows==1 &&
      request_cols==LINE_BYTES && !c.input_s16 &&
      ((32'(c.group_offset)+request_origin_channel)&(LINE_BYTES-1))==0 &&
      request_origin_channel+2*LINE_BYTES<=32'(c.group_c) &&
      (!pf_window_ahead || pf_distance==LINE_BYTES/4);
    if (!pf_coordinate_valid && pf_next_fragment) begin
      pf_addr=cache_req_addr;pf_index=req_index;pf_epoch=req_epoch;pf_retire=req_retire;
    end
    pf_valid=cache_req_valid && cache_req_ready && c.prefetch_enable &&
      (pf_next_fragment || (pf_coordinate_valid &&
       (pf_addr>>$clog2(LINE_BYTES))!=(cache_req_addr>>$clog2(LINE_BYTES))));
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE; c<='0; configured<=0; error<=0; tile_done<=0; tile_error<=0;
      fragment_image_fits<=0;
      reduction_len<=0; position_count<=0; tensor_bytes<=0;
      p0<=0; q0<=0; tap0<=0; row_idx<=0; col_idx<=0; rows_q<=0; cols_q<=SIZE;
      ox<=0; oy<=0; ky<=0; kx<=0; ch<=0; ky0<=0; kx0<=0; ch0<=0;
      q_current<=0; ix<=0; iy<=0; pixel_index<=0; pad_q<=0; addr<=0;
      word_buf<=0; word_addr<=0; word_valid<=0; slot_q<=0;
      group_q<=0;groups_q<=0;geometry_tile<=0;line_hint_valid<=0;line_hint_rank<=32'hffff_ffff;
      p_cache_valid<=0;last_p_valid<=0;last_p<=0;last_y<=0;last_x<=0;
      address_step_phase<=0;row_wrap_dx<=0;tap_wrap_dx<=0;
      row_y_pixels<=0;tap_y_pixels<=0;row_wrap_pixels<=0;tap_wrap_pixels<=0;
      row_step_bytes<=0;tap_step_bytes<=0;row_wrap_bytes<=0;tap_wrap_bytes<=0;group_bytes<=0;
      row_base_valid<=0;coordinate_address_valid<=0;
      row_base_ix<=0;row_base_iy<=0;row_base_pixel<=0;row_base_addr<=0;
      for (int t=0;t<4;t++) begin p_cache_key[t]<=0;p_cache_y[t]<=0;p_cache_x[t]<=0;end
    end else begin
      tile_done<=finishing_tile; tile_error<=0;
      if (state==WAIT_WORD && wr_valid && wr_ready) begin
        word_buf<=cache_rsp_data;word_addr<={addr[31:2],2'b0};word_valid<=1;
      end
      if (address_step_phase==2) begin
        row_wrap_pixels<=row_y_pixels+row_wrap_dx;
        tap_wrap_pixels<=tap_y_pixels+tap_wrap_dx;
        address_step_phase<=1;
      end else if (address_step_phase==1) begin
        row_wrap_bytes<=32'(($unsigned(row_wrap_pixels)*64'(c.input_c))<<c.input_s16);
        tap_wrap_bytes<=32'(($unsigned(tap_wrap_pixels)*64'(c.input_c))<<c.input_s16);
        address_step_phase<=0;
      end
      if (pred_done) begin line_hint_valid<=1;line_hint_rank<=pred_rank;end
      if (pred_start) line_hint_valid<=0;
      if (cfg_valid && cfg_ready) begin
        c<=cfg; configured<=cfg_ok; error<=!cfg_ok;
        word_valid<=0; reduction_len<=32'(cfg_red);
        fragment_image_fits<=CACHE_WAYS>=2 &&
          cfg_input_bytes<=((64'(cfg.input_c)<<cfg.input_s16)<<$clog2(CACHE_SETS));
        position_count<=32'(cfg_positions); tensor_bytes<=32'(cfg_input_bytes);
        groups_q<=cfg_sched_groups;geometry_tile<=0;line_hint_valid<=0;
        p_cache_valid<=0;last_p_valid<=0;
        address_step_phase<=2;row_base_valid<=0;coordinate_address_valid<=0;
        row_wrap_dx<=-$signed((64'(cfg.output_w)-1)*64'(cfg.stride_w));
        tap_wrap_dx<=-$signed((64'(cfg.kernel_w)-1)*64'(cfg.dilation_w));
        row_y_pixels<=$signed(64'(cfg.stride_h)*64'(cfg.input_w));
        tap_y_pixels<=$signed(64'(cfg.dilation_h)*64'(cfg.input_w));
        row_step_bytes<=32'((64'(cfg.stride_w)*64'(cfg.input_c))<<cfg.input_s16);
        tap_step_bytes<=32'((64'(cfg.dilation_w)*64'(cfg.input_c))<<cfg.input_s16);
        group_bytes<=32'(cfg.group_c)<<cfg.input_s16;
      end else if (tile_valid && tile_ready) begin
          if (tile_rows==0 || 32'(tile_rows)>SIZE || 32'(tile_cols)>SIZE || tile_q0>=reduction_len ||
              ({1'b0,tile_p0}+33'(tile_rows) > {1'b0,position_count})) begin
            tile_error<=1; error<=1; state<=IDLE;
          end else begin
            p0<=tile_p0; q0<=tile_q0; q_current<={1'b0,tile_q0};
            rows_q<=32'(tile_rows); cols_q <= (tile_cols==0) ? 32'(SIZE) : 32'(tile_cols);
            row_idx<=0; col_idx<=0; slot_q<=tile_slot;
            group_q<=tile_group;
            row_base_valid<=0;coordinate_address_valid<=0;
            // Windowed requests carry spatial retirement metadata directly.
            geometry_tile<=pred_enabled && (CACHE_POLICY!=3 || !c.windowed) &&
                           (tile_cols==0 || 32'(tile_cols)==SIZE) && tile_p0[3:0]==0 && tile_q0[3:0]==0 &&
                           tile_group<groups_q;
            if(incoming_fast) begin
              ox<=p_fast_x;oy<=p_fast_y;tap0<=incoming_tap;
              ch<=incoming_ch;ch0<=incoming_ch;
              ky<=incoming_ky;ky0<=incoming_ky;kx<=incoming_kx;kx0<=incoming_kx;
              ix<=incoming_ix;iy<=incoming_iy;pixel_index<=incoming_pixel;
              addr<=incoming_addr;pad_q<=incoming_padding;
              row_base_valid<=1;coordinate_address_valid<=1;
              row_base_ix<=incoming_ix;row_base_iy<=incoming_iy;
              row_base_pixel<=incoming_pixel;row_base_addr<=incoming_addr;
              last_p_valid<=1;last_p<=tile_p0;last_y<=p_fast_y;last_x<=p_fast_x;
              p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=tile_p0;
              p_cache_y[p_cache_select]<=p_fast_y;p_cache_x[p_cache_select]<=p_fast_x;
              if (incoming_padding) state<=ZERO_STREAM;
              else if (incoming_word_hit) state<=STREAM;
              else state<=cache_req_ready ? WAIT_WORD : FETCH;
            end else state<=P_DECODE;
          end
      end else case (state)
        IDLE: ;
        P_DECODE: if (p_fast_valid) begin
          oy<=p_fast_y;ox<=p_fast_x;state<=Q_DECODE;
          last_p_valid<=1;last_p<=p0;last_y<=p_fast_y;last_x<=p_fast_x;
          p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=p0;
          p_cache_y[p_cache_select]<=p_fast_y;p_cache_x[p_cache_select]<=p_fast_x;
        end else state<=P_START;
        P_START: state<=P_WAIT;
        P_WAIT: if (div_done) begin
          oy<=div_quot;ox<=div_rem;state<=Q_DECODE;
          last_p_valid<=1;last_p<=p0;last_y<=div_quot;last_x<=div_rem;
          p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=p0;
          p_cache_y[p_cache_select]<=div_quot;p_cache_x[p_cache_select]<=div_rem;
        end
        Q_DECODE: begin
          if (q0==0) begin tap0<=0;ch<=0;ch0<=0;state<=K_DECODE;end
          else if (is_power_two(32'(c.group_c))) begin
            tap0<=q0>>power_shift(32'(c.group_c));
            ch<=q0&(32'(c.group_c)-1);ch0<=q0&(32'(c.group_c)-1);state<=K_DECODE;
          end else if (c.group_c==3) begin
            tap0<=q0/32'd3;ch<=q0%32'd3;ch0<=q0%32'd3;state<=K_DECODE;
          end else state<=Q_START;
        end
        Q_START: state<=Q_WAIT;
        Q_WAIT: if (div_done) begin tap0<=div_quot; ch<=div_rem; ch0<=div_rem; state<=K_DECODE; end
        K_DECODE: begin
          if (is_power_two(32'(c.kernel_w))) begin
            ky<=tap0>>power_shift(32'(c.kernel_w));ky0<=tap0>>power_shift(32'(c.kernel_w));
            kx<=tap0&(32'(c.kernel_w)-1);kx0<=tap0&(32'(c.kernel_w)-1);state<=COORD;
          end else if (c.kernel_w==3) begin
            ky<=tap0/32'd3;ky0<=tap0/32'd3;kx<=tap0%32'd3;kx0<=tap0%32'd3;state<=COORD;
          end else state<=K_START;
        end
        K_START: state<=K_WAIT;
        K_WAIT: if (div_done) begin
          ky<=div_quot; ky0<=div_quot; kx<=div_rem; kx0<=div_rem; state<=COORD;
        end
        COORD: begin
          coordinate_address_valid<=0;
          ix <= $signed(64'(ox)*64'(c.stride_w)) - $signed(64'(c.pad_left))
                + $signed(64'(kx)*64'(c.dilation_w));
          iy <= $signed(64'(oy)*64'(c.stride_h)) - $signed(64'(c.pad_top))
                + $signed(64'(ky)*64'(c.dilation_h));
          state<=ADDRESS;
        end
        ADDRESS: begin
          if (q_current >= {1'b0,reduction_len} || ix<0 || iy<0 ||
              ix >= $signed(64'(c.input_w)) || iy >= $signed(64'(c.input_h))) begin
            pad_q<=1; state<=ZERO_STREAM;
          end else if (!geometry_tile || col_idx!=0 || (!pred_busy && !cache_hint_pending)) begin
            pixel_index <= 64'(iy)*64'(c.input_w)+64'(ix);
            pad_q<=0; state<=ADDRESS_CHANNEL;
          end
        end
        ADDRESS_CHANNEL: begin
          addr <= c.input_base + 32'((pixel_index*64'(c.input_c)
                  +64'(c.group_offset)+64'(ch)) << c.input_s16);
          coordinate_address_valid<=1;
          if (col_idx==0) begin
            row_base_valid<=1;row_base_ix<=ix;row_base_iy<=iy;row_base_pixel<=pixel_index;
            row_base_addr<=c.input_base+32'((pixel_index*64'(c.input_c)+
                             64'(c.group_offset)+64'(ch))<<c.input_s16);
          end
          state<=FETCH;
        end
        FETCH: begin
          if (word_valid && word_addr=={addr[31:2],2'b0}) state<=STREAM;
          else if (cache_req_ready) state<=WAIT_WORD;
        end
        WAIT_WORD, STREAM, ZERO_STREAM: begin
          if (state==WAIT_WORD && cache_rsp_valid && cache_rsp_error) begin
            error<=1;tile_error<=1;state<=IDLE;
          end else if (wr_valid && wr_ready) begin
          if (col_idx+chunk_count==cols_q) begin
            if (row_idx+1==rows_q) begin tile_done<=1; state<=IDLE; end
            else begin
              row_idx<=row_idx+1; col_idx<=0; q_current<={1'b0,q0};
              ky<=ky0; kx<=kx0; ch<=ch0;
              if (ox+1==32'(c.output_w)) begin ox<=0; oy<=oy+1; end
              else ox<=ox+1;
              if (c.windowed && CACHE_POLICY==3 && row_base_valid) begin
                ix<=next_row_ix;iy<=next_row_iy;pixel_index<=next_row_pixel;
                addr<=next_row_addr;pad_q<=next_row_padding;coordinate_address_valid<=1;
                row_base_ix<=next_row_ix;row_base_iy<=next_row_iy;
                row_base_pixel<=next_row_pixel;row_base_addr<=next_row_addr;
                state<=next_row_padding ? ZERO_STREAM : FETCH;
              end else begin row_base_valid<=0;state<=COORD;end
            end
          end else begin
            col_idx<=col_idx+chunk_count; q_current<=q_current+33'(chunk_count);
            if (q_current+33'(chunk_count) >= {1'b0,reduction_len}) state<=ZERO_STREAM;
            else if (ch+chunk_count==32'(c.group_c)) begin
              ch<=0;
              if (c.windowed && CACHE_POLICY==3 && coordinate_address_valid) begin
                if (tap_wrap) begin kx<=0;ky<=ky+1;end
                else kx<=kx+1;
                ix<=next_tap_ix;iy<=next_tap_iy;pixel_index<=next_tap_pixel;
                addr<=next_tap_addr;pad_q<=next_tap_padding;
                if (next_tap_padding) state<=ZERO_STREAM;
                else if (next_tap_addr[31:2]==addr[31:2] && !pad_q) state<=STREAM;
                else state<=FETCH;
              end else if (kx+1==32'(c.kernel_w)) begin kx<=0; ky<=ky+1;state<=COORD;end
              else begin
                kx<=kx+1;
                if (!pad_q && c.group_c==c.input_c && c.group_offset==0 && c.dilation_w==1 &&
                    ix+1<$signed(64'(c.input_w))) begin
                  ix<=ix+1;pixel_index<=pixel_index+1;addr<=next_byte_addr;
                  if (next_byte_addr[31:2]==addr[31:2]) state<=STREAM;
                else if (stream_next_request && cache_req_ready) state<=WAIT_WORD;
                else state<=FETCH;
                end else state<=COORD;
              end
            end else begin
              ch<=ch+chunk_count;
              if (pad_q) begin addr<=next_byte_addr;state<=ZERO_STREAM;end
              else begin
                addr<=next_byte_addr;
                if (next_byte_addr[31:2]==addr[31:2]) state<=STREAM;
                else if (stream_next_request && cache_req_ready) state<=WAIT_WORD;
                else state<=FETCH;
              end
            end
          end
        end
        end
        default: begin state<=IDLE; configured<=0; error<=1; end
      endcase
    end
  end
`ifndef SYNTHESIS
  initial begin
    if (SIZE<2 || (SIZE & (SIZE-1))!=0) $fatal(1,"SIZE must be a power of two >=2");
    if (LANES<1 || LANES>4) $fatal(1,"LANES must be in [1,4]");
  end
`endif
`ifdef CONV_ASSERT
  always_ff @(posedge clk) if (rst_n) begin
    if (div_start) assert (!div_busy);
    if (div_done) assert (!div_zero);
    if (wr_valid) begin
      assert (wr_mask!='0 && chunk_count!=0);
      assert (col_idx+chunk_count<=cols_q && row_idx<rows_q);
    end
    if (cache_req_valid) begin
      assert (cache_req_addr>=c.input_base);
      assert ({1'b0,cache_req_addr} < {1'b0,c.input_base}+{1'b0,tensor_bytes});
    end
  end
`endif
endmodule
