`default_nettype none

module vec_requant #(
    parameter int BUS_WIDTH = 32,
    parameter int VLEN         = 16,
    parameter int REG_WIDTH    = 32,
    parameter int MAX_IA_REUSE = 2,
    parameter int unsigned ENABLE_PER_CHANNEL = 1,
    parameter int unsigned ENABLE_IS_MODE = 1,
    parameter bit ENABLE_S16 = 1'b0,
    parameter int unsigned p_compute_lanes = VLEN,
    parameter int unsigned p_input_rows = VLEN * MAX_IA_REUSE
) (
    input wire logic clk,
    input wire logic rst_n,

    // 配置
    input wire logic               init_cfg,
    input wire logic               cfg_per_channel,
    input wire logic               cfg_dataflow_mode,
    input wire logic               cfg_s16 = 1'b0,
    input wire logic signed [31:0] activation_min_in,
    input wire logic signed [31:0] activation_max_in,
    input wire logic signed [31:0] dst_offset_in,
    // per-tensor 常量；per-channel 下这两个做为“基地址”使用
    input wire logic signed [31:0] multiplier_in,
    input wire logic signed [31:0] shift_in,
    input wire logic        [31:0] k,                  // 行数
    input wire logic        [31:0] m,                  // 列数
    input wire logic        [31:0] ia_reuse_num_in,    // 输出 tile 行复用顺序

    // 量化参数装载握手（外部可用；TB里通常 grant=req）
    output logic load_quant_req,
    input  wire logic load_quant_granted,
    output logic quant_params_valid,

    // Native DMA read client for per-channel quant parameters.
    output logic                        dma_start,
    output logic                        dma_is_write,
    output logic                        dma_linear_read_mode,
    output logic [REG_WIDTH-1:0]        dma_base_addr,
    output logic [REG_WIDTH-1:0]        dma_row_stride,
    output logic [REG_WIDTH-1:0]        dma_rows_to_read,
    output logic [7:0]                  dma_burst_len_m1,
    output logic                        dma_slot_id,
    output logic                        dma_use_16bits,
    output logic signed [REG_WIDTH-1:0] dma_lhs_zp,
    input  wire logic [BUS_WIDTH-1:0]        dma_raw_data,
    input  wire logic                        dma_raw_valid,

    // 组级预留在输入首行之前完成，分时运算在整组输出后恢复接收许可。
    input wire logic i_group_start = 1'b0,
    input wire logic [31:0] i_group_rows = 32'd0,
    output logic o_group_ready,

    // DW 与矩阵任务共用运算流水，任务期间配置保持稳定。
    input wire logic i_dw_enable = 1'b0,
    input wire logic i_dw_valid = 1'b0,
    output logic o_dw_ready,
    input wire logic i_dw_tag = 1'b0,
    input wire logic signed [31:0] i_dw_accumulator[VLEN] = '{default:32'sd0},
    input wire logic signed [31:0] i_dw_multiplier[VLEN] = '{default:32'sd0},
    input wire logic [5:0] i_dw_right[VLEN] = '{default:6'd0},
    input wire logic [VLEN-1:0] i_dw_mask = '0,
    input wire logic signed [31:0] i_dw_offset = 32'sd0,
    input wire logic signed [31:0] i_dw_minimum = -32'sd128,
    input wire logic signed [31:0] i_dw_maximum = 32'sd127,
    output logic o_dw_valid,
    output logic o_dw_tag,

    // 数据口
    input  wire logic               in_valid,
    input  wire logic               in_tile_done,
    input  wire logic signed [31:0] in_vec_s32[VLEN],
    output logic               out_valid,
    output logic               out_tile_done,
    output logic signed [ 7:0] out_vec_s8[VLEN],
    output logic signed [15:0] out_vec_s16[VLEN],
    output logic signed [31:0] quant_multiplier_lane[VLEN],
    output logic signed [31:0] quant_shift_lane[VLEN]
);

  generate
    if ((ENABLE_PER_CHANNEL == 0) && (ENABLE_IS_MODE == 0) && !ENABLE_S16 && (p_compute_lanes >= VLEN)) begin : g_tensor_ws
      assign o_group_ready = 1'b1;
      assign o_dw_ready = 1'b0;
      assign o_dw_valid = 1'b0;
      assign o_dw_tag = 1'b0;
      vec_requant_tensor_ws #(
          .BUS_WIDTH(BUS_WIDTH),
          .VLEN     (VLEN),
          .REG_WIDTH(REG_WIDTH)
      ) u_tensor_ws (
          .clk               (clk),
          .rst_n             (rst_n),
          .init_cfg          (init_cfg),
          .cfg_per_channel   (cfg_per_channel),
          .cfg_dataflow_mode (cfg_dataflow_mode),
          .activation_min_in (activation_min_in),
          .activation_max_in (activation_max_in),
          .dst_offset_in     (dst_offset_in),
          .multiplier_in     (multiplier_in),
          .shift_in          (shift_in),
          .k                 (k),
          .m                 (m),
          .ia_reuse_num_in   (ia_reuse_num_in),
          .load_quant_req    (load_quant_req),
          .load_quant_granted(load_quant_granted),
          .quant_params_valid(quant_params_valid),
          .dma_start         (dma_start),
          .dma_is_write      (dma_is_write),
          .dma_linear_read_mode(dma_linear_read_mode),
          .dma_base_addr     (dma_base_addr),
          .dma_row_stride    (dma_row_stride),
          .dma_rows_to_read  (dma_rows_to_read),
          .dma_burst_len_m1  (dma_burst_len_m1),
          .dma_slot_id       (dma_slot_id),
          .dma_use_16bits    (dma_use_16bits),
          .dma_lhs_zp        (dma_lhs_zp),
          .dma_raw_data      (dma_raw_data),
          .dma_raw_valid     (dma_raw_valid),
          .in_valid          (in_valid),
          .in_tile_done      (in_tile_done),
          .in_vec_s32        (in_vec_s32),
          .out_valid         (out_valid),
          .out_tile_done     (out_tile_done),
          .out_vec_s8        (out_vec_s8)
      );
      for (genvar lane = 0; lane < VLEN; lane++) begin : gen_tensor_quant
        assign out_vec_s16[lane] = '0;
        assign quant_multiplier_lane[lane] = multiplier_in;
        assign quant_shift_lane[lane] = shift_in;
      end
    end else begin : g_full
      vec_requant_full #(
          .BUS_WIDTH(BUS_WIDTH),
          .VLEN              (VLEN),
          .REG_WIDTH         (REG_WIDTH),
          .MAX_IA_REUSE      (MAX_IA_REUSE),
          .ENABLE_PER_CHANNEL(ENABLE_PER_CHANNEL),
          .ENABLE_IS_MODE    (ENABLE_IS_MODE),
          .ENABLE_S16        (ENABLE_S16),
          .p_compute_lanes   (p_compute_lanes),
          .p_input_rows      (p_input_rows)
      ) u_full (
          .i_dw_enable(i_dw_enable), .i_dw_valid(i_dw_valid), .o_dw_ready(o_dw_ready),
          .i_dw_tag(i_dw_tag), .i_dw_accumulator(i_dw_accumulator),
          .i_dw_multiplier(i_dw_multiplier), .i_dw_right(i_dw_right), .i_dw_mask(i_dw_mask),
          .i_dw_offset(i_dw_offset), .i_dw_minimum(i_dw_minimum), .i_dw_maximum(i_dw_maximum),
          .o_dw_valid(o_dw_valid), .o_dw_tag(o_dw_tag),
          .i_group_start(i_group_start),
          .i_group_rows(i_group_rows),
          .o_group_ready(o_group_ready),
          .clk               (clk),
          .rst_n             (rst_n),
          .init_cfg          (init_cfg),
          .cfg_per_channel   (cfg_per_channel),
          .cfg_dataflow_mode (cfg_dataflow_mode),
          .cfg_s16           (cfg_s16),
          .activation_min_in (activation_min_in),
          .activation_max_in (activation_max_in),
          .dst_offset_in     (dst_offset_in),
          .multiplier_in     (multiplier_in),
          .shift_in          (shift_in),
          .k                 (k),
          .m                 (m),
          .ia_reuse_num_in   (ia_reuse_num_in),
          .load_quant_req    (load_quant_req),
          .load_quant_granted(load_quant_granted),
          .quant_params_valid(quant_params_valid),
          .dma_start         (dma_start),
          .dma_is_write      (dma_is_write),
          .dma_linear_read_mode(dma_linear_read_mode),
          .dma_base_addr     (dma_base_addr),
          .dma_row_stride    (dma_row_stride),
          .dma_rows_to_read  (dma_rows_to_read),
          .dma_burst_len_m1  (dma_burst_len_m1),
          .dma_slot_id       (dma_slot_id),
          .dma_use_16bits    (dma_use_16bits),
          .dma_lhs_zp        (dma_lhs_zp),
          .dma_raw_data      (dma_raw_data),
          .dma_raw_valid     (dma_raw_valid),
          .in_valid          (in_valid),
          .in_tile_done      (in_tile_done),
          .in_vec_s32        (in_vec_s32),
          .out_valid         (out_valid),
          .out_tile_done     (out_tile_done),
          .out_vec_s8        (out_vec_s8),
          .out_vec_s16       (out_vec_s16),
          .quant_multiplier_lane(quant_multiplier_lane),
          .quant_shift_lane(quant_shift_lane)
      );
    end
  endgenerate

endmodule

module vec_requant_tensor_ws #(
    parameter int BUS_WIDTH = 32,
    parameter int VLEN      = 16,
    parameter int REG_WIDTH = 32
) (
    input wire logic clk,
    input wire logic rst_n,

    input wire logic               init_cfg,
    input wire logic               cfg_per_channel,
    input wire logic               cfg_dataflow_mode,
    input wire logic signed [31:0] activation_min_in,
    input wire logic signed [31:0] activation_max_in,
    input wire logic signed [31:0] dst_offset_in,
    input wire logic signed [31:0] multiplier_in,
    input wire logic signed [31:0] shift_in,
    input wire logic        [31:0] k,
    input wire logic        [31:0] m,
    input wire logic        [31:0] ia_reuse_num_in,

    output logic load_quant_req,
    input  wire logic load_quant_granted,
    output logic quant_params_valid,

    output logic                        dma_start,
    output logic                        dma_is_write,
    output logic                        dma_linear_read_mode,
    output logic [REG_WIDTH-1:0]        dma_base_addr,
    output logic [REG_WIDTH-1:0]        dma_row_stride,
    output logic [REG_WIDTH-1:0]        dma_rows_to_read,
    output logic [7:0]                  dma_burst_len_m1,
    output logic                        dma_slot_id,
    output logic                        dma_use_16bits,
    output logic signed [REG_WIDTH-1:0] dma_lhs_zp,
    input  wire logic [BUS_WIDTH-1:0]        dma_raw_data,
    input  wire logic                        dma_raw_valid,

    input  wire logic               in_valid,
    input  wire logic               in_tile_done,
    input  wire logic signed [31:0] in_vec_s32[VLEN],
    output logic               out_valid,
    output logic               out_tile_done,
    output logic signed [ 7:0] out_vec_s8[VLEN]
);

  function automatic logic signed [63:0] round_shift_even(
      input logic signed [63:0] value, input integer amount);
    logic signed [63:0] quotient;
    logic [63:0] remainder, mask, half;
    begin
      if (amount <= 0) begin
        round_shift_even = value;
      end else if (amount > 63) begin
        round_shift_even = 64'sd0;
      end else begin
        quotient = value >>> amount;
        mask = 64'hffffffffffffffff >> (64 - amount);
        remainder = $unsigned(value) & mask;
        half = 64'd1 << (amount - 1);
        round_shift_even = quotient + 64'((remainder > half) ||
            ((remainder == half) && quotient[0]));
      end
    end
  endfunction

  localparam int VLEN_SHIFT = $clog2(VLEN);
  localparam int VLEN_CNT_W = (VLEN <= 1) ? 1 : $clog2(VLEN + 1);
  localparam int TILE_CNT_W = (REG_WIDTH < 16) ? REG_WIDTH : 16;

  typedef logic [TILE_CNT_W-1:0] tile_idx_t;

  logic signed [31:0] pt_multiplier_r;
  logic [5:0]         pt_lshift_r;
  logic [5:0]         pt_rshift_r;
  logic signed [31:0] activation_min_r;
  logic signed [31:0] activation_max_r;
  logic signed [31:0] dst_offset_r;
  logic [31:0]        k_r;
  logic [31:0]        m_r;
  logic [31:0]        ia_reuse_num_r;
  tile_idx_t          ia_reuse_mask_tile_r;
  tile_idx_t          tile_row;
  tile_idx_t          tile_col;
  tile_idx_t          last_row_tile;
  tile_idx_t          last_col_tile;

  logic signed [31:0] pt_shift_abs_next;
  logic [5:0]         pt_lshift_next;
  logic [5:0]         pt_rshift_next;
  tile_idx_t          num_row_tiles_next;
  tile_idx_t          num_col_tiles_next;

  logic [31:0] lane_start_cur;
  logic [31:0] lane_remaining_cur;
  logic [31:0] lane_need_cur;
  tile_idx_t   reuse_group_base_row;
  tile_idx_t   row_offset_in_group;
  tile_idx_t   tile_row_inc;
  tile_idx_t   tile_col_inc;
  tile_idx_t   next_tile_row_cur;
  tile_idx_t   next_tile_col_cur;
  logic        cur_last_row_tile;
  logic        cur_last_col_tile;
  logic        cur_last_row_in_group;

  logic stage0_valid;
  logic stage1_valid;
  logic stage2_valid;
  logic stage3_valid;
  logic stage4_valid;
  logic stage5_valid;
  logic stage6_valid;
  logic stage7_valid;
  logic stage8_valid;
  logic stage9_valid;
  logic stage10_valid;
  logic stage11_valid;
  logic stage0_tile_done;
  logic stage1_tile_done;
  logic stage2_tile_done;
  logic stage3_tile_done;
  logic stage4_tile_done;
  logic stage5_tile_done;
  logic stage6_tile_done;
  logic stage7_tile_done;
  logic stage8_tile_done;
  logic stage9_tile_done;
  logic stage10_tile_done;
  logic stage11_tile_done;

  logic signed [31:0] mult_s0;
  logic signed [31:0] mult_s1;
  logic [5:0]         lshift_s0;
  logic [5:0]         lshift_s1;
  logic [5:0]         lshift_s2;
  logic [5:0]         lshift_s3;
  logic [5:0]         lshift_s4;
  logic [5:0]         lshift_s5;
  logic [5:0]         rshift_s0;
  logic [5:0]         rshift_s1;
  logic [5:0]         rshift_s2;
  logic [5:0]         rshift_s3;
  logic [5:0]         rshift_s4;
  logic [5:0]         rshift_s5;

  assign load_quant_req       = 1'b0;
  assign dma_start            = 1'b0;
  assign dma_is_write         = 1'b0;
  assign dma_linear_read_mode = 1'b0;
  assign dma_base_addr        = '0;
  assign dma_row_stride       = REG_WIDTH'(REG_WIDTH / 8);
  assign dma_rows_to_read     = REG_WIDTH'(1);
  assign dma_burst_len_m1     = 8'd0;
  assign dma_slot_id          = 1'b0;
  assign dma_use_16bits       = 1'b0;
  assign dma_lhs_zp           = '0;
  assign out_valid            = stage11_valid;
  assign out_tile_done        = stage11_tile_done;

  always_comb begin
    pt_shift_abs_next = -shift_in;
    pt_lshift_next = 6'd0;
    pt_rshift_next = 6'd0;
    if (shift_in > 32'sd0) begin
      pt_lshift_next = shift_in[5:0];
    end else if (shift_in < 32'sd0) begin
      pt_rshift_next = (pt_shift_abs_next > 32'sd63) ? 6'd63 : pt_shift_abs_next[5:0];
    end
  end

  assign num_row_tiles_next = (k == 0) ? '0 : tile_idx_t'((k + VLEN - 1) >> VLEN_SHIFT);
  assign num_col_tiles_next = (m == 0) ? '0 : tile_idx_t'((m + VLEN - 1) >> VLEN_SHIFT);

  always_comb begin
    lane_start_cur = REG_WIDTH'(tile_col) << VLEN_SHIFT;
    lane_remaining_cur = (m_r > lane_start_cur) ? (m_r - lane_start_cur) : 32'd0;
    lane_need_cur = (lane_remaining_cur >= REG_WIDTH'(VLEN))
                  ? REG_WIDTH'(VLEN)
                  : lane_remaining_cur;

    reuse_group_base_row = tile_row & ~ia_reuse_mask_tile_r;
    row_offset_in_group = tile_row & ia_reuse_mask_tile_r;
    tile_row_inc = tile_row + tile_idx_t'(1);
    tile_col_inc = tile_col + tile_idx_t'(1);
    cur_last_row_tile = (tile_row == last_row_tile);
    cur_last_col_tile = (tile_col == last_col_tile);
    cur_last_row_in_group = cur_last_row_tile ||
                            (row_offset_in_group == ia_reuse_mask_tile_r);

    if (!cur_last_row_in_group) begin
      next_tile_row_cur = tile_row_inc;
      next_tile_col_cur = tile_col;
    end else if (!cur_last_col_tile) begin
      next_tile_row_cur = reuse_group_base_row;
      next_tile_col_cur = tile_col_inc;
    end else if (!cur_last_row_tile) begin
      next_tile_row_cur = reuse_group_base_row + tile_idx_t'(ia_reuse_num_r);
      next_tile_col_cur = '0;
    end else begin
      next_tile_row_cur = '0;
      next_tile_col_cur = '0;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      pt_multiplier_r      <= '0;
      pt_lshift_r          <= 6'd0;
      pt_rshift_r          <= 6'd0;
      activation_min_r     <= '0;
      activation_max_r     <= '0;
      dst_offset_r         <= '0;
      k_r                  <= '0;
      m_r                  <= '0;
      ia_reuse_num_r       <= 32'd1;
      ia_reuse_mask_tile_r <= '0;
      tile_row             <= '0;
      tile_col             <= '0;
      last_row_tile        <= '0;
      last_col_tile        <= '0;
      quant_params_valid   <= 1'b0;
    end else if (init_cfg) begin
      pt_multiplier_r      <= multiplier_in;
      pt_lshift_r          <= pt_lshift_next;
      pt_rshift_r          <= pt_rshift_next;
      activation_min_r     <= activation_min_in;
      activation_max_r     <= activation_max_in;
      dst_offset_r         <= dst_offset_in;
      k_r                  <= k;
      m_r                  <= m;
      ia_reuse_num_r       <= (ia_reuse_num_in == 32'd0) ? 32'd1 : ia_reuse_num_in;
      ia_reuse_mask_tile_r <= (ia_reuse_num_in <= 32'd1) ? '0 : tile_idx_t'(ia_reuse_num_in - 32'd1);
      tile_row             <= '0;
      tile_col             <= '0;
      last_row_tile        <= (num_row_tiles_next == '0) ? '0 : (num_row_tiles_next - tile_idx_t'(1));
      last_col_tile        <= (num_col_tiles_next == '0) ? '0 : (num_col_tiles_next - tile_idx_t'(1));
      quant_params_valid   <= 1'b1;
    end else if (in_valid && in_tile_done) begin
      tile_row <= next_tile_row_cur;
      tile_col <= next_tile_col_cur;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      stage0_valid      <= 1'b0;
      stage1_valid      <= 1'b0;
      stage2_valid      <= 1'b0;
      stage3_valid      <= 1'b0;
      stage4_valid      <= 1'b0;
      stage5_valid      <= 1'b0;
      stage6_valid      <= 1'b0;
      stage7_valid      <= 1'b0;
      stage8_valid      <= 1'b0;
      stage9_valid      <= 1'b0;
      stage10_valid     <= 1'b0;
      stage11_valid     <= 1'b0;
      stage0_tile_done  <= 1'b0;
      stage1_tile_done  <= 1'b0;
      stage2_tile_done  <= 1'b0;
      stage3_tile_done  <= 1'b0;
      stage4_tile_done  <= 1'b0;
      stage5_tile_done  <= 1'b0;
      stage6_tile_done  <= 1'b0;
      stage7_tile_done  <= 1'b0;
      stage8_tile_done  <= 1'b0;
      stage9_tile_done  <= 1'b0;
      stage10_tile_done <= 1'b0;
      stage11_tile_done <= 1'b0;
    end else if (init_cfg) begin
      stage0_valid      <= 1'b0;
      stage1_valid      <= 1'b0;
      stage2_valid      <= 1'b0;
      stage3_valid      <= 1'b0;
      stage4_valid      <= 1'b0;
      stage5_valid      <= 1'b0;
      stage6_valid      <= 1'b0;
      stage7_valid      <= 1'b0;
      stage8_valid      <= 1'b0;
      stage9_valid      <= 1'b0;
      stage10_valid     <= 1'b0;
      stage11_valid     <= 1'b0;
      stage0_tile_done  <= 1'b0;
      stage1_tile_done  <= 1'b0;
      stage2_tile_done  <= 1'b0;
      stage3_tile_done  <= 1'b0;
      stage4_tile_done  <= 1'b0;
      stage5_tile_done  <= 1'b0;
      stage6_tile_done  <= 1'b0;
      stage7_tile_done  <= 1'b0;
      stage8_tile_done  <= 1'b0;
      stage9_tile_done  <= 1'b0;
      stage10_tile_done <= 1'b0;
      stage11_tile_done <= 1'b0;
    end else begin
      stage0_valid      <= in_valid;
      stage1_valid      <= stage0_valid;
      stage2_valid      <= stage1_valid;
      stage3_valid      <= stage2_valid;
      stage4_valid      <= stage3_valid;
      stage5_valid      <= stage4_valid;
      stage6_valid      <= stage5_valid;
      stage7_valid      <= stage6_valid;
      stage8_valid      <= stage7_valid;
      stage9_valid      <= stage8_valid;
      stage10_valid     <= stage9_valid;
      stage11_valid     <= stage10_valid;
      stage0_tile_done  <= in_valid && in_tile_done;
      stage1_tile_done  <= stage0_tile_done;
      stage2_tile_done  <= stage1_tile_done;
      stage3_tile_done  <= stage2_tile_done;
      stage4_tile_done  <= stage3_tile_done;
      stage5_tile_done  <= stage4_tile_done;
      stage6_tile_done  <= stage5_tile_done;
      stage7_tile_done  <= stage6_tile_done;
      stage8_tile_done  <= stage7_tile_done;
      stage9_tile_done  <= stage8_tile_done;
      stage10_tile_done <= stage9_tile_done;
      stage11_tile_done <= stage10_tile_done;
    end
  end

  always_ff @(posedge clk) begin
    if (init_cfg) begin
      mult_s0   <= '0;
      mult_s1   <= '0;
      lshift_s0 <= 6'd0;
      lshift_s1 <= 6'd0;
      lshift_s2 <= 6'd0;
      lshift_s3 <= 6'd0;
      lshift_s4 <= 6'd0;
      lshift_s5 <= 6'd0;
      rshift_s0 <= 6'd0;
      rshift_s1 <= 6'd0;
      rshift_s2 <= 6'd0;
      rshift_s3 <= 6'd0;
      rshift_s4 <= 6'd0;
      rshift_s5 <= 6'd0;
    end else begin
      mult_s0   <= pt_multiplier_r;
      mult_s1   <= mult_s0;
      lshift_s0 <= pt_lshift_r;
      lshift_s1 <= lshift_s0;
      lshift_s2 <= lshift_s1;
      lshift_s3 <= lshift_s2;
      lshift_s4 <= lshift_s3;
      lshift_s5 <= lshift_s4;
      rshift_s0 <= pt_rshift_r;
      rshift_s1 <= rshift_s0;
      rshift_s2 <= rshift_s1;
      rshift_s3 <= rshift_s2;
      rshift_s4 <= rshift_s3;
      rshift_s5 <= rshift_s4;
    end
  end

  genvar j;
  generate
    for (j = 0; j < VLEN; j++) begin : LANE
      logic signed [31:0] acc_s0;
      logic signed [31:0] acc_s1;
      (* use_dsp = "yes" *) logic signed [63:0] prod_s2;
      logic signed [63:0] prod_s3;
      logic signed [63:0] prod_s4;
      logic signed [63:0] prod_s5;
      logic signed [63:0] product_s6;
      integer round_shift_s6;
      logic signed [63:0] rounded_s7;
      logic signed [63:0] rounded_s8;
      logic signed [63:0] rounded_s9;
      logic signed [63:0] rounded_s10;
      logic               lane_en_s0;
      logic               lane_en_s1;
      logic               lane_en_s2;
      logic               lane_en_s3;
      logic               lane_en_s4;
      logic               lane_en_s5;
      logic               lane_en_s6;
      logic               lane_en_s7;
      logic               lane_en_s8;
      logic               lane_en_s9;
      logic               lane_en_s10;

      always_ff @(posedge clk) begin
        if (!rst_n) begin
          lane_en_s0    <= 1'b0;
          lane_en_s1    <= 1'b0;
          lane_en_s2    <= 1'b0;
          lane_en_s3    <= 1'b0;
          lane_en_s4    <= 1'b0;
          lane_en_s5    <= 1'b0;
          lane_en_s6    <= 1'b0;
          lane_en_s7    <= 1'b0;
          lane_en_s8    <= 1'b0;
          lane_en_s9    <= 1'b0;
          lane_en_s10   <= 1'b0;
          out_vec_s8[j] <= '0;
        end else if (init_cfg) begin
          lane_en_s0    <= 1'b0;
          lane_en_s1    <= 1'b0;
          lane_en_s2    <= 1'b0;
          lane_en_s3    <= 1'b0;
          lane_en_s4    <= 1'b0;
          lane_en_s5    <= 1'b0;
          lane_en_s6    <= 1'b0;
          lane_en_s7    <= 1'b0;
          lane_en_s8    <= 1'b0;
          lane_en_s9    <= 1'b0;
          lane_en_s10   <= 1'b0;
          out_vec_s8[j] <= '0;
        end else begin
          lane_en_s0  <= in_valid && (j < lane_need_cur);
          lane_en_s1  <= lane_en_s0;
          lane_en_s2  <= lane_en_s1;
          lane_en_s3  <= lane_en_s2;
          lane_en_s4  <= lane_en_s3;
          lane_en_s5  <= lane_en_s4;
          lane_en_s6  <= lane_en_s5;
          lane_en_s7  <= lane_en_s6;
          lane_en_s8  <= lane_en_s7;
          lane_en_s9  <= lane_en_s8;
          lane_en_s10 <= lane_en_s9;

          if (!lane_en_s10) begin
            out_vec_s8[j] <= 8'sd0;
          end else if (rounded_s10 < $signed({{4{activation_min_r[31]}},activation_min_r})) begin
            out_vec_s8[j] <= activation_min_r[7:0];
          end else if (rounded_s10 > $signed({{4{activation_max_r[31]}},activation_max_r})) begin
            out_vec_s8[j] <= activation_max_r[7:0];
          end else if (rounded_s10 > 36'sd127) begin
            out_vec_s8[j] <= 8'sd127;
          end else if (rounded_s10 < -36'sd128) begin
            out_vec_s8[j] <= -8'sd128;
          end else begin
            out_vec_s8[j] <= rounded_s10[7:0];
          end
        end
      end

      always_ff @(posedge clk) begin
        if (!init_cfg) begin
          acc_s0 <= in_vec_s32[j];
          acc_s1 <= acc_s0;
          prod_s2 <= acc_s1 * mult_s1;
          prod_s3 <= prod_s2;
          prod_s4 <= prod_s3;
          prod_s5 <= prod_s4;
          product_s6 <= prod_s5;
          round_shift_s6 <= 31 + integer'(rshift_s5) - integer'(lshift_s5);
          rounded_s7 <= round_shift_even(product_s6, round_shift_s6);
          rounded_s8 <= rounded_s7;
          rounded_s9 <= rounded_s8;
          rounded_s10 <= rounded_s9 + {{32{dst_offset_r[31]}}, dst_offset_r};
        end
      end
    end
  endgenerate

endmodule

module vec_requant_full #(
    parameter int BUS_WIDTH = 32,
    parameter int VLEN         = 16,
    parameter int REG_WIDTH    = 32,
    parameter int MAX_IA_REUSE = 2,
    parameter int unsigned ENABLE_PER_CHANNEL = 1,
    parameter int unsigned ENABLE_IS_MODE = 1,
    parameter bit ENABLE_S16 = 1'b0,
    parameter int unsigned p_compute_lanes = VLEN,
    parameter int unsigned p_input_rows = VLEN * MAX_IA_REUSE
) (
    input wire logic clk,
    input wire logic rst_n,

    // 配置
    input wire logic               init_cfg,
    input wire logic               cfg_per_channel,
    input wire logic               cfg_dataflow_mode,
    input wire logic               cfg_s16 = 1'b0,
    input wire logic signed [31:0] activation_min_in,
    input wire logic signed [31:0] activation_max_in,
    input wire logic signed [31:0] dst_offset_in,
    // per-tensor 常量；per-channel 下这两个做为“基地址”使用
    input wire logic signed [31:0] multiplier_in,
    input wire logic signed [31:0] shift_in,
    input wire logic        [31:0] k,                  // 行数
    input wire logic        [31:0] m,                  // 列数
    input wire logic        [31:0] ia_reuse_num_in,    // 输出 tile 行复用顺序

    // 量化参数装载握手（外部可用；TB里通常 grant=req）
    output logic load_quant_req,
    input  wire logic load_quant_granted,
    output logic quant_params_valid,

    // Native DMA read client for per-channel quant parameters.
    output logic                        dma_start,
    output logic                        dma_is_write,
    output logic                        dma_linear_read_mode,
    output logic [REG_WIDTH-1:0]        dma_base_addr,
    output logic [REG_WIDTH-1:0]        dma_row_stride,
    output logic [REG_WIDTH-1:0]        dma_rows_to_read,
    output logic [7:0]                  dma_burst_len_m1,
    output logic                        dma_slot_id,
    output logic                        dma_use_16bits,
    output logic signed [REG_WIDTH-1:0] dma_lhs_zp,
    input  wire logic [BUS_WIDTH-1:0]        dma_raw_data,
    input  wire logic                        dma_raw_valid,

    // 组级预留在输入首行之前完成，分时运算在整组输出后恢复接收许可。
    input wire logic i_group_start = 1'b0,
    input wire logic [31:0] i_group_rows = 32'd0,
    output logic o_group_ready,

    // DW 输入在原有输入寄存器采样，输出标签随有效信号传播。
    input wire logic i_dw_enable = 1'b0,
    input wire logic i_dw_valid = 1'b0,
    output logic o_dw_ready,
    input wire logic i_dw_tag = 1'b0,
    input wire logic signed [31:0] i_dw_accumulator[VLEN] = '{default:32'sd0},
    input wire logic signed [31:0] i_dw_multiplier[VLEN] = '{default:32'sd0},
    input wire logic [5:0] i_dw_right[VLEN] = '{default:6'd0},
    input wire logic [VLEN-1:0] i_dw_mask = '0,
    input wire logic signed [31:0] i_dw_offset = 32'sd0,
    input wire logic signed [31:0] i_dw_minimum = -32'sd128,
    input wire logic signed [31:0] i_dw_maximum = 32'sd127,
    output logic o_dw_valid,
    output logic o_dw_tag,

    // 数据口
    input  wire logic               in_valid,
    input  wire logic               in_tile_done,
    input  wire logic signed [31:0] in_vec_s32[VLEN],
    output logic               out_valid,
    output logic               out_tile_done,
    output logic signed [ 7:0] out_vec_s8[VLEN],
    output logic signed [15:0] out_vec_s16[VLEN],
    output logic signed [31:0] quant_multiplier_lane[VLEN],
    output logic signed [31:0] quant_shift_lane[VLEN]
);

  // ----------------------------
  // 常量与类型
  // ----------------------------

  // INT16 乘数采用最近偶数舍入，两个字节并行递增并保留正向饱和。
  function automatic logic signed [31:0] prepare_multiplier(
      input logic signed [31:0] value, input logic use_s16);
    logic round_increment, high_increment;
    logic [15:0] rounded;
    logic unused_low_carry, unused_high_carry;
    begin
      round_increment = value[15] && ((|value[14:0]) || value[16]);
      high_increment = value[15] && (&value[23:16]);
      {unused_low_carry, rounded[7:0]} = {1'b0, value[23:16]} + 9'(round_increment);
      {unused_high_carry, rounded[15:8]} = {1'b0, value[31:24]} + 9'(high_increment);
      prepare_multiplier = (ENABLE_S16 && use_s16) ?
          ((value[31:16] == 16'h7fff) ? 32'sd32767 : 32'($signed(rounded))) : value;
    end
  endfunction

  // 两种输出精度共用六位模减法，范围判断保留各自的边界处理。
  function automatic logic [6:0] prepare_amount(
      input logic signed [31:0] value, input logic use_s16);
    logic [5:0] amount_base, amount_difference;
    logic unused_borrow;
    begin
      amount_base = (ENABLE_S16 && use_s16) ? 6'd15 : 6'd31;
      {unused_borrow, amount_difference} = {1'b0, amount_base} - {1'b0, value[5:0]};
      if (ENABLE_S16 && use_s16) begin
        if (value >= 32'sd15 || value[31:4] == 28'h8000000) prepare_amount = 7'd0;
        else if (value < -32'sd48) prepare_amount = 7'd63;
        else prepare_amount = {1'b0, amount_difference};
      end else begin
        if (value > 32'sd0)
          prepare_amount = (value[5:0] >= 6'd31) ? 7'd0 : {1'b0, amount_difference};
        else if (value == 32'sh80000000) prepare_amount = 7'd31;
        else if (value < -32'sd32) prepare_amount = 7'd64;
        else prepare_amount = {1'b0, amount_difference};
      end
    end
  endfunction

  logic s16_mode;
  always_ff @(posedge clk) begin
    if (!rst_n) s16_mode<=1'b0;
    else if (init_cfg) s16_mode<=ENABLE_S16 && cfg_s16;
  end

  localparam int BYTES_PER_WORD = REG_WIDTH / 8;  // 32位=4
  localparam int QBUF_DEPTH     = VLEN * MAX_IA_REUSE;
  localparam int QBUF_IDX_W     = (QBUF_DEPTH <= 1) ? 1 : $clog2(QBUF_DEPTH);
  localparam int VLEN_SHIFT     = $clog2(VLEN);
  localparam int VLEN_CNT_W     = (VLEN <= 1) ? 1 : $clog2(VLEN + 1);
  localparam int TILE_CNT_W     = (REG_WIDTH < 16) ? REG_WIDTH : 16;
  localparam bit p_direct_tail_count = (VLEN > 0) && ((VLEN & (VLEN - 1)) == 0) &&
      (REG_WIDTH >= VLEN_CNT_W);

  typedef logic [TILE_CNT_W-1:0] tile_idx_t;

  // ----------------------------
  // 状态机与游标
  // ----------------------------
  typedef enum logic [1:0] {
    IDLE,
    LOAD,
    COMPUTE
  } state_e;
  state_e state;

  // LOAD 内部用 phase 区分 mul/shift。
  typedef enum logic [0:0] {
    PH_MUL   = 1'b0,
    PH_SHIFT = 1'b1
  } phase_e;
  phase_e          load_phase;  // 当前子阶段（先 mul 后 shift）

  tile_idx_t       tile_col;  // 当前列 tile 号
  logic [VLEN_CNT_W-1:0] row_in_tile_cnt;  // 本 tile 已完成的行数
  logic     [31:0] lane_need_cur;  // 本 tile 需要的列数（尾块可能 < VLEN）
  logic     [31:0] quant_need_cur;  // 本 tile 需要加载的 per-channel 参数数
  logic     [31:0] quant_tile_idx_cur;
  tile_idx_t       tile_row;  // 当前行 tile 号
  logic     [31:0] rows_need_cur;  // 当前行 tile 需要的行数（最后一块为余数）
  logic     [31:0] lane_need_q;  // 锁存，用于计算/屏蔽无效 lane
  logic     [ 7:0] burst_len_cur;  // = lane_need_cur - 1
  tile_idx_t       reuse_group_base_row;
  tile_idx_t       row_offset_in_group;
  logic     [31:0] group_rows_need_cur;
  logic     [31:0] load_offset;
  logic     [31:0] chunk_need_cur;
  logic     [32:0] remaining_words;
  logic [VLEN_CNT_W-1:0] chunk_words;
  logic [VLEN_CNT_W-1:0] burst_word_index;
  logic [32:0] load_advance;
  logic load_remainder_greater;
  logic load_has_more;

  // per-channel：mul/shift 两次突发的采样计数
  logic [VLEN_CNT_W-1:0] rd_beats_cnt;
  logic [VLEN_CNT_W-1:0] beats_expect;
  logic            cmd_busy;
  logic            cmd_valid_r;
  logic [REG_WIDTH-1:0] cmd_base_addr_r;
  logic [7:0]     cmd_burst_len_m1_r;
  logic [VLEN_CNT_W-1:0] cmd_beats_expect_r;
  logic [REG_WIDTH-1:0] dma_base_addr_cur;
  logic            load_meta_valid;
  logic [31:0]     quant_need_load_r;
  logic [31:0]     quant_tile_idx_load_r;

  // track number of tiles & finished flag
  tile_idx_t       num_row_tiles_next;
  tile_idx_t       num_col_tiles_next;
  tile_idx_t       last_row_tile;
  tile_idx_t       last_col_tile;
  logic            all_tiles_done;

  logic serial_per_channel_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) serial_per_channel_q <= 1'b0;
    else if (init_cfg) serial_per_channel_q <= cfg_per_channel;
  end
  wire cfg_per_channel_eff = (ENABLE_PER_CHANNEL != 0) ?
      (((p_compute_lanes < VLEN) && !init_cfg) ? serial_per_channel_q : cfg_per_channel) : 1'b0;
  wire cfg_dataflow_mode_eff = (ENABLE_IS_MODE != 0) ? cfg_dataflow_mode : 1'b0;

  // ----------------------------
  // 配置寄存
  // ----------------------------
  logic signed [31:0] pt_multiplier_r;  // per-tensor 常量
  logic signed [31:0] pt_shift_r;
  logic signed [31:0] pt_product_multiplier_r;
  logic [6:0] pt_product_amount_r;
  logic signed [31:0] activation_min_r;
  logic signed [31:0] activation_max_r;
  logic signed [31:0] dst_offset_r;
  logic [31:0] k_r, m_r;  // 锁存的尺寸
  logic [31:0] ia_reuse_num_r;
  logic        has_tiles_r;
  tile_idx_t   ia_reuse_mask_tile_r;
  logic [31:0] mul_base_r, sh_base_r;  // per-channel 基地址
  logic        is_mode_r;

  // 原始参数和精度已在配置边沿保存，准备值直接供现有运算输入级采样。
  assign pt_product_multiplier_r = prepare_multiplier(pt_multiplier_r, s16_mode);
  assign pt_product_amount_r = prepare_amount(pt_shift_r, s16_mode);

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      pt_multiplier_r  <= '0;
      pt_shift_r       <= '0;
      activation_min_r  <= '0;
      activation_max_r  <= '0;
      dst_offset_r      <= '0;
      k_r              <= '0;
      m_r              <= '0;
      ia_reuse_num_r   <= 32'd1;
      has_tiles_r      <= 1'b0;
      ia_reuse_mask_tile_r <= '0;
      mul_base_r       <= '0;
      sh_base_r        <= '0;
      is_mode_r        <= 1'b0;
      last_row_tile    <= '0;
      last_col_tile    <= '0;
    end else if (init_cfg) begin
      pt_multiplier_r  <= multiplier_in;
      pt_shift_r       <= shift_in;
      activation_min_r  <= activation_min_in;
      activation_max_r  <= activation_max_in;
      dst_offset_r      <= dst_offset_in;
      k_r              <= k;
      m_r              <= m;
      ia_reuse_num_r   <= (ia_reuse_num_in == 32'd0) ? 32'd1 : ia_reuse_num_in;
      has_tiles_r      <= (k != 32'd0) && (m != 32'd0);
      ia_reuse_mask_tile_r <= (ia_reuse_num_in <= 32'd1) ? '0 : tile_idx_t'(ia_reuse_num_in - 32'd1);
      // per-channel 基地址（接口复用 multiplier_in/shift_in）
      mul_base_r       <= multiplier_in;
      sh_base_r        <= shift_in;
      is_mode_r        <= cfg_dataflow_mode_eff;
      last_row_tile    <= (num_row_tiles_next == '0) ? '0 : (num_row_tiles_next - tile_idx_t'(1));
      last_col_tile    <= (num_col_tiles_next == '0) ? '0 : (num_col_tiles_next - tile_idx_t'(1));
    end
  end

  // compute number of tiles once at configuration time
  assign num_row_tiles_next = (k == 0) ? '0 : tile_idx_t'((k + VLEN - 1) >> VLEN_SHIFT);
  assign num_col_tiles_next = (m == 0) ? '0 : tile_idx_t'((m + VLEN - 1) >> VLEN_SHIFT);

  // ----------------------------
  // tile 列需要多少 lane（尾块）
  // ----------------------------
  logic [31:0] lane_start_cur;
  logic [31:0] row_start_cur;
  logic [31:0] lane_remaining_cur;
  logic [31:0] rows_remaining_cur;
  logic [31:0] reuse_group_row_start;
  logic [31:0] reuse_group_capacity;
  logic [31:0] group_rows_remaining_cur;
  tile_idx_t   tile_row_inc;
  tile_idx_t   tile_col_inc;
  tile_idx_t   next_tile_row_cur;
  tile_idx_t   next_tile_col_cur;
  logic        final_tile_cur;
  logic        next_same_quant_group_cur;
  logic        cur_last_row_tile;
  logic        cur_last_col_tile;
  logic        cur_last_row_in_group;
  logic        step_row_in_group;
  logic        step_col_in_group;
  logic        step_next_group;

  // 每次进入 LOAD 前计算 lane_need\row_need
  always_comb begin
    lane_start_cur = REG_WIDTH'(tile_col) << VLEN_SHIFT;
    row_start_cur  = REG_WIDTH'(tile_row) << VLEN_SHIFT;
    lane_remaining_cur = (m_r > lane_start_cur) ? (m_r - lane_start_cur) : 32'd0;
    rows_remaining_cur = (k_r > row_start_cur) ? (k_r - row_start_cur) : 32'd0;
    // 通道数为二的幂次时，块起点的低位恒为零；高位比较决定整块、尾块或空块。
    // 尾块直接使用尺寸的低位，保持完整三十二位尺寸和块坐标的范围行为。
    if (p_direct_tail_count) begin
      if ((m_r >> VLEN_SHIFT) > (lane_start_cur >> VLEN_SHIFT)) begin
        lane_need_cur = REG_WIDTH'(VLEN);
      end else if ((m_r >> VLEN_SHIFT) == (lane_start_cur >> VLEN_SHIFT)) begin
        lane_need_cur = m_r & REG_WIDTH'(VLEN - 1);
      end else begin
        lane_need_cur = 32'd0;
      end
      if ((k_r >> VLEN_SHIFT) > (row_start_cur >> VLEN_SHIFT)) begin
        rows_need_cur = REG_WIDTH'(VLEN);
      end else if ((k_r >> VLEN_SHIFT) == (row_start_cur >> VLEN_SHIFT)) begin
        rows_need_cur = k_r & REG_WIDTH'(VLEN - 1);
      end else begin
        rows_need_cur = 32'd0;
      end
    end else begin
      lane_need_cur = (lane_remaining_cur >= REG_WIDTH'(VLEN))
                    ? REG_WIDTH'(VLEN)
                    : lane_remaining_cur;
      rows_need_cur = (rows_remaining_cur >= REG_WIDTH'(VLEN))
                    ? REG_WIDTH'(VLEN)
                    : rows_remaining_cur;
    end

    reuse_group_base_row = tile_row & ~ia_reuse_mask_tile_r;
    row_offset_in_group  = tile_row & ia_reuse_mask_tile_r;
    reuse_group_row_start = REG_WIDTH'(reuse_group_base_row) << VLEN_SHIFT;
    reuse_group_capacity  = ia_reuse_num_r << VLEN_SHIFT;
    group_rows_remaining_cur = (k_r > reuse_group_row_start)
                             ? (k_r - reuse_group_row_start)
                             : 32'd0;
    group_rows_need_cur  = (group_rows_remaining_cur >= reuse_group_capacity)
                         ? reuse_group_capacity
                         : group_rows_remaining_cur;
    quant_need_cur       = is_mode_r ? group_rows_need_cur : lane_need_cur;
    quant_tile_idx_cur   = is_mode_r ? REG_WIDTH'(reuse_group_base_row) : REG_WIDTH'(tile_col);

    tile_row_inc = tile_row + tile_idx_t'(1);
    tile_col_inc = tile_col + tile_idx_t'(1);
    cur_last_row_tile = (tile_row == last_row_tile);
    cur_last_col_tile = (tile_col == last_col_tile);
    cur_last_row_in_group = cur_last_row_tile ||
                            (row_offset_in_group == ia_reuse_mask_tile_r);
    step_row_in_group = !cur_last_row_in_group;
    step_col_in_group = cur_last_row_in_group && !cur_last_col_tile;
    step_next_group   = cur_last_row_in_group && cur_last_col_tile && !cur_last_row_tile;

    if (step_row_in_group) begin
      next_tile_row_cur = tile_row_inc;
      next_tile_col_cur = tile_col;
    end else if (step_col_in_group) begin
      next_tile_row_cur = reuse_group_base_row;
      next_tile_col_cur = tile_col_inc;
    end else if (step_next_group) begin
      next_tile_row_cur = reuse_group_base_row + tile_idx_t'(ia_reuse_num_r);
      next_tile_col_cur = '0;
    end else begin
      next_tile_row_cur = '0;
      next_tile_col_cur = '0;
    end
    final_tile_cur = cur_last_col_tile && cur_last_row_tile;
    next_same_quant_group_cur = step_row_in_group ||
                                (step_col_in_group && is_mode_r);
  end

  // 参数就绪拍锁存（供计算屏蔽尾块）
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      lane_need_q <= '0;
    end else if (init_cfg) begin
      lane_need_q <= '0;
    end else begin
      // per-tensor 模式也要跟随当前列 tile，避免尾列把无效 lane 写出。
      if (!cfg_per_channel_eff) begin
        lane_need_q <= lane_need_cur;
      end  // per-channel 模式下：在 quant_params_valid 时锁存当前需要的 lanes
      else if (quant_params_valid) begin
        lane_need_q <= lane_need_cur;
      end
    end
  end

  // 完整三十三位差值同时给出剩余字数和借位，超过装载总数的偏移返回零。
  // 末拍编号的窄减法与范围判断并行，随后按 VLEN 上限选择饱和值。
  assign remaining_words = {1'b0, quant_need_load_r} - {1'b0, load_offset};
  assign burst_word_index = VLEN_CNT_W'(remaining_words) - VLEN_CNT_W'(1);
  always_comb begin
    if (remaining_words[32]) begin
      chunk_words = '0;
      burst_len_cur = 8'd0;
    end else if (remaining_words[31:0] > 32'(VLEN)) begin
      chunk_words = VLEN_CNT_W'(VLEN);
      burst_len_cur = 8'((VLEN - 1) / (BUS_WIDTH/32));
    end else begin
      chunk_words = VLEN_CNT_W'(remaining_words);
      burst_len_cur = (VLEN_CNT_W'(remaining_words) != '0) ?
          8'(burst_word_index / (BUS_WIDTH/32)) : 8'd0;
    end
  end
  assign chunk_need_cur = 32'(chunk_words);

  // 装载完成比较复用剩余字数，扩展加法保留三十二位偏移回绕的进位。
  // 剩余字数的借位决定进位与短计数比较的组合方式。
  assign load_advance = {1'b0, load_offset} + 33'(REG_WIDTH'(beats_expect));
  assign load_remainder_greater = remaining_words[31:0] > 32'(REG_WIDTH'(beats_expect));
  if (REG_WIDTH == 32) begin : g_load_completion_compare
    assign load_has_more = remaining_words[32] ?
        (load_advance[32] && load_remainder_greater) :
        (load_advance[32] || load_remainder_greater);
  end else begin : g_generic_load_completion_compare
    assign load_has_more = (load_offset + REG_WIDTH'(beats_expect)) < quant_need_load_r;
  end

  // ----------------------------
  // Native DMA 命令/响应
  // ----------------------------
  wire dma_start_hskd = (state == LOAD) && !cmd_busy && cmd_valid_r && load_quant_granted;
  wire rsp_hskd = dma_raw_valid && cmd_busy;
  logic [QBUF_IDX_W-1:0] quant_rsp_idx;

  always_comb begin
    quant_rsp_idx = QBUF_IDX_W'(load_offset + REG_WIDTH'(rd_beats_cnt));
  end

  assign dma_start = dma_start_hskd;
  assign dma_is_write = 1'b0;
  assign dma_linear_read_mode = 1'b0;
  assign dma_base_addr_cur = (load_phase == PH_MUL)
                           ? (mul_base_r + (quant_tile_idx_load_r * VLEN + load_offset) * BYTES_PER_WORD)
                           : (sh_base_r  + (quant_tile_idx_load_r * VLEN + load_offset) * BYTES_PER_WORD);
  assign dma_base_addr = cmd_base_addr_r;
  assign dma_row_stride = REG_WIDTH'(REG_WIDTH / 8);
  assign dma_rows_to_read = REG_WIDTH'(1);
  assign dma_burst_len_m1 = cmd_burst_len_m1_r;
  assign dma_slot_id = 1'b0;
  assign dma_use_16bits = 1'b0;
  assign dma_lhs_zp = '0;

  // ----------------------------
  // per-channel 参数缓冲
  // ----------------------------
  localparam int VLEN_IDX_W = (VLEN <= 1) ? 1 : $clog2(VLEN);
  logic signed [31:0] ch_multiplier_lane_r[VLEN];
  logic signed [31:0] ch_shift_lane_r[VLEN];
  logic signed [31:0] ch_product_multiplier_lane_r[VLEN];
  logic [6:0] ch_product_amount_lane_r[VLEN];
  localparam int PARAM_BANKS = BUS_WIDTH / 32;
  wire signed [31:0] ch_multiplier_is_read [PARAM_BANKS];
  wire signed [31:0] ch_shift_is_read [PARAM_BANKS];
  wire signed [31:0] ch_product_multiplier_is_read[PARAM_BANKS];
  wire [6:0] ch_product_amount_is_read[PARAM_BANKS];
  wire signed [31:0] parameter_value [BUS_WIDTH/32];
  wire signed [31:0] parameter_product_multiplier[BUS_WIDTH/32];
  wire [6:0] parameter_product_amount[BUS_WIDTH/32];
  wire [QBUF_IDX_W-1:0] parameter_index [BUS_WIDTH/32];
  for(genvar word=0;word<BUS_WIDTH/32;word++)begin:g_parameter_word
    wire signed [31:0] value=$signed(dma_raw_data[word*32+:32]);
    assign parameter_value[word]=value;
    assign parameter_product_multiplier[word]=prepare_multiplier(value,s16_mode);
    assign parameter_product_amount[word]=prepare_amount(value,s16_mode);
    assign parameter_index[word]=quant_rsp_idx+QBUF_IDX_W'(word);
  end
  logic [QBUF_IDX_W-1:0] input_group_idx_cur;
  logic [QBUF_IDX_W-1:0] parameter_read_idx;
  logic row_consume_valid, row_consume_tile_done;
  for (genvar bank = 0; bank < PARAM_BANKS; bank++) begin : gen_is_parameter_bank
    localparam int BANK_DEPTH = (QBUF_DEPTH + PARAM_BANKS - 1) / PARAM_BANKS;
    localparam int BANK_ADDR_W = (BANK_DEPTH <= 1) ? 1 : $clog2(BANK_DEPTH);
    logic write_enable;
    logic [BANK_ADDR_W-1:0] write_addr;
    logic signed [31:0] write_value;
    logic signed [31:0] write_product_multiplier;
    logic [6:0] write_product_amount;
    always_comb begin
      write_enable = 1'b0;
      write_addr = '0;
      write_value = '0;
      write_product_multiplier = '0;
      write_product_amount = '0;
      for (int word = 0; word < BUS_WIDTH/32; word++) begin
        if (rsp_hskd && is_mode_r &&
            (32'(rd_beats_cnt)+word) < 32'(beats_expect) &&
            (int'(parameter_index[word]) % PARAM_BANKS) == bank) begin
          write_enable = 1'b1;
          write_addr = BANK_ADDR_W'(parameter_index[word] / PARAM_BANKS);
          write_value = parameter_value[word];
          write_product_multiplier = parameter_product_multiplier[word];
          write_product_amount = parameter_product_amount[word];
        end
      end
    end
    // 原始参数保持组合读取；运算参数在输入采样边沿同步读取。
    // 两类存储使用相同的写入条件，保存完整的原始参数与预处理参数。
    logic multiplier_i_wr_en, multiplier_i_wr_mask, multiplier_i_rd_en;
    logic [BANK_ADDR_W-1:0] multiplier_i_wr_addr, multiplier_i_rd_addr;
    logic [31:0] multiplier_i_wr_data, multiplier_o_rd_data;
    logic shift_i_wr_en, shift_i_wr_mask, shift_i_rd_en;
    logic [BANK_ADDR_W-1:0] shift_i_wr_addr, shift_i_rd_addr;
    logic [31:0] shift_i_wr_data, shift_o_rd_data;
    logic product_multiplier_i_wr_en, product_multiplier_i_wr_mask, product_multiplier_i_rd_en;
    logic [BANK_ADDR_W-1:0] product_multiplier_i_wr_addr, product_multiplier_i_rd_addr;
    logic [31:0] product_multiplier_i_wr_data, product_multiplier_o_rd_data;
    logic product_amount_i_wr_en, product_amount_i_wr_mask, product_amount_i_rd_en;
    logic [BANK_ADDR_W-1:0] product_amount_i_wr_addr, product_amount_i_rd_addr;
    logic [6:0] product_amount_i_wr_data, product_amount_o_rd_data;

    assign multiplier_i_wr_en = write_enable && (load_phase == PH_MUL);
    assign multiplier_i_wr_addr = write_addr;
    assign multiplier_i_wr_data = write_value;
    assign multiplier_i_wr_mask = 1'b1;
    assign multiplier_i_rd_en = 1'b1;
    assign multiplier_i_rd_addr = BANK_ADDR_W'(input_group_idx_cur / PARAM_BANKS);
    assign ch_multiplier_is_read[bank] = $signed(multiplier_o_rd_data);
    assign shift_i_wr_en = write_enable && (load_phase != PH_MUL);
    assign shift_i_wr_addr = write_addr;
    assign shift_i_wr_data = write_value;
    assign shift_i_wr_mask = 1'b1;
    assign shift_i_rd_en = 1'b1;
    assign shift_i_rd_addr = BANK_ADDR_W'(input_group_idx_cur / PARAM_BANKS);
    assign ch_shift_is_read[bank] = $signed(shift_o_rd_data);

    assign product_multiplier_i_wr_en = multiplier_i_wr_en;
    assign product_multiplier_i_wr_addr = write_addr;
    assign product_multiplier_i_wr_data = write_product_multiplier;
    assign product_multiplier_i_wr_mask = 1'b1;
    assign product_multiplier_i_rd_en = !init_cfg;
    assign product_multiplier_i_rd_addr = BANK_ADDR_W'(parameter_read_idx / PARAM_BANKS);
    assign ch_product_multiplier_is_read[bank] = $signed(product_multiplier_o_rd_data);
    assign product_amount_i_wr_en = shift_i_wr_en;
    assign product_amount_i_wr_addr = write_addr;
    assign product_amount_i_wr_data = write_product_amount;
    assign product_amount_i_wr_mask = 1'b1;
    assign product_amount_i_rd_en = !init_cfg;
    assign product_amount_i_rd_addr = product_multiplier_i_rd_addr;
    assign ch_product_amount_is_read[bank] = product_amount_o_rd_data;

    regfile #(
        .p_data_width(32), .p_depth(BANK_DEPTH), .p_addr_width(BANK_ADDR_W),
        .p_write_unit(32), .p_sync_read(1'b0)
    ) u_multiplier (
        .clk(clk), .i_wr_en(multiplier_i_wr_en), .i_wr_addr(multiplier_i_wr_addr),
        .i_wr_data(multiplier_i_wr_data), .i_wr_mask(multiplier_i_wr_mask),
        .i_rd_en(multiplier_i_rd_en), .i_rd_addr(multiplier_i_rd_addr), .o_rd_data(multiplier_o_rd_data)
    );
    regfile #(
        .p_data_width(32), .p_depth(BANK_DEPTH), .p_addr_width(BANK_ADDR_W),
        .p_write_unit(32), .p_sync_read(1'b0)
    ) u_shift (
        .clk(clk), .i_wr_en(shift_i_wr_en), .i_wr_addr(shift_i_wr_addr),
        .i_wr_data(shift_i_wr_data), .i_wr_mask(shift_i_wr_mask),
        .i_rd_en(shift_i_rd_en), .i_rd_addr(shift_i_rd_addr), .o_rd_data(shift_o_rd_data)
    );
    regfile #(
        .p_data_width(32), .p_depth(BANK_DEPTH), .p_addr_width(BANK_ADDR_W),
        .p_write_unit(32), .p_sync_read(1'b1)
    ) u_product_multiplier (
        .clk(clk), .i_wr_en(product_multiplier_i_wr_en), .i_wr_addr(product_multiplier_i_wr_addr),
        .i_wr_data(product_multiplier_i_wr_data), .i_wr_mask(product_multiplier_i_wr_mask),
        .i_rd_en(product_multiplier_i_rd_en), .i_rd_addr(product_multiplier_i_rd_addr),
        .o_rd_data(product_multiplier_o_rd_data)
    );
    regfile #(
        .p_data_width(7), .p_depth(BANK_DEPTH), .p_addr_width(BANK_ADDR_W),
        .p_write_unit(7), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_product_amount (
        .clk(clk), .i_wr_en(product_amount_i_wr_en), .i_wr_addr(product_amount_i_wr_addr),
        .i_wr_data(product_amount_i_wr_data), .i_wr_mask(product_amount_i_wr_mask),
        .i_rd_en(product_amount_i_rd_en), .i_rd_addr(product_amount_i_rd_addr),
        .o_rd_data(product_amount_o_rd_data)
    );
  end
  // 连续 DMA 字按低位分入不同 bank，同一 bank 的通道共用写数据选择。
  // 每个通道保持独立存储位置，常量读地址同时提供全部 WS 通道参数。
  if (((PARAM_BANKS & (PARAM_BANKS - 1)) == 0) && (PARAM_BANKS <= VLEN) &&
      ((VLEN & (VLEN - 1)) == 0)) begin : g_ws_bank_write
    localparam int p_bank_depth = VLEN / PARAM_BANKS;
    localparam int p_bank_addr_width = (p_bank_depth <= 1) ? 1 : $clog2(p_bank_depth);

    for (genvar bank = 0; bank < PARAM_BANKS; bank++) begin : g_bank
      logic write_word_vld;
      logic write_fire;
      logic [p_bank_addr_width-1:0] write_addr;
      logic signed [31:0] write_value;
      logic signed [31:0] write_product_multiplier;
      logic [6:0] write_product_amount;
      logic multiplier_i_wr_en, multiplier_i_wr_mask;
      logic [p_bank_addr_width-1:0] multiplier_i_wr_addr;
      logic [63:0] multiplier_i_wr_data;
      logic [p_bank_depth-1:0] multiplier_i_rd_en;
      logic [p_bank_depth-1:0][p_bank_addr_width-1:0] multiplier_i_rd_addr;
      logic [p_bank_depth-1:0][63:0] multiplier_o_rd_data;
      logic shift_i_wr_en, shift_i_wr_mask;
      logic [p_bank_addr_width-1:0] shift_i_wr_addr;
      logic [38:0] shift_i_wr_data;
      logic [p_bank_depth-1:0] shift_i_rd_en;
      logic [p_bank_depth-1:0][p_bank_addr_width-1:0] shift_i_rd_addr;
      logic [p_bank_depth-1:0][38:0] shift_o_rd_data;

      // bank 数为二的幂时，一个总线拍恰好为每个 bank 提供一个字。
      // 尾拍有效字数只控制写使能，数据选择可由全部通道共用。
      always_comb begin
        write_word_vld = 1'b0;
        write_addr = '0;
        write_value = '0;
        write_product_multiplier = '0;
        write_product_amount = '0;
        for (int word = 0; word < PARAM_BANKS; word++) begin
          if ((int'(parameter_index[word]) % PARAM_BANKS) == bank) begin
            write_word_vld = (32'(rd_beats_cnt) + 32'(word)) < 32'(beats_expect);
            write_addr = p_bank_addr_width'(VLEN_IDX_W'(parameter_index[word]) / PARAM_BANKS);
            write_value = parameter_value[word];
            write_product_multiplier = parameter_product_multiplier[word];
            write_product_amount = parameter_product_amount[word];
          end
        end
      end

      assign write_fire = rsp_hskd && !is_mode_r && write_word_vld;
      assign multiplier_i_wr_en = write_fire && (load_phase == PH_MUL);
      assign multiplier_i_wr_addr = write_addr;
      assign multiplier_i_wr_data = {write_product_multiplier, write_value};
      assign multiplier_i_wr_mask = 1'b1;
      assign multiplier_i_rd_en = '1;
      assign shift_i_wr_en = write_fire && (load_phase != PH_MUL);
      assign shift_i_wr_addr = write_addr;
      assign shift_i_wr_data = {write_product_amount, write_value};
      assign shift_i_wr_mask = 1'b1;
      assign shift_i_rd_en = '1;

      for (genvar row = 0; row < p_bank_depth; row++) begin : g_read_lane
        localparam int p_lane = row * PARAM_BANKS + bank;
        assign multiplier_i_rd_addr[row] = p_bank_addr_width'(row);
        assign shift_i_rd_addr[row] = p_bank_addr_width'(row);
        assign ch_multiplier_lane_r[p_lane] = $signed(multiplier_o_rd_data[row][31:0]);
        assign ch_product_multiplier_lane_r[p_lane] = $signed(multiplier_o_rd_data[row][63:32]);
        assign ch_shift_lane_r[p_lane] = $signed(shift_o_rd_data[row][31:0]);
        assign ch_product_amount_lane_r[p_lane] = shift_o_rd_data[row][38:32];
      end

      regfile #(
          .p_data_width(64), .p_depth(p_bank_depth), .p_addr_width(p_bank_addr_width),
          .p_write_unit(64), .p_read_ports(p_bank_depth), .p_sync_read(1'b0)
      ) u_multiplier (
          .clk(clk), .i_wr_en(multiplier_i_wr_en), .i_wr_addr(multiplier_i_wr_addr),
          .i_wr_data(multiplier_i_wr_data), .i_wr_mask(multiplier_i_wr_mask),
          .i_rd_en(multiplier_i_rd_en), .i_rd_addr(multiplier_i_rd_addr), .o_rd_data(multiplier_o_rd_data)
      );
      regfile #(
          .p_data_width(39), .p_depth(p_bank_depth), .p_addr_width(p_bank_addr_width),
          .p_write_unit(39), .p_read_ports(p_bank_depth), .p_sync_read(1'b0)
      ) u_shift (
          .clk(clk), .i_wr_en(shift_i_wr_en), .i_wr_addr(shift_i_wr_addr),
          .i_wr_data(shift_i_wr_data), .i_wr_mask(shift_i_wr_mask),
          .i_rd_en(shift_i_rd_en), .i_rd_addr(shift_i_rd_addr), .o_rd_data(shift_o_rd_data)
      );
    end
  end else begin : g_ws_direct_write
    // 其他参数组合按字顺序更新；同地址重复写入由较后的有效字覆盖。
    always_ff @(posedge clk) begin
      for (int word = 0; word < BUS_WIDTH/32; word++) begin
        if (rsp_hskd && !is_mode_r && (32'(rd_beats_cnt) + 32'(word)) < 32'(beats_expect)) begin
          if (load_phase == PH_MUL) begin
            ch_multiplier_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_value[word];
            ch_product_multiplier_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_product_multiplier[word];
          end else begin
            ch_shift_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_value[word];
            ch_product_amount_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_product_amount[word];
          end
        end
      end
    end
  end

  // ----------------------------
  // 主状态机（只保留 4 个状态名）
  // ----------------------------
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      // reset all sequential state
      state              <= IDLE;
      load_phase         <= PH_MUL;
	      quant_params_valid <= 1'b0;
	      row_in_tile_cnt    <= '0;
	      rd_beats_cnt       <= '0;
	      beats_expect       <= '0;
	      cmd_busy           <= 1'b0;
	      cmd_valid_r        <= 1'b0;
	      cmd_base_addr_r    <= '0;
	      cmd_burst_len_m1_r <= '0;
	      cmd_beats_expect_r <= '0;
	      load_meta_valid    <= 1'b0;
	      quant_need_load_r  <= 32'd0;
	      quant_tile_idx_load_r <= 32'd0;
	      load_quant_req     <= 1'b0;
      tile_col           <= '0;
      tile_row           <= '0;
      load_offset        <= 32'd0;
      all_tiles_done     <= 1'b0;
    end else begin
      // default per-cycle de-asserts (will be overridden in branches)
      //load_quant_req      <= 1'b0;
      // note: do NOT clear quant_params_valid/lane_need_q here (they are cleared when tile completes)

      // handle init_cfg (single-cycle reset of per-tile counters)
      if (init_cfg) begin
        state              <= IDLE;
        quant_params_valid <= (cfg_per_channel_eff ? 1'b0 : 1'b1);
	        row_in_tile_cnt    <= '0;
	        rd_beats_cnt       <= '0;
	        cmd_busy           <= 1'b0;
	        cmd_valid_r        <= 1'b0;
	        cmd_base_addr_r    <= '0;
	        cmd_burst_len_m1_r <= '0;
	        cmd_beats_expect_r <= '0;
	        load_meta_valid    <= 1'b0;
	        quant_need_load_r  <= 32'd0;
	        quant_tile_idx_load_r <= 32'd0;
	        tile_col           <= '0;
        tile_row           <= '0;
        load_offset        <= 32'd0;
        all_tiles_done     <= 1'b0;  // clear done on re-config

      end else begin

        case (state)
          // ----------------------
	          IDLE: begin
	            rd_beats_cnt    <= '0;
	            cmd_busy        <= 1'b0;
	            cmd_valid_r     <= 1'b0;
	            row_in_tile_cnt <= '0;

            // 如果所有 tile 都做完了 -> stay IDLE 等待 init_cfg 清除
            if (all_tiles_done) begin
              load_quant_req <= 1'b0;
              // remain idle
            end else begin
              // 保持请求直到 grant（避免单拍丢失）
              if (cfg_per_channel_eff && has_tiles_r && !quant_params_valid) begin
                load_quant_req <= 1'b1;
                if (load_quant_granted) begin
                  load_phase     <= PH_MUL;
                  load_offset    <= 32'd0;
                  load_meta_valid <= 1'b0;
                  state          <= LOAD;

                  // do not clear load_quant_req here; default loop will clear next cycle if needed
                end
              end

              // per-tensor 或 已有参数: 直接响应输入
              if (!cfg_per_channel_eff || quant_params_valid) begin
                if (row_consume_valid) begin
                  if (row_consume_tile_done) begin
                    row_in_tile_cnt <= '0;
                    all_tiles_done  <= final_tile_cur;

                    if (final_tile_cur) begin
                      tile_row <= '0;
                      tile_col <= '0;
                      load_quant_req <= 1'b0;
                      quant_params_valid <= cfg_per_channel_eff ? 1'b0 : 1'b1;
                      state <= IDLE;
                    end else begin
                      tile_row <= next_tile_row_cur;
                      tile_col <= next_tile_col_cur;

                      if (!cfg_per_channel_eff) begin
                        state <= COMPUTE;
                      end else if (next_same_quant_group_cur) begin
                        load_quant_req <= 1'b0;
                        quant_params_valid <= 1'b1;
                        state <= COMPUTE;
                      end else begin
                        load_quant_req <= 1'b0;
                        load_meta_valid <= 1'b0;
                        load_phase <= PH_MUL;
                        load_offset <= 32'd0;
                        quant_params_valid <= 1'b0;
                        state <= LOAD;
                      end
                    end
                  end else begin
                    // IDLE 中接住的第一拍 row_consume_valid 已经被数据通路消费，
                    // 行计数也必须同步推进，避免下一拍把 tile_done 提前一行。
                    row_in_tile_cnt <= VLEN_CNT_W'(1);
                    state <= COMPUTE;
                  end
                end
              end
            end
          end

          // ----------------------
          LOAD: begin
            row_in_tile_cnt <= '0;
	            // 1) 先锁存本 LOAD 的量化参数范围，避免命令寄存器直接吃尺寸组合路径。
	            if (!load_meta_valid) begin
	              load_meta_valid      <= 1'b1;
	              quant_need_load_r    <= quant_need_cur;
	              quant_tile_idx_load_r <= quant_tile_idx_cur;
	              load_offset          <= 32'd0;
	              load_quant_req       <= 1'b1;

	            end else if (!cmd_busy) begin
	              // 2) 若当前没有在途命令，则按 phase 发一条 DMA 读命令。
	              if (!cmd_valid_r) begin

	                cmd_valid_r        <= 1'b1;
	                cmd_base_addr_r    <= dma_base_addr_cur;
	                cmd_burst_len_m1_r <= burst_len_cur;
	                cmd_beats_expect_r <= VLEN_CNT_W'(chunk_need_cur);
	                load_quant_req     <= 1'b1;
	              end else begin
	                load_quant_req <= 1'b1;
	              end

	              if (dma_start_hskd) begin
	                // 命令已被 DMA 接受，本次突发开始
	                cmd_busy       <= 1'b1;
	                cmd_valid_r    <= 1'b0;
	                load_quant_req <= 1'b0;
	                rd_beats_cnt   <= '0;
	                beats_expect   <= cmd_beats_expect_r;  // 需要收的拍数

	              end
            end

            // 3) 接收响应拍：mul/shift 缓冲写入
            if (rsp_hskd && cmd_busy) begin
              // 防护断言（仿真）

              rd_beats_cnt <= rd_beats_cnt + VLEN_CNT_W'(BUS_WIDTH/32);

              // 3) 本次突发收满：决定是切 phase 还是完成 LOAD
              if ((rd_beats_cnt + VLEN_CNT_W'(BUS_WIDTH/32)) >= beats_expect) begin
                cmd_busy <= 1'b0;  // 本突发结束

                if (load_phase == PH_MUL) begin
                  if (load_has_more) begin
                    load_offset <= load_offset + REG_WIDTH'(beats_expect);
                  end else begin
                    // mul 收满 -> 切到 shift，下一拍会去发 shift 的命令
                    load_phase  <= PH_SHIFT;
                    load_offset <= 32'd0;
                  end
                end else begin
                  if (load_has_more) begin
                    load_offset <= load_offset + REG_WIDTH'(beats_expect);
                  end else begin
                    // shift 也收满，参数就绪：同时锁存 lane_need，并根据当拍 row_consume_valid 决定是否直接进 COMPUTE
                    quant_params_valid <= 1'b1;
                    load_offset        <= 32'd0;
                    load_meta_valid    <= 1'b0;
                    //lane_need_q        <= lane_need_cur;   // <-- 把 lane_need 在参数就绪时锁存

                    if (row_consume_valid) begin
                      state <= COMPUTE; // 允许在同一时钟周期观察到 row_consume_valid 并直接进入 COMPUTE
                    end else begin
                      state <= IDLE;
                    end
                  end
                end
              end
            end
          end

          // ----------------------
          COMPUTE: begin
            load_phase <= PH_MUL;

            if (row_consume_valid) begin

              if (row_consume_tile_done) begin
                row_in_tile_cnt <= '0;
                all_tiles_done  <= final_tile_cur;

                if (final_tile_cur) begin
                  tile_row <= '0;
                  tile_col <= '0;
                  load_quant_req <= 1'b0;
                          quant_params_valid <= cfg_per_channel_eff ? 1'b0 : 1'b1;
                  state <= IDLE;
                end else begin
                  tile_row <= next_tile_row_cur;
                  tile_col <= next_tile_col_cur;

                  if (!cfg_per_channel_eff) begin
                    state <= COMPUTE;
                  end else if (next_same_quant_group_cur) begin
                    load_quant_req <= 1'b0;
                    quant_params_valid <= 1'b1;
                    state <= COMPUTE;
                  end else begin
                    load_quant_req <= 1'b0;
                    load_meta_valid <= 1'b0;
                    load_phase <= PH_MUL;
                    load_offset <= 32'd0;
                    quant_params_valid <= 1'b0;
                    state <= LOAD;
                  end
                end
              end else begin
                row_in_tile_cnt <= row_in_tile_cnt + 1'b1;
                state <= COMPUTE;
              end
            end
          end

          default: begin
            // 保底：防止卡死
            state <= IDLE;
          end

        endcase
      end  // !init_cfg
    end  // !rst_n
  end

  // ----------------------------
  // 数据通路（全吞吐流水：in_valid -> out_valid）
  // ----------------------------
  logic accept_valid;
  logic stage0_valid;
  logic stage1_valid;
  logic stage2_valid;
  logic stage3_valid;
  logic stage4_valid;
  logic stage5_valid;
  logic stage6_valid;
  logic stage7_valid;
  logic stage8_valid;
  logic stage9_valid;
  logic stage10_valid;
  logic stage11_valid;
  logic stage0_tile_done;
  logic stage1_tile_done;
  logic stage2_tile_done;
  logic stage3_tile_done;
  logic stage4_tile_done;
  logic stage5_tile_done;
  logic stage6_tile_done;
  logic stage7_tile_done;
  logic stage8_tile_done;
  logic stage9_tile_done;
  logic stage10_tile_done;
  logic stage11_tile_done;

  logic dw_accept;
  assign dw_accept = i_dw_valid && o_dw_ready;
  assign accept_valid = dw_accept ||
      (in_valid && !i_dw_enable && ((!cfg_per_channel_eff) || quant_params_valid));
  if (p_compute_lanes >= VLEN) begin : g_parallel_control
    logic [11:0] dw_owner_pipe, dw_tag_pipe;
    assign o_dw_ready = i_dw_enable && !init_cfg && !in_valid;
    assign o_dw_valid = stage11_valid && dw_owner_pipe[11];
    assign o_dw_tag = dw_tag_pipe[11];
    assign row_consume_valid = in_valid && !i_dw_enable;
    assign row_consume_tile_done = in_tile_done;
    assign parameter_read_idx = input_group_idx_cur;
    assign o_group_ready = 1'b1;
    assign out_valid = stage11_valid && !dw_owner_pipe[11];
    assign out_tile_done = stage11_tile_done && !dw_owner_pipe[11];
    always_ff @(posedge clk) begin
      if (!rst_n || init_cfg) begin
        dw_owner_pipe <= '0;
        dw_tag_pipe <= '0;
      end else begin
        dw_owner_pipe <= {dw_owner_pipe[10:0],dw_accept};
        dw_tag_pipe <= {dw_tag_pipe[10:0],i_dw_tag};
      end
    end
  end else begin : g_private_serial_control
    assign o_dw_ready = 1'b0;
    assign o_dw_valid = 1'b0;
    assign o_dw_tag = 1'b0;
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      stage0_valid     <= 1'b0;
      stage1_valid     <= 1'b0;
      stage2_valid     <= 1'b0;
      stage3_valid     <= 1'b0;
      stage4_valid     <= 1'b0;
      stage5_valid     <= 1'b0;
      stage6_valid     <= 1'b0;
      stage7_valid     <= 1'b0;
      stage8_valid     <= 1'b0;
      stage9_valid     <= 1'b0;
      stage10_valid    <= 1'b0;
      stage11_valid    <= 1'b0;
      stage0_tile_done <= 1'b0;
      stage1_tile_done <= 1'b0;
      stage2_tile_done <= 1'b0;
      stage3_tile_done <= 1'b0;
      stage4_tile_done <= 1'b0;
      stage5_tile_done <= 1'b0;
      stage6_tile_done <= 1'b0;
      stage7_tile_done <= 1'b0;
      stage8_tile_done <= 1'b0;
      stage9_tile_done <= 1'b0;
      stage10_tile_done <= 1'b0;
      stage11_tile_done <= 1'b0;
    end else if (init_cfg) begin
      stage0_valid     <= 1'b0;
      stage1_valid     <= 1'b0;
      stage2_valid     <= 1'b0;
      stage3_valid     <= 1'b0;
      stage4_valid     <= 1'b0;
      stage5_valid     <= 1'b0;
      stage6_valid     <= 1'b0;
      stage7_valid     <= 1'b0;
      stage8_valid     <= 1'b0;
      stage9_valid     <= 1'b0;
      stage10_valid    <= 1'b0;
      stage11_valid    <= 1'b0;
      stage0_tile_done <= 1'b0;
      stage1_tile_done <= 1'b0;
      stage2_tile_done <= 1'b0;
      stage3_tile_done <= 1'b0;
      stage4_tile_done <= 1'b0;
      stage5_tile_done <= 1'b0;
      stage6_tile_done <= 1'b0;
      stage7_tile_done <= 1'b0;
      stage8_tile_done <= 1'b0;
      stage9_tile_done <= 1'b0;
      stage10_tile_done <= 1'b0;
      stage11_tile_done <= 1'b0;
    end else begin
      stage0_valid     <= accept_valid;
      stage1_valid     <= stage0_valid;
      stage2_valid     <= stage1_valid;
      stage3_valid     <= stage2_valid;
      stage4_valid     <= stage3_valid;
      stage5_valid     <= stage4_valid;
      stage6_valid     <= stage5_valid;
      stage7_valid     <= stage6_valid;
      stage8_valid     <= stage7_valid;
      stage9_valid     <= stage8_valid;
      stage10_valid    <= stage9_valid;
      stage11_valid    <= stage10_valid;
      stage0_tile_done <= accept_valid && in_tile_done;
      stage1_tile_done <= stage0_tile_done;
      stage2_tile_done <= stage1_tile_done;
      stage3_tile_done <= stage2_tile_done;
      stage4_tile_done <= stage3_tile_done;
      stage5_tile_done <= stage4_tile_done;
      stage6_tile_done <= stage5_tile_done;
      stage7_tile_done <= stage6_tile_done;
      stage8_tile_done <= stage7_tile_done;
      stage9_tile_done <= stage8_tile_done;
      stage10_tile_done <= stage9_tile_done;
      stage11_tile_done <= stage10_tile_done;
    end
  end

  logic [VLEN_CNT_W-1:0] input_row_idx_cur;
  logic signed [31:0] ch_multiplier_is_sel;
  logic signed [31:0] ch_shift_is_sel;
  logic signed [31:0] ch_product_multiplier_is_sel;
  logic [6:0] ch_product_amount_is_sel;
  localparam int p_parameter_width = 32 + 32;
  localparam int p_product_parameter_width = 32 + 7;
  localparam int p_bank_index_width = (PARAM_BANKS <= 1) ? 1 : $clog2(PARAM_BANKS);
  logic [p_parameter_width-1:0] common_parameters;
  logic ws_parameters_select;
  logic ws_parameters_select_s0;
  logic per_channel_s0;
  logic [p_bank_index_width-1:0] parameter_bank_s0;
  logic signed [31:0] pt_product_multiplier_s0;
  logic [6:0] pt_product_amount_s0;
  logic [p_product_parameter_width-1:0] common_product_parameters_s0;
  assign input_row_idx_cur = row_in_tile_cnt;
  assign input_group_idx_cur = QBUF_IDX_W'((REG_WIDTH'(row_offset_in_group) << VLEN_SHIFT) +
                                         REG_WIDTH'(input_row_idx_cur));
  always_comb begin
    ch_multiplier_is_sel = ch_multiplier_is_read[(int'(input_group_idx_cur) % PARAM_BANKS)];
    ch_shift_is_sel = ch_shift_is_read[(int'(input_group_idx_cur) % PARAM_BANKS)];
    ch_product_multiplier_is_sel = ch_product_multiplier_is_read[parameter_bank_s0];
    ch_product_amount_is_sel = ch_product_amount_is_read[parameter_bank_s0];
  end

  // IS 与 per-tensor 参数由所有通道共用，先形成一个公共数据字。
  // 只有 per-channel WS 从各通道独立参数中取值，选择保持当前周期的模式行为。
  assign common_parameters = cfg_per_channel_eff ?
      {ch_multiplier_is_sel, ch_shift_is_sel} : {pt_multiplier_r, pt_shift_r};
  assign ws_parameters_select = cfg_per_channel_eff && !is_mode_r;
  assign common_product_parameters_s0 = per_channel_s0 ?
      {ch_product_multiplier_is_sel, ch_product_amount_is_sel} :
      {pt_product_multiplier_s0, pt_product_amount_s0};

  // 存储读地址、模式和整张量参数在同一边沿采样，与 DSP 的 AREG 输入同步。
  always_ff @(posedge clk) begin
    if (!init_cfg) begin
      ws_parameters_select_s0 <= i_dw_enable || ws_parameters_select;
      per_channel_s0 <= cfg_per_channel_eff;
      parameter_bank_s0 <= p_bank_index_width'(int'(input_group_idx_cur) % PARAM_BANKS);
      pt_product_multiplier_s0 <= pt_product_multiplier_r;
      pt_product_amount_s0 <= pt_product_amount_r;
    end
  end

  logic signed [35:0] rounding_offset;
  logic signed [31:0] arithmetic_minimum, arithmetic_maximum;
  assign rounding_offset = i_dw_enable ? {{4{i_dw_offset[31]}},i_dw_offset} :
      s16_mode ? 36'sd0 : {{4{dst_offset_r[31]}}, dst_offset_r};
  assign arithmetic_minimum = i_dw_enable ? i_dw_minimum : activation_min_r;
  assign arithmetic_maximum = i_dw_enable ? i_dw_maximum : activation_max_r;

  // 配置和 DMA 装载阶段预先处理量化参数。每个通道每周期接收一个累加值，
  // 十二个寄存阶段保持固定延迟；乘积形成、移位和输出裁剪分别执行。
  if (p_compute_lanes >= VLEN) begin : g_parallel_arithmetic
  for (genvar j = 0; j < VLEN; j++) begin : LANE
    logic signed [31:0] mult_sel, shift_sel_raw;
    logic signed [31:0] product_multiplier_sel;
    logic [6:0] product_amount_sel;
    logic [p_parameter_width-1:0] parameter_mux_i_direct, parameter_mux_i_shifted;
    logic parameter_mux_i_select;
    logic [p_parameter_width-1:0] parameter_mux_o_value;
    logic signed [31:0] ws_product_multiplier_s0;
    logic [6:0] ws_product_amount_s0;
    logic [p_product_parameter_width-1:0] product_parameter_mux_i_direct;
    logic [p_product_parameter_width-1:0] product_parameter_mux_i_shifted;
    logic product_parameter_mux_i_select;
    logic [p_product_parameter_width-1:0] product_parameter_mux_o_value;
    logic [6:0] amount_s0;
    logic [6:0] amount_s1, amount_s2;
    logic signed [63:0] prod_s2;
    logic lane_en_s0, lane_en_s1, lane_en_s2, lane_en_s3;
    logic lane_en_s4, lane_en_s5, lane_en_s6, lane_en_s7;
    logic lane_en_s8, lane_en_s9, lane_en_s10;
    logic signed [33:0] quotient_s9;
    logic round_increment_s9;
    (* use_dsp = "yes" *) logic signed [35:0] rounded_s10;
    logic product_i_en;
    logic signed [31:0] product_i_a, product_i_b;
    logic signed [63:0] product_o_product;
    logic rounding_sum_i_en;
    logic signed [35:0] rounding_sum_i_lhs, rounding_sum_i_rhs;
    logic rounding_sum_i_carry;
    logic signed [35:0] rounding_sum_o_sum;
    logic signed [35:0] activation_compare_i_value;
    logic signed [31:0] activation_compare_i_minimum, activation_compare_i_maximum;
    logic activation_compare_o_below, activation_compare_o_above;

    // 阶段 0 在 AREG 保存累加值，同步参数存储或通道寄存器保存右操作数。
    // 阶段 1/2 依次保存部分积及完整乘积，三个边沿共用配置暂停使能。
    assign product_i_en = !init_cfg;
    assign product_i_a = i_dw_enable ? i_dw_accumulator[j] : in_vec_s32[j];
    assign product_i_b = product_multiplier_sel;
    assign prod_s2 = product_o_product;
    registered_multiplier_s32 #(
        .p_input_register(1'b1), .p_b_input_register(1'b0)
    ) u_product (
        .clk(clk),
        .i_en(product_i_en),
        .i_a(product_i_a),
        .i_b(product_i_b),
        .o_product(product_o_product)
    );

    // 阶段 10 同时接收商、偏移和舍入进位，不改变最终裁剪的采样边沿。
    assign rounding_sum_i_en = !init_cfg;
    assign rounding_sum_i_lhs = {{2{quotient_s9[33]}}, quotient_s9};
    assign rounding_sum_i_rhs = rounding_offset;
    assign rounding_sum_i_carry = round_increment_s9;
    assign rounded_s10 = rounding_sum_o_sum;
    requant_registered_sum #(.p_width(36)) u_rounding_sum (
        .clk(clk),
        .i_en(rounding_sum_i_en),
        .i_lhs(rounding_sum_i_lhs),
        .i_rhs(rounding_sum_i_rhs),
        .i_carry(rounding_sum_i_carry),
        .o_sum(rounding_sum_o_sum)
    );

    // 两种输出精度共用完整结果与激活边界的有符号比较。
    assign activation_compare_i_value = rounded_s10;
    assign activation_compare_i_minimum = arithmetic_minimum;
    assign activation_compare_i_maximum = arithmetic_maximum;
    requant_activation_compare u_activation_compare (
        .i_value(activation_compare_i_value),
        .i_minimum(activation_compare_i_minimum),
        .i_maximum(activation_compare_i_maximum),
        .o_below_minimum(activation_compare_o_below),
        .o_above_maximum(activation_compare_o_above)
    );

    // 通道端只执行二选一，相邻数据位可共用同一个查找表的两个输出。
    assign parameter_mux_i_direct = common_parameters;
    assign parameter_mux_i_shifted = {ch_multiplier_lane_r[j], ch_shift_lane_r[j]};
    assign parameter_mux_i_select = ws_parameters_select;
    assign {mult_sel, shift_sel_raw} = parameter_mux_o_value;
    assign quant_multiplier_lane[j] = mult_sel;
    assign quant_shift_lane[j] = shift_sel_raw;
    requant_shift_mux #(.p_width(p_parameter_width)) u_parameter_mux (
        .i_direct(parameter_mux_i_direct),
        .i_shifted(parameter_mux_i_shifted),
        .i_select(parameter_mux_i_select),
        .o_value(parameter_mux_o_value)
    );

    // WS 参数与 IS 同步读结果占用同一个输入周期，再选择本次运算参数。
    assign product_parameter_mux_i_direct = common_product_parameters_s0;
    assign product_parameter_mux_i_shifted = {ws_product_multiplier_s0, ws_product_amount_s0};
    assign product_parameter_mux_i_select = ws_parameters_select_s0;
    assign {product_multiplier_sel, product_amount_sel} = product_parameter_mux_o_value;
    assign amount_s0 = product_amount_sel;
    requant_shift_mux #(.p_width(p_product_parameter_width)) u_product_parameter_mux (
        .i_direct(product_parameter_mux_i_direct),
        .i_shifted(product_parameter_mux_i_shifted),
        .i_select(product_parameter_mux_i_select),
        .o_value(product_parameter_mux_o_value)
    );

    logic shift_en;
    logic signed [33:0] shift_o_quotient;
    logic shift_o_increment;

    // 乘积的移位、溢出检查和舍入信息占用七个时钟边沿，保持通道输出延迟。
    assign shift_en = !init_cfg;
    assign quotient_s9 = shift_o_quotient;
    assign round_increment_s9 = shift_o_increment;
    requant_shift_pipeline u_shift (
        .clk         (clk),
        .i_en        (shift_en),
        .i_product   (prod_s2),
        .i_amount    (amount_s2),
        .o_quotient  (shift_o_quotient),
        .o_increment (shift_o_increment)
    );

    always_ff @(posedge clk) begin
      if (!rst_n) begin
        lane_en_s0    <= 1'b0;
        lane_en_s1    <= 1'b0;
        lane_en_s2    <= 1'b0;
        lane_en_s3    <= 1'b0;
        lane_en_s4    <= 1'b0;
        lane_en_s5    <= 1'b0;
        lane_en_s6    <= 1'b0;
        lane_en_s7    <= 1'b0;
        lane_en_s8    <= 1'b0;
        lane_en_s9    <= 1'b0;
        lane_en_s10   <= 1'b0;
        out_vec_s8[j] <= '0;
        out_vec_s16[j] <= '0;
      end else if (init_cfg) begin
        lane_en_s0    <= 1'b0;
        lane_en_s1    <= 1'b0;
        lane_en_s2    <= 1'b0;
        lane_en_s3    <= 1'b0;
        lane_en_s4    <= 1'b0;
        lane_en_s5    <= 1'b0;
        lane_en_s6    <= 1'b0;
        lane_en_s7    <= 1'b0;
        lane_en_s8    <= 1'b0;
        lane_en_s9    <= 1'b0;
        lane_en_s10   <= 1'b0;
        out_vec_s8[j] <= '0;
        out_vec_s16[j] <= '0;
      end else begin
        lane_en_s0  <= accept_valid && (i_dw_enable ? i_dw_mask[j] :
            (j < (cfg_per_channel_eff ? lane_need_q : lane_need_cur)));
        lane_en_s1  <= lane_en_s0;
        lane_en_s2  <= lane_en_s1;
        lane_en_s3  <= lane_en_s2;
        lane_en_s4  <= lane_en_s3;
        lane_en_s5  <= lane_en_s4;
        lane_en_s6  <= lane_en_s5;
        lane_en_s7  <= lane_en_s6;
        lane_en_s8  <= lane_en_s7;
        lane_en_s9  <= lane_en_s8;
        lane_en_s10 <= lane_en_s9;

        if (!lane_en_s10) out_vec_s16[j]<=16'sd0;
        else if (activation_compare_o_below) out_vec_s16[j]<=arithmetic_minimum[15:0];
        else if (activation_compare_o_above) out_vec_s16[j]<=arithmetic_maximum[15:0];
        else if (rounded_s10 < -36'sd32768) out_vec_s16[j]<=-16'sd32768;
        else if (rounded_s10 > 36'sd32767) out_vec_s16[j]<=16'sd32767;
        else out_vec_s16[j]<=rounded_s10[15:0];

        if (!lane_en_s10) begin
          out_vec_s8[j] <= 8'sd0;
        end else if (activation_compare_o_below) begin
          out_vec_s8[j] <= arithmetic_minimum[7:0];
        end else if (activation_compare_o_above) begin
          out_vec_s8[j] <= arithmetic_maximum[7:0];
        end else if (rounded_s10 > 36'sd127) begin
          out_vec_s8[j] <= 8'sd127;
        end else if (rounded_s10 < -36'sd128) begin
          out_vec_s8[j] <= -8'sd128;
        end else begin
          out_vec_s8[j] <= rounded_s10[7:0];
        end
      end
    end

    always_ff @(posedge clk) begin
      if (!init_cfg) begin
        ws_product_multiplier_s0 <= i_dw_enable ? i_dw_multiplier[j] : ch_product_multiplier_lane_r[j];
        ws_product_amount_s0 <= i_dw_enable ? {1'b0,i_dw_right[j]} : ch_product_amount_lane_r[j];
        amount_s1 <= amount_s0;
        amount_s2 <= amount_s1;
      end
    end
  end
  end

  if (p_compute_lanes < VLEN) begin : g_serial_arithmetic
    localparam int p_batches = VLEN / p_compute_lanes;
    localparam int p_batch_width = (p_batches <= 1) ? 1 : $clog2(p_batches);
    localparam int p_stages = 12;
    logic [p_batch_width-1:0] batch_q;
    logic [p_batch_width-1:0] batch_pipe_q [p_stages];
    logic [p_stages-1:0] tile_done_pipe_q;
    logic row_i_group_start, row_i_clear, row_i_valid, row_i_tile_done;
    logic [31:0] row_i_group_rows;
    logic signed [31:0] row_i_data [VLEN], row_o_data [VLEN];
    logic row_o_group_ready, row_o_valid, row_o_tile_done;
    logic row_i_ready, row_i_output_valid;
    logic issue_valid, last_batch, parameters_ready_q;
    logic [p_bank_index_width-1:0] parameter_bank_q;
    logic signed [31:0] common_multiplier;
    logic [6:0] common_amount;
    logic lane_o_valid [p_compute_lanes];
    logic signed [7:0] lane_o_s8 [p_compute_lanes];
    logic signed [15:0] lane_o_s16 [p_compute_lanes];

    assign row_i_group_start = i_group_start;
    assign row_i_group_rows = i_group_rows;
    assign row_i_clear = init_cfg;
    assign row_i_valid = in_valid;
    assign row_i_tile_done = in_tile_done;
    assign row_i_data = in_vec_s32;
    assign o_group_ready = row_o_group_ready;
    assign issue_valid = row_o_valid && parameters_ready_q &&
        (!cfg_per_channel_eff || quant_params_valid) && !init_cfg;
    assign last_batch = batch_q == p_batch_width'(p_batches-1);
    assign row_consume_valid = issue_valid && last_batch;
    assign row_consume_tile_done = row_o_tile_done;
    assign row_i_ready = row_consume_valid;
    assign row_i_output_valid = out_valid;

    requant_group_buffer #(.p_lanes(VLEN), .p_rows(p_input_rows)) u_group_buffer (
        .clk(clk), .rst_n(rst_n), .i_clear(row_i_clear),
        .i_group_start(row_i_group_start), .i_group_rows(row_i_group_rows),
        .o_group_ready(row_o_group_ready),
        .i_row_valid(row_i_valid), .i_row_tile_done(row_i_tile_done), .i_row_data(row_i_data),
        .o_row_valid(row_o_valid), .o_row_tile_done(row_o_tile_done), .o_row_data(row_o_data),
        .i_row_ready(row_i_ready), .i_output_valid(row_i_output_valid)
    );

    // 最后一批发射时读取下一行参数，读取结果与下一行缓存同时更新。
    // 原始参数的观察端口仍由当前行坐标选择。
    always_comb begin
      parameter_read_idx = input_group_idx_cur;
      if (row_consume_valid) begin
        if (row_consume_tile_done) begin
          parameter_read_idx = QBUF_IDX_W'(
              REG_WIDTH'(next_tile_row_cur & ia_reuse_mask_tile_r) << VLEN_SHIFT);
        end else begin
          parameter_read_idx = input_group_idx_cur + 1'b1;
        end
      end
    end
    always_ff @(posedge clk) begin
      if (!init_cfg) parameter_bank_q <= p_bank_index_width'(int'(parameter_read_idx) % PARAM_BANKS);
    end
    // 装载完成后留出同步读边沿，保证仅一行参数的短组也取得本次装载值。
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) parameters_ready_q <= 1'b0;
      else if (init_cfg) parameters_ready_q <= 1'b0;
      else parameters_ready_q <= !cfg_per_channel_eff || quant_params_valid;
    end
    assign common_multiplier = cfg_per_channel_eff ?
        ch_product_multiplier_is_read[parameter_bank_q] : pt_product_multiplier_r;
    assign common_amount = cfg_per_channel_eff ?
        ch_product_amount_is_read[parameter_bank_q] : pt_product_amount_r;

    for (genvar lane = 0; lane < VLEN; lane++) begin : g_parameter_output
      assign quant_multiplier_lane[lane] = ws_parameters_select ?
          ch_multiplier_lane_r[lane] : $signed(common_parameters[63:32]);
      assign quant_shift_lane[lane] = ws_parameters_select ?
          ch_shift_lane_r[lane] : $signed(common_parameters[31:0]);
    end

    for (genvar lane = 0; lane < p_compute_lanes; lane++) begin : g_compute_lane
      logic lane_i_en, lane_i_clear, lane_i_valid, lane_i_lane_enable, lane_i_s16;
      logic [VLEN_IDX_W-1:0] element_index;
      logic signed [31:0] lane_i_value, lane_i_multiplier, lane_i_dst_offset;
      logic signed [31:0] lane_i_activation_min, lane_i_activation_max;
      logic [6:0] lane_i_amount;

      assign element_index = VLEN_IDX_W'(batch_q * p_compute_lanes + lane);
      assign lane_i_en = 1'b1;
      assign lane_i_clear = init_cfg;
      assign lane_i_valid = issue_valid;
      assign lane_i_lane_enable = 32'(element_index) <
          (cfg_per_channel_eff ? lane_need_q : lane_need_cur);
      assign lane_i_s16 = s16_mode;
      assign lane_i_value = row_o_data[element_index];
      assign lane_i_multiplier = ws_parameters_select ?
          ch_product_multiplier_lane_r[element_index] : common_multiplier;
      assign lane_i_amount = ws_parameters_select ?
          ch_product_amount_lane_r[element_index] : common_amount;
      assign lane_i_dst_offset = dst_offset_r;
      assign lane_i_activation_min = activation_min_r;
      assign lane_i_activation_max = activation_max_r;

      requant_compute_lane u_lane (
          .clk(clk), .rst_n(rst_n), .i_en(lane_i_en), .i_clear(lane_i_clear),
          .i_valid(lane_i_valid), .i_lane_enable(lane_i_lane_enable),
          .i_value(lane_i_value), .i_multiplier(lane_i_multiplier), .i_amount(lane_i_amount),
          .i_s16(lane_i_s16), .i_dst_offset(lane_i_dst_offset),
          .i_activation_min(lane_i_activation_min), .i_activation_max(lane_i_activation_max),
          .o_valid(lane_o_valid[lane]), .o_s8(lane_o_s8[lane]), .o_s16(lane_o_s16[lane])
      );
    end

    // 各批次使用相同的十二级有效流水，完整一行组装后产生一个输出有效周期。
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        batch_q <= '0;
        tile_done_pipe_q <= '0;
        out_valid <= 1'b0;
        out_tile_done <= 1'b0;
        for (int stage = 0; stage < p_stages; stage++) batch_pipe_q[stage] <= '0;
        for (int lane = 0; lane < VLEN; lane++) begin
          out_vec_s8[lane] <= '0;
          out_vec_s16[lane] <= '0;
        end
      end else if (init_cfg) begin
        batch_q <= '0;
        tile_done_pipe_q <= '0;
        out_valid <= 1'b0;
        out_tile_done <= 1'b0;
        for (int stage = 0; stage < p_stages; stage++) batch_pipe_q[stage] <= '0;
        for (int lane = 0; lane < VLEN; lane++) begin
          out_vec_s8[lane] <= '0;
          out_vec_s16[lane] <= '0;
        end
      end else begin
        if (issue_valid) batch_q <= last_batch ? '0 : batch_q + 1'b1;
        batch_pipe_q[0] <= batch_q;
        for (int stage = 1; stage < p_stages; stage++)
          batch_pipe_q[stage] <= batch_pipe_q[stage-1];
        tile_done_pipe_q <= {tile_done_pipe_q[p_stages-2:0],
                            row_consume_valid && row_o_tile_done};
        out_valid <= lane_o_valid[0] &&
            (batch_pipe_q[p_stages-1] == p_batch_width'(p_batches-1));
        out_tile_done <= lane_o_valid[0] && tile_done_pipe_q[p_stages-1];
        if (lane_o_valid[0]) begin
          for (int lane = 0; lane < p_compute_lanes; lane++) begin
            out_vec_s8[batch_pipe_q[p_stages-1]*p_compute_lanes+lane] <= lane_o_s8[lane];
            out_vec_s16[batch_pipe_q[p_stages-1]*p_compute_lanes+lane] <= lane_o_s16[lane];
          end
        end
      end
    end
  end

endmodule

// 定宽加法在一个使能边沿后更新结果，支持与原寄存数据通路相同的暂停行为。
module requant_registered_sum #(
    parameter int p_width = 48,
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
    input  wire logic clk,
    input  wire logic i_en,
    input  wire logic signed [p_width-1:0] i_lhs,
    input  wire logic signed [p_width-1:0] i_rhs,
    input  wire logic i_carry,
    output logic signed [p_width-1:0] o_sum
);
    // p_use_dsp 仅保留实例参数兼容；无复位、使能保持与原寄存器一致。
    generate
        begin : g_generic
            logic [p_width-1:0] next_sum;
            logic unused_carry;
            assign {unused_carry, next_sum} = {1'b0, i_lhs} + {1'b0, i_rhs} + (p_width+1)'(i_carry);
            always_ff @(posedge clk) begin
                if (i_en) begin
                    o_sum <= $signed(next_sum);
                end
            end
        end
    endgenerate
endmodule

// 有符号乘积右移：保留三十四位商、保护位和舍弃位，支持每周期一组输入。
module requant_shift_pipeline (
    input  wire logic               clk,
    input  wire logic               i_en,
    input  wire logic signed [63:0] i_product,
    input  wire logic        [6:0]  i_amount,
    output logic signed [33:0] o_quotient,
    output logic              o_increment
);
    //! 0. 辅助定义
    //! -----------

    logic signed [65:0] shifted_stage [6];
    logic [6:0] amount_stage [6];
    logic overflow_stage [6];
    logic sign_stage [6];
    logic signed [33:0] bounded_quotient;
    logic round_increment;
    logic signed [33:0] quotient_stage_q;
    logic increment_stage_q;

    //! 1. 输入编码
    //! -----------

    assign shifted_stage[0] = {i_product, 2'b00};
    assign amount_stage[0] = i_amount;
    assign overflow_stage[0] = 1'b0;
    assign sign_stage[0] = i_product[63];

    //! 2. 寄存移位结果
    //! ---------------

    // 首级合并三十二位和十六位选择。后续仅保留最终商及尚未移出的位，
    // 每次缩窄前记录符号扩展不成立的情况，避免丢失最终饱和方向。
    for (genvar stage = 0; stage < 5; stage++) begin : g_shift
        localparam int p_distance = 16 >> stage;
        localparam int p_input_width = (stage == 0) ? 66 : 35 + (32 >> stage);
        localparam int p_output_width = 35 + p_distance;
        logic signed [p_input_width-1:0] input_value;
        logic signed [p_input_width-1:0] coarse_value;
        logic signed [p_input_width-1:0] shifted_value;
        logic signed [p_output_width-1:0] stored_value_q;
        logic [6:0] stored_amount_q;
        logic stored_overflow_q;
        logic stored_sign_q;
        logic new_overflow;

        assign input_value = shifted_stage[stage][p_input_width-1:0];
        if (stage == 0) begin : g_coarse_shift
            assign coarse_value = amount_stage[stage][5] ?
                {{32{input_value[p_input_width-1]}}, input_value[p_input_width-1:33], (|input_value[32:0])} :
                input_value;
        end else begin : g_direct_input
            assign coarse_value = input_value;
        end
        if (stage == 0) begin : g_first_selection
            assign shifted_value = amount_stage[stage][4-stage] ?
                {{p_distance{coarse_value[p_input_width-1]}}, coarse_value[p_input_width-1:p_distance+1],
                 (|coarse_value[p_distance:0])} : coarse_value;
        end else begin : g_paired_selection
            logic [p_input_width-2:0] mux_i_direct;
            logic [p_input_width-2:0] mux_i_shifted;
            logic mux_i_select;
            logic [p_input_width-2:0] mux_o_value;

            assign mux_i_direct = coarse_value[p_input_width-2:0];
            assign mux_i_shifted = {{(p_distance-1){coarse_value[p_input_width-1]}},
                coarse_value[p_input_width-1:p_distance+1], (|coarse_value[p_distance:0])};
            assign mux_i_select = amount_stage[stage][4-stage];
            assign shifted_value = {coarse_value[p_input_width-1], mux_o_value};
            requant_shift_mux #(.p_width(p_input_width-1)) u_mux (
                .i_direct (mux_i_direct),
                .i_shifted(mux_i_shifted),
                .i_select (mux_i_select),
                .o_value  (mux_o_value)
            );
        end
        assign new_overflow = shifted_value[p_input_width-1:p_output_width-1] !=
            {(p_input_width-p_output_width+1){shifted_value[p_output_width-1]}};

        always_ff @(posedge clk) begin
            if (i_en) begin
                stored_value_q <= shifted_value[p_output_width-1:0];
                stored_amount_q <= amount_stage[stage];
                stored_overflow_q <= overflow_stage[stage] || new_overflow;
                stored_sign_q <= sign_stage[stage];
            end
        end
        assign shifted_stage[stage+1] = {{(66-p_output_width){stored_value_q[p_output_width-1]}}, stored_value_q};
        assign amount_stage[stage+1] = stored_amount_q;
        assign overflow_stage[stage+1] = stored_overflow_q;
        assign sign_stage[stage+1] = stored_sign_q;
    end

    // 大于六十三位的移位返回零；溢出时按原始符号选择饱和值。
    always_comb begin
        bounded_quotient = $signed(shifted_stage[5][35:2]);
        if (amount_stage[5][6]) begin
            bounded_quotient = '0;
        end else if (overflow_stage[5]) begin
            bounded_quotient = sign_stage[5] ? 34'sh200000000 : 34'sh1ffffffff;
        end
    end
    assign round_increment = (amount_stage[5] != 7'd0) && !amount_stage[5][6] &&
        shifted_stage[5][1] && (shifted_stage[5][0] || shifted_stage[5][2]);

    // 两级商寄存与量化通道的有效位同步，使完整量化仍为十二个寄存阶段。
    always_ff @(posedge clk) begin
        if (i_en) begin
            quotient_stage_q <= bounded_quotient;
            increment_stage_q <= round_increment;
            o_quotient <= quotient_stage_q;
            o_increment <= increment_stage_q;
        end
    end
endmodule


// 选择当前移位阶段的直接输入或候选移位结果。
module requant_shift_mux #(
    parameter int p_width = 2
) (
    input  wire logic [p_width-1:0] i_direct,
    input  wire logic [p_width-1:0] i_shifted,
    input  wire logic               i_select,
    output logic [p_width-1:0] o_value
);
    assign o_value = i_select ? i_shifted : i_direct;
endmodule

// 根据完整三十六位结果与两个三十二位有符号边界产生激活裁剪条件。
module requant_activation_compare (
    input  wire logic signed [35:0] i_value,
    input  wire logic signed [31:0] i_minimum,
    input  wire logic signed [31:0] i_maximum,
    output logic               o_below_minimum,
    output logic               o_above_maximum
);
    //! 0. 比较分组信号
    //! -----------------

    logic [1:0] bound_less;

    //! 1. 并行比较数据分组
    //! -------------------

    // 八位分组独立计算大小与相等关系，最高四位按有符号数解释。
    // 分组输出形成组合边界，高位相等条件与各组大小关系并行合并。
    for (genvar bound_index = 0; bound_index < 2; bound_index++) begin : g_bound
        logic [35:0] lhs, rhs;
        (* keep = 1 *) logic [4:0] equal_group, greater_group;
        logic [4:0] greater_selected;
        logic greater_or_equal;

        if (bound_index == 0) begin : g_minimum
            assign lhs = i_value;
            assign rhs = {{4{i_minimum[31]}}, i_minimum};
        end else begin : g_maximum
            assign lhs = {{4{i_maximum[31]}}, i_maximum};
            assign rhs = i_value;
        end
        for (genvar group_index = 0; group_index < 5; group_index++) begin : g_group
            localparam int p_group_width = (group_index == 4) ? 4 : 8;

            assign equal_group[group_index] =
                lhs[8*group_index +: p_group_width] == rhs[8*group_index +: p_group_width];
            if (group_index == 4) begin : g_signed
                assign greater_group[group_index] = $signed(lhs[35:32]) > $signed(rhs[35:32]);
                assign greater_selected[group_index] = greater_group[group_index];
            end else begin : g_unsigned
                assign greater_group[group_index] =
                    lhs[8*group_index +: 8] > rhs[8*group_index +: 8];
                assign greater_selected[group_index] = greater_group[group_index] &
                    (&equal_group[4:group_index+1]);
            end
        end
        assign greater_or_equal = (|greater_selected) | (&equal_group);
        assign bound_less[bound_index] = !greater_or_equal;
    end

    //! 2. 输出比较结果
    //! ---------------

    assign o_below_minimum = bound_less[0];
    assign o_above_maximum = bound_less[1];

endmodule

`default_nettype wire
