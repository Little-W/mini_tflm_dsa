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
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
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
  output logic arvalid,
  input logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input logic rvalid,
  output logic rready,
  input logic [BUS_WIDTH-1:0] rdata,
  input logic [1:0] rresp,
  input logic rlast
);
  import conv_im2col_pkg::*;
  typedef enum logic [4:0] {IDLE, P_DECODE, P_START, P_WAIT, Q_DECODE, Q_START, Q_WAIT,
    K_DECODE, K_START, K_WAIT, COORD, COORD_SUM, COORD_PAD, ADDRESS, ADDRESS_PIXEL,
    ADDRESS_PRODUCT, ADDRESS_BASE, ADDRESS_CHANNEL, FETCH, WAIT_WORD, STREAM, ZERO_STREAM} st_t;
  st_t state;
  conv_cfg_t c;
  logic configured, cfg_ok, cfg_basic_valid, cfg_basic_saved;
  logic [1:0] cfg_prepare_phase;
  logic [31:0] cfg_input_hw, cfg_kernel_taps, cfg_position_product;
  logic [48:0] cfg_tensor_product;
  logic [47:0] cfg_reduction_product;
  logic [32:0] cfg_address_sum;
  logic [63:0] cfg_input_bytes, cfg_red;
  logic [31:0] cfg_positions;
  logic [31:0] reduction_len, position_count, tensor_bytes;
  localparam int TILE_COUNT_W=$clog2(SIZE+1);
  localparam int CHUNK_COUNT_W=$clog2(LANES+1);
  logic [31:0] p0, q0, tap0;
  logic [TILE_COUNT_W-1:0] row_idx, col_idx, rows_q, cols_q, active_cols_q;
  logic [TILE_COUNT_W-1:0] col_remaining, active_remaining;
  logic [16:0] group_remaining;
  logic [LANES-1:0] chunk_lane_allowed;
  logic [15:0] ox_q, oy_q, ky_q, kx_q, ch_q, ky0_q, kx0_q, ch0_q;
  wire [31:0] ox=32'(ox_q), oy=32'(oy_q), ky=32'(ky_q), kx=32'(kx_q), ch=32'(ch_q);
  wire [31:0] ky0=32'(ky0_q), kx0=32'(kx0_q), ch0=32'(ch0_q);
  logic [32:0] q_current;
  localparam int COORD_W=35;
  logic signed [COORD_W-1:0] ix, iy;
  logic [31:0] pixel_index;
  logic [31:0] coord_out_x,coord_out_y,coord_kernel_x,coord_kernel_y;
  logic [32:0] coord_sum_x,coord_sum_y;
  logic [31:0] pixel_product,channel_product,group_base_addr;
  logic [31:0] tap_group_base,row_group_base,next_row_group_base,incoming_group_base;
  logic pad_q;
  logic [31:0] addr;
  logic [31:0] word_buf, word_addr;
  logic word_valid;
  logic [CHUNK_COUNT_W-1:0] chunk_count;
  logic [31:0] word_available;
  logic [SLOT_W-1:0] slot_q;
  logic [31:0] decode_index, decode_outer, decode_inner;
  logic cache_cfg_ready, cache_req_ready, cache_rsp_valid, cache_rsp_error;
  logic cache_req_valid, cache_rsp_ready, stream_next_request,stream_context;
  logic [3:0] byte_offset_sum;
  logic word_boundary;
  logic incoming_request, incoming_context, incoming_word_hit, finishing_tile;
  logic cache_port_valid;
  logic [31:0] cache_req_addr;
  logic request_pending, cache_port_ready, request_bypass;
  logic [31:0] current_req_index, current_req_epoch;
  logic [31:0] request_addr_q, request_index_q, request_epoch_q;
  logic [15:0] request_y_q;
  logic [31:0] request_progress_q;
  logic retire_enabled_q, short_pixel_q;
  logic [3:0] retire_shift_q;
  logic [15:0] retire_last_row_q, second_last_row_q, last_output_col_q, second_last_col_q;
  logic request_geometry_q, request_event_first_q, request_index_valid_q;
  logic [31:0] cache_rsp_data;
  logic [31:0] selected_word;
  logic pred_cfg_eligible, pred_enabled, pred_busy, pred_done, pred_start;
  logic pred_cfg_busy, cache_cfg_pending, cache_config_valid;
  logic pred_cfg_pending;
  logic [31:0] predictor_cfg_r;
  logic [31:0] pred_rank, group_q, groups_q;
  logic geometry_tile, line_hint_valid, cache_hint_pending;
  logic [31:0] line_hint_rank;

  logic [3:0] p_cache_valid;
  logic [31:0] p_cache_key[4];
  logic [15:0] p_cache_y[4],p_cache_x[4];
  logic last_p_valid;
  logic [31:0] last_p,last_p_limit;
  logic [15:0] last_y,last_x;
  logic p_fast_valid;
  logic [31:0] p_fast_y,p_fast_x,p_decode;
  logic [15:0] p_delta;
  logic [16:0] p_sum;
  logic incoming_fast, incoming_q_fast, incoming_padding;
  logic [31:0] incoming_tap,incoming_ch,incoming_ky,incoming_kx,incoming_addr;
  logic signed [COORD_W-1:0] incoming_ix,incoming_iy;
  logic [31:0] incoming_pixel;
  logic [1:0] p_cache_select;
  logic [31:0] req_index, req_epoch, req_retire_current;
  logic req_index_valid,window_index_valid_q;
  logic [4:0] window_index_shift_q;
  logic pf_valid, pf_ready;
  logic [31:0] pf_addr, pf_index, pf_epoch, pf_retire;
  logic pf_index_valid;
  logic [3:0] prefetch_phase;
  logic [31:0] pf_distance_q, pf_step_q, pf_address_calc, pf_channel_product;
  logic pf_offer_valid;
  wire prefetch_active = prefetch_phase!=0;
  logic signed [COORD_W-1:0] pfa_x, pfa_y;
  logic [31:0] pfa_channel, pfa_origin_channel, pfa_output_x, pfa_output_y;
  logic [31:0] pfa_kernel_x, pfa_rows, pfa_cols;
  logic [31:0] pfa_ref_addr, pfa_ref_index, pfa_ref_epoch, pfa_retire;
  logic pfa_ref_index_valid;
  logic [31:0] pf0_x, pf0_y, pf0_channel, pf0_epoch;
  logic [31:0] pf0_ref_addr, pf0_ref_index, pf0_ref_epoch, pf0_ref_retire;
  logic pf0_ref_index_valid, pf0_fragment, pf0_coordinate_valid;
  logic [31:0] pf1_pixel, pf1_channel, pf1_epoch, pf1_retire;
  logic [31:0] pf1_ref_addr, pf1_ref_index, pf1_ref_epoch, pf1_ref_retire;
  logic pf1_ref_index_valid, pf1_fragment, pf1_coordinate_valid;
  logic [31:0] pf_x, pf_y, pf_step, pf_channel, pf_distance;
  logic [31:0] pixel_bytes;
  logic [31:0] cfg_pixel_bytes, cfg_line_pixels, cfg_pf_step, pf_step_base;
  logic pf_coordinate_valid;
  logic fragment_image_fits, pf_next_fragment;
  logic [9:0] current_q_times11;
  logic [4:0] current_q_div3;
  logic signed [COORD_W-1:0] request_y;
  logic [31:0] request_pixel;
  logic [31:0] request_channel, request_output_y;
  logic signed [COORD_W-1:0] pf_wrap_x;
  logic pf_window_ahead, pf_window_row_valid_q;
  logic pf_ahead_two, pf_wrap_once, pf_wrap_twice;
  logic signed [32:0] pf_window_dx_q, pf_fragment_dx_q, row_pair_dx;
  logic [16:0] pf_window_dy_q;
  logic signed [COORD_W-1:0] pf_window_x,pf_window_y;
  logic [31:0] next_byte_addr;
  logic [1:0] address_step_phase;
  logic signed [32:0] row_wrap_dx, tap_wrap_dx;
  logic signed [32:0] row_y_pixels, tap_y_pixels, row_wrap_pixels, tap_wrap_pixels;
  logic [31:0] row_step_bytes, tap_step_bytes, row_wrap_bytes, tap_wrap_bytes, group_bytes;
  logic row_base_valid, coordinate_address_valid;
  logic row_coordinate_valid,current_coordinate_valid;
  logic signed [COORD_W-1:0] row_base_ix, row_base_iy;
  logic [31:0] row_base_pixel;
  logic [31:0] row_base_addr;
  logic row_wrap, tap_wrap, next_row_padding, next_tap_padding;
  logic signed [COORD_W-1:0] next_row_ix, next_row_iy, next_tap_ix, next_tap_iy;
  logic [31:0] next_row_pixel, next_tap_pixel;
  logic [31:0] next_row_addr, next_tap_addr;

  // Configuration-time products leave only additions and bounds checks at
  // row and tap boundaries while the current word is being transferred.
  always_comb begin
    row_wrap=ox+1==32'(c.output_w);
    next_row_ix=row_base_ix+(row_wrap ? $signed(COORD_W'(row_wrap_dx)) : $signed(COORD_W'(c.stride_w)));
    next_row_iy=row_base_iy+(row_wrap ? $signed(COORD_W'(c.stride_h)) : 35'sd0);
    next_row_pixel=row_base_pixel+32'($unsigned(row_wrap ? row_wrap_pixels : $signed(33'(c.stride_w))));
    next_row_addr=row_base_addr+(row_wrap ? row_wrap_bytes : row_step_bytes);
    next_row_group_base=row_group_base+(row_wrap ? row_wrap_bytes : row_step_bytes);
    next_row_padding=next_row_ix<0 || next_row_iy<0 ||
      next_row_ix>=$signed(COORD_W'(c.input_w)) || next_row_iy>=$signed(COORD_W'(c.input_h));
    tap_wrap=kx+1==32'(c.kernel_w);
    next_tap_ix=ix+(tap_wrap ? $signed(COORD_W'(tap_wrap_dx)) : $signed(COORD_W'(c.dilation_w)));
    next_tap_iy=iy+(tap_wrap ? $signed(COORD_W'(c.dilation_h)) : 35'sd0);
    next_tap_pixel=pixel_index+32'($unsigned(tap_wrap ? tap_wrap_pixels : $signed(33'(c.dilation_w))));
    next_tap_addr=tap_group_base+(tap_wrap ? tap_wrap_bytes : tap_step_bytes);
    next_tap_padding=next_tap_ix<0 || next_tap_iy<0 ||
      next_tap_ix>=$signed(COORD_W'(c.input_w)) || next_tap_iy>=$signed(COORD_W'(c.input_h));
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
  function automatic logic [31:0] window_retirement(input logic [15:0] input_row);
    logic [16:0] shifted_row;
    shifted_row=({1'b0,input_row}+{1'b0,c.pad_top})>>retire_shift_q;
    if (shifted_row>{1'b0,retire_last_row_q}) shifted_row={1'b0,retire_last_row_q};
    if (short_pixel_q && shifted_row<{1'b0,retire_last_row_q}) shifted_row=shifted_row+17'd1;
    return retire_enabled_q ? 32'(shifted_row) : 32'hffff_ffff;
  endfunction
  always_comb begin
    p_decode=(state==P_DECODE || state==P_START || state==P_WAIT) ? p0 : tile_p0;
    p_cache_select=2'(p_decode>>CW);
    p_delta=16'(p_decode-last_p);
    p_sum={1'b0,last_x}+{1'b0,p_delta};
    p_fast_valid=0;p_fast_y=0;p_fast_x=0;
    if (p_decode==0) p_fast_valid=1;
    else if (p_cache_valid[p_cache_select] && p_cache_key[p_cache_select]==p_decode) begin
      p_fast_valid=1;p_fast_y=32'(p_cache_y[p_cache_select]);p_fast_x=32'(p_cache_x[p_cache_select]);
    end else if (last_p_valid && p_decode>=last_p && p_decode<=last_p_limit) begin
      p_fast_valid=1;p_fast_y=32'(last_y);p_fast_x=32'(p_sum);
      if (p_sum>={1'b0,c.output_w}) begin p_fast_x=32'(p_sum-{1'b0,c.output_w});p_fast_y=32'(last_y)+1;end
    end
  end

  always_comb begin
    current_q_times11=(10'(q0[4:0])<<3)+(10'(q0[4:0])<<1)+10'(q0[4:0]);
    current_q_div3=5'(current_q_times11>>5);
    incoming_q_fast=tile_q0==q0 || {1'b0,tile_q0}==({1'b0,q0}+33'(c.group_c));
    incoming_fast=CACHE_POLICY==3 && c.windowed && row_base_valid &&
      coordinate_address_valid && rows_q==1 && tile_rows==1 && tile_p0==p0 &&
      32'(cols_q)<=32'(c.group_c)-ch0 && incoming_q_fast;
    incoming_tap=tap0;incoming_ch=ch0;incoming_kx=kx0;incoming_ky=ky0;
    incoming_ix=row_base_ix;incoming_iy=row_base_iy;
    incoming_pixel=row_base_pixel;incoming_addr=row_base_addr;incoming_group_base=row_group_base;
    if (tile_q0!=q0) begin
      incoming_tap=tap0+1;
      if (kx0+1==32'(c.kernel_w)) begin
        incoming_kx=0;incoming_ky=ky0+1;
        incoming_ix=row_base_ix+$signed(COORD_W'(tap_wrap_dx));
        incoming_iy=row_base_iy+$signed(COORD_W'(c.dilation_h));
        incoming_pixel=row_base_pixel+32'($unsigned(tap_wrap_pixels));
        incoming_addr=row_base_addr+tap_wrap_bytes;incoming_group_base=row_group_base+tap_wrap_bytes;
      end else begin
        incoming_kx=kx0+1;
        incoming_ix=row_base_ix+$signed(COORD_W'(c.dilation_w));
        incoming_pixel=row_base_pixel+32'(c.dilation_w);
        incoming_addr=row_base_addr+tap_step_bytes;incoming_group_base=row_group_base+tap_step_bytes;
      end
    end
    incoming_padding=incoming_ix<0 || incoming_iy<0 || incoming_ix>=$signed(COORD_W'(c.input_w)) ||
                     incoming_iy>=$signed(COORD_W'(c.input_h));
  end

  // Configuration products cross register boundaries before overflow checks.
  always_comb begin
    cfg_basic_valid=cfg.input_h!=0 && cfg.input_w!=0 && cfg.input_c!=0 &&
      cfg.group_c!=0 && cfg.kernel_h!=0 && cfg.kernel_w!=0 &&
      cfg.output_h!=0 && cfg.output_w!=0 && cfg.stride_h!=0 && cfg.stride_w!=0 &&
      cfg.dilation_h!=0 && cfg.dilation_w!=0 &&
      (17'(cfg.group_offset)+17'(cfg.group_c)<=17'(cfg.input_c));
    if (cfg.input_s16) cfg_basic_valid=cfg_basic_valid && cfg.input_offset==0 && !cfg.input_base[0];
    else cfg_basic_valid=cfg_basic_valid && $signed(cfg.input_offset)>=-127 && $signed(cfg.input_offset)<=128;
    cfg_input_bytes={15'd0,cfg_tensor_product};
    cfg_red={16'd0,cfg_reduction_product};
    cfg_positions=cfg_position_product;
    cfg_address_sum={1'b0,c.input_base}+{1'b0,cfg_tensor_product[31:0]};
    cfg_ok=cfg_basic_saved && cfg_tensor_product[48:32]==0 &&
      cfg_reduction_product[47:32]==0 && !cfg_address_sum[32];
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cfg_prepare_phase<=0;
      cfg_basic_saved<=0;
    end else if (cfg_valid && cfg_ready) begin
      cfg_prepare_phase<=1;
      cfg_basic_saved<=cfg_basic_valid;
      cfg_input_hw<=32'(cfg.input_h)*32'(cfg.input_w);
      cfg_kernel_taps<=32'(cfg.kernel_h)*32'(cfg.kernel_w);
      cfg_position_product<=32'(cfg.output_h)*32'(cfg.output_w);
    end else case (cfg_prepare_phase)
      1: begin
        cfg_tensor_product<=(49'(cfg_input_hw)*49'(c.input_c))<<c.input_s16;
        cfg_reduction_product<=48'(cfg_kernel_taps)*48'(c.group_c);
        cfg_prepare_phase<=2;
      end
      2: cfg_prepare_phase<=0;
      default: ;
    endcase
  end
  assign cfg_ready = state==IDLE && cfg_prepare_phase==0 && cache_cfg_ready && !pred_busy && !pred_cfg_busy &&
                     !cache_cfg_pending && !pred_cfg_pending && !cache_hint_pending &&
                     !prefetch_active && !request_pending && address_step_phase==0;
  assign finishing_tile=wr_valid && wr_ready && wr_last;
  assign tile_ready = (state==IDLE || finishing_tile) && cfg_prepare_phase==0 && configured && !error && !cfg_valid &&
                      !pred_busy && !pred_cfg_busy && !pred_cfg_pending && !cache_cfg_pending &&
                      !cache_hint_pending && address_step_phase==0;
  assign busy = state!=IDLE || cfg_prepare_phase!=0 || pred_busy || pred_cfg_busy || pred_cfg_pending || cache_cfg_pending ||
                cache_hint_pending || !cache_cfg_ready ||
                prefetch_active || request_pending || address_step_phase!=0;
  assign wr_valid = state==STREAM || state==ZERO_STREAM ||
                    (state==WAIT_WORD && cache_rsp_valid && !cache_rsp_error);
  assign wr_slot = slot_q;
  assign wr_row = CW'(row_idx);
  assign wr_col = CW'(col_idx);
  assign wr_last=row_idx+1==rows_q && TILE_COUNT_W'(chunk_count)==col_remaining;

  assign pred_start = state==ADDRESS && geometry_tile && col_idx==0 &&
    q_current<{1'b0,reduction_len} && ix>=0 && iy>=0 &&
    ix<$signed(COORD_W'(c.input_w)) && iy<$signed(COORD_W'(c.input_h)) &&
    !pred_busy && !cache_hint_pending;
  generate if (SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0) begin : g_next_use
    conv_next_use_predictor u_predictor (
      .clk,.rst_n,.cfg_valid(pred_cfg_pending),.cfg(c),
      .cfg_r(predictor_cfg_r),.cfg_groups(groups_q),
      .cfg_eligible(pred_cfg_eligible),.cfg_busy(pred_cfg_busy),.enabled(pred_enabled),.start(pred_start),
      .input_y(32'(iy)),.input_x(32'(ix)),.channel(ch),
      .current_p(p0+32'(row_idx)),.current_q(32'(q_current)),.current_group(group_q),
      .busy(pred_busy),.done(pred_done),.next_rank(pred_rank)
    );
  end else begin : g_no_next_use
    assign pred_cfg_eligible=0;assign pred_cfg_busy=0;assign pred_enabled=0;assign pred_busy=0;
    assign pred_done=0;assign pred_rank=32'hffff_ffff;
  end endgenerate

  assign byte_offset_sum={2'b0,addr[1:0]}+(4'(chunk_count)<<c.input_s16);
  assign word_boundary=byte_offset_sum>=4;
  assign stream_context=state==STREAM || state==WAIT_WORD;
  assign stream_next_request=wr_valid && wr_ready && state!=ZERO_STREAM &&
    TILE_COUNT_W'(chunk_count)<col_remaining && TILE_COUNT_W'(chunk_count)<active_remaining &&
    17'(chunk_count)<group_remaining && word_boundary;
  assign incoming_word_hit=(finishing_tile && state==WAIT_WORD) ?
    addr[31:2]==incoming_addr[31:2] :
    word_valid && word_addr=={incoming_addr[31:2],2'b0};
  assign incoming_request=tile_valid && tile_ready && incoming_fast && !incoming_padding &&
    !incoming_word_hit && tile_rows!=0 && 32'(tile_rows)<=SIZE && 32'(tile_cols)<=SIZE &&
    tile_q0<reduction_len && {1'b0,tile_p0}+33'(tile_rows)<={1'b0,position_count};
  assign cache_req_valid = incoming_request ||
                           (state==FETCH && !(word_valid && word_addr=={addr[31:2],2'b0})) ||
                           stream_next_request;
  assign incoming_context=tile_valid && incoming_fast &&
    (state==IDLE || ((state==WAIT_WORD || state==STREAM || state==ZERO_STREAM) && wr_last));
  assign cache_req_addr=incoming_context ? incoming_addr : stream_context ? next_byte_addr : addr;
  assign cache_rsp_ready = state==WAIT_WORD && (wr_ready || cache_rsp_error);
  assign cache_config_valid = cache_cfg_pending && !pred_cfg_pending && !pred_cfg_busy;
  // The registered trigger consumes the accepted configuration. Cache setup
  // waits until the predictor has produced its new eligibility flag.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pred_cfg_pending<=1'b0;
    else if (cfg_prepare_phase==2)
      pred_cfg_pending<=cfg_ok && SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0;
    else pred_cfg_pending<=1'b0;
  end
  always_ff @(posedge clk) begin
    if (cfg_valid && cfg_ready) predictor_cfg_r<=cfg_sched_r;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cache_cfg_pending <= 1'b0;
    else if (cfg_valid && cfg_ready) cache_cfg_pending <= 1'b0;
    else if (cfg_prepare_phase==2) cache_cfg_pending <= cfg_ok;
    else if (cache_config_valid && cache_cfg_ready) cache_cfg_pending <= 1'b0;
  end
  // The registered request isolates writeback completion and descriptor
  // selection from the cache RAM address and enable inputs.
  assign request_bypass = state==FETCH && !request_pending;
  assign cache_port_valid = request_pending ||
    (request_bypass && !(word_valid && word_addr=={addr[31:2],2'b0}));
  assign cache_req_ready = request_bypass ? cache_port_ready : (!request_pending || cache_port_ready);
  always_comb begin
    current_req_index = pixel_index;
    current_req_epoch = ((32'(c.group_offset)+ch)<<c.input_s16)>>$clog2(LINE_BYTES);
    if (short_pixel_q) begin
      current_req_index = pixel_index>>window_index_shift_q;
      current_req_epoch = 0;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) request_pending <= 1'b0;
    else if (cache_req_ready) request_pending <= cache_req_valid && !request_bypass;
  end
  always_ff @(posedge clk) begin
    if (!request_pending || cache_port_ready) begin
      request_addr_q <= cache_req_addr;
      request_geometry_q <= geometry_tile;
      request_event_first_q <= geometry_tile && cache_req_addr[3:0]==0;
      request_index_valid_q <= req_index_valid;
      request_index_q <= req_index;
      request_epoch_q <= req_epoch;
      request_y_q <= request_y[15:0];
      request_progress_q <= request_output_y;
    end
  end
  conv_read_cache #(.SETS(CACHE_SETS),.WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES),
    .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_cache (
    .clk,.rst_n,
    .cfg_valid(cache_config_valid),.cfg_ready(cache_cfg_ready),
    .cfg_base(c.input_base),.cfg_bytes(tensor_bytes),.cfg_bypass(c.bypass_cache),
    .cfg_geometry(pred_cfg_eligible),
    .cfg_windowed(c.windowed),.cfg_prefetch_enable(c.prefetch_enable),
    .req_valid(cache_port_valid),.req_ready(cache_port_ready),
    .req_addr(request_pending ? request_addr_q : addr),
    .req_geometry(request_pending ? request_geometry_q : geometry_tile),
    .req_event_first(request_pending ? request_event_first_q : (geometry_tile && addr[3:0]==0)),
    .hint_valid(line_hint_valid),.hint_next(line_hint_rank),.hint_pending(cache_hint_pending),
    .req_window_index_valid(request_pending ? request_index_valid_q : req_index_valid),
    .req_window_index(request_pending ? request_index_q : current_req_index),
    .req_window_epoch(request_pending ? request_epoch_q : current_req_epoch),
    .req_window_retire(request_pending ? window_retirement(request_y_q) : req_retire_current),
    .req_window_progress(request_pending ? request_progress_q : oy),
    .prefetch_valid(pf_valid),.prefetch_ready(pf_ready),.prefetch_addr(pf_addr),
    .prefetch_window_index_valid(pf_index_valid),.prefetch_window_index(pf_index),
    .prefetch_window_epoch(pf_epoch),.prefetch_window_retire(
      (!pf1_coordinate_valid && pf1_fragment) ? pf1_ref_retire : pf1_retire),
    .prefetch_next_fragment(pf1_fragment),
    .prefetch_ref_valid(1'b1),.prefetch_ref_addr(pf1_ref_addr),
    .prefetch_ref_index_valid(pf1_ref_index_valid),.prefetch_ref_index(pf1_ref_index),
    .prefetch_ref_epoch(pf1_ref_epoch),
    .rsp_valid(cache_rsp_valid),.rsp_ready(cache_rsp_ready),
    .rsp_data(cache_rsp_data),.rsp_error(cache_rsp_error),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
  );
  always_comb begin
    col_remaining=cols_q-col_idx;
    active_remaining=active_cols_q-col_idx;
    group_remaining={1'b0,c.group_c}-{1'b0,ch_q};
    word_available = (32'd4-{30'd0,addr[1:0]}) >> c.input_s16;
    chunk_count = '0;
    for (int lane=0;lane<LANES;lane++) begin
      chunk_lane_allowed[lane]=TILE_COUNT_W'(lane)<col_remaining &&
        (col_idx>=active_cols_q || (17'(lane)<group_remaining && TILE_COUNT_W'(lane)<active_remaining)) &&
        ((state!=STREAM && state!=WAIT_WORD) || 32'(lane)<word_available);
      if (chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
    end
    selected_word = (state==WAIT_WORD ? cache_rsp_data : word_buf) >> (addr[1:0]*8);
    next_byte_addr=addr+(32'(chunk_count)<<c.input_s16);
    for (int l=0;l<LANES;l++) begin
      wr_mask[l]=32'(l)<chunk_count;
      wr_data[l]=0;
      if ((state==STREAM || state==WAIT_WORD) && 32'(l)<chunk_count) begin
        if (c.input_s16) wr_data[l]=$signed(16'(selected_word>>(l*16)));
        else wr_data[l]=$signed(16'($signed(8'(selected_word>>(l*8)))))+c.input_offset;
      end
    end
  end

  always_comb begin
    cfg_pixel_bytes = 32'(cfg.input_c) << cfg.input_s16;
    cfg_line_pixels = 1;
    for (int n=1; n<=LINE_BYTES; n++)
      if (cfg_pixel_bytes <= 32'((LINE_BYTES-1)/n)) cfg_line_pixels=32'(n)+1;
    cfg_pf_step=cfg.kernel_w==1 ? 32'(cfg.stride_w) : 32'(cfg.dilation_w);
    if (cfg_pf_step<cfg_line_pixels) cfg_pf_step=cfg_line_pixels;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pixel_bytes<=0;pf_step_base<=1;
      retire_enabled_q<=0;short_pixel_q<=0;retire_shift_q<=0;retire_last_row_q<=0;
      window_index_valid_q<=0;window_index_shift_q<=0;
      second_last_row_q<=0;last_output_col_q<=0;second_last_col_q<=0;
    end else if (cfg_valid && cfg_ready) begin
      pixel_bytes<=cfg_pixel_bytes;pf_step_base<=cfg_pf_step;
      retire_enabled_q<=is_power_two(32'(cfg.stride_h));
      short_pixel_q<=cfg_pixel_bytes<LINE_BYTES;
      window_index_valid_q<=cfg.windowed && cfg.input_base[$clog2(LINE_BYTES)-1:0]==0 &&
        ((cfg_pixel_bytes>=LINE_BYTES && (cfg_pixel_bytes&(LINE_BYTES-1))==0) ||
         (is_power_two(cfg_pixel_bytes) && cfg_pixel_bytes<LINE_BYTES));
      window_index_shift_q<=cfg_pixel_bytes<LINE_BYTES ?
        power_shift(32'(LINE_BYTES))-power_shift(cfg_pixel_bytes) : 5'd0;
      retire_shift_q<=4'(power_shift(32'(cfg.stride_h)));
      retire_last_row_q<=cfg.output_h-16'd1;
      second_last_row_q<=cfg.output_h-16'd2;
      last_output_col_q<=cfg.output_w-16'd1;second_last_col_q<=cfg.output_w-16'd2;
    end
  end

  // Spatial indexing retains a channel fragment across the moving window.
  // The physical line tag preserves correctness for every tensor alignment.
  always_comb begin
    request_y=incoming_context ? incoming_iy : iy;
    request_pixel=incoming_context ? incoming_pixel : pixel_index;
    request_channel=incoming_context ? incoming_ch : ch;
    request_output_y=incoming_context ? p_fast_y : oy;
    req_index_valid=window_index_valid_q;
    req_index=32'(request_pixel);
    req_epoch=(32'(c.group_offset)+request_channel)<<c.input_s16;
    req_epoch=req_epoch>>$clog2(LINE_BYTES);
    if (short_pixel_q) begin
      req_index=32'(request_pixel)>>window_index_shift_q;
      req_epoch=0;
    end
    req_retire_current=window_retirement(iy[15:0]);
    pf_step=pf_step_q;
    pf_distance=pf_distance_q;
    pf_x=32'(pfa_x)+pf_step;pf_y=32'(pfa_y);
    if (pf_x>=32'(c.input_w)) begin
      pf_x=0;
      pf_y=32'(pfa_y)+(c.kernel_h==1 ? 32'(c.stride_h) : 32'(c.dilation_h));
    end
    // A single-position channel fragment follows the kernel rows. Keep its
    // lookahead inside the next kernel row before advancing along the image.
    pf_wrap_x=pfa_x+$signed(COORD_W'(pf_fragment_dx_q));
    if (c.windowed && pfa_rows==1 && pfa_cols<=32'(c.group_c) &&
        c.kernel_w>1 && c.kernel_h>1 && c.dilation_w==1 && c.dilation_h==1 &&
        pfa_kernel_x+pf_distance>=32'(c.kernel_w) &&
        pfa_kernel_x+pf_distance<2*32'(c.kernel_w)) begin
      pf_x=pf_wrap_x<0 ? 0 : 32'(pf_wrap_x);
      pf_y=32'(pfa_y)+1;
    end
    // Strided windows prefetch the same kernel coordinate in the following
    // two output positions. Word offsets distribute requests across both
    // positions, including the next output row.
    pf_window_ahead=c.windowed && pfa_rows==1 && pfa_cols<=32'(c.group_c) &&
      (c.stride_h>1 || c.stride_w>1);
    pf_ahead_two=!pf_distance[0];
    pf_wrap_once=pfa_output_x==32'(last_output_col_q) ||
      (pf_ahead_two && pfa_output_x==32'(second_last_col_q));
    pf_wrap_twice=c.output_w==1 && pf_ahead_two;
    pf_window_x=pfa_x+$signed(COORD_W'(pf_window_dx_q));
    pf_window_y=pfa_y+$signed(COORD_W'(pf_window_dy_q));
    if(pf_window_ahead) begin pf_x=32'(pf_window_x);pf_y=32'(pf_window_y);end
    pf_coordinate_valid=pfa_x>=0 && pfa_y>=0 && pfa_x<$signed(COORD_W'(c.input_w)) &&
      pfa_y<$signed(COORD_W'(c.input_h)) &&
      (!pf_window_ahead || (pf_window_row_valid_q && pf_window_x>=0 && pf_window_y>=0));
    pf_channel=32'(c.group_offset)+pfa_channel;
    pfa_retire=window_retirement(pfa_y[15:0]);
    pf_retire=window_retirement(pf0_y[15:0]);
    // Two ways retain the active and following channel fragments when each
    // spatial pixel has a distinct set. Both fragments use physical tags.
    pf_next_fragment=fragment_image_fits && pfa_ref_index_valid && pfa_rows==1 &&
      pfa_cols==LINE_BYTES && !c.input_s16 &&
      ((32'(c.group_offset)+pfa_origin_channel)&(LINE_BYTES-1))==0 &&
      pfa_origin_channel+2*LINE_BYTES<=32'(c.group_c) &&
      (!pf_window_ahead || pf_distance==LINE_BYTES/4);
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prefetch_phase <= '0;
      pf_offer_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      prefetch_phase <= '0;
      pf_offer_valid <= 1'b0;
    end else begin
      case (prefetch_phase)
        0: if (cache_port_valid && cache_port_ready && c.prefetch_enable) begin
          prefetch_phase <= 1;
          pfa_x <= ix; pfa_y <= iy;
          pfa_channel <= ch; pfa_origin_channel <= ch0;
          pfa_output_x <= ox; pfa_output_y <= oy;
          pfa_kernel_x <= kx; pfa_rows <= 32'(rows_q); pfa_cols <= 32'(cols_q);
          pfa_ref_addr <= request_pending ? request_addr_q : addr;
          pfa_ref_index <= request_pending ? request_index_q : current_req_index;
          pfa_ref_epoch <= request_pending ? request_epoch_q : current_req_epoch;
          pfa_ref_index_valid <= request_pending ? request_index_valid_q : req_index_valid;
        end
        1: begin
          pf_distance_q <= c.windowed ? 1+(((pfa_channel-pfa_origin_channel)<<c.input_s16)>>2) : 32'd1;
          prefetch_phase <= 2;
        end
        2: begin
          pf_step_q <= pf_step_base * pf_distance_q;
          pf_fragment_dx_q <= tap_wrap_dx+$signed(33'(pf_distance_q))-33'sd1;
          if (c.output_w==1) pf_window_dx_q<=0;
          else if (pf_wrap_once) pf_window_dx_q<=pf_ahead_two ? row_pair_dx : row_wrap_dx;
          else pf_window_dx_q<=$signed(33'(c.stride_w)<<pf_ahead_two);
          pf_window_dy_q<=pf_wrap_twice ? (17'(c.stride_h)<<1) :
                            pf_wrap_once ? 17'(c.stride_h) : 17'd0;
          pf_window_row_valid_q<=pf_wrap_twice ?
              (c.output_h>1 && pfa_output_y<32'(second_last_row_q)) :
              (!pf_wrap_once || pfa_output_y<32'(retire_last_row_q));
          prefetch_phase <= 3;
        end
        3: begin
          pf0_x <= pf_x; pf0_y <= pf_y; pf0_channel <= pf_channel;
          pf0_epoch <= pfa_ref_epoch;
          pf0_ref_addr <= pfa_ref_addr; pf0_ref_index <= pfa_ref_index;
          pf0_ref_epoch <= pfa_ref_epoch; pf0_ref_retire <= pfa_retire;
          pf0_ref_index_valid <= pfa_ref_index_valid; pf0_fragment <= pf_next_fragment;
          pf0_coordinate_valid <= pf_coordinate_valid;
          prefetch_phase <= 4;
        end
        4: begin
          pf1_pixel <= pf0_y * 32'(c.input_w) + pf0_x;
          pf1_channel <= pf0_channel; pf1_epoch <= pf0_epoch; pf1_retire <= pf_retire;
          pf1_ref_addr <= pf0_ref_addr; pf1_ref_index <= pf0_ref_index;
          pf1_ref_epoch <= pf0_ref_epoch; pf1_ref_retire <= pf0_ref_retire;
          pf1_ref_index_valid <= pf0_ref_index_valid; pf1_fragment <= pf0_fragment;
          pf1_coordinate_valid <= pf0_coordinate_valid && pf0_x<32'(c.input_w) && pf0_y<32'(c.input_h);
          prefetch_phase <= 5;
        end
        5: begin
          pf_channel_product<=pf1_pixel*32'(c.input_c);
          prefetch_phase<=6;
        end
        6: begin
          pf_addr<=pf_address_calc;
          prefetch_phase<=7;
        end
        7: begin
          pf_offer_valid <= pf1_fragment || (pf1_coordinate_valid &&
              (pf_addr>>$clog2(LINE_BYTES))!=(pf1_ref_addr>>$clog2(LINE_BYTES)));
          prefetch_phase<=8;
        end
        default: prefetch_phase <= 0;
      endcase
    end
  end

  always_comb begin
    pf_address_calc=c.input_base+((pf_channel_product+pf1_channel)<<c.input_s16);
    pf_index_valid=pf1_ref_index_valid; pf_index=pf1_pixel; pf_epoch=pf1_epoch;
    if (short_pixel_q)
      pf_index=pf1_pixel>>window_index_shift_q;
    if (!pf1_coordinate_valid && pf1_fragment) begin
      pf_address_calc=pf1_ref_addr;pf_index=pf1_ref_index;pf_epoch=pf1_ref_epoch;
    end
    pf_valid=prefetch_phase==8 && pf_offer_valid;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE; c<='0; configured<=0; error<=0; tile_done<=0; tile_error<=0;
      fragment_image_fits<=0;
      reduction_len<=0; position_count<=0; tensor_bytes<=0;
      p0<=0; q0<=0; tap0<=0; row_idx<=0; col_idx<=0; rows_q<=0; cols_q<=TILE_COUNT_W'(SIZE);active_cols_q<=0;
      ox_q <= 16'(0); oy_q <= 16'(0); ky_q <= 16'(0); kx_q <= 16'(0); ch_q <= 16'(0); ky0_q <= 16'(0); kx0_q <= 16'(0); ch0_q <= 16'(0);
      tap_group_base<=0;row_group_base<=0;
      q_current<=0; ix <= COORD_W'(0); iy <= COORD_W'(0); pixel_index <= 32'(0); pad_q<=0; addr<=0;
      word_buf<=0; word_addr<=0; word_valid<=0; slot_q<=0;
      group_q<=0;groups_q<=0;geometry_tile<=0;line_hint_valid<=0;line_hint_rank<=32'hffff_ffff;
      p_cache_valid<=0;last_p_valid<=0;last_p<=0;last_p_limit<=0;last_y<=0;last_x<=0;
      address_step_phase<=0;row_wrap_dx <= 33'(0);tap_wrap_dx <= 33'(0);row_pair_dx<=0;
      row_y_pixels <= 33'(0);tap_y_pixels <= 33'(0);row_wrap_pixels <= 33'(0);tap_wrap_pixels <= 33'(0);
      row_step_bytes<=0;tap_step_bytes<=0;row_wrap_bytes<=0;tap_wrap_bytes<=0;group_bytes<=0;
      row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;current_coordinate_valid<=0;
      row_base_ix <= COORD_W'(0);row_base_iy <= COORD_W'(0);row_base_pixel <= 32'(0);row_base_addr<=0;
      for (int t=0;t<4;t++) begin p_cache_key[t]<=0;p_cache_y[t]<=0;p_cache_x[t]<=0;end
    end else begin
      tile_done<=finishing_tile; tile_error<=0;
      if (state==WAIT_WORD && wr_valid && wr_ready) begin
        word_buf<=cache_rsp_data;word_addr<={addr[31:2],2'b0};word_valid<=1;
      end
      if (address_step_phase==2) begin
        row_pair_dx<=row_wrap_dx+$signed(33'(c.stride_w));
        row_wrap_pixels <= 33'(row_y_pixels+$signed(COORD_W'(row_wrap_dx)));
        tap_wrap_pixels <= 33'(tap_y_pixels+$signed(COORD_W'(tap_wrap_dx)));
        address_step_phase<=1;
      end else if (address_step_phase==1) begin
        row_wrap_bytes<=32'(($unsigned(row_wrap_pixels)*COORD_W'(c.input_c))<<c.input_s16);
        tap_wrap_bytes<=32'(($unsigned(tap_wrap_pixels)*COORD_W'(c.input_c))<<c.input_s16);
        address_step_phase<=0;
      end
      if (cfg_prepare_phase==2) begin
        configured<=cfg_ok;error<=!cfg_ok;
        reduction_len<=32'(cfg_red);position_count<=cfg_positions;tensor_bytes<=32'(cfg_input_bytes);
        fragment_image_fits<=CACHE_WAYS>=2 &&
          cfg_input_bytes<=((64'(c.input_c)<<c.input_s16)<<$clog2(CACHE_SETS));
      end
      if (pred_done) begin line_hint_valid<=1;line_hint_rank<=pred_rank;end
      if (pred_start) line_hint_valid<=0;
      if (cfg_valid && cfg_ready) begin
        c<=cfg; configured<=0; error<=!cfg_basic_valid;
        word_valid<=0; reduction_len<=0;
        fragment_image_fits<=0;
        position_count<=0; tensor_bytes<=0;
        groups_q<=cfg_sched_groups;geometry_tile<=0;line_hint_valid<=0;
        p_cache_valid<=0;last_p_valid<=0;
        address_step_phase<=2;row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;current_coordinate_valid<=0;
        row_wrap_dx <= 33'(-$signed((64'(cfg.output_w)-1)*64'(cfg.stride_w)));
        tap_wrap_dx <= 33'(-$signed((64'(cfg.kernel_w)-1)*64'(cfg.dilation_w)));
        row_y_pixels <= 33'($signed(64'(cfg.stride_h)*64'(cfg.input_w)));
        tap_y_pixels <= 33'($signed(64'(cfg.dilation_h)*64'(cfg.input_w)));
        row_step_bytes<=32'((64'(cfg.stride_w)*64'(cfg.input_c))<<cfg.input_s16);
        tap_step_bytes<=32'((64'(cfg.dilation_w)*64'(cfg.input_c))<<cfg.input_s16);
        group_bytes<=32'(cfg.group_c)<<cfg.input_s16;
      end else if (tile_valid && tile_ready) begin
          if (tile_rows==0 || 32'(tile_rows)>SIZE || 32'(tile_cols)>SIZE || tile_q0>=reduction_len ||
              ({1'b0,tile_p0}+33'(tile_rows) > {1'b0,position_count})) begin
            tile_error<=1; error<=1; state<=IDLE;
          end else begin
            p0<=tile_p0; q0<=tile_q0; q_current<={1'b0,tile_q0};
            rows_q<=TILE_COUNT_W'(tile_rows); cols_q <= (tile_cols==0) ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols);
            if (reduction_len-tile_q0<32'(tile_cols==0 ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols)))
              active_cols_q<=TILE_COUNT_W'(reduction_len-tile_q0);
            else active_cols_q<=(tile_cols==0) ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols);
            row_idx<=0; col_idx<=0; slot_q<=tile_slot;
            group_q<=tile_group;
            row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;current_coordinate_valid<=0;
            // Windowed requests carry spatial retirement metadata directly.
            geometry_tile<=pred_enabled && (CACHE_POLICY!=3 || !c.windowed) &&
                           (tile_cols==0 || 32'(tile_cols)==SIZE) && tile_p0[3:0]==0 && tile_q0[3:0]==0 &&
                           tile_group<groups_q;
            if(incoming_fast) begin
              tap0<=incoming_tap;ch_q <= 16'(incoming_ch);ch0_q <= 16'(incoming_ch);
              ky_q <= 16'(incoming_ky);ky0_q <= 16'(incoming_ky);kx_q <= 16'(incoming_kx);kx0_q <= 16'(incoming_kx);
              ix <= COORD_W'(incoming_ix);iy <= COORD_W'(incoming_iy);pixel_index <= 32'(incoming_pixel);
              addr<=incoming_addr;pad_q<=incoming_padding;
              tap_group_base<=incoming_group_base;row_group_base<=incoming_group_base;
              row_base_valid<=1;coordinate_address_valid<=1;row_coordinate_valid<=1;current_coordinate_valid<=1;
              row_base_ix <= COORD_W'(incoming_ix);row_base_iy <= COORD_W'(incoming_iy);
              row_base_pixel <= 32'(incoming_pixel);row_base_addr<=incoming_addr;
              if (incoming_padding) state<=ZERO_STREAM;
              else if (incoming_word_hit) state<=STREAM;
              else state<=cache_req_ready ? WAIT_WORD : FETCH;
            end else state<=P_DECODE;
          end
      end else case (state)
        WAIT_WORD, STREAM, ZERO_STREAM: begin
          if (state==WAIT_WORD && cache_rsp_valid && cache_rsp_error) begin
            error<=1;tile_error<=1;state<=IDLE;
          end else if (wr_valid && wr_ready) begin
          if (TILE_COUNT_W'(chunk_count)==col_remaining) begin
            if (row_idx+1==rows_q) begin tile_done<=1; state<=IDLE; end
            else begin
              row_idx<=row_idx+1; col_idx<=0; q_current<={1'b0,q0};
              ky_q <= 16'(ky0); kx_q <= 16'(kx0); ch_q <= 16'(ch0);
              if (ox+1==32'(c.output_w)) begin ox_q <= 16'(0); oy_q <= 16'(oy+1); end
              else ox_q <= 16'(ox+1);
              if (row_base_valid && !geometry_tile) begin
                ix <= COORD_W'(next_row_ix);iy <= COORD_W'(next_row_iy);pixel_index <= 32'(next_row_pixel);
                addr<=next_row_addr;pad_q<=next_row_padding;coordinate_address_valid<=1;
                tap_group_base<=next_row_group_base;row_group_base<=next_row_group_base;
                row_base_ix <= COORD_W'(next_row_ix);row_base_iy <= COORD_W'(next_row_iy);
                row_base_pixel <= 32'(next_row_pixel);row_base_addr<=next_row_addr;
                state<=next_row_padding ? ZERO_STREAM : FETCH;
              end else if (row_coordinate_valid) begin
                ix<=next_row_ix;iy<=next_row_iy;
                row_base_ix<=next_row_ix;row_base_iy<=next_row_iy;
                row_base_valid<=0;coordinate_address_valid<=0;state<=ADDRESS;
              end else begin row_base_valid<=0;state<=COORD;end
            end
          end else begin
            col_idx<=col_idx+TILE_COUNT_W'(chunk_count); q_current<=q_current+33'(chunk_count);
            if (col_idx>=active_cols_q || TILE_COUNT_W'(chunk_count)>=active_remaining) state<=ZERO_STREAM;
            else if (17'(chunk_count)==group_remaining) begin
              ch_q <= 16'(0);
              if (coordinate_address_valid) begin
                if (tap_wrap) begin kx_q <= 16'(0);ky_q <= 16'(ky+1);end
                else kx_q <= 16'(kx+1);
                ix <= COORD_W'(next_tap_ix);iy <= COORD_W'(next_tap_iy);pixel_index <= 32'(next_tap_pixel);
                addr<=next_tap_addr;pad_q<=next_tap_padding;tap_group_base<=next_tap_addr;
                if (next_tap_padding) state<=ZERO_STREAM;
                else if (next_tap_addr[31:2]==addr[31:2] && !pad_q) state<=STREAM;
                else state<=FETCH;
              end else if (current_coordinate_valid) begin
                if (tap_wrap) begin kx_q<=0;ky_q<=16'(ky+1);end
                else kx_q<=16'(kx+1);
                ix<=next_tap_ix;iy<=next_tap_iy;
                coordinate_address_valid<=0;state<=ADDRESS;
              end else if (kx+1==32'(c.kernel_w)) begin kx_q <= 16'(0); ky_q <= 16'(ky+1);state<=COORD;end
              else begin
                kx_q <= 16'(kx+1);
                if (!pad_q && c.group_c==c.input_c && c.group_offset==0 && c.dilation_w==1 &&
                    ix+1<$signed(COORD_W'(c.input_w))) begin
                  ix <= COORD_W'(ix+1);pixel_index <= 32'(pixel_index+1);addr<=next_byte_addr;
                  if (!word_boundary) state<=STREAM;
                else if (stream_next_request && cache_req_ready) state<=WAIT_WORD;
                else state<=FETCH;
                end else state<=COORD;
              end
            end else begin
              ch_q <= 16'(ch+32'(chunk_count));
              if (pad_q) begin addr<=next_byte_addr;state<=ZERO_STREAM;end
              else begin
                addr<=next_byte_addr;
                if (!word_boundary) state<=STREAM;
                else if (stream_next_request && cache_req_ready) state<=WAIT_WORD;
                else state<=FETCH;
              end
            end
          end
        end
        end
        default: ;
      endcase
      case (state)
        P_DECODE: if (p_fast_valid) begin
          oy_q <= 16'(p_fast_y);ox_q <= 16'(p_fast_x);state<=Q_DECODE;
          last_p_valid<=1;last_p<=p0;last_p_limit<=p0+32'(c.output_w);last_y<=16'(p_fast_y);last_x<=16'(p_fast_x);
          p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=p0;
          p_cache_y[p_cache_select]<=16'(p_fast_y);p_cache_x[p_cache_select]<=16'(p_fast_x);
        end else state<=P_START;
        P_START: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=P_WAIT;end
        P_WAIT: if (decode_index==p0) begin
          oy_q <= 16'(decode_outer);ox_q <= 16'(decode_inner);state<=Q_DECODE;
          last_p_valid<=1;last_p<=p0;last_p_limit<=p0+32'(c.output_w);last_y<=16'(decode_outer);last_x<=16'(decode_inner);
          p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=p0;
          p_cache_y[p_cache_select]<=16'(decode_outer);p_cache_x[p_cache_select]<=16'(decode_inner);
        end else begin
          decode_index<=decode_index+1;
          if (decode_inner+1==32'(c.output_w)) begin decode_inner<=0;decode_outer<=decode_outer+1;end
          else decode_inner<=decode_inner+1;
        end
        Q_DECODE: begin
          if (q0==0) begin tap0<=0;ch_q <= 16'(0);ch0_q <= 16'(0);state<=K_DECODE;end
          else if (is_power_two(32'(c.group_c))) begin
            tap0<=q0>>power_shift(32'(c.group_c));
            ch_q <= 16'(q0&(32'(c.group_c)-1));ch0_q <= 16'(q0&(32'(c.group_c)-1));state<=K_DECODE;
          end else if (c.group_c==3 && q0<27) begin
            tap0<=32'(current_q_div3);
            ch_q <= 16'(q0-3*32'(current_q_div3));
            ch0_q <= 16'(q0-3*32'(current_q_div3));
            state<=K_DECODE;
          end else state<=Q_START;
        end
        Q_START: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=Q_WAIT;end
        Q_WAIT: if (decode_index==q0) begin tap0<=decode_outer; ch_q <= 16'(decode_inner); ch0_q <= 16'(decode_inner); state<=K_DECODE; end
        else begin
          decode_index<=decode_index+1;
          if (decode_inner+1==32'(c.group_c)) begin decode_inner<=0;decode_outer<=decode_outer+1;end
          else decode_inner<=decode_inner+1;
        end
        K_DECODE: begin
          if (is_power_two(32'(c.kernel_w))) begin
            ky_q <= 16'(tap0>>power_shift(32'(c.kernel_w)));ky0_q <= 16'(tap0>>power_shift(32'(c.kernel_w)));
            kx_q <= 16'(tap0&(32'(c.kernel_w)-1));kx0_q <= 16'(tap0&(32'(c.kernel_w)-1));state<=COORD;
          end else if (c.kernel_w==3 && tap0<9) begin
            if (tap0<3) begin ky_q <= 16'(0);ky0_q <= 16'(0);kx_q <= 16'(tap0);kx0_q <= 16'(tap0);end
            else if (tap0<6) begin ky_q <= 16'(1);ky0_q <= 16'(1);kx_q <= 16'(tap0-3);kx0_q <= 16'(tap0-3);end
            else begin ky_q <= 16'(2);ky0_q <= 16'(2);kx_q <= 16'(tap0-6);kx0_q <= 16'(tap0-6);end
            state<=COORD;
          end else state<=K_START;
        end
        K_START: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=K_WAIT;end
        K_WAIT: if (decode_index==tap0) begin
          ky_q <= 16'(decode_outer); ky0_q <= 16'(decode_outer); kx_q <= 16'(decode_inner); kx0_q <= 16'(decode_inner); state<=COORD;
        end else begin
          decode_index<=decode_index+1;
          if (decode_inner+1==32'(c.kernel_w)) begin decode_inner<=0;decode_outer<=decode_outer+1;end
          else decode_inner<=decode_inner+1;
        end
        COORD: begin
          coordinate_address_valid<=0;current_coordinate_valid<=0;
          coord_out_x<=32'(ox_q)*32'(c.stride_w);
          coord_out_y<=32'(oy_q)*32'(c.stride_h);
          coord_kernel_x<=32'(kx_q)*32'(c.dilation_w);
          coord_kernel_y<=32'(ky_q)*32'(c.dilation_h);
          state<=COORD_SUM;
        end
        COORD_SUM: begin
          coord_sum_x<={1'b0,coord_out_x}+{1'b0,coord_kernel_x};
          coord_sum_y<={1'b0,coord_out_y}+{1'b0,coord_kernel_y};
          state<=COORD_PAD;
        end
        COORD_PAD: begin
          current_coordinate_valid<=1;
          ix<=$signed(COORD_W'(coord_sum_x))-$signed(COORD_W'(c.pad_left));
          iy<=$signed(COORD_W'(coord_sum_y))-$signed(COORD_W'(c.pad_top));
          state<=ADDRESS;
        end
        ADDRESS: begin
          if (col_idx==0) begin
            row_coordinate_valid<=1;row_base_ix<=ix;row_base_iy<=iy;
          end
          if (q_current >= {1'b0,reduction_len} || ix<0 || iy<0 ||
              ix >= $signed(COORD_W'(c.input_w)) || iy >= $signed(COORD_W'(c.input_h))) begin
            pad_q<=1; state<=ZERO_STREAM;
          end else if (!geometry_tile || col_idx!=0 || (!pred_busy && !cache_hint_pending)) begin
            pixel_product <= 32'(iy[15:0]) * 32'(c.input_w);
            pad_q<=0; state<=ADDRESS_PIXEL;
          end
        end
        ADDRESS_PIXEL: begin
          pixel_index<=pixel_product+32'(ix);
          state<=ADDRESS_PRODUCT;
        end
        ADDRESS_PRODUCT: begin
          channel_product<=pixel_index*32'(c.input_c);
          state<=ADDRESS_BASE;
        end
        ADDRESS_BASE: begin
          group_base_addr<=c.input_base+((channel_product+32'(c.group_offset))<<c.input_s16);
          state<=ADDRESS_CHANNEL;
        end
        ADDRESS_CHANNEL: begin
          addr<=group_base_addr+(ch<<c.input_s16);
          tap_group_base<=group_base_addr;
          coordinate_address_valid<=1;
          if (col_idx==0) begin
            row_base_valid<=1;row_base_ix<=ix;row_base_iy<=iy;row_base_pixel<=pixel_index;
            row_base_addr<=group_base_addr+(ch<<c.input_s16);
            row_group_base<=group_base_addr;
          end
          state<=FETCH;
        end
        FETCH: begin
          if (word_valid && word_addr=={addr[31:2],2'b0}) state<=STREAM;
          else if (cache_req_ready) state<=WAIT_WORD;
        end
        IDLE, WAIT_WORD, STREAM, ZERO_STREAM: ;
        default: begin state<=IDLE; configured<=0; error<=1; end
      endcase
    end
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    if (SIZE<2 || (SIZE & (SIZE-1))!=0) $fatal(1,"SIZE must be a power of two >=2");
    if (LANES<1 || LANES>4) $fatal(1,"LANES must be in [1,4]");
  end
`endif
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n) begin
    if (wr_valid) begin
      assert (wr_mask!='0 && chunk_count!=0);
      assert (col_idx+TILE_COUNT_W'(chunk_count)<=cols_q && row_idx<rows_q);
    end
    if (cache_req_valid) begin
      assert (cache_req_addr>=c.input_base);
      assert ({1'b0,cache_req_addr} < {1'b0,c.input_base}+{1'b0,tensor_bytes});
    end
  end
`endif
endmodule
