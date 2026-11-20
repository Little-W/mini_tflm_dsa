// SPDX-License-Identifier: Apache-2.0
// Geometry-derived next whole-line event. Eligible lines are one pixel's
// aligned 16-channel s8 fragment; no per-pixel plan table or runtime division.
module conv_next_use_predictor (
  input logic clk, rst_n,
  input logic cfg_valid,
  input conv_im2col_pkg::conv_cfg_t cfg,
  input logic [31:0] cfg_r, cfg_groups,
  output logic cfg_eligible, cfg_busy,
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
  // 非零幂次直接由并行分组判断，结果与配置寄存器同时采样。
  logic [31:0] row_shape_i_value;
  logic row_shape_o_valid;
  assign row_shape_i_value = cfg_r;
  onehot_check #(.p_width(32), .p_allow_zero(1'b0)) u_row_shape (
    .i_value(row_shape_i_value),
    .o_valid(row_shape_o_valid)
  );
  logic [15:0] height_shape_i_value;
  logic height_shape_o_valid;
  assign height_shape_i_value = cfg.stride_h;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_height_shape (
    .i_value(height_shape_i_value),
    .o_valid(height_shape_o_valid)
  );
  logic [15:0] width_shape_i_value;
  logic width_shape_o_valid;
  assign width_shape_i_value = cfg.stride_w;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_width_shape (
    .i_value(width_shape_i_value),
    .o_valid(width_shape_o_valid)
  );
  logic [5:0] cfg_r_shift, cfg_h_shift, cfg_w_shift;
  logic [2:0] cfg_phase;
  logic cfg_basic_q;
  logic [31:0] cfg_points_q, cfg_taps_q, cfg_blocks_q;
  logic [31:0] block_rows_q;
  logic [16:0] cfg_qtiles_q;
  logic [3:0] cfg_multiply_phase;
  logic cfg_product_done;
  logic [31:0] cfg_factor_a, cfg_factor_b, cfg_factor_a_q, cfg_factor_b_q;
  logic [15:0] cfg_partial_a, cfg_partial_b;
  (* use_dsp="yes" *) logic [31:0] cfg_partial_product;
  logic [63:0] cfg_product_accumulator, cfg_product;
  wire cfg_product_start = cfg_phase>=1 && cfg_phase<=4 &&
      cfg_multiply_phase==0 && !cfg_product_done &&
      (cfg_phase!=1 || (cfg_basic_q && cfg_taps_q!=0 && cfg_taps_q<=25));
  logic [32:0] cfg_block_round;
  logic [32:0] cfg_round_sum, cfg_round_carry;
  logic [16:0] cfg_round_low, cfg_round_high_zero, cfg_round_high_one;
  logic unused_cfg_round_zero_carry, unused_cfg_round_one_carry;

  // 取整偏移先压缩为两个操作数，高位并行计算两种进位结果。
  assign cfg_round_sum = ~({1'b0, cfg_points_q} ^ {1'b0, block_rows_q});
  assign cfg_round_carry = {cfg_points_q | block_rows_q, 1'b0};
  assign cfg_round_low = {1'b0, cfg_round_sum[15:0]} + {1'b0, cfg_round_carry[15:0]};
  assign {unused_cfg_round_zero_carry, cfg_round_high_zero} =
    {1'b0, cfg_round_sum[32:16]} + {1'b0, cfg_round_carry[32:16]};
  assign {unused_cfg_round_one_carry, cfg_round_high_one} =
    {1'b0, cfg_round_sum[32:16]} + {1'b0, cfg_round_carry[32:16]} + 18'd1;
  assign cfg_block_round = {
    cfg_round_low[16] ? cfg_round_high_one : cfg_round_high_zero, cfg_round_low[15:0]};
  assign cfg_r_shift = log2_pow2(cfg_r);
  assign cfg_h_shift = log2_pow2({16'd0,cfg.stride_h});
  assign cfg_w_shift = log2_pow2({16'd0,cfg.stride_w});
  assign cfg_eligible = enabled;

  logic [15:0] kh_q, kw_q, oh_q, ow_q, cg_q, dh_q, dw_q, ph_q, pw_q;
  logic [5:0] block_shift_q, h_shift_q, w_shift_q;
  logic [31:0] groups_q, group_span_q, block_span_q;
  logic [31:0] y_limit_q, x_limit_q;
  logic [15:0] h_mask_q, w_mask_q;
  logic [32:0] y_pad_q, x_pad_q;
  logic [31:0] channel_q, current_pb_q, current_local_q, current_group_q;
  logic [15:0] ky_q, kx_q;
  logic [4:0] tap_index_q;
  logic issue_complete;
  logic [31:0] best_q;
  logic [6:0] pipe_valid, pipe_last;
  logic [31:0] mul_y_s0, mul_x_s0;
  logic [4:0] tap_s0, tap_s1;
  logic signed [33:0] ny_s0, nx_s0;
  logic [1:0][32:0] coordinate_pad;
  logic [1:0][31:0] coordinate_product;
  logic [1:0][33:0] coordinate_difference;
  logic [31:0] oy_s0, ox_s0;
  logic coordinate_good_s0, coordinate_good_s1;
  logic [15:0] oy_s1, ox_s1;
  logic [31:0] position_s2, reduction_s2;
  logic coordinate_good_s2, candidate_good_s3, candidate_good_s4, candidate_good_s5, candidate_good_s6;
  logic [31:0] block_s3, local_s3, block_s4, group_s4, local_s4, local_s5;
  logic [31:0] product_block_s5, product_group_s5;
  logic [31:0] rank_s6;
  logic [31:0] best_next;
  logic last_tap;

  always_comb begin
    cfg_factor_a = '0;
    cfg_factor_b = '0;
    case (cfg_phase)
      1: begin cfg_factor_a=32'(cfg_taps_q[4:0]); cfg_factor_b=32'(cg_q); end
      2: begin cfg_factor_a=32'(cfg_qtiles_q); cfg_factor_b=block_rows_q; end
      3: begin cfg_factor_a=groups_q; cfg_factor_b=group_span_q; end
      4: begin cfg_factor_a=cfg_blocks_q; cfg_factor_b=block_span_q; end
      default: begin end
    endcase
    cfg_partial_a = (cfg_multiply_phase==7 || cfg_multiply_phase==5) ?
        cfg_factor_a_q[31:16] : cfg_factor_a_q[15:0];
    cfg_partial_b = (cfg_multiply_phase==7 || cfg_multiply_phase==3) ?
        cfg_factor_b_q[31:16] : cfg_factor_b_q[15:0];
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cfg_multiply_phase <= '0;
      cfg_product_done <= 1'b0;
    end else if (cfg_valid) begin
      cfg_multiply_phase <= '0;
      cfg_product_done <= 1'b0;
    end else begin
      cfg_product_done <= 1'b0;
      if (cfg_product_start) begin
        cfg_factor_a_q <= cfg_factor_a;
        cfg_factor_b_q <= cfg_factor_b;
        cfg_multiply_phase <= 1;
      end else case (cfg_multiply_phase)
        1,3,5,7: begin
          cfg_partial_product <= cfg_partial_a * cfg_partial_b;
          cfg_multiply_phase <= cfg_multiply_phase + 1'b1;
        end
        2: begin
          cfg_product_accumulator <= {32'd0,cfg_partial_product};
          cfg_multiply_phase <= 3;
        end
        4,6: begin
          cfg_product_accumulator <= cfg_product_accumulator + {16'd0,cfg_partial_product,16'd0};
          cfg_multiply_phase <= cfg_multiply_phase + 1'b1;
        end
        8: begin
          cfg_product <= cfg_product_accumulator + {cfg_partial_product,32'd0};
          cfg_product_done <= 1'b1;
          cfg_multiply_phase <= 0;
        end
        default: begin end
      endcase
    end
  end

  // 高十八位的两种借位结果并行计算，低十六位只选择相应结果。
  assign coordinate_pad[0] = y_pad_q;
  assign coordinate_pad[1] = x_pad_q;
  assign coordinate_product[0] = mul_y_s0;
  assign coordinate_product[1] = mul_x_s0;
  for (genvar axis = 0; axis < 2; axis++) begin : g_coordinate_difference
    logic [16:0] low_difference;
    logic [17:0] high_without_borrow, high_with_borrow;

    assign low_difference = {1'b0, coordinate_pad[axis][15:0]} -
      {1'b0, coordinate_product[axis][15:0]};
    assign high_without_borrow = {1'b0, coordinate_pad[axis][32:16]} -
      {2'b0, coordinate_product[axis][31:16]};
    // 减去乘积和借位等价于相反次序的差值取反，只需一次十八位减法。
    assign high_with_borrow = ~({2'b0, coordinate_product[axis][31:16]} -
      {1'b0, coordinate_pad[axis][32:16]});
    assign coordinate_difference[axis] = {
      low_difference[16] ? high_with_borrow : high_without_borrow,
      low_difference[15:0]};
  end
  assign ny_s0 = $signed(coordinate_difference[0]);
  assign nx_s0 = $signed(coordinate_difference[1]);

  always_comb begin
    oy_s0 = 32'(ny_s0) >> h_shift_q;
    ox_s0 = 32'(nx_s0) >> w_shift_q;
    coordinate_good_s0 = ny_s0>=34'sd0 && nx_s0>=34'sd0 &&
      ($unsigned(ny_s0) & 34'(h_mask_q))==34'd0 &&
      ($unsigned(nx_s0) & 34'(w_mask_q))==34'd0 &&
      $unsigned(ny_s0)<34'(y_limit_q) && $unsigned(nx_s0)<34'(x_limit_q);
    last_tap = ky_q==kh_q-16'd1 && kx_q==kw_q-16'd1;
    // 候选比较与有效性判断并行，无效候选直接保留当前最早访问位置。
    best_next = candidate_good_s6 && rank_s6<best_q ? rank_s6 : best_q;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      enabled<=0;busy<=0;done<=0;next_rank<=INF;best_q<=INF;
      cfg_phase<=0;cfg_busy<=0;cfg_basic_q<=0;
      kh_q<=0;kw_q<=0;oh_q<=0;ow_q<=0;cg_q<=0;dh_q<=0;dw_q<=0;ph_q<=0;pw_q<=0;
      block_shift_q<=0;h_shift_q<=0;w_shift_q<=0;
      groups_q<=0;block_rows_q<=0;group_span_q<=0;block_span_q<=0;
      y_limit_q<=0;x_limit_q<=0;h_mask_q<=0;w_mask_q<=0;
      y_pad_q<=33'd0;x_pad_q<=33'd0;
      channel_q<=0;current_pb_q<=0;current_local_q<=0;current_group_q<=0;
      ky_q<=0;kx_q<=0;tap_index_q<=0;issue_complete<=0;pipe_valid<='0;pipe_last<='0;
    end else begin
      done<=0;
      if (cfg_valid) begin
        enabled<=0;busy<=0;next_rank<=INF;pipe_valid<='0;pipe_last<='0;
        // 配置忙标志与阶段同时更新，使用方直接读取寄存结果。
        cfg_phase<=1;cfg_busy<=1;
        cfg_basic_q<=!cfg.input_s16 && !cfg.bypass_cache &&
          cfg.input_base[3:0]==0 && cfg.input_c!=0 && cfg.input_c[3:0]==0 &&
          cfg.group_c!=0 && cfg.group_c[3:0]==0 && cfg.group_offset[3:0]==0 &&
          cfg.input_h!=0 && cfg.input_w!=0 && cfg.output_h!=0 && cfg.output_w!=0 &&
          row_shape_o_valid && cfg_r[31:28]==0 && cfg_groups!=0 &&
          height_shape_o_valid &&
          width_shape_o_valid &&
          cfg.dilation_h!=0 && cfg.dilation_w!=0;
        cfg_points_q<=32'(cfg.output_h)*32'(cfg.output_w);
        cfg_taps_q<=32'(cfg.kernel_h)*32'(cfg.kernel_w);
        kh_q<=cfg.kernel_h;kw_q<=cfg.kernel_w;oh_q<=cfg.output_h;ow_q<=cfg.output_w;
        cg_q<=cfg.group_c;dh_q<=cfg.dilation_h;dw_q<=cfg.dilation_w;
        ph_q<=cfg.pad_top;pw_q<=cfg.pad_left;
        block_shift_q<=cfg_r_shift+6'd4;h_shift_q<=cfg_h_shift;w_shift_q<=cfg_w_shift;
        groups_q<=cfg_groups;block_rows_q<=cfg_r<<4;
        y_limit_q<=32'(cfg.output_h)<<cfg_h_shift;x_limit_q<=32'(cfg.output_w)<<cfg_w_shift;
        h_mask_q<=cfg.stride_h-16'd1;w_mask_q<=cfg.stride_w-16'd1;
      end else if (cfg_phase!=0) begin
        if (cfg_phase==1 && (!cfg_basic_q || cfg_taps_q==0 || cfg_taps_q>25)) begin
          enabled<=1'b0;
          cfg_phase<=0;cfg_busy<=0;
        end else if (cfg_product_done) begin
          case (cfg_phase)
            1: begin
              cfg_qtiles_q<=cfg_product[20:4];
              cfg_blocks_q<=32'(cfg_block_round>>block_shift_q);
              cfg_phase<=2;
            end
            2: begin
              group_span_q<=cfg_product[31:0];
              cfg_phase<=cfg_product[63:32]!=0 ? 3'd0 : 3'd3;
              cfg_busy<=cfg_product[63:32]==0;
            end
            3: begin
              block_span_q<=cfg_product[31:0];
              cfg_phase<=cfg_product[63:32]!=0 ? 3'd0 : 3'd4;
              cfg_busy<=cfg_product[63:32]==0;
            end
            default: begin
              enabled<=cfg_product<64'hffff_ffff;
              cfg_phase<=0;cfg_busy<=0;
            end
          endcase
        end
      end else if (start && !busy) begin
        // 33位求和保留32位坐标加16位填充的进位，每次启动后保持至候选处理结束。
        y_pad_q <= {1'b0, input_y} + {17'd0, ph_q};
        x_pad_q <= {1'b0, input_x} + {17'd0, pw_q};
        channel_q<=channel;
        current_pb_q<=current_p>>block_shift_q;
        current_local_q<=((current_q>>4)<<block_shift_q) | (current_p & (block_rows_q-32'd1));
        current_group_q<=current_group;
        ky_q<=0;kx_q<=0;tap_index_q<=0;issue_complete<=0;best_q<=INF;
        pipe_valid<='0;pipe_last<='0;
        if (enabled) busy<=1;
        else begin done<=1;next_rank<=INF;end
      end else if (busy) begin
        pipe_valid <= {pipe_valid[5:0],!issue_complete};
        pipe_last <= {pipe_last[5:0],!issue_complete && last_tap};
        if (!issue_complete) begin
          mul_y_s0<=32'(ky_q)*32'(dh_q);mul_x_s0<=32'(kx_q)*32'(dw_q);
          tap_s0<=tap_index_q;tap_index_q<=tap_index_q+5'd1;
          if (last_tap) issue_complete<=1;
          else if (kx_q==kw_q-16'd1) begin kx_q<=0;ky_q<=ky_q+16'd1;end
          else kx_q<=kx_q+16'd1;
        end
        if (pipe_valid[0]) begin
          oy_s1<=oy_s0[15:0];ox_s1<=ox_s0[15:0];tap_s1<=tap_s0;
          coordinate_good_s1<=coordinate_good_s0;
        end
        if (pipe_valid[1]) begin
          position_s2<=32'(oy_s1)*32'(ow_q)+32'(ox_s1);
          reduction_s2<=32'(tap_s1)*32'(cg_q)+channel_q;
          coordinate_good_s2<=coordinate_good_s1;
        end
        if (pipe_valid[2]) begin
          block_s3<=position_s2>>block_shift_q;
          local_s3<=((reduction_s2>>4)<<block_shift_q) |
                    (position_s2 & (block_rows_q-32'd1));
          candidate_good_s3<=coordinate_good_s2;
        end
        if (pipe_valid[3]) begin : group_stage
          logic [31:0] candidate_group;
          candidate_group=0;
          if (block_s3==current_pb_q) begin
            candidate_group=current_group_q;
            if (local_s3<=current_local_q) candidate_group=candidate_group+32'd1;
          end
          block_s4<=block_s3;local_s4<=local_s3;group_s4<=candidate_group;
          candidate_good_s4<=candidate_good_s3 && block_s3>=current_pb_q &&
                             candidate_group<groups_q;
        end
        if (pipe_valid[4]) begin
          product_block_s5<=block_s4*block_span_q;
          product_group_s5<=group_s4*group_span_q;
          local_s5<=local_s4;candidate_good_s5<=candidate_good_s4;
        end
        if (pipe_valid[5]) begin
          rank_s6<=product_block_s5+product_group_s5+local_s5;
          candidate_good_s6<=candidate_good_s5;
        end
        if (pipe_valid[6]) begin
          best_q<=best_next;
          if (pipe_last[6]) begin busy<=0;done<=1;next_rank<=best_next;end
        end
      end
    end
  end
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n) begin
    if (start) begin
      assert (!busy);
      if (enabled) begin
        assert (channel[3:0]==0 && channel<32'(cg_q));
        assert (current_group<groups_q && current_q[3:0]==0);
      end
    end
    if (busy && pipe_valid[5] && candidate_good_s5)
      assert (64'(product_block_s5)+64'(product_group_s5)+64'(local_s5)<64'hffff_ffff);
  end
`endif
endmodule
