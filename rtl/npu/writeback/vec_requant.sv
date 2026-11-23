// SPDX-License-Identifier: Apache-2.0
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
    parameter int unsigned p_input_rows = VLEN * MAX_IA_REUSE,
    // 原始参数观察接口独立于量化计算，实例可按实际连接选择。
    parameter bit p_parameter_output = 1'b1
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
    // 整张量模式使用常量，逐通道模式使用参数存储的基地址。
    input wire logic signed [31:0] multiplier_in,
    input wire logic signed [31:0] shift_in,
    input wire logic        [31:0] k,                  // 行数
    input wire logic        [31:0] m,                  // 列数
    input wire logic        [31:0] ia_reuse_num_in,    // 输出分块的行复用顺序

    // 量化参数装载请求与许可。
    output logic load_quant_req,
    input  wire logic load_quant_granted,
    output logic quant_params_valid,

    // 逐通道量化参数的 DMA 读取接口。
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

    // 深度卷积输入在数据输入级采样，输出标签随有效信号传播。
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

  localparam int p_pipeline_stages = requant_pkg::REQUANT_LATENCY;

  logic s16_mode;
  always_ff @(posedge clk) begin
    if (!rst_n) s16_mode<=1'b0;
    else if (init_cfg) s16_mode<=ENABLE_S16 && cfg_s16;
  end

  localparam int BYTES_PER_WORD = REG_WIDTH / 8;  // 三十二位参数占四个字节
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

  // LOAD 状态依次装载乘数和移位参数。
  typedef enum logic [0:0] {
    PH_MUL   = 1'b0,
    PH_SHIFT = 1'b1
  } phase_e;
  phase_e          load_phase;  // 当前参数装载阶段

  tile_idx_t       tile_col;  // 当前列分块编号
  logic [VLEN_CNT_W-1:0] row_in_tile_cnt;  // 当前分块已完成的行数
  logic     [31:0] lane_need_cur;  // 当前分块有效列数，尾块可少于 VLEN
  logic     [31:0] quant_need_cur;  // 当前分块需要装载的逐通道参数数量
  logic     [31:0] quant_tile_idx_cur;
  tile_idx_t       tile_row;  // 当前行分块编号
  logic     [31:0] rows_need_cur;  // 当前行分块的有效行数，尾块使用剩余行数
  logic     [31:0] lane_need_q;  // 保存有效通道数，用于屏蔽尾块的无效通道
  logic     [ 7:0] burst_len_cur;  // 当前突发的总线拍数减一
  tile_idx_t       reuse_group_base_row;
  tile_idx_t       row_offset_in_group;
  logic     [31:0] group_rows_need_cur;
  logic     [31:0] load_offset;
  logic     [31:0] chunk_need_cur;
  logic     [32:0] remaining_words;
  logic [VLEN_CNT_W-1:0] chunk_words;
  logic [VLEN_CNT_W-1:0] burst_word_index;
  logic cmd_has_more_prepare;
  logic cmd_has_more_r;

  // 逐通道参数装载的接收字数与突发控制。
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

  // 分块数量与任务完成状态。
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
  // 运行状态只使用已保存的串行配置，初始化边沿仍直接接收外部配置。
  wire cfg_control_per_channel;
`ifdef SYNTHESIS
  assign cfg_control_per_channel = (ENABLE_PER_CHANNEL != 0) ?
      ((p_compute_lanes < VLEN) ? serial_per_channel_q : cfg_per_channel) : 1'b0;
`else
  assign cfg_control_per_channel = cfg_per_channel_eff;
`endif


  // ----------------------------
  // 配置寄存
  // ----------------------------
  logic signed [31:0] pt_multiplier_r;  // 整张量模式的量化常量
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
  logic [31:0] mul_base_r, sh_base_r;  // 逐通道参数基地址
  logic        is_mode_r;

  // 原始参数和精度在配置边沿保存，预处理结果供运算输入级采样。
  assign pt_product_multiplier_r = requant_pkg::requant_prepare_multiplier(pt_multiplier_r, s16_mode);
  assign pt_product_amount_r = requant_pkg::requant_prepare_amount(pt_shift_r, s16_mode);

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
      // 逐通道参数基地址通过 multiplier_in 和 shift_in 接收。
      mul_base_r       <= multiplier_in;
      sh_base_r        <= shift_in;
      is_mode_r        <= cfg_dataflow_mode_eff;
      last_row_tile    <= (num_row_tiles_next == '0) ? '0 : (num_row_tiles_next - tile_idx_t'(1));
      last_col_tile    <= (num_col_tiles_next == '0) ? '0 : (num_col_tiles_next - tile_idx_t'(1));
    end
  end

  // 接收配置时计算分块数量。
  assign num_row_tiles_next = (k == 0) ? '0 : tile_idx_t'((k + VLEN - 1) >> VLEN_SHIFT);
  assign num_col_tiles_next = (m == 0) ? '0 : tile_idx_t'((m + VLEN - 1) >> VLEN_SHIFT);

  // ----------------------------
  // 分块有效通道数与尾块范围
  // ----------------------------
  logic [31:0] lane_start_cur;
  logic [31:0] row_start_cur;
  logic [31:0] lane_remaining_cur;
  logic [31:0] rows_remaining_cur;
  logic [31:0] reuse_group_row_start;
  logic [31:0] reuse_group_capacity;
  logic [31:0] group_rows_remaining_cur;
  logic [31:0] group_rows_difference, group_rows_subtrahend;
  logic unused_group_rows_carry;
  logic [32:0] group_rows_start_ext, group_rows_capacity_ext, group_rows_limit_inv;
  logic [32:0] group_rows_sum_bits, group_rows_carry_bits, group_rows_shifted_carry;
  logic [32:0] unused_group_rows_limit_sum;
  logic unused_group_rows_high_carry, group_rows_capacity_exceeds;
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

  assign reuse_group_base_row = tile_row & ~ia_reuse_mask_tile_r;
  assign row_offset_in_group = tile_row & ia_reuse_mask_tile_r;
  assign reuse_group_row_start = REG_WIDTH'(reuse_group_base_row) << VLEN_SHIFT;
  assign reuse_group_capacity = ia_reuse_num_r << VLEN_SHIFT;
  assign group_rows_subtrahend = ~reuse_group_row_start;
  // 各四位分组独立求差，组间并行产生借位，保留完整三十二位行数。
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_group_rows_difference (
      .i_a(k_r), .i_b(group_rows_subtrahend), .i_carry(1'b1),
      .o_sum(group_rows_difference), .o_carry(unused_group_rows_carry)
  );
  // 容量比较与差值并行计算，三十三位末端覆盖起点与容量相加的溢出。
  assign group_rows_start_ext = {1'b0, reuse_group_row_start};
  assign group_rows_capacity_ext = {1'b0, reuse_group_capacity};
  assign group_rows_limit_inv = ~{1'b0, k_r};
  assign group_rows_sum_bits = group_rows_start_ext ^ group_rows_capacity_ext ^ group_rows_limit_inv;
  assign group_rows_carry_bits = (group_rows_start_ext & group_rows_capacity_ext) |
      ((group_rows_start_ext | group_rows_capacity_ext) & group_rows_limit_inv);
  assign {unused_group_rows_high_carry, group_rows_shifted_carry} = {group_rows_carry_bits, 1'b0};
  parallel_prefix_add #(.p_width(33), .p_group_width(4), .p_preserve_groups(1'b1)) u_group_rows_limit (
      .i_a(group_rows_sum_bits), .i_b(group_rows_shifted_carry), .i_carry(1'b0),
      .o_sum(unused_group_rows_limit_sum), .o_carry(group_rows_capacity_exceeds)
  );

  // 每次进入 LOAD 前计算有效通道数和有效行数。
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

    group_rows_remaining_cur = (k_r > reuse_group_row_start)
                             ? group_rows_difference
                             : 32'd0;
    group_rows_need_cur = (k_r <= reuse_group_row_start) ? 32'd0 :
        !group_rows_capacity_exceeds ? reuse_group_capacity : group_rows_difference;
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

  // 保存当前有效通道数，供计算阶段屏蔽尾块。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      lane_need_q <= '0;
    end else if (init_cfg) begin
      lane_need_q <= '0;
    end else begin
      // 整张量模式按当前列分块更新有效通道数。
      if (!cfg_per_channel_eff) begin
        lane_need_q <= lane_need_cur;
      end  // 逐通道模式在参数有效时更新通道数
      else if (quant_params_valid) begin
        lane_need_q <= lane_need_cur;
      end
    end
  end

  // 完整三十三位差值同时给出剩余字数和借位，超过装载总数的偏移返回零。
  // 末拍编号的窄减法与范围判断并行，随后按 VLEN 上限选择饱和值。
  logic [32:0] remaining_words_inverse;
  logic unused_remaining_words_carry;
  assign remaining_words_inverse = ~{1'b0, load_offset};
  parallel_prefix_add #(.p_width(33), .p_preserve_groups(1'b1)) u_remaining_words (
      .i_a({1'b0, quant_need_load_r}), .i_b(remaining_words_inverse), .i_carry(1'b1),
      .o_sum(remaining_words), .o_carry(unused_remaining_words_carry)
  );
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

  // 命令准备时保存后续参数资格，等待许可和接收响应期间保持不变。
  if (REG_WIDTH == 32) begin : g_load_command_compare
    // 位级进位传递保留未知输入的四态传播语义。
    function automatic logic full_carry(
        input logic [31:0] left, right,
        input logic carry_in
    );
      logic carry;
      begin
        carry = carry_in;
        for (int bit_index = 0; bit_index < 32; bit_index++) begin
          carry = (left[bit_index] & right[bit_index]) |
              ((left[bit_index] | right[bit_index]) & carry);
        end
        full_carry = carry;
      end
    endfunction

    function automatic logic completion_with_unknown(
        input logic [31:0] offset, increment, limit
    );
      logic [31:0] inverse_limit, compressed_sum, compressed_carry;
      logic advance_carry, comparison_carry;
      begin
        inverse_limit = ~limit;
        compressed_sum = offset ^ increment ^ inverse_limit;
        compressed_carry = (offset & increment) | (offset & inverse_limit) |
            (increment & inverse_limit);
        advance_carry = full_carry(offset, increment, 1'b0);
        comparison_carry = full_carry(compressed_sum,
            {compressed_carry[30:0], 1'b0}, 1'b1);
        completion_with_unknown = !(advance_carry ^ compressed_carry[31] ^ comparison_carry);
      end
    endfunction

    // 当前突发最多接收 VLEN 个字，剩余量超过该值时还需发送下一条命令。
    always_comb begin
      case (^{quant_need_load_r, load_offset, chunk_words})
        1'b0, 1'b1: cmd_has_more_prepare =
            !remaining_words[32] && remaining_words[31:0] > 32'(VLEN);
        default: cmd_has_more_prepare = completion_with_unknown(
            load_offset, 32'(chunk_words), quant_need_load_r);
      endcase
    end
  end else begin : g_generic_load_command_compare
    assign cmd_has_more_prepare =
        (load_offset + REG_WIDTH'(chunk_words)) < quant_need_load_r;
  end

  // ----------------------------
  // DMA 命令与响应
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
  localparam int p_dma_address_width = REG_WIDTH > 32 ? REG_WIDTH : 32;
  logic [p_dma_address_width-1:0] dma_element_offset;
  logic [p_dma_address_width-1:0] dma_byte_offset;
  logic [p_dma_address_width-1:0] dma_multiplier_address;
  logic [p_dma_address_width-1:0] dma_shift_address;
  logic [31:0] load_next_offset;

  // 两类量化参数共用元素偏移，基地址分别相加后再选择，保持完整表达式位宽。
  assign dma_element_offset = quant_tile_idx_load_r * VLEN + load_offset;
  assign dma_byte_offset = dma_element_offset * BYTES_PER_WORD;
  assign dma_multiplier_address = mul_base_r + dma_byte_offset;
  assign dma_shift_address = sh_base_r + dma_byte_offset;
  assign load_next_offset = load_offset + REG_WIDTH'(beats_expect);
  assign dma_base_addr_cur = (load_phase == PH_MUL)
                           ? REG_WIDTH'(dma_multiplier_address)
                           : REG_WIDTH'(dma_shift_address);
  assign dma_base_addr = cmd_base_addr_r;
  assign dma_row_stride = REG_WIDTH'(REG_WIDTH / 8);
  assign dma_rows_to_read = REG_WIDTH'(1);
  assign dma_burst_len_m1 = cmd_burst_len_m1_r;
  assign dma_slot_id = 1'b0;
  assign dma_use_16bits = 1'b0;
  assign dma_lhs_zp = '0;

  // ----------------------------
  // 逐通道参数存储
  // ----------------------------
  localparam int VLEN_IDX_W = (VLEN <= 1) ? 1 : $clog2(VLEN);
  logic signed [31:0] ch_multiplier_lane_r[VLEN];
  logic signed [31:0] ch_shift_lane_r[VLEN];
  logic signed [31:0] ch_product_multiplier_lane_r[VLEN];
  logic [6:0] ch_product_amount_lane_r[VLEN];
  localparam int PARAM_BANKS = BUS_WIDTH / 32;
  localparam int p_serial_read_ports = (p_compute_lanes < VLEN) ? p_compute_lanes : 0;
  logic [VLEN_IDX_W-1:0] serial_element_index [p_compute_lanes];
  logic signed [31:0] serial_product_multiplier [p_compute_lanes];
  logic [6:0] serial_product_amount [p_compute_lanes];
  wire signed [31:0] serial_bank_multiplier [PARAM_BANKS][p_compute_lanes];
  wire [6:0] serial_bank_amount [PARAM_BANKS][p_compute_lanes];
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
    assign parameter_product_multiplier[word]=requant_pkg::requant_prepare_multiplier(value,s16_mode);
    assign parameter_product_amount[word]=requant_pkg::requant_prepare_amount(value,s16_mode);
    assign parameter_index[word]=quant_rsp_idx+QBUF_IDX_W'(word);
  end
  logic [QBUF_IDX_W-1:0] input_group_idx_cur;
  logic [QBUF_IDX_W-1:0] parameter_read_idx;
  logic row_consume_valid, row_consume_tile_done;
  for (genvar bank = 0; bank < PARAM_BANKS; bank++) begin : gen_is_parameter_bank
    localparam int BANK_DEPTH = (QBUF_DEPTH + PARAM_BANKS - 1) / PARAM_BANKS;
    localparam int BANK_ADDR_W = (BANK_DEPTH <= 1) ? 1 : $clog2(BANK_DEPTH);
    localparam int p_amount_values_per_word = (BANK_DEPTH > 128) ? 2 : 1;
    localparam int p_amount_data_width = 7 * p_amount_values_per_word;
    localparam int p_amount_depth = (BANK_DEPTH + p_amount_values_per_word - 1) / p_amount_values_per_word;
    localparam int p_amount_addr_width = (p_amount_depth <= 1) ? 1 : $clog2(p_amount_depth);
    logic write_enable;
    logic write_last;
    logic [BANK_ADDR_W-1:0] write_addr;
    logic signed [31:0] write_value;
    logic signed [31:0] write_product_multiplier;
    logic [6:0] write_product_amount;
    always_comb begin
      write_enable = 1'b0;
      write_last = 1'b0;
      write_addr = '0;
      write_value = '0;
      write_product_multiplier = '0;
      write_product_amount = '0;
      for (int word = 0; word < BUS_WIDTH/32; word++) begin
        if (rsp_hskd && is_mode_r &&
            (32'(rd_beats_cnt)+word) < 32'(beats_expect) &&
            (int'(parameter_index[word]) % PARAM_BANKS) == bank) begin
          write_enable = 1'b1;
          write_last = ({1'b0, 32'(parameter_index[word])} + 33'(PARAM_BANKS)) >=
              {1'b0, quant_need_load_r};
          write_addr = BANK_ADDR_W'(parameter_index[word] / PARAM_BANKS);
          write_value = parameter_value[word];
          write_product_multiplier = parameter_product_multiplier[word];
          write_product_amount = parameter_product_amount[word];
        end
      end
    end
    // 原始参数按接收字保存并组合读取；运算参数在输入采样边沿同步读取。
    // 乘数逐条写入，移位量按静态存储几何确定每个存储字的参数数量。
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
    logic [p_amount_addr_width-1:0] product_amount_i_wr_addr, product_amount_i_rd_addr;
    logic [p_amount_data_width-1:0] product_amount_i_wr_data, product_amount_o_rd_data;
    logic [6:0] amount_pair_low;
    logic amount_read_half;

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
    // 浅表逐条保存七位移位量，较深的表按装载顺序合并相邻两条参数。
    // 偶数地址暂存可跨突发保持；不足两条的尾部复制有效值填充未使用的高半字。
    assign product_amount_i_wr_en = shift_i_wr_en &&
        ((p_amount_values_per_word == 1) || write_addr[0] || write_last);
    assign product_amount_i_wr_addr = p_amount_addr_width'(write_addr / p_amount_values_per_word);
    assign product_amount_i_wr_data = (p_amount_values_per_word == 1) ?
        p_amount_data_width'(write_product_amount) :
        p_amount_data_width'({write_product_amount, (write_addr[0] ? amount_pair_low : write_product_amount)});
    assign product_amount_i_wr_mask = 1'b1;
    assign product_amount_i_rd_en = !init_cfg;
    assign product_amount_i_rd_addr =
        p_amount_addr_width'(product_multiplier_i_rd_addr / p_amount_values_per_word);
    assign ch_product_amount_is_read[bank] = (p_amount_values_per_word == 1) ?
        product_amount_o_rd_data[6:0] : product_amount_o_rd_data[amount_read_half*7 +: 7];

    // 初始化取消未完成的参数对；读地址低位与同步存储在同一边沿采样。
    always_ff @(posedge clk) begin
      if (!rst_n || init_cfg) begin
        amount_pair_low <= '0;
      end else if (shift_i_wr_en && !write_addr[0]) begin
        amount_pair_low <= write_product_amount;
      end
      if (product_amount_i_rd_en) begin
        amount_read_half <= product_multiplier_i_rd_addr[0];
      end
    end

    // 观察接口使用原始参数；算术流水使用独立的同步预处理参数。
    if (p_parameter_output) begin : g_parameter_output
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
    end else begin : g_parameter_output_zero
      assign multiplier_o_rd_data = '0;
      assign shift_o_rd_data = '0;
    end
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
        .p_data_width(p_amount_data_width), .p_depth(p_amount_depth), .p_addr_width(p_amount_addr_width),
        .p_write_unit(p_amount_data_width), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_product_amount (
        .clk(clk), .i_wr_en(product_amount_i_wr_en), .i_wr_addr(product_amount_i_wr_addr),
        .i_wr_data(product_amount_i_wr_data), .i_wr_mask(product_amount_i_wr_mask),
        .i_rd_en(product_amount_i_rd_en), .i_rd_addr(product_amount_i_rd_addr),
        .o_rd_data(product_amount_o_rd_data)
    );
  end
  // 连续 DMA 字按低位分配到不同存储组，同一存储组的通道共用写数据选择。
  // 每个通道保持独立存储位置，常量读地址同时提供全部 WS 通道参数。
  if (((PARAM_BANKS & (PARAM_BANKS - 1)) == 0) && (PARAM_BANKS <= VLEN) &&
      ((VLEN & (VLEN - 1)) == 0)) begin : g_ws_bank_write
    localparam int p_bank_depth = VLEN / PARAM_BANKS;
    localparam int p_read_ports = p_bank_depth + p_serial_read_ports;
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
      logic [p_read_ports-1:0] multiplier_i_rd_en;
      logic [p_read_ports-1:0][p_bank_addr_width-1:0] multiplier_i_rd_addr;
      logic [p_read_ports-1:0][63:0] multiplier_o_rd_data;
      logic shift_i_wr_en, shift_i_wr_mask;
      logic [p_bank_addr_width-1:0] shift_i_wr_addr;
      logic [38:0] shift_i_wr_data;
      logic [p_read_ports-1:0] shift_i_rd_en;
      logic [p_read_ports-1:0][p_bank_addr_width-1:0] shift_i_rd_addr;
      logic [p_read_ports-1:0][38:0] shift_o_rd_data;

      // 存储组数为二的幂时，一个总线拍为每个存储组提供一个字。
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

      // 串行计算直接读取当前批次的参数，读地址随批次选择独立存储端口。
      for (genvar lane = 0; lane < p_serial_read_ports; lane++) begin : g_serial_read
        assign multiplier_i_rd_addr[p_bank_depth + lane] =
            p_bank_addr_width'(serial_element_index[lane] / PARAM_BANKS);
        assign shift_i_rd_addr[p_bank_depth + lane] =
            p_bank_addr_width'(serial_element_index[lane] / PARAM_BANKS);
        assign serial_bank_multiplier[bank][lane] =
            $signed(multiplier_o_rd_data[p_bank_depth + lane][63:32]);
        assign serial_bank_amount[bank][lane] = shift_o_rd_data[p_bank_depth + lane][38:32];
      end

      regfile #(
          .p_data_width(64), .p_depth(p_bank_depth), .p_addr_width(p_bank_addr_width),
          .p_write_unit(64), .p_read_ports(p_read_ports), .p_sync_read(1'b0)
      ) u_multiplier (
          .clk(clk), .i_wr_en(multiplier_i_wr_en), .i_wr_addr(multiplier_i_wr_addr),
          .i_wr_data(multiplier_i_wr_data), .i_wr_mask(multiplier_i_wr_mask),
          .i_rd_en(multiplier_i_rd_en), .i_rd_addr(multiplier_i_rd_addr), .o_rd_data(multiplier_o_rd_data)
      );
      regfile #(
          .p_data_width(39), .p_depth(p_bank_depth), .p_addr_width(p_bank_addr_width),
          .p_write_unit(39), .p_read_ports(p_read_ports), .p_sync_read(1'b0)
      ) u_shift (
          .clk(clk), .i_wr_en(shift_i_wr_en), .i_wr_addr(shift_i_wr_addr),
          .i_wr_data(shift_i_wr_data), .i_wr_mask(shift_i_wr_mask),
          .i_rd_en(shift_i_rd_en), .i_rd_addr(shift_i_rd_addr), .o_rd_data(shift_o_rd_data)
      );
    end
    for (genvar lane = 0; lane < p_serial_read_ports; lane++) begin : g_serial_parameter
      assign serial_product_multiplier[lane] =
          serial_bank_multiplier[int'(serial_element_index[lane]) % PARAM_BANKS][lane];
      assign serial_product_amount[lane] =
          serial_bank_amount[int'(serial_element_index[lane]) % PARAM_BANKS][lane];
    end
  end else begin : g_ws_direct_write
    for (genvar lane = 0; lane < p_serial_read_ports; lane++) begin : g_serial_parameter
      assign serial_product_multiplier[lane] = ch_product_multiplier_lane_r[serial_element_index[lane]];
      assign serial_product_amount[lane] = ch_product_amount_lane_r[serial_element_index[lane]];
    end
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
  // 主状态机与参数装载
  // ----------------------------
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      // 复位任务状态、参数有效位和 DMA 命令状态。
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
          cmd_has_more_r     <= 1'b0;
	      load_meta_valid    <= 1'b0;
	      quant_need_load_r  <= 32'd0;
	      quant_tile_idx_load_r <= 32'd0;
	      load_quant_req     <= 1'b0;
      tile_col           <= '0;
      tile_row           <= '0;
      load_offset        <= 32'd0;
      all_tiles_done     <= 1'b0;
    end else begin
      // 接收新配置时重置分块坐标与装载计数。
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
          cmd_has_more_r     <= 1'b0;
	        load_meta_valid    <= 1'b0;
	        quant_need_load_r  <= 32'd0;
	        quant_tile_idx_load_r <= 32'd0;
	        tile_col           <= '0;
        tile_row           <= '0;
        load_offset        <= 32'd0;
        all_tiles_done     <= 1'b0;  // 新配置开始时清除完成状态

      end else begin

        case (state)
          // ----------------------
	          IDLE: begin
	            rd_beats_cnt    <= '0;
	            cmd_busy        <= 1'b0;
	            cmd_valid_r     <= 1'b0;
	            row_in_tile_cnt <= '0;

            // 全部分块完成后保持空闲，等待新的配置。
            if (all_tiles_done) begin
              load_quant_req <= 1'b0;
            end else begin
              // 装载请求保持至收到许可。
              if (cfg_control_per_channel && has_tiles_r && !quant_params_valid) begin
                load_quant_req <= 1'b1;
                if (load_quant_granted) begin
                  load_phase     <= PH_MUL;
                  load_offset    <= 32'd0;
                  load_meta_valid <= 1'b0;
                  state          <= LOAD;

                end
              end

              // 整张量模式或参数已经有效时接收输入行。
              if (!cfg_control_per_channel || quant_params_valid) begin
                if (row_consume_valid) begin
                  if (row_consume_tile_done) begin
                    row_in_tile_cnt <= '0;
                    all_tiles_done  <= final_tile_cur;

                    if (final_tile_cur) begin
                      tile_row <= '0;
                      tile_col <= '0;
                      load_quant_req <= 1'b0;
                      quant_params_valid <= cfg_control_per_channel ? 1'b0 : 1'b1;
                      state <= IDLE;
                    end else begin
                      tile_row <= next_tile_row_cur;
                      tile_col <= next_tile_col_cur;

                      if (!cfg_control_per_channel) begin
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
                    // IDLE 接收的首行已进入数据通路，行计数在同一边沿更新。
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
	            // 先保存本次 LOAD 的参数范围，命令寄存器读取已保存的尺寸。
	            if (!load_meta_valid) begin
	              load_meta_valid      <= 1'b1;
	              quant_need_load_r    <= quant_need_cur;
	              quant_tile_idx_load_r <= quant_tile_idx_cur;
	              load_offset          <= 32'd0;
	              load_quant_req       <= 1'b1;

	            end else if (!cmd_busy) begin
	              // 当前没有在途命令时，按装载阶段发送 DMA 读取命令。
	              if (!cmd_valid_r) begin

	                cmd_valid_r        <= 1'b1;
	                cmd_base_addr_r    <= dma_base_addr_cur;
	                cmd_burst_len_m1_r <= burst_len_cur;
	                cmd_beats_expect_r <= VLEN_CNT_W'(chunk_need_cur);
                  cmd_has_more_r     <= cmd_has_more_prepare;
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
	                beats_expect   <= cmd_beats_expect_r;  // 当前突发需要接收的参数字数

	              end
            end

            // 接收 DMA 响应并更新当前参数突发的字数。
            if (rsp_hskd && cmd_busy) begin

              rd_beats_cnt <= rd_beats_cnt + VLEN_CNT_W'(BUS_WIDTH/32);

              // 当前突发完成后推进装载阶段或结束参数装载。
              if ((rd_beats_cnt + VLEN_CNT_W'(BUS_WIDTH/32)) >= beats_expect) begin
                cmd_busy <= 1'b0;  // 本突发结束

                if (load_phase == PH_MUL) begin
                  if (cmd_has_more_r) begin
                    load_offset <= load_next_offset;
                  end else begin
                    // 乘数装载完成后切换至移位参数，从起始偏移发出读取命令。
                    load_phase  <= PH_SHIFT;
                    load_offset <= 32'd0;
                  end
                end else begin
                  if (cmd_has_more_r) begin
                    load_offset <= load_next_offset;
                  end else begin
                    // 移位参数装载完成后置位参数有效标志，并按当前输入选择运行状态。
                    quant_params_valid <= 1'b1;
                    load_offset        <= 32'd0;
                    load_meta_valid    <= 1'b0;

                    if (row_consume_valid) begin
                      state <= COMPUTE; // 同一拍接收到输入行时进入计算状态
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
                          quant_params_valid <= cfg_control_per_channel ? 1'b0 : 1'b1;
                  state <= IDLE;
                end else begin
                  tile_row <= next_tile_row_cur;
                  tile_col <= next_tile_col_cur;

                  if (!cfg_control_per_channel) begin
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
            // 非法状态返回空闲状态。
            state <= IDLE;
          end

        endcase
      end  // !init_cfg
    end  // !rst_n
  end

  // ----------------------------
  // 数据通路（并行逐拍输入，分时按批次组装输出行）
  // ----------------------------
  logic accept_valid, dw_accept;
  logic [VLEN-1:0] parallel_lane_valid;
  assign dw_accept = i_dw_valid && o_dw_ready;
  assign accept_valid = dw_accept ||
      (in_valid && !i_dw_enable && (!cfg_per_channel_eff || quant_params_valid));

  if (p_compute_lanes >= VLEN) begin : g_parallel_control
    logic [p_pipeline_stages-1:0] dw_owner_q, dw_tag_q, tile_done_q;
    assign o_dw_ready = i_dw_enable && !init_cfg && !in_valid;
    assign o_dw_valid = parallel_lane_valid[0] && dw_owner_q[p_pipeline_stages-1];
    assign o_dw_tag = dw_tag_q[p_pipeline_stages-1];
    assign row_consume_valid = in_valid && !i_dw_enable;
    assign row_consume_tile_done = in_tile_done;
    assign parameter_read_idx = input_group_idx_cur;
    assign o_group_ready = 1'b1;
    assign out_valid = parallel_lane_valid[0] && !dw_owner_q[p_pipeline_stages-1];
    assign out_tile_done = tile_done_q[p_pipeline_stages-1] && !dw_owner_q[p_pipeline_stages-1];
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        dw_owner_q <= '0;
        dw_tag_q <= '0;
        tile_done_q <= '0;
      end else if (init_cfg) begin
        dw_owner_q <= '0;
        dw_tag_q <= '0;
        tile_done_q <= '0;
      end else begin
        dw_owner_q <= {dw_owner_q[p_pipeline_stages-2:0], dw_accept};
        dw_tag_q <= {dw_tag_q[p_pipeline_stages-2:0], i_dw_tag};
        tile_done_q <= {tile_done_q[p_pipeline_stages-2:0], accept_valid && in_tile_done};
      end
    end
  end else begin : g_serial_control
    assign o_dw_ready = 1'b0;
    assign o_dw_valid = 1'b0;
    assign o_dw_tag = 1'b0;
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

  // IS 模式与整张量模式的参数由所有通道共用，先形成一个公共数据字。
  // 逐通道 WS 模式读取各通道独立参数，参数选择由当前工作模式决定。
  assign common_parameters = cfg_per_channel_eff ?
      {ch_multiplier_is_sel, ch_shift_is_sel} : {pt_multiplier_r, pt_shift_r};
  assign ws_parameters_select = cfg_per_channel_eff && !is_mode_r;
  assign common_product_parameters_s0 = per_channel_s0 ?
      {ch_product_multiplier_is_sel, ch_product_amount_is_sel} :
      {pt_product_multiplier_s0, pt_product_amount_s0};

  // 存储读地址、模式和整张量参数在数据输入级的同一边沿采样。
  always_ff @(posedge clk) begin
    if (!init_cfg) begin
      ws_parameters_select_s0 <= i_dw_enable || ws_parameters_select;
      per_channel_s0 <= cfg_per_channel_eff;
      parameter_bank_s0 <= p_bank_index_width'(int'(input_group_idx_cur) % PARAM_BANKS);
      pt_product_multiplier_s0 <= pt_product_multiplier_r;
      pt_product_amount_s0 <= pt_product_amount_r;
    end
  end

  // 同步参数表在数据接收后的下一个边沿提供乘数，通道只保存一次数据输入。
  if (p_compute_lanes >= VLEN) begin : g_parallel_arithmetic
    for (genvar lane = 0; lane < VLEN; lane++) begin : g_lane
      logic signed [31:0] ws_multiplier_q, lane_multiplier;
      logic [6:0] ws_amount_q, lane_amount;
      logic lane_i_valid, lane_i_lane_enable, lane_i_en, lane_i_clear, lane_i_s16;
      logic signed [31:0] lane_i_value, lane_i_multiplier, lane_i_dst_offset;
      logic signed [31:0] lane_i_activation_min, lane_i_activation_max;
      logic [6:0] lane_i_amount;
      logic lane_o_valid;
      logic signed [7:0] lane_o_s8;
      logic signed [15:0] lane_o_s16;
      assign lane_multiplier = ws_parameters_select_s0 ?
          ws_multiplier_q : $signed(common_product_parameters_s0[38:7]);
      assign lane_amount = ws_parameters_select_s0 ? ws_amount_q : common_product_parameters_s0[6:0];
      assign lane_i_lane_enable = i_dw_enable ? i_dw_mask[lane] :
          (lane < (cfg_per_channel_eff ? lane_need_q : lane_need_cur));
      assign quant_multiplier_lane[lane] = p_parameter_output ?
          (ws_parameters_select ? ch_multiplier_lane_r[lane] : $signed(common_parameters[63:32])) : '0;
      assign quant_shift_lane[lane] = p_parameter_output ?
          (ws_parameters_select ? ch_shift_lane_r[lane] : $signed(common_parameters[31:0])) : '0;
      always_ff @(posedge clk) begin
        if (!init_cfg) begin
          ws_multiplier_q <= i_dw_enable ? i_dw_multiplier[lane] : ch_product_multiplier_lane_r[lane];
          ws_amount_q <= i_dw_enable ? {1'b0, i_dw_right[lane]} : ch_product_amount_lane_r[lane];
        end
      end
      assign lane_i_en = 1'b1;
      assign lane_i_clear = init_cfg;
      assign lane_i_valid = accept_valid;
      assign lane_i_value = i_dw_enable ? i_dw_accumulator[lane] : in_vec_s32[lane];
      assign lane_i_multiplier = lane_multiplier;
      assign lane_i_amount = lane_amount;
      assign lane_i_s16 = i_dw_enable ? 1'b0 : s16_mode;
      assign lane_i_dst_offset = i_dw_enable ? i_dw_offset : dst_offset_r;
      assign lane_i_activation_min = i_dw_enable ? i_dw_minimum : activation_min_r;
      assign lane_i_activation_max = i_dw_enable ? i_dw_maximum : activation_max_r;
      assign parallel_lane_valid[lane] = lane_o_valid;
      assign out_vec_s8[lane] = lane_o_s8;
      assign out_vec_s16[lane] = lane_o_s16;
      requant_compute_lane #(.p_delayed_parameters(1'b1)) u_lane (
          .clk(clk), .rst_n(rst_n), .i_en(lane_i_en), .i_clear(lane_i_clear),
          .i_valid(lane_i_valid), .i_lane_enable(lane_i_lane_enable),
          .i_value(lane_i_value), .i_multiplier(lane_i_multiplier), .i_amount(lane_i_amount),
          .i_s16(lane_i_s16), .i_dst_offset(lane_i_dst_offset),
          .i_activation_min(lane_i_activation_min), .i_activation_max(lane_i_activation_max),
          .o_valid(lane_o_valid), .o_s8(lane_o_s8), .o_s16(lane_o_s16)
      );
    end
  end

  if (p_compute_lanes < VLEN) begin : g_serial_arithmetic
    localparam int p_batches = VLEN / p_compute_lanes;
    localparam int p_batch_width = (p_batches <= 1) ? 1 : $clog2(p_batches);
    localparam int p_stages = p_pipeline_stages;
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
    (* keep = 1 *) logic row_batch_ready;
    (* keep = 1 *) logic serial_parameters_available;
    assign serial_parameters_available = !cfg_control_per_channel || quant_params_valid;
    assign issue_valid = row_o_valid && parameters_ready_q &&
        serial_parameters_available && !init_cfg;
    assign last_batch = batch_q == p_batch_width'(p_batches-1);
    // 行缓存和末批位置并行判断，初始化与参数许可在末端合并。
    assign row_batch_ready = row_o_valid && parameters_ready_q && last_batch;
    assign row_consume_valid = row_batch_ready && serial_parameters_available && !init_cfg;
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
      else parameters_ready_q <= !cfg_control_per_channel || quant_params_valid;
    end
    assign common_multiplier = cfg_per_channel_eff ?
        ch_product_multiplier_is_read[parameter_bank_q] : pt_product_multiplier_r;
    assign common_amount = cfg_per_channel_eff ?
        ch_product_amount_is_read[parameter_bank_q] : pt_product_amount_r;

    for (genvar lane = 0; lane < VLEN; lane++) begin : g_parameter_output
      assign quant_multiplier_lane[lane] = p_parameter_output ?
          (ws_parameters_select ? ch_multiplier_lane_r[lane] : $signed(common_parameters[63:32])) : '0;
      assign quant_shift_lane[lane] = p_parameter_output ?
          (ws_parameters_select ? ch_shift_lane_r[lane] : $signed(common_parameters[31:0])) : '0;
    end

    for (genvar lane = 0; lane < p_compute_lanes; lane++) begin : g_compute_lane
      logic lane_i_en, lane_i_clear, lane_i_valid, lane_i_lane_enable, lane_i_s16;
      logic [VLEN_IDX_W-1:0] element_index;
      logic signed [31:0] lane_i_value, lane_i_multiplier, lane_i_dst_offset;
      logic signed [31:0] lane_i_activation_min, lane_i_activation_max;
      logic [6:0] lane_i_amount;

      assign element_index = VLEN_IDX_W'(batch_q * p_compute_lanes + lane);
      assign serial_element_index[lane] = element_index;
      assign lane_i_en = 1'b1;
      assign lane_i_clear = init_cfg;
      assign lane_i_valid = issue_valid;
      assign lane_i_lane_enable = 32'(element_index) <
          (cfg_per_channel_eff ? lane_need_q : lane_need_cur);
      assign lane_i_s16 = s16_mode;
      assign lane_i_value = row_o_data[element_index];
      assign lane_i_multiplier = ws_parameters_select ?
          serial_product_multiplier[lane] : common_multiplier;
      assign lane_i_amount = ws_parameters_select ?
          serial_product_amount[lane] : common_amount;
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

    // 批次编号与有效位经过同样的算术级数，完整一行组装后产生输出有效信号。
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

`default_nettype wire
