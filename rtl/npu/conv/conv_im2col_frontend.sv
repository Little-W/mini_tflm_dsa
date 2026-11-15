// SPDX-License-Identifier: Apache-2.0
// Implicit im2col frontend. Does not change the PE array or allocate an expanded
// activation matrix in external memory. Feed tile descriptors from IA scheduling.
// Emits corrected signed-16 values to the existing IA tile RAM write interface.
module conv_im2col_frontend #(
  parameter int SIZE=16,
  parameter int SLOT_W=3,
  parameter int LANES=2,       // Two internal s16 values / cycle on a 32-bit path
  parameter int CACHE_SETS=32,
  parameter int CACHE_WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int CACHE_POLICY=2,
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
  output logic [31:0] stat_hits, stat_misses, stat_read_bytes,
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
  typedef enum logic [4:0] {IDLE, P_START, P_WAIT, Q_START, Q_WAIT,
    K_START, K_WAIT, COORD, ADDRESS, ADDRESS_CHANNEL, FETCH, WAIT_WORD, PACK, ZERO_PACK, SEND} st_t;
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
  logic [31:0] chunk_count, send_count;
  logic [31:0] word_available;
  logic [SLOT_W-1:0] slot_q;
  logic div_start, div_busy, div_done, div_zero;
  logic [31:0] div_num, div_den, div_quot, div_rem;
  logic cache_cfg_ready, cache_req_ready, cache_rsp_valid, cache_rsp_error;
  logic cache_req_valid, cache_rsp_ready;
  logic [31:0] cache_rsp_data;
  logic [31:0] selected_word;
  logic pred_cfg_eligible, pred_enabled, pred_busy, pred_done, pred_start;
  logic [31:0] pred_rank, group_q, groups_q;
  logic geometry_tile, line_hint_valid, cache_hint_pending;
  logic [31:0] line_hint_rank;
  

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
  assign cfg_ready = state==IDLE && cache_cfg_ready && !pred_busy && !cache_hint_pending;
  assign tile_ready = state==IDLE && configured && !error && !cfg_valid &&
                      !pred_busy && !cache_hint_pending;
  assign busy = state!=IDLE || pred_busy || cache_hint_pending;
  assign wr_valid = state==SEND;
  assign wr_slot = slot_q;
  assign wr_row = CW'(row_idx);
  assign wr_col = CW'(col_idx);

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

  assign cache_req_valid = state==FETCH && !(word_valid && word_addr=={addr[31:2],2'b0});
  assign cache_rsp_ready = state==WAIT_WORD;
  conv_read_cache #(.SETS(CACHE_SETS),.WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES),
    .CACHE_POLICY(CACHE_POLICY)) u_cache (
    .clk,.rst_n,
    .cfg_valid(cfg_valid && cfg_ready && cfg_ok),.cfg_ready(cache_cfg_ready),
    .cfg_base(cfg.input_base),.cfg_bytes(32'(cfg_input_bytes)),.cfg_bypass(cfg.bypass_cache),
    .cfg_geometry(pred_cfg_eligible),
    .req_valid(cache_req_valid),.req_ready(cache_req_ready),.req_addr(addr),
    .req_geometry(geometry_tile),.req_event_first(geometry_tile && addr[3:0]==0),
    .hint_valid(line_hint_valid),.hint_next(line_hint_rank),.hint_pending(cache_hint_pending),
    .rsp_valid(cache_rsp_valid),.rsp_ready(cache_rsp_ready),
    .rsp_data(cache_rsp_data),.rsp_error(cache_rsp_error),
    .stat_hits,.stat_misses,.stat_read_bytes,
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
    if (state==PACK && chunk_count > word_available) chunk_count = word_available;
    selected_word = word_buf >> (addr[1:0]*8);
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE; c<='0; configured<=0; error<=0; tile_done<=0; tile_error<=0;
      reduction_len<=0; position_count<=0; tensor_bytes<=0;
      p0<=0; q0<=0; tap0<=0; row_idx<=0; col_idx<=0; rows_q<=0; cols_q<=SIZE;
      ox<=0; oy<=0; ky<=0; kx<=0; ch<=0; ky0<=0; kx0<=0; ch0<=0;
      q_current<=0; ix<=0; iy<=0; pixel_index<=0; pad_q<=0; addr<=0;
      word_buf<=0; word_addr<=0; word_valid<=0; slot_q<=0; send_count<=0;
      group_q<=0;groups_q<=0;geometry_tile<=0;line_hint_valid<=0;line_hint_rank<=32'hffff_ffff;
      wr_mask<='0;
      for (int l=0;l<LANES;l++) wr_data[l]<=0;
    end else begin
      tile_done<=0; tile_error<=0;
      if (pred_done) begin line_hint_valid<=1;line_hint_rank<=pred_rank;end
      if (pred_start) line_hint_valid<=0;
      if (cfg_valid && cfg_ready) begin
        c<=cfg; configured<=cfg_ok; error<=!cfg_ok;
        word_valid<=0; reduction_len<=32'(cfg_red);
        position_count<=32'(cfg_positions); tensor_bytes<=32'(cfg_input_bytes);
        groups_q<=cfg_sched_groups;geometry_tile<=0;line_hint_valid<=0;
      end else case (state)
        IDLE: if (tile_valid && tile_ready) begin
          if (tile_rows==0 || 32'(tile_rows)>SIZE || 32'(tile_cols)>SIZE || tile_q0>=reduction_len ||
              ({1'b0,tile_p0}+33'(tile_rows) > {1'b0,position_count})) begin
            tile_error<=1; error<=1;
          end else begin
            p0<=tile_p0; q0<=tile_q0; q_current<={1'b0,tile_q0};
            rows_q<=32'(tile_rows); cols_q <= (tile_cols==0) ? 32'(SIZE) : 32'(tile_cols);
            row_idx<=0; col_idx<=0; slot_q<=tile_slot;
            group_q<=tile_group;
            geometry_tile<=pred_enabled && (tile_cols==0 || 32'(tile_cols)==SIZE) && tile_p0[3:0]==0 && tile_q0[3:0]==0 &&
                           tile_group<groups_q;
            state<=P_START;
          end
        end
        P_START: state<=P_WAIT;
        P_WAIT: if (div_done) begin oy<=div_quot; ox<=div_rem; state<=Q_START; end
        Q_START: state<=Q_WAIT;
        Q_WAIT: if (div_done) begin tap0<=div_quot; ch<=div_rem; ch0<=div_rem; state<=K_START; end
        K_START: state<=K_WAIT;
        K_WAIT: if (div_done) begin
          ky<=div_quot; ky0<=div_quot; kx<=div_rem; kx0<=div_rem; state<=COORD;
        end
        COORD: begin
          ix <= $signed(64'(ox)*64'(c.stride_w)) - $signed(64'(c.pad_left))
                + $signed(64'(kx)*64'(c.dilation_w));
          iy <= $signed(64'(oy)*64'(c.stride_h)) - $signed(64'(c.pad_top))
                + $signed(64'(ky)*64'(c.dilation_h));
          state<=ADDRESS;
        end
        ADDRESS: begin
          if (q_current >= {1'b0,reduction_len} || ix<0 || iy<0 ||
              ix >= $signed(64'(c.input_w)) || iy >= $signed(64'(c.input_h))) begin
            pad_q<=1; state<=ZERO_PACK;
          end else if (!geometry_tile || col_idx!=0 || (!pred_busy && !cache_hint_pending)) begin
            pixel_index <= 64'(iy)*64'(c.input_w)+64'(ix);
            pad_q<=0; state<=ADDRESS_CHANNEL;
          end
        end
        ADDRESS_CHANNEL: begin
          addr <= c.input_base + 32'((pixel_index*64'(c.input_c)
                  +64'(c.group_offset)+64'(ch)) << c.input_s16);
          state<=FETCH;
        end
        FETCH: begin
          if (word_valid && word_addr=={addr[31:2],2'b0}) state<=PACK;
          else if (cache_req_ready) state<=WAIT_WORD;
        end
        WAIT_WORD: if (cache_rsp_valid) begin
          if (cache_rsp_error) begin error<=1; tile_error<=1; state<=IDLE; end
          else begin
            word_buf<=cache_rsp_data; word_addr<={addr[31:2],2'b0}; word_valid<=1;
            state<=PACK;
          end
        end
        PACK, ZERO_PACK: begin
          send_count<=chunk_count;
          for (int l=0; l<LANES; l++) begin
            wr_mask[l]<=32'(l)<chunk_count;
            if (state==ZERO_PACK || 32'(l)>=chunk_count) wr_data[l]<=0;
            else if (c.input_s16)
              wr_data[l] <= $signed(16'(selected_word >> (l*16)));
            else
              wr_data[l] <= $signed({{8{selected_word[l*8+7]}},selected_word[l*8 +: 8]})
                            + c.input_offset;
          end
          state<=SEND;
        end
        SEND: if (wr_ready) begin
          if (col_idx+send_count==cols_q) begin
            if (row_idx+1==rows_q) begin tile_done<=1; state<=IDLE; end
            else begin
              row_idx<=row_idx+1; col_idx<=0; q_current<={1'b0,q0};
              ky<=ky0; kx<=kx0; ch<=ch0;
              if (ox+1==32'(c.output_w)) begin ox<=0; oy<=oy+1; end
              else ox<=ox+1;
              state<=COORD;
            end
          end else begin
            col_idx<=col_idx+send_count; q_current<=q_current+33'(send_count);
            if (q_current+33'(send_count) >= {1'b0,reduction_len}) state<=ZERO_PACK;
            else if (ch+send_count==32'(c.group_c)) begin
              ch<=0;
              if (kx+1==32'(c.kernel_w)) begin kx<=0; ky<=ky+1; end
              else kx<=kx+1;
              state<=COORD;
            end else begin
              ch<=ch+send_count;
              if (pad_q) state<=ZERO_PACK;
              else begin addr<=addr+(send_count<<c.input_s16); state<=FETCH; end
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
    if (LANES<1 || LANES>2) $fatal(1,"LANES is limited to 1 or 2 for this 32-bit implementation");
  end
`endif
`ifdef CONV_ASSERT
  always_ff @(posedge clk) if (rst_n) begin
    if (div_start) assert (!div_busy);
    if (div_done) assert (!div_zero);
    if (wr_valid) begin
      assert (wr_mask!='0 && send_count!=0);
      assert (col_idx+send_count<=cols_q && row_idx<rows_q);
    end
    if (cache_req_valid) begin
      assert (addr>=c.input_base);
      assert ({1'b0,addr} < {1'b0,c.input_base}+{1'b0,tensor_bytes});
    end
  end
`endif
endmodule
