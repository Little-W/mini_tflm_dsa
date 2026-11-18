module vec_requant #(
    parameter int BUS_WIDTH = 32,
    parameter int VLEN         = 16,
    parameter int REG_WIDTH    = 32,
    parameter int MAX_IA_REUSE = 2,
    parameter int unsigned ENABLE_PER_CHANNEL = 1,
    parameter int unsigned ENABLE_IS_MODE = 1,
    parameter bit ENABLE_S16 = 1'b0
) (
    input logic clk,
    input logic rst_n,

    // 配置
    input logic               init_cfg,
    input logic               cfg_per_channel,
    input logic               cfg_dataflow_mode,
    input logic               cfg_s16 = 1'b0,
    input logic signed [31:0] activation_min_in,
    input logic signed [31:0] activation_max_in,
    input logic signed [31:0] dst_offset_in,
    // per-tensor 常量；per-channel 下这两个做为“基地址”使用
    input logic signed [31:0] multiplier_in,
    input logic signed [31:0] shift_in,
    input logic        [31:0] k,                  // 行数
    input logic        [31:0] m,                  // 列数
    input logic        [31:0] ia_reuse_num_in,    // 输出 tile 行复用顺序

    // 量化参数装载握手（外部可用；TB里通常 grant=req）
    output logic load_quant_req,
    input  logic load_quant_granted,
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
    input  logic [BUS_WIDTH-1:0]        dma_raw_data,
    input  logic                        dma_raw_valid,

    // 数据口
    input  logic               in_valid,
    input  logic               in_tile_done,
    input  logic signed [31:0] in_vec_s32[VLEN],
    output logic               out_valid,
    output logic               out_tile_done,
    output logic signed [ 7:0] out_vec_s8[VLEN],
    output logic signed [15:0] out_vec_s16[VLEN],
    output logic signed [31:0] quant_multiplier_lane[VLEN],
    output logic signed [31:0] quant_shift_lane[VLEN]
);

  generate
    if ((ENABLE_PER_CHANNEL == 0) && (ENABLE_IS_MODE == 0) && !ENABLE_S16) begin : g_tensor_ws
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
          .ENABLE_S16        (ENABLE_S16)
      ) u_full (
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
    input logic clk,
    input logic rst_n,

    input logic               init_cfg,
    input logic               cfg_per_channel,
    input logic               cfg_dataflow_mode,
    input logic signed [31:0] activation_min_in,
    input logic signed [31:0] activation_max_in,
    input logic signed [31:0] dst_offset_in,
    input logic signed [31:0] multiplier_in,
    input logic signed [31:0] shift_in,
    input logic        [31:0] k,
    input logic        [31:0] m,
    input logic        [31:0] ia_reuse_num_in,

    output logic load_quant_req,
    input  logic load_quant_granted,
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
    input  logic [BUS_WIDTH-1:0]        dma_raw_data,
    input  logic                        dma_raw_valid,

    input  logic               in_valid,
    input  logic               in_tile_done,
    input  logic signed [31:0] in_vec_s32[VLEN],
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
    parameter bit ENABLE_S16 = 1'b0
) (
    input logic clk,
    input logic rst_n,

    // 配置
    input logic               init_cfg,
    input logic               cfg_per_channel,
    input logic               cfg_dataflow_mode,
    input logic               cfg_s16 = 1'b0,
    input logic signed [31:0] activation_min_in,
    input logic signed [31:0] activation_max_in,
    input logic signed [31:0] dst_offset_in,
    // per-tensor 常量；per-channel 下这两个做为“基地址”使用
    input logic signed [31:0] multiplier_in,
    input logic signed [31:0] shift_in,
    input logic        [31:0] k,                  // 行数
    input logic        [31:0] m,                  // 列数
    input logic        [31:0] ia_reuse_num_in,    // 输出 tile 行复用顺序

    // 量化参数装载握手（外部可用；TB里通常 grant=req）
    output logic load_quant_req,
    input  logic load_quant_granted,
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
    input  logic [BUS_WIDTH-1:0]        dma_raw_data,
    input  logic                        dma_raw_valid,

    // 数据口
    input  logic               in_valid,
    input  logic               in_tile_done,
    input  logic signed [31:0] in_vec_s32[VLEN],
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

  function automatic logic signed [31:0] prepare_multiplier(
      input logic signed [31:0] value, input logic use_s16);
    logic signed [16:0] reduced;
    begin
      reduced = $signed({value[31],value[31:16]}) +
          ((value[15:0]>16'h8000 || (value[15:0]==16'h8000 && value[16])) ? 17'sd1 : 17'sd0);
      prepare_multiplier = (ENABLE_S16 && use_s16) ?
          (reduced>17'sd32767 ? 32'sd32767 : 32'($signed(reduced))) : value;
    end
  endfunction

  function automatic logic [6:0] prepare_amount(
      input logic signed [31:0] value, input logic use_s16);
    begin
      if (ENABLE_S16 && use_s16) begin
        if (value>=32'sd15 || value[31:4]==28'h8000000) prepare_amount=7'd0;
        else if (value < -32'sd48) prepare_amount=7'd63;
        else prepare_amount={1'b0,(6'd15-value[5:0])};
      end else begin
        if (value>32'sd0)
          prepare_amount=(value[5:0]>=6'd31) ? 7'd0 : {1'b0,(6'd31-value[5:0])};
        else if (value==32'sh80000000) prepare_amount=7'd31;
        else if (value < -32'sd32) prepare_amount=7'd64;
        else prepare_amount=7'd31+{1'b0,(6'd0-value[5:0])};
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

  wire cfg_per_channel_eff = (ENABLE_PER_CHANNEL != 0) ? cfg_per_channel : 1'b0;
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

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      pt_multiplier_r  <= '0;
      pt_shift_r       <= '0;
      pt_product_multiplier_r <= '0;
      pt_product_amount_r <= 7'd31;
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
      pt_product_multiplier_r <= prepare_multiplier(multiplier_in,cfg_s16);
      pt_product_amount_r <= prepare_amount(shift_in,cfg_s16);
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
    lane_need_cur = (lane_remaining_cur >= REG_WIDTH'(VLEN))
                  ? REG_WIDTH'(VLEN)
                  : lane_remaining_cur;
    rows_need_cur = (rows_remaining_cur >= REG_WIDTH'(VLEN))
                  ? REG_WIDTH'(VLEN)
                  : rows_remaining_cur;

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
    chunk_need_cur       = (quant_need_load_r > load_offset)
                         ? (((quant_need_load_r - load_offset) > VLEN)
                              ? VLEN
                              : (quant_need_load_r - load_offset))
                         : 32'd0;

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

  // DMA len = 需要拍数-1（0 表示 1 拍）
  always_comb begin
    burst_len_cur = 8'((chunk_need_cur > 0) ? ((chunk_need_cur+BUS_WIDTH/32-1)/(BUS_WIDTH/32) - 1) : 0);
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
  for (genvar bank = 0; bank < PARAM_BANKS; bank++) begin : gen_is_parameter_bank
    localparam int BANK_DEPTH = (QBUF_DEPTH + PARAM_BANKS - 1) / PARAM_BANKS;
    localparam int BANK_ADDR_W = (BANK_DEPTH <= 1) ? 1 : $clog2(BANK_DEPTH);
    (* ram_style = "distributed" *) logic signed [31:0] multiplier_mem [BANK_DEPTH];
    (* ram_style = "distributed" *) logic signed [31:0] shift_mem [BANK_DEPTH];
    (* ram_style = "distributed" *) logic signed [31:0] product_multiplier_mem[BANK_DEPTH];
    (* ram_style = "distributed" *) logic [6:0] product_amount_mem[BANK_DEPTH];
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
    always_ff @(posedge clk) begin
      if (write_enable) begin
        if (load_phase == PH_MUL) begin
          multiplier_mem[write_addr] <= write_value;
          product_multiplier_mem[write_addr] <= write_product_multiplier;
        end
        else begin
          shift_mem[write_addr] <= write_value;
          product_amount_mem[write_addr] <= write_product_amount;
        end
      end
    end
    assign ch_multiplier_is_read[bank] = multiplier_mem[BANK_ADDR_W'(input_group_idx_cur / PARAM_BANKS)];
    assign ch_shift_is_read[bank] = shift_mem[BANK_ADDR_W'(input_group_idx_cur / PARAM_BANKS)];
    assign ch_product_multiplier_is_read[bank] = product_multiplier_mem[BANK_ADDR_W'(input_group_idx_cur / PARAM_BANKS)];
    assign ch_product_amount_is_read[bank] = product_amount_mem[BANK_ADDR_W'(input_group_idx_cur / PARAM_BANKS)];
  end
  always @(posedge clk) begin
    for (integer word = 0; word < BUS_WIDTH/32; word++) begin
      if (rsp_hskd && !is_mode_r && (32'(rd_beats_cnt)+word)<32'(beats_expect)) begin
        if (load_phase==PH_MUL) begin
          ch_multiplier_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_value[word];
          ch_product_multiplier_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_product_multiplier[word];
        end
        else begin
          ch_shift_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_value[word];
          ch_product_amount_lane_r[VLEN_IDX_W'(parameter_index[word])] <= parameter_product_amount[word];
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
                if (in_valid) begin
                  if (in_tile_done) begin
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
                    // IDLE 中接住的第一拍 in_valid 已经被数据通路消费，
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
                  if ((load_offset + REG_WIDTH'(beats_expect)) < quant_need_load_r) begin
                    load_offset <= load_offset + REG_WIDTH'(beats_expect);
                  end else begin
                    // mul 收满 -> 切到 shift，下一拍会去发 shift 的命令
                    load_phase  <= PH_SHIFT;
                    load_offset <= 32'd0;
                  end
                end else begin
                  if ((load_offset + REG_WIDTH'(beats_expect)) < quant_need_load_r) begin
                    load_offset <= load_offset + REG_WIDTH'(beats_expect);
                  end else begin
                    // shift 也收满，参数就绪：同时锁存 lane_need，并根据当拍 in_valid 决定是否直接进 COMPUTE
                    quant_params_valid <= 1'b1;
                    load_offset        <= 32'd0;
                    load_meta_valid    <= 1'b0;
                    //lane_need_q        <= lane_need_cur;   // <-- 把 lane_need 在参数就绪时锁存

                    if (in_valid) begin
                      state <= COMPUTE; // 允许在同一时钟周期观察到 in_valid 并直接进入 COMPUTE
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

            if (in_valid) begin

              if (in_tile_done) begin
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

  assign accept_valid = in_valid && ((!cfg_per_channel_eff) || quant_params_valid);
  assign out_valid = stage11_valid;
  assign out_tile_done = stage11_tile_done;

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
  logic signed [31:0] ch_product_multiplier_is_sel;
  logic [6:0] ch_product_amount_is_sel;
  assign input_row_idx_cur = row_in_tile_cnt;
  assign input_group_idx_cur = QBUF_IDX_W'((REG_WIDTH'(row_offset_in_group) << VLEN_SHIFT) +
                                         REG_WIDTH'(input_row_idx_cur));
  always_comb begin
    ch_multiplier_is_sel = ch_multiplier_is_read[(int'(input_group_idx_cur) % PARAM_BANKS)];
    ch_product_multiplier_is_sel = ch_product_multiplier_is_read[(int'(input_group_idx_cur) % PARAM_BANKS)];
    ch_product_amount_is_sel = ch_product_amount_is_read[(int'(input_group_idx_cur) % PARAM_BANKS)];
  end

  // Parameters are normalized during configuration and DMA loading. Each lane
  // accepts one accumulator every cycle with twelve cycles of fixed latency.
  // Partial products and the six shift decisions use separate register stages.
  for (genvar j = 0; j < VLEN; j++) begin : LANE
    logic signed [31:0] mult_sel, shift_sel_raw;
    logic signed [31:0] product_multiplier_sel;
    logic [6:0] product_amount_sel;
    logic signed [31:0] acc_s0, mult_s0;
    logic [6:0] amount_s0;
    logic [6:0] amount_s1, amount_s2;
    (* use_dsp = "yes" *) logic signed [47:0] product_low_s1, product_high_s1;
    (* use_dsp = "yes" *) logic signed [47:0] product_high_s2;
    logic [15:0] product_low_s2;
    wire signed [63:0] prod_s2 = {product_high_s2,product_low_s2};
    logic lane_en_s0, lane_en_s1, lane_en_s2, lane_en_s3;
    logic lane_en_s4, lane_en_s5, lane_en_s6, lane_en_s7;
    logic lane_en_s8, lane_en_s9, lane_en_s10;
    logic signed [33:0] quotient_s9;
    logic round_increment_s9;
    (* use_dsp = "yes" *) logic signed [35:0] rounded_s10;

    always_comb begin
      if (cfg_per_channel_eff) begin
        mult_sel = is_mode_r ? ch_multiplier_is_sel : ch_multiplier_lane_r[j];
        shift_sel_raw = is_mode_r ? ch_shift_is_read[(int'(input_group_idx_cur) % PARAM_BANKS)]
                                  : ch_shift_lane_r[j];
        product_multiplier_sel = is_mode_r ? ch_product_multiplier_is_sel : ch_product_multiplier_lane_r[j];
        product_amount_sel = is_mode_r ? ch_product_amount_is_sel : ch_product_amount_lane_r[j];
      end else begin
        mult_sel = pt_multiplier_r;
        shift_sel_raw = pt_shift_r;
        product_multiplier_sel = pt_product_multiplier_r;
        product_amount_sel = pt_product_amount_r;
      end
      quant_multiplier_lane[j] = mult_sel;
      quant_shift_lane[j] = shift_sel_raw;
    end

    wire signed [65:0] shifted_stage [7];
    wire [6:0] amount_stage [7];
    wire overflow_stage [7];
    wire sign_stage [7];
    assign shifted_stage[0] = {prod_s2,2'b00};
    assign amount_stage[0] = amount_s2;
    assign overflow_stage[0] = 1'b0;
    assign sign_stage[0] = prod_s2[63];
    for (genvar stage=0;stage<6;stage++) begin : g_round_stage
      localparam int DISTANCE = 32 >> stage;
      localparam int PREVIOUS_DISTANCE = 64 >> stage;
      localparam int INPUT_WIDTH = (stage<2) ? 66 : 35+PREVIOUS_DISTANCE;
      localparam int OUTPUT_WIDTH = (35+DISTANCE>66) ? 66 : 35+DISTANCE;
      wire signed [INPUT_WIDTH-1:0] input_value = shifted_stage[stage][INPUT_WIDTH-1:0];
      wire signed [INPUT_WIDTH-1:0] shifted_value = amount_stage[stage][5-stage] ?
          {{DISTANCE{input_value[INPUT_WIDTH-1]}},input_value[INPUT_WIDTH-1:DISTANCE+1],
           (|input_value[DISTANCE:0])} : input_value;
      logic signed [OUTPUT_WIDTH-1:0] value_r;
      logic [6:0] amount_r;
      logic overflow_r, sign_r;
      wire new_overflow;
      if (OUTPUT_WIDTH < INPUT_WIDTH) begin : g_overflow
        assign new_overflow = shifted_value[INPUT_WIDTH-1:OUTPUT_WIDTH-1] !=
            {(INPUT_WIDTH-OUTPUT_WIDTH+1){shifted_value[OUTPUT_WIDTH-1]}};
      end else begin : g_same_width
        assign new_overflow = 1'b0;
      end
      always_ff @(posedge clk) begin
        if (!init_cfg) begin
          value_r <= shifted_value[OUTPUT_WIDTH-1:0];
          amount_r <= amount_stage[stage];
          overflow_r <= overflow_stage[stage] || new_overflow;
          sign_r <= sign_stage[stage];
        end
      end
      assign shifted_stage[stage+1] = {{(66-OUTPUT_WIDTH){value_r[OUTPUT_WIDTH-1]}},value_r};
      assign amount_stage[stage+1] = amount_r;
      assign overflow_stage[stage+1] = overflow_r;
      assign sign_stage[stage+1] = sign_r;
    end
    wire [35:0] shifted_s8 = shifted_stage[6][35:0];
    logic signed [33:0] bounded_quotient_s8;
    always_comb begin
      if (amount_stage[6][6]) bounded_quotient_s8 = '0;
      else if (!overflow_stage[6]) bounded_quotient_s8 = $signed(shifted_s8[35:2]);
      else bounded_quotient_s8 = sign_stage[6] ? 34'sh200000000 : 34'sh1ffffffff;
    end
    wire round_up_s8 = amount_stage[6] != 0 && !amount_stage[6][6] &&
        shifted_s8[1] && (shifted_s8[0] || shifted_s8[2]);

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
        lane_en_s0  <= accept_valid && (j < (cfg_per_channel_eff ? lane_need_q : lane_need_cur));
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
        else if (rounded_s10<$signed({{4{activation_min_r[31]}},activation_min_r})) out_vec_s16[j]<=activation_min_r[15:0];
        else if (rounded_s10>$signed({{4{activation_max_r[31]}},activation_max_r})) out_vec_s16[j]<=activation_max_r[15:0];
        else if (rounded_s10 < -36'sd32768) out_vec_s16[j]<=-16'sd32768;
        else if (rounded_s10 > 36'sd32767) out_vec_s16[j]<=16'sd32767;
        else out_vec_s16[j]<=rounded_s10[15:0];

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
        mult_s0 <= product_multiplier_sel;
        amount_s0 <= product_amount_sel;
        product_low_s1 <= acc_s0 * $signed({1'b0,mult_s0[15:0]});
        product_high_s1 <= acc_s0 * $signed(mult_s0[31:16]);
        amount_s1 <= amount_s0;
        product_high_s2 <= product_high_s1 +
            {{16{product_low_s1[47]}},product_low_s1[47:16]};
        product_low_s2 <= product_low_s1[15:0];
        amount_s2 <= amount_s1;
        quotient_s9 <= bounded_quotient_s8;
        round_increment_s9 <= round_up_s8;
        rounded_s10 <= {{2{quotient_s9[33]}},quotient_s9} +
            (s16_mode ? 36'sd0 : {{4{dst_offset_r[31]}},dst_offset_r}) +
            36'(round_increment_s9);
      end
    end
  end

endmodule
