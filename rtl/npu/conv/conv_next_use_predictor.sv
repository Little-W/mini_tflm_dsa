// SPDX-License-Identifier: Apache-2.0
// Geometry-derived next whole-line event. Eligible lines are one pixel's
// aligned 16-channel s8 fragment; no per-pixel plan table or runtime division.
module conv_next_use_predictor (
  input logic clk, rst_n,
  input logic cfg_valid,
  input conv_im2col_pkg::conv_cfg_t cfg,
  input logic [31:0] cfg_r, cfg_groups,
  output logic cfg_eligible,
  output logic enabled,
  input logic start,
  input logic [31:0] input_y, input_x, channel,
  input logic [31:0] current_p, current_q, current_group,
  output logic busy, done,
  output logic [31:0] next_rank
);
  localparam logic [31:0] INF = 32'hffff_ffff;
  function automatic logic [5:0] log2_pow2(input logic [31:0] value);
    logic [5:0] result;
    result = 0;
    for (int bit_n=0; bit_n<32; bit_n++)
      if (value[bit_n]) result = 6'(bit_n);
    return result;
  endfunction
  logic [5:0] cfg_r_shift, cfg_h_shift, cfg_w_shift;
  logic [63:0] cfg_points, cfg_taps, cfg_qtiles, cfg_block_rows;
  logic [63:0] cfg_group_span, cfg_block_span, cfg_blocks, cfg_rank_limit;
  always_comb begin
    cfg_r_shift = log2_pow2(cfg_r);
    cfg_h_shift = log2_pow2({16'd0,cfg.stride_h});
    cfg_w_shift = log2_pow2({16'd0,cfg.stride_w});
    cfg_points = 64'(cfg.output_h) * 64'(cfg.output_w);
    cfg_taps = 64'(cfg.kernel_h) * 64'(cfg.kernel_w);
    cfg_qtiles = (cfg_taps * 64'(cfg.group_c)) >> 4;
    cfg_block_rows = 64'(cfg_r) << 4;
    cfg_group_span = cfg_qtiles * {32'd0,cfg_block_rows[31:0]};
    cfg_block_span = 64'(cfg_groups) * {32'd0,cfg_group_span[31:0]};
    cfg_blocks = (cfg_points + cfg_block_rows - 1) >> (cfg_r_shift + 6'd4);
    cfg_rank_limit = cfg_blocks * {32'd0,cfg_block_span[31:0]};
    cfg_eligible = !cfg.input_s16 && !cfg.bypass_cache &&
      cfg.input_base[3:0]==0 && cfg.input_c!=0 && cfg.input_c[3:0]==0 &&
      cfg.group_c!=0 && cfg.group_c[3:0]==0 && cfg.group_offset[3:0]==0 &&
      cfg.input_h!=0 && cfg.input_w!=0 && cfg.output_h!=0 && cfg.output_w!=0 &&
      cfg_r!=0 && (cfg_r & (cfg_r-32'd1))==0 && cfg_groups!=0 &&
      cfg.stride_h!=0 && (cfg.stride_h & (cfg.stride_h-16'd1))==0 &&
      cfg.stride_w!=0 && (cfg.stride_w & (cfg.stride_w-16'd1))==0 &&
      cfg.dilation_h!=0 && cfg.dilation_w!=0 && cfg_taps!=0 && cfg_taps<=25 &&
      cfg_block_rows<=64'hffff_ffff && cfg_group_span<=64'hffff_ffff &&
      cfg_block_span<=64'hffff_ffff && cfg_rank_limit<64'hffff_ffff;
  end

  logic [15:0] kh_q, kw_q, oh_q, ow_q, cg_q, dh_q, dw_q, ph_q, pw_q;
  logic [5:0] block_shift_q, h_shift_q, w_shift_q;
  logic [31:0] groups_q, block_rows_q, group_span_q, block_span_q;
  logic [31:0] y_q, x_q, channel_q, current_pb_q, current_local_q, current_group_q;
  logic [15:0] ky_q, kx_q;
  logic [31:0] best_q;
  logic signed [63:0] ny, nx;
  logic [63:0] oy, ox, candidate_p, candidate_q, candidate_pb;
  logic [63:0] candidate_local, candidate_group, candidate_rank_wide;
  logic candidate_valid, last_tap;
  logic [31:0] candidate_rank, best_next;
  always_comb begin
    ny = $signed({32'd0,y_q}) + $signed({48'd0,ph_q}) -
         $signed(64'(ky_q)*64'(dh_q));
    nx = $signed({32'd0,x_q}) + $signed({48'd0,pw_q}) -
         $signed(64'(kx_q)*64'(dw_q));
    oy = $unsigned(ny) >> h_shift_q;
    ox = $unsigned(nx) >> w_shift_q;
    candidate_p = oy * 64'(ow_q) + ox;
    candidate_q = (64'(ky_q)*64'(kw_q)+64'(kx_q))*64'(cg_q)+64'(channel_q);
    candidate_pb = candidate_p >> block_shift_q;
    candidate_local = (candidate_q >> 4)*64'(block_rows_q) +
                      (candidate_p & (64'(block_rows_q)-64'd1));
    candidate_group = 0;
    candidate_valid = ny>=0 && nx>=0 &&
      (($unsigned(ny) & ((64'd1 << h_shift_q)-64'd1))==0) &&
      (($unsigned(nx) & ((64'd1 << w_shift_q)-64'd1))==0) &&
      oy<64'(oh_q) && ox<64'(ow_q) && candidate_pb>=64'(current_pb_q);
    if (candidate_pb==64'(current_pb_q)) begin
      candidate_group = 64'(current_group_q);
      if (candidate_local<=64'(current_local_q)) candidate_group = candidate_group+64'd1;
    end
    if (candidate_group>=64'(groups_q)) candidate_valid = 0;
    candidate_rank_wide = candidate_pb*64'(block_span_q) +
                         candidate_group*64'(group_span_q) + candidate_local;
    candidate_rank = candidate_valid ? candidate_rank_wide[31:0] : INF;
    best_next = (candidate_rank<best_q) ? candidate_rank : best_q;
    last_tap = ky_q==kh_q-16'd1 && kx_q==kw_q-16'd1;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      enabled<=0; busy<=0; done<=0; next_rank<=INF; best_q<=INF;
      kh_q<=0;kw_q<=0;oh_q<=0;ow_q<=0;cg_q<=0;dh_q<=0;dw_q<=0;ph_q<=0;pw_q<=0;
      block_shift_q<=0;h_shift_q<=0;w_shift_q<=0;
      groups_q<=0;block_rows_q<=0;group_span_q<=0;block_span_q<=0;
      y_q<=0;x_q<=0;channel_q<=0;current_pb_q<=0;current_local_q<=0;current_group_q<=0;
      ky_q<=0;kx_q<=0;
    end else begin
      done<=0;
      if (cfg_valid) begin
        enabled<=cfg_eligible; busy<=0; next_rank<=INF;
        kh_q<=cfg.kernel_h;kw_q<=cfg.kernel_w;oh_q<=cfg.output_h;ow_q<=cfg.output_w;
        cg_q<=cfg.group_c;dh_q<=cfg.dilation_h;dw_q<=cfg.dilation_w;
        ph_q<=cfg.pad_top;pw_q<=cfg.pad_left;
        block_shift_q<=cfg_r_shift+6'd4;h_shift_q<=cfg_h_shift;w_shift_q<=cfg_w_shift;
        groups_q<=cfg_groups;block_rows_q<=cfg_block_rows[31:0];
        group_span_q<=cfg_group_span[31:0];block_span_q<=cfg_block_span[31:0];
      end else if (start && !busy) begin
        y_q<=input_y;x_q<=input_x;channel_q<=channel;
        current_pb_q<=current_p>>block_shift_q;
        current_local_q<=32'((64'(current_q>>4)*64'(block_rows_q))+
                             (64'(current_p) & (64'(block_rows_q)-64'd1)));
        current_group_q<=current_group;
        ky_q<=0;kx_q<=0;best_q<=INF;
        if (enabled) busy<=1;
        else begin done<=1;next_rank<=INF;end
      end else if (busy) begin
        best_q<=best_next;
        if (last_tap) begin busy<=0;done<=1;next_rank<=best_next;end
        else if (kx_q==kw_q-16'd1) begin kx_q<=0;ky_q<=ky_q+16'd1;end
        else kx_q<=kx_q+16'd1;
      end
    end
  end
`ifdef CONV_ASSERT
  always_ff @(posedge clk) if (rst_n) begin
    if (start) begin
      assert (!busy);
      if (enabled) begin
        assert (channel[3:0]==0 && channel<32'(cg_q));
        assert (current_group<groups_q && current_q[3:0]==0);
      end
    end
    if (busy && candidate_valid) assert (candidate_rank_wide<64'hffff_ffff);
  end
`endif
endmodule
