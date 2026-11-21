`default_nettype none

module kernel_loader_ctrl #(
    parameter int unsigned SIZE      = 4,
    parameter int unsigned REG_WIDTH = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH
) (
    input  wire logic                        clk,
    input  wire logic                        rst_n,
    input  wire logic                        clear = 1'b0,
    input  wire logic                        cfg_valid,
    input  wire logic [REG_WIDTH-1:0]        cfg_k,
    input  wire logic [REG_WIDTH-1:0]        cfg_n,
    input  wire logic [REG_WIDTH-1:0]        cfg_m,
    input  wire logic [REG_WIDTH-1:0]        cfg_rhs_base,
    input  wire logic [REG_WIDTH-1:0]        cfg_rhs_row_stride_b,
    input  wire logic signed [REG_WIDTH-1:0] cfg_rhs_zp,
    input  wire logic                        cfg_use_16bits,
    input  wire logic                        cfg_tile_packed = 1'b0,
    input  wire logic [REG_WIDTH-1:0]        cfg_ia_reuse_num,
    input  wire logic [REG_WIDTH-1:0]        cfg_w_reuse_num,
    input wire logic [REG_WIDTH-1:0] cfg_row_groups,
    input wire logic [REG_WIDTH-1:0] cfg_row_tail_tiles,
    input wire logic [REG_WIDTH-1:0] cfg_col_groups,
    input wire logic [REG_WIDTH-1:0] cfg_col_tail_tiles,
    input  wire logic                        load_weight_granted,
    input  wire logic                        send_weight_trigger,
    input  wire logic                        buf_weight_data_valid,
    input  wire logic                        buf_weight_sending_done,
    input  wire logic                        buf_load_ready,
    input  wire logic                        load_done,
    output logic                        load_weight_req,
    output logic                        dma_start,
    output logic [REG_WIDTH-1:0]        dma_p0,
    output logic [REG_WIDTH-1:0]        dma_q0,
    output logic [REG_WIDTH-1:0]        dma_group,
    output logic [REG_WIDTH-1:0]        dma_tile_base_addr,
    output logic [REG_WIDTH-1:0]        o_column_group_base,
    output logic [REG_WIDTH-1:0]        o_column_group_offset,
    output logic [REG_WIDTH-1:0]        o_address_group_base,
    output logic [REG_WIDTH-1:0]        o_address_row_offset,
    output logic [REG_WIDTH-1:0]        o_address_column_offset,
    output logic                       o_descriptor_update,
    output logic [REG_WIDTH-1:0]        dma_rows_to_read,
    output logic [REG_WIDTH-1:0]        dma_row_stride_b,
    output logic signed [REG_WIDTH-1:0] dma_rhs_zp,
    output logic                        buf_load_start,
    output logic                        buf_send_start,
    output logic [REG_WIDTH-1:0]        dma_valid_cols,
    output logic                        ctrl_all_done,
    output logic [REG_WIDTH-1:0]        tile_row_dbg,
    output logic [REG_WIDTH-1:0]        tile_col_dbg,
    output logic [REG_WIDTH-1:0]        repeat_dbg
);

  localparam int unsigned SIZE_SHIFT = $clog2(SIZE);
  localparam int unsigned CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
  typedef logic [CNT_W-1:0] count_t;
  // 任务总数覆盖三个遍历维度的乘积，计数宽度保留每个维度的完整范围。
  localparam int unsigned TOTAL_CNT_W = 3 * CNT_W;
  typedef logic [TOTAL_CNT_W-1:0] total_count_t;

  typedef enum logic [1:0] {S_IDLE, S_INIT, S_RUN, S_DONE} state_t;

  state_t state;

  count_t tile_rows_total;
  count_t tile_cols_total;
  count_t l2_groups_total;
  count_t repeat_total;
  count_t current_group_width;
  count_t valid_n_rows;
  count_t valid_m_cols;
  logic [REG_WIDTH-1:0] elem_bytes;
  count_t w_reuse_norm;
  count_t ia_reuse_norm;
  count_t cfg_tile_rows_total;
  count_t cfg_tile_cols_total;
  count_t cfg_output_row_tiles_total;
  count_t cfg_l2_groups_total;
  count_t cfg_repeat_total;
  count_t last_n_rows;
  count_t last_m_cols;
  count_t cfg_last_n_rows;
  count_t cfg_last_m_cols;
  count_t cfg_group_tail_cols;
  count_t cfg_last_group_width;
  count_t first_group_width;

  count_t load_tile_row;
  count_t load_repeat;
  count_t load_l2;
  count_t load_col_in_group;
  count_t group_base_col;
  count_t load_tile_col;
  total_count_t loaded_count;
  total_count_t sent_count;
  logic [1:0] pending_loads;
  logic [1:0] pending_sends;
  logic                 load_complete;
  logic                 all_loads_done;
  logic                 all_loads_issued;
  total_count_t         issued_count;
  logic                 last_col_in_group;
  logic                 last_tile_row;
  logic                 last_l2_group;
  logic                 last_repeat;
  logic                 final_load_done;
  logic                 load_complete_after;
  total_count_t issued_count_next;
  localparam int p_issued_part_bits = 6;
  localparam int p_issued_parts = (TOTAL_CNT_W + p_issued_part_bits - 1) / p_issued_part_bits;
  logic [p_issued_parts-1:0] issued_chunk_carry_q;
  localparam int p_issued_levels = $clog2(p_issued_parts);
  logic [p_issued_parts-1:0] issued_prefix [0:p_issued_levels];
  logic [1:0] remaining_loads, remaining_sends;
  logic issued_zero, issued_one, loads_wrap, sends_wrap;
  logic load_count_reached, sent_count_covers_loads;
  count_t w_reuse_total;
  logic [REG_WIDTH-1:0] base_addr_reg;
  logic [REG_WIDTH-1:0] col_addr_step;
  logic [REG_WIDTH-1:0] row_addr_step;
  logic [REG_WIDTH-1:0] group_addr_step_q;
  logic [REG_WIDTH-1:0] group_base_addr;
  logic [REG_WIDTH-1:0] row_addr_offset;
  logic [REG_WIDTH-1:0] col_addr_offset;
  logic [REG_WIDTH-1:0] cfg_col_addr_step;
  logic [REG_WIDTH-1:0] cfg_row_addr_step;
  logic [REG_WIDTH-1:0] group_addr_step_next;
  logic [REG_WIDTH-1:0] group_step_25_sum, group_step_25_carry;
  logic [REG_WIDTH-1:0] group_step_25_fast, group_step_25;
  logic unused_group_step_25_carry;

  // 二十五倍步长先压缩三个移位项，最后进行一次完整模宽求和。
  assign group_step_25_sum = (col_addr_step << 4) ^ (col_addr_step << 3) ^ col_addr_step;
  assign group_step_25_carry = (((col_addr_step << 4) & (col_addr_step << 3)) |
      ((col_addr_step << 4) & col_addr_step) | ((col_addr_step << 3) & col_addr_step)) << 1;
  parallel_prefix_add #(.p_width(REG_WIDTH)) u_group_step_25 (
      .i_a(group_step_25_sum), .i_b(group_step_25_carry), .i_carry(1'b0),
      .o_sum(group_step_25_fast), .o_carry(unused_group_step_25_carry)
  );
  always_comb begin
    case (^col_addr_step)
      1'b0, 1'b1: group_step_25 = group_step_25_fast;
      default: group_step_25 = (col_addr_step << 4) + (col_addr_step << 3) + col_addr_step;
    endcase
  end
  count_t last_group_width;
  count_t following_group_width;
  count_t row_last_equal_i_a, row_last_equal_i_b, row_last_equal_i_target;
  logic row_last_equal_i_carry_in;
  logic row_last_equal_o_equal;
  count_t column_last_equal_i_a, column_last_equal_i_b, column_last_equal_i_c;
  count_t column_last_equal_i_target;
  logic column_last_equal_o_equal;

  logic [REG_WIDTH-1:0] dma_address_sum, dma_address_carry, dma_address_fast, dma_address_next;
  logic unused_dma_address_carry;
  // 三个地址分量先压缩，再以三位分组计算进位。
  assign dma_address_sum = group_base_addr ^ row_addr_offset ^ col_addr_offset;
  assign dma_address_carry = ((group_base_addr & row_addr_offset) |
      (group_base_addr & col_addr_offset) | (row_addr_offset & col_addr_offset)) << 1;
  parallel_prefix_add #(.p_width(REG_WIDTH), .p_group_width(3), .p_preserve_groups(1'b1)) u_dma_address (
      .i_a(dma_address_sum), .i_b(dma_address_carry), .i_carry(1'b0),
      .o_sum(dma_address_fast), .o_carry(unused_dma_address_carry)
  );
  always_comb begin
    case (^{group_base_addr, row_addr_offset, col_addr_offset})
      1'b0, 1'b1: dma_address_next = dma_address_fast;
      default: dma_address_next = group_base_addr + row_addr_offset + col_addr_offset;
    endcase
  end

  logic [3:0][CNT_W-1:0] traversal_i_value, traversal_o_next;
  logic column_value_covers_limit, column_next_equals_limit;
  logic column_increment_wrap;
  logic column_below_limit, first_group_below_limit, following_group_below_limit;
  logic unused_column_equal, unused_first_group_equal, unused_following_group_equal;
  logic unused_following_group_carry;
  count_t following_group_index, following_group_fast;
  logic [2:0][REG_WIDTH-1:0] cfg_dimension, cfg_rounded_fast, cfg_rounded;
  logic [2:0] unused_cfg_round_carry;

  assign cfg_dimension[0] = cfg_n;
  assign cfg_dimension[1] = cfg_m;
  assign cfg_dimension[2] = cfg_k;
  // 配置维度先计算完整模宽的向上取整分子，再选择固定右移位数。
  for (genvar dimension = 0; dimension < 3; dimension++) begin : g_cfg_round
    parallel_prefix_add #(.p_width(REG_WIDTH)) u_round (
        .i_a(cfg_dimension[dimension]),
        .i_b(REG_WIDTH'(count_t'(SIZE)) - REG_WIDTH'(1)), .i_carry(1'b0),
        .o_sum(cfg_rounded_fast[dimension]), .o_carry(unused_cfg_round_carry[dimension])
    );
    always_comb begin
      case (^cfg_dimension[dimension])
        1'b0, 1'b1: cfg_rounded[dimension] = cfg_rounded_fast[dimension];
        default: cfg_rounded[dimension] = cfg_dimension[dimension] +
            REG_WIDTH'(count_t'(SIZE)) - REG_WIDTH'(1);
      endcase
    end
  end
  assign traversal_i_value[0] = load_col_in_group;
  assign traversal_i_value[1] = load_tile_row;
  assign traversal_i_value[2] = load_l2;
  assign traversal_i_value[3] = load_repeat;
  // 四个遍历维度独立递增，边界比较和状态更新共用完整模宽结果。
  for (genvar dimension = 0; dimension < 4; dimension++) begin : g_traversal_next
    if (dimension == 0) begin : g_parallel
      kernel_count_increment #(.p_width(CNT_W)) u_increment (
        .i_value(traversal_i_value[dimension]), .o_next(traversal_o_next[dimension])
      );
    end else begin : g_increment
      assign traversal_o_next[dimension] = traversal_i_value[dimension] + count_t'(1);
    end
  end

  // 列边界并行检查当前值和相邻值，单独保留计数回绕时的无符号比较结果。
  unsigned_compare #(.p_width(CNT_W)) u_column_limit (
      .i_a(load_col_in_group), .i_b(current_group_width),
      .o_less(column_below_limit), .o_equal(unused_column_equal)
  );
  assign column_value_covers_limit = !column_below_limit;

  // 模宽递增的边界判断并行检查大小、相邻相等和回绕条件。
  kernel_count_next_reaches #(.p_width(CNT_W)) u_row_limit (
      .i_value(load_tile_row), .i_limit(tile_rows_total), .o_reaches(last_tile_row)
  );
  kernel_count_next_reaches #(.p_width(CNT_W)) u_group_limit (
      .i_value(load_l2), .i_limit(l2_groups_total), .o_reaches(last_l2_group)
  );
  kernel_count_next_reaches #(.p_width(CNT_W)) u_repeat_limit (
      .i_value(load_repeat), .i_limit(repeat_total), .o_reaches(last_repeat)
  );
  unsigned_compare #(.p_width(CNT_W)) u_first_group_limit (
      .i_a(tile_cols_total), .i_b(w_reuse_total),
      .o_less(first_group_below_limit), .o_equal(unused_first_group_equal)
  );
  parallel_prefix_add #(.p_width(CNT_W)) u_following_group_index (
      .i_a(load_l2), .i_b(count_t'(2)), .i_carry(1'b0),
      .o_sum(following_group_fast), .o_carry(unused_following_group_carry)
  );
  always_comb begin
    case (^load_l2)
      1'b0, 1'b1: following_group_index = following_group_fast;
      default: following_group_index = load_l2 + count_t'(2);
    endcase
  end
  unsigned_compare #(.p_width(CNT_W)) u_following_group_limit (
      .i_a(following_group_index), .i_b(l2_groups_total),
      .o_less(following_group_below_limit), .o_equal(unused_following_group_equal)
  );
  add_equal #(.p_width(CNT_W)) u_column_next_equal (
      .i_a(load_col_in_group), .i_b({CNT_W{1'b0}}), .i_target(current_group_width),
      .i_carry_in(1'b1), .o_equal(column_next_equals_limit)
  );
  assign column_increment_wrap = &load_col_in_group;

  function automatic count_t divide_rounded_pow2(input logic [REG_WIDTH-1:0] biased,
                                                input count_t pow2);
    begin
      unique case (pow2)
        count_t'(1):    divide_rounded_pow2 = count_t'(biased);
        count_t'(2):    divide_rounded_pow2 = count_t'(biased >> 1);
        count_t'(4):    divide_rounded_pow2 = count_t'(biased >> 2);
        count_t'(8):    divide_rounded_pow2 = count_t'(biased >> 3);
        count_t'(16):   divide_rounded_pow2 = count_t'(biased >> 4);
        count_t'(32):   divide_rounded_pow2 = count_t'(biased >> 5);
        count_t'(64):   divide_rounded_pow2 = count_t'(biased >> 6);
        count_t'(128):  divide_rounded_pow2 = count_t'(biased >> 7);
        count_t'(256):  divide_rounded_pow2 = count_t'(biased >> 8);
        count_t'(512):  divide_rounded_pow2 = count_t'(biased >> 9);
        count_t'(1024): divide_rounded_pow2 = count_t'(biased >> 10);
        default:        divide_rounded_pow2 = count_t'(biased);
      endcase
    end
  endfunction

  always_comb begin
    ia_reuse_norm = (cfg_ia_reuse_num == 0) ? count_t'(1) : count_t'(cfg_ia_reuse_num);
    w_reuse_norm  = (cfg_w_reuse_num  == 0) ? count_t'(1) : count_t'(cfg_w_reuse_num);

    cfg_tile_rows_total        = divide_rounded_pow2(cfg_rounded[0], count_t'(SIZE));
    cfg_tile_cols_total        = divide_rounded_pow2(cfg_rounded[1], count_t'(SIZE));
    cfg_output_row_tiles_total = divide_rounded_pow2(cfg_rounded[2], count_t'(SIZE));
    cfg_l2_groups_total = count_t'(cfg_col_groups);
    cfg_repeat_total = count_t'(cfg_row_groups);
    if (cfg_tile_rows_total == 0) cfg_tile_rows_total = count_t'(1);
    if (cfg_tile_cols_total == 0) cfg_tile_cols_total = count_t'(1);
    if (cfg_l2_groups_total == 0) cfg_l2_groups_total = count_t'(1);
    if (cfg_repeat_total == 0) cfg_repeat_total = count_t'(1);

    cfg_last_n_rows = count_t'(cfg_n & REG_WIDTH'(SIZE - 1));
    cfg_last_m_cols = count_t'(cfg_m & REG_WIDTH'(SIZE - 1));
    if (cfg_last_n_rows == 0) cfg_last_n_rows = count_t'(SIZE);
    if (cfg_last_m_cols == 0) cfg_last_m_cols = count_t'(SIZE);

    cfg_group_tail_cols = count_t'(cfg_col_tail_tiles);
    cfg_last_group_width = count_t'(cfg_col_tail_tiles);

    if (first_group_below_limit) begin
      first_group_width = tile_cols_total;
    end else begin
      first_group_width = w_reuse_total;
    end
    if (first_group_width == 0) first_group_width = count_t'(1);

    if (!following_group_below_limit) begin
      following_group_width = last_group_width;
    end else begin
      following_group_width = w_reuse_total;
    end

    load_tile_col = group_base_col + load_col_in_group;
    valid_n_rows = row_last_equal_o_equal ? last_n_rows : count_t'(SIZE);
    valid_m_cols = column_last_equal_o_equal ? last_m_cols : count_t'(SIZE);
    if (valid_n_rows == 0) valid_n_rows = count_t'(1);
    if (valid_m_cols == 0) valid_m_cols = count_t'(1);
    elem_bytes = cfg_use_16bits ? REG_WIDTH'(2) : REG_WIDTH'(1);

    cfg_col_addr_step = cfg_tile_packed ?
        (REG_WIDTH'(cfg_tile_rows_total) << (2*SIZE_SHIFT + (cfg_use_16bits ? 1 : 0))) :
        (cfg_rhs_row_stride_b << SIZE_SHIFT);
    cfg_row_addr_step = REG_WIDTH'(1) <<
        ((cfg_tile_packed ? 2*SIZE_SHIFT : SIZE_SHIFT) + (cfg_use_16bits ? 1 : 0));
    case (w_reuse_total)
      count_t'(1):    group_addr_step_next = col_addr_step;
      count_t'(2):    group_addr_step_next = col_addr_step << 1;
      count_t'(4):    group_addr_step_next = col_addr_step << 2;
      count_t'(8):    group_addr_step_next = col_addr_step << 3;
      count_t'(16):   group_addr_step_next = col_addr_step << 4;
      count_t'(25):   group_addr_step_next = group_step_25;
      count_t'(32):   group_addr_step_next = col_addr_step << 5;
      count_t'(64):   group_addr_step_next = col_addr_step << 6;
      count_t'(128):  group_addr_step_next = col_addr_step << 7;
      count_t'(256):  group_addr_step_next = col_addr_step << 8;
      count_t'(512):  group_addr_step_next = col_addr_step << 9;
      count_t'(1024): group_addr_step_next = col_addr_step << 10;
      default:          group_addr_step_next = col_addr_step;
    endcase

    last_col_in_group = (current_group_width == '0) ||
        (!column_increment_wrap && (column_value_covers_limit || column_next_equals_limit));
    final_load_done = load_done && all_loads_issued && load_count_reached;

    load_complete = all_loads_done;
    load_complete_after = all_loads_done || final_load_done;

    tile_row_dbg = REG_WIDTH'(load_tile_row);
    tile_col_dbg = REG_WIDTH'(load_tile_col);
    repeat_dbg   = REG_WIDTH'(load_repeat);

    load_weight_req = !clear && (state == S_RUN) && !all_loads_issued && buf_load_ready;
    dma_start       = load_weight_req && load_weight_granted;
    buf_load_start  = dma_start;
    buf_send_start  = !clear && (state == S_RUN) && send_weight_trigger && buf_weight_data_valid;
    ctrl_all_done   = !clear && (state == S_DONE);

    // W is column-flattened: each DMA "row" is one output column,
    // and each burst reads contiguous N/K elements from that column.
    // In IS, this same loader reads image-derived A rows: output positions
    // replace output channels, while reduction columns keep their direction.
    dma_p0            = REG_WIDTH'(load_tile_col) << SIZE_SHIFT;
    dma_q0            = REG_WIDTH'(load_tile_row) << SIZE_SHIFT;
    dma_group         = REG_WIDTH'(load_repeat);
    dma_tile_base_addr = dma_address_next;
    dma_rows_to_read   = REG_WIDTH'(valid_m_cols);
    dma_row_stride_b   = cfg_tile_packed ?
        (REG_WIDTH'(SIZE) << (cfg_use_16bits ? 1 : 0)) : cfg_rhs_row_stride_b;
    dma_rhs_zp         = cfg_rhs_zp;
    dma_valid_cols     = REG_WIDTH'(valid_n_rows);
  end

  // 描述符比较使用独立寄存操作数，地址输出继续保留完整和值。
  assign o_column_group_base = REG_WIDTH'(group_base_col) << SIZE_SHIFT;
  assign o_column_group_offset = REG_WIDTH'(load_col_in_group) << SIZE_SHIFT;
  assign o_address_group_base = group_base_addr;
  assign o_address_row_offset = row_addr_offset;
  assign o_address_column_offset = col_addr_offset;
  // 描述符仅在配置接收、初始化和请求接受边沿更新。
  assign o_descriptor_update = clear || (state == S_IDLE && cfg_valid) ||
      (state == S_INIT) || dma_start;

  // 尾部分块由模加法等式确定，各位进位并行比较。
  assign row_last_equal_i_a = load_tile_row;
  assign row_last_equal_i_b = '0;
  assign row_last_equal_i_target = tile_rows_total;
  assign row_last_equal_i_carry_in = 1'b1;
  assign column_last_equal_i_a = group_base_col;
  assign column_last_equal_i_b = load_col_in_group;
  assign column_last_equal_i_c = count_t'(1);
  assign column_last_equal_i_target = tile_cols_total;

  add_equal #(.p_width(CNT_W)) u_row_last_equal (
      .i_a(row_last_equal_i_a), .i_b(row_last_equal_i_b),
      .i_target(row_last_equal_i_target), .i_carry_in(row_last_equal_i_carry_in),
      .o_equal(row_last_equal_o_equal)
  );
  add3_equal #(.p_width(CNT_W)) u_column_last_equal (
      .i_a(column_last_equal_i_a), .i_b(column_last_equal_i_b),
      .i_c(column_last_equal_i_c), .i_target(column_last_equal_i_target),
      .o_equal(column_last_equal_o_equal)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state               <= S_IDLE;
      load_tile_row       <= '0;
      load_repeat         <= '0;
      load_l2             <= '0;
      load_col_in_group   <= '0;
      pending_loads       <= '0;
      pending_sends       <= '0;
      all_loads_done      <= 1'b0;
      all_loads_issued    <= 1'b0;
      issued_count       <= '0;
      tile_rows_total     <= count_t'(1);
      tile_cols_total     <= count_t'(1);
      l2_groups_total     <= count_t'(1);
      repeat_total        <= count_t'(1);
      last_n_rows         <= count_t'(SIZE);
      last_m_cols         <= count_t'(SIZE);
      current_group_width <= count_t'(1);
      w_reuse_total       <= count_t'(1);
      last_group_width    <= count_t'(SIZE);
      base_addr_reg       <= '0;
      col_addr_step       <= '0;
      row_addr_step       <= REG_WIDTH'(SIZE);
      group_addr_step_q     <= '0;
      group_base_col      <= '0;
      group_base_addr     <= '0;
      row_addr_offset     <= '0;
      col_addr_offset     <= '0;
    end else if (clear) begin
      // Configuration invalidates the current traversal. Address registers
      // remain unused until S_IDLE captures the next descriptor.
      state<=S_IDLE;
      all_loads_done<=1'b0;
      all_loads_issued<=1'b0;
    end else begin
      case (state)
        S_IDLE: begin
          if (cfg_valid) begin
            load_tile_row       <= '0;
            load_repeat         <= '0;
            load_l2             <= '0;
            load_col_in_group   <= '0;
            pending_loads       <= '0;
            pending_sends       <= '0;
            all_loads_done      <= 1'b0;
            all_loads_issued    <= 1'b0;
            issued_count       <= '0;
            tile_rows_total     <= cfg_tile_rows_total;
            tile_cols_total     <= cfg_tile_cols_total;
            l2_groups_total <= cfg_l2_groups_total;
            repeat_total <= cfg_repeat_total;
            last_group_width <= cfg_last_group_width;
            last_n_rows         <= cfg_last_n_rows;
            last_m_cols         <= cfg_last_m_cols;
            current_group_width <= count_t'(1);
            w_reuse_total       <= w_reuse_norm;
            base_addr_reg       <= cfg_rhs_base;
            col_addr_step       <= cfg_col_addr_step;
            row_addr_step       <= cfg_row_addr_step;
            group_base_col      <= '0;
            group_base_addr     <= cfg_rhs_base;
            row_addr_offset     <= '0;
            col_addr_offset     <= '0;
            state               <= S_INIT;
          end
        end

        S_INIT: begin
          // 列步长和复用次数已在配置接受边沿保存，此周期计算分组步长。
          group_addr_step_q   <= group_addr_step_next;
          current_group_width <= first_group_width;
          group_base_addr     <= base_addr_reg;
          state               <= S_RUN;
        end

        S_RUN: begin
          // 两个逻辑槽位保存加载请求，发送使用第三个物理槽位。
          case ({dma_start, load_done})
            2'b10: pending_loads <= pending_loads + 2'd1;
            2'b01: pending_loads <= pending_loads - 2'd1;
            default: ;
          endcase
          case ({dma_start, buf_weight_sending_done})
            2'b10: pending_sends <= pending_sends + 2'd1;
            2'b01: pending_sends <= pending_sends - 2'd1;
            default: ;
          endcase
          if (load_done) begin
            if (final_load_done) begin
              all_loads_done <= 1'b1;
            end
          end
          if (dma_start) begin
            issued_count <= issued_count_next;
            if (last_col_in_group && last_tile_row && last_l2_group && last_repeat)
              all_loads_issued <= 1'b1;
            if (!last_col_in_group) begin
              load_col_in_group <= traversal_o_next[0];
              col_addr_offset   <= col_addr_offset + col_addr_step;
            end else begin
              load_col_in_group <= '0;
              col_addr_offset   <= '0;
              if (!last_tile_row) begin
                load_tile_row   <= traversal_o_next[1];
                row_addr_offset <= row_addr_offset + row_addr_step;
              end else begin
                load_tile_row   <= '0;
                row_addr_offset <= '0;
                if (!last_l2_group) begin
                  load_l2             <= traversal_o_next[2];
                  group_base_col      <= group_base_col + current_group_width;
                  current_group_width <= following_group_width;
                  group_base_addr     <= group_base_addr + group_addr_step_q;
                end else begin
                  load_l2             <= '0;
                  group_base_col      <= '0;
                  current_group_width <= first_group_width;
                  group_base_addr     <= base_addr_reg;
                  if (!last_repeat) begin
                    load_repeat <= traversal_o_next[3];
                  end
                end
              end
            end
          end

          if (buf_weight_sending_done) begin
            if (load_complete_after && sent_count_covers_loads) begin
              state <= S_DONE;
            end
          end
        end

        S_DONE: begin
          if (!cfg_valid) begin
            state <= S_IDLE;
          end
        end

        default: state <= S_IDLE;
      endcase
    end
  end

  // 已发出总数保留完整模宽；加载与发送数量由有界差值表示。
  assign loaded_count = issued_count - total_count_t'(pending_loads);
  assign sent_count = issued_count - total_count_t'(pending_sends);
  // 各组输入进位对应当前计数的低位全一条件，与完整计数在同一边沿更新。
  assign issued_chunk_carry_q[0] = 1'b1;
  // 每组六位先独立判断，前缀按二叉层次归并，配置使能只参与最终更新。
  for (genvar part = 0; part < p_issued_parts; part++) begin : g_issued_condition
    localparam int p_low = part * p_issued_part_bits;
    localparam int p_width = TOTAL_CNT_W - p_low < p_issued_part_bits ?
        TOTAL_CNT_W - p_low : p_issued_part_bits;
    (* keep = 1 *) logic part_all;
    if (part == p_issued_parts-1) begin : g_unused
      assign part_all = 1'b1;
    end else if (part == 0) begin : g_low
      assign part_all = !issued_count[0] && (&issued_count[p_width-1:1]);
    end else begin : g_high
      assign part_all = &issued_count[p_low +: p_width];
    end
    assign issued_prefix[0][part] = part_all;
  end
  for (genvar level = 0; level < p_issued_levels; level++) begin : g_issued_level
    for (genvar part = 0; part < p_issued_parts; part++) begin : g_part
      if ((part % (2 << level)) >= (1 << level)) begin : g_merge
        localparam int p_left_end = (part / (2 << level)) * (2 << level) + (1 << level) - 1;
        (* keep = 1 *) logic merged_all;
        assign merged_all = issued_prefix[level][part] && issued_prefix[level][p_left_end];
        assign issued_prefix[level+1][part] = merged_all;
      end else begin : g_pass
        assign issued_prefix[level+1][part] = issued_prefix[level][part];
      end
    end
  end
  for (genvar part = 0; part < p_issued_parts; part++) begin : g_issued_part
    localparam int p_low = part * p_issued_part_bits;
    localparam int p_width = TOTAL_CNT_W - p_low < p_issued_part_bits ?
      TOTAL_CNT_W - p_low : p_issued_part_bits;
    logic unused_carry;
    assign {unused_carry, issued_count_next[p_low +: p_width]} =
      {1'b0, issued_count[p_low +: p_width]} + (p_width+1)'(issued_chunk_carry_q[part]);
    if (part != 0) begin : g_carry
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) issued_chunk_carry_q[part] <= 1'b0;
        else if (!clear) begin
          if (state == S_IDLE && cfg_valid)
            issued_chunk_carry_q[part] <= 1'b0;
          else if (state == S_RUN && dma_start)
            issued_chunk_carry_q[part] <= issued_prefix[p_issued_levels][part-1];
        end
      end
    end
  end

  // 比较完整无符号计数时，同时处理低端回绕后的大小关系。
  assign issued_zero = issued_count == '0;
  assign issued_one = issued_count == total_count_t'(1);
  assign remaining_loads = pending_loads - 2'(load_done);
  assign remaining_sends = pending_sends - 2'd1;
  assign loads_wrap = (remaining_loads != 0 && issued_zero) ||
      (remaining_loads == 2 && issued_one);
  assign sends_wrap = (remaining_sends != 0 && issued_zero) ||
      (remaining_sends == 2 && issued_one);
  assign load_count_reached = pending_loads == 1 || (pending_loads == 2 && issued_zero);
  assign sent_count_covers_loads = (sends_wrap != loads_wrap) ? sends_wrap :
      (remaining_sends <= remaining_loads);

endmodule

// 五位分组和六组聚合形成并行进位，各结果位独立计算翻转条件。
module kernel_count_increment #(
    parameter int p_width = 48
) (
    input  wire logic [p_width-1:0] i_value,
    output logic [p_width-1:0] o_next
);
    localparam int p_chunk_bits = 5;
    localparam int p_block_chunks = 6;
    localparam int p_chunks = (p_width + p_chunk_bits - 1) / p_chunk_bits;
    localparam int p_blocks = (p_chunks + p_block_chunks - 1) / p_block_chunks;
    (* keep *) logic [p_chunks-1:0] chunk_all;
    (* keep *) logic [p_blocks-1:0] block_all;

    for (genvar block_index = 0; block_index < p_blocks; block_index++) begin : g_block
        localparam int p_low_chunk = block_index * p_block_chunks;
        localparam int p_block_width = p_chunks - p_low_chunk < p_block_chunks ?
            p_chunks - p_low_chunk : p_block_chunks;
        assign block_all[block_index] = &chunk_all[p_low_chunk +: p_block_width];
    end
    for (genvar chunk = 0; chunk < p_chunks; chunk++) begin : g_chunk
        localparam int p_low = chunk * p_chunk_bits;
        localparam int p_chunk_width = p_width - p_low < p_chunk_bits ?
            p_width - p_low : p_chunk_bits;
        localparam int p_block = chunk / p_block_chunks;
        localparam int p_inner = chunk % p_block_chunks;
        logic chunk_carry;
        assign chunk_all[chunk] = &i_value[p_low +: p_chunk_width];
        if (chunk == 0) begin : g_first
            assign chunk_carry = 1'b1;
        end else if (p_block == 0) begin : g_first_block
            assign chunk_carry = &chunk_all[chunk-1:0];
        end else if (p_inner == 0) begin : g_block_start
            assign chunk_carry = &block_all[p_block-1:0];
        end else begin : g_inside_block
            assign chunk_carry = (&block_all[p_block-1:0]) &&
                (&chunk_all[p_block*p_block_chunks +: p_inner]);
        end
        for (genvar bit_index = 0; bit_index < p_chunk_width; bit_index++) begin : g_bit
            if (bit_index == 0) begin : g_low
                assign o_next[p_low] = i_value[p_low] ^ chunk_carry;
            end else begin : g_high
                assign o_next[p_low+bit_index] = i_value[p_low+bit_index] ^
                    (chunk_carry && (&i_value[p_low +: bit_index]));
            end
        end
    end
endmodule

// 分块无符号比较并组合各块结果。
module kernel_count_compare #(
    parameter int p_width = 48,
    parameter int p_chunk_width = 8
) (
    input  wire logic [p_width-1:0] i_lhs,
    input  wire logic [p_width-1:0] i_rhs,
    output logic o_ge
);
    localparam int p_compare_width = p_chunk_width;
    localparam int p_chunks = (p_width + p_compare_width - 1) / p_compare_width;
    localparam int p_leaves = 1 << $clog2(p_chunks);
    // 保留相邻区间的比较节点，完整层次合并时仍按平衡树计算。
    (* keep = 1 *) logic [2*p_leaves-1:1] equal_tree;
    (* keep = 1 *) logic [2*p_leaves-1:1] greater_tree;

    for (genvar part = 0; part < p_leaves; part++) begin : g_compare
        if (part < p_chunks) begin : g_value
            localparam int p_low = part * p_compare_width;
            localparam int p_part_width = ((p_width - p_low) < p_compare_width) ?
                p_width - p_low : p_compare_width;
            assign equal_tree[p_leaves + part] =
                i_lhs[p_low +: p_part_width] == i_rhs[p_low +: p_part_width];
            assign greater_tree[p_leaves + part] =
                i_lhs[p_low +: p_part_width] > i_rhs[p_low +: p_part_width];
        end else begin : g_padding
            assign equal_tree[p_leaves + part] = 1'b1;
            assign greater_tree[p_leaves + part] = 1'b0;
        end
    end
    for (genvar node = 1; node < p_leaves; node++) begin : g_merge
        assign equal_tree[node] = equal_tree[2*node+1] && equal_tree[2*node];
        assign greater_tree[node] = greater_tree[2*node+1] ||
            (equal_tree[2*node+1] && greater_tree[2*node]);
    end
    assign o_ge = greater_tree[1] || equal_tree[1];
endmodule

// 完整模宽的加一边界比较，包含最大计数回绕至零的情况。
module kernel_count_next_reaches #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_value,
    input wire logic [p_width-1:0] i_limit,
    output logic o_reaches
);
    logic value_less, unused_value_equal, next_equal, reaches_binary;

    unsigned_compare #(.p_width(p_width)) u_current_compare (
        .i_a(i_value), .i_b(i_limit),
        .o_less(value_less), .o_equal(unused_value_equal)
    );
    add_equal #(.p_width(p_width)) u_next_equal (
        .i_a(i_value), .i_b({p_width{1'b0}}), .i_target(i_limit),
        .i_carry_in(1'b1), .o_equal(next_equal)
    );
    assign reaches_binary = (i_limit == '0) ||
        ((!(&i_value)) && (!value_less || next_equal));
    always_comb begin
        case (^{i_value, i_limit})
            1'b0, 1'b1: o_reaches = reaches_binary;
            default: o_reaches = (i_value + p_width'(1)) >= i_limit;
        endcase
    end
endmodule

`default_nettype wire
