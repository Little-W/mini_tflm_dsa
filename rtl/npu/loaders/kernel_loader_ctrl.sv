
`default_nettype none
// 按复用分组遍历矩阵分块，生成 DMA 描述符并控制装载与发送顺序。
module kernel_loader_ctrl #(
    parameter int unsigned SIZE      = 4,
    parameter int unsigned REG_WIDTH = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH
) (
    input  wire logic                        clk, // 分块调度与地址控制的工作时钟。
    input  wire logic                        rst_n, // 低有效异步复位。
    input  wire logic                        clear = 1'b0, // 清除当前分块调度和装载状态。
    input  wire logic                        cfg_valid, // 新任务的装载配置有效。
    input  wire logic [REG_WIDTH-1:0]        cfg_k, // 流式维度长度，WS 对应输出行数，IS 对应输出列数。
    input  wire logic [REG_WIDTH-1:0]        cfg_n, // 装载矩阵的归约维度长度。
    input  wire logic [REG_WIDTH-1:0]        cfg_m, // 驻留维度长度，WS 对应输出列数，IS 对应输出行数。
    input  wire logic [REG_WIDTH-1:0]        cfg_rhs_base, // 装载矩阵的外部存储首地址。
    input  wire logic [REG_WIDTH-1:0]        cfg_rhs_row_stride_b, // 相邻 DMA 行起点之间的字节跨度。
    input  wire logic signed [REG_WIDTH-1:0] cfg_rhs_zp, // 装载元素需要扣除的有符号量化零点。
    input  wire logic                        cfg_use_16bits, // 按十六位元素计算地址和传输跨度。
    input  wire logic                        cfg_tile_packed = 1'b0, // 外部矩阵按完整分块连续存放。
    input  wire logic [REG_WIDTH-1:0]        cfg_ia_reuse_num, // 一个流式操作数复用组包含的分块数。
    input  wire logic [REG_WIDTH-1:0]        cfg_w_reuse_num, // 一个驻留操作数复用组包含的分块数。
    input wire logic [REG_WIDTH-1:0] cfg_row_groups, // 流式维度的分块组数，WS 对应输出行，IS 对应输出列。
    input wire logic [REG_WIDTH-1:0] cfg_row_tail_tiles, // 最后一个流式维度分组的有效分块数。
    input wire logic [REG_WIDTH-1:0] cfg_col_groups, // 驻留维度的分块组数，WS 对应输出列，IS 对应输出行。
    input wire logic [REG_WIDTH-1:0] cfg_col_tail_tiles, // 最后一个驻留维度分组的有效分块数。
    input  wire logic                        load_weight_granted, // 当前装载请求取得资源授予。
    input  wire logic                        send_weight_trigger, // 外部请求启动队首权重发送。
    input  wire logic                        buf_weight_data_valid, // 权重缓冲区已有可发送分块。
    input  wire logic                        buf_weight_sending_done, // 权重缓冲区完成当前分块发送。
    input  wire logic                        buf_load_ready, // 权重缓冲区可接受下一分块装载。
    input  wire logic                        load_done, // 当前需求分块装载完成。
    output logic                        load_weight_req, // 当前调度项请求装载权重。
    output logic                        dma_start, // 当前装载请求被授予并启动 DMA。
    output logic [REG_WIDTH-1:0]        dma_p0, // 当前分块的列位置或图像输出位置起点。
    output logic [REG_WIDTH-1:0]        dma_q0, // 当前分块的归约位置起点。
    output logic [REG_WIDTH-1:0]        dma_group, // 当前 DMA 分块所属的流式维度复用组编号。
    output logic [REG_WIDTH-1:0]        dma_tile_base_addr, // 当前分块的 DMA 起始字节地址。
    output logic [REG_WIDTH-1:0]        o_column_group_base, // 当前列复用组的起始元素位置。
    output logic [REG_WIDTH-1:0]        o_column_group_offset, // 当前分块相对列复用组的元素偏移。
    output logic [REG_WIDTH-1:0]        o_address_group_base, // 当前列复用组的起始字节地址。
    output logic [REG_WIDTH-1:0]        o_address_row_offset, // 当前归约行分块的字节地址偏移。
    output logic [REG_WIDTH-1:0]        o_address_column_offset, // 当前列分块在复用组内的字节地址偏移。
    output logic                       o_descriptor_update, // 当前边沿需要更新分块描述符。
    output logic [REG_WIDTH-1:0]        dma_rows_to_read, // 当前 DMA 需要读取的矩阵列数或图像位置数。
    output logic [REG_WIDTH-1:0]        dma_row_stride_b, // 当前 DMA 相邻行起点之间的字节跨度。
    output logic signed [REG_WIDTH-1:0] dma_rhs_zp, // 当前 DMA 元素需要扣除的有符号零点。
    output logic                        buf_load_start, // 通知权重缓冲区预留装载槽位。
    output logic                        buf_send_start, // 通知权重缓冲区开始发送队首分块。
    output logic [REG_WIDTH-1:0]        dma_valid_cols, // 当前 DMA 每行的有效归约元素数。
    output logic                        ctrl_all_done, // 当前任务的装载和发送调度全部完成。
    output logic [REG_WIDTH-1:0]        tile_row_dbg, // 当前装载分块的归约行索引。
    output logic [REG_WIDTH-1:0]        tile_col_dbg, // 当前装载分块的输出列索引。
    output logic [REG_WIDTH-1:0]        repeat_dbg // 当前装载分块所属的流式维度复用组编号。
);

  localparam int unsigned SIZE_SHIFT = $clog2(SIZE);
  localparam int unsigned CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
  typedef logic [CNT_W-1:0] count_t;
  // 任务总数覆盖三个遍历维度的乘积，计数宽度保留每个维度的完整范围。
  localparam int unsigned TOTAL_CNT_W = 3 * CNT_W;
  typedef logic [TOTAL_CNT_W-1:0] total_count_t;

  typedef enum logic [1:0] {S_IDLE, S_INIT, S_RUN, S_DONE} state_t;

  state_t state;
  logic load_pending_q;

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
  count_t first_group_width, first_tile_width, first_reuse_width;

  count_t load_tile_row;
  count_t load_repeat;
  count_t load_l2;
  count_t load_col_in_group;
  count_t group_base_col;
  count_t column_position_q, column_position_next;
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
  (* keep = "true" *) logic last_l2_group;
  (* keep = "true" *) logic last_repeat;
  logic                 final_load_done;
  logic                 sending_completes_task;
  total_count_t issued_count_next;
  localparam int p_issued_part_bits = 6;
  localparam int p_issued_parts = (TOTAL_CNT_W + p_issued_part_bits - 1) / p_issued_part_bits;
  logic [p_issued_parts-1:0] issued_chunk_carry_q;
  localparam int p_issued_levels = $clog2(p_issued_parts);
  logic [p_issued_parts-1:0] issued_prefix [0:p_issued_levels];
  logic issued_zero, issued_one;
  (* keep = "true" *) logic issued_high_zero;
  logic load_count_reached;
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
  logic [REG_WIDTH-1:0] group_step_i_step, group_step_o_product;
  count_t group_step_i_reuse;
  logic [REG_WIDTH-1:0] group_step_product;

  // 完整分组步长独立计算，配置边沿与初始化状态的更新规则保持不变。
  assign group_step_i_step = col_addr_step;
  assign group_step_i_reuse = w_reuse_total;
  assign group_step_product = group_step_o_product;
  kernel_group_step #(.p_width(REG_WIDTH), .p_count_width(CNT_W)) u_group_step (
      .i_step(group_step_i_step), .i_reuse(group_step_i_reuse),
      .o_product(group_step_o_product)
  );

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
  (* keep = "true" *) logic row_last_equal_o_equal;
  logic row_last_four_state, last_row_saved_q;
  (* keep = "true" *) logic row_two_ahead_equal;
  count_t column_last_equal_i_a, column_last_equal_i_b, column_last_equal_i_c;
  count_t column_last_equal_i_target;
  (* keep = "true" *) logic column_last_equal_o_equal;
  logic column_last_equal_four_state, column_last_equal_fast;

  // 列位置与组内索引同时更新，描述符坐标直接读取定宽列位置状态。
  (* keep_hierarchy = "yes" *)
  kernel_count_increment #(.p_width(CNT_W)) u_column_position_next (
      .i_value(column_position_q), .o_next(column_position_next)
  );
  always_comb begin
    case (^{group_base_col, load_col_in_group})
      1'b0, 1'b1: load_tile_col = column_position_q;
      default: load_tile_col = group_base_col + load_col_in_group;
    endcase
  end

  logic [REG_WIDTH-1:0] dma_address_next;
  logic [REG_WIDTH-1:0] row_base_address_q, dma_address_q;
  logic [REG_WIDTH-1:0] row_base_address_increment, dma_address_increment;
  // 行起点和当前分块地址随遍历状态同时更新，发出描述符时直接读取完整地址。
  logic [REG_WIDTH-1:0] row_base_address_fast;
  logic unused_row_base_address_carry;
  // 行首地址的两段同时求和，低段进位只参与高段的分组修正。
  parallel_prefix_add #(.p_width(REG_WIDTH), .p_dsp_split_width(REG_WIDTH/2),
      .p_preserve_groups(1'b1), .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)) u_row_base_next (
      .i_a(row_base_address_q), .i_b(row_addr_step), .i_carry(1'b0),
      .o_sum(row_base_address_fast), .o_carry(unused_row_base_address_carry)
  );
  always_comb begin
    case (^{row_base_address_q, row_addr_step})
      1'b0, 1'b1: row_base_address_increment = row_base_address_fast;
      default: row_base_address_increment = row_base_address_q + row_addr_step;
    endcase
  end
  assign dma_address_increment = dma_address_q + col_addr_step;
  always_comb begin
    case (^{group_base_addr, row_addr_offset, col_addr_offset})
      1'b0, 1'b1: dma_address_next = dma_address_q;
      default: dma_address_next = group_base_addr + row_addr_offset + col_addr_offset;
    endcase
  end

  logic [3:0][CNT_W-1:0] traversal_i_value;
   logic [3:0][CNT_W-1:0] traversal_o_next;
   logic [REG_WIDTH-1:0] column_offset_increment;
   logic [REG_WIDTH-1:0] row_offset_increment, group_address_increment;
   count_t group_column_increment;
  // 地址和分组递增在接收条件之前并行计算，保留完整模宽。
  assign column_offset_increment = col_addr_offset + col_addr_step;
  assign row_offset_increment = row_addr_offset + row_addr_step;
  logic [CNT_W-1:0] group_column_increment_fast;
  logic unused_group_column_carry;
  parallel_prefix_add #(.p_width(CNT_W), .p_dsp_split_width(CNT_W/2),
      .p_preserve_groups(1'b1), .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)) u_group_column_next (
      .i_a(group_base_col), .i_b(current_group_width), .i_carry(1'b0),
      .o_sum(group_column_increment_fast), .o_carry(unused_group_column_carry)
  );
  always_comb begin
    case (^{group_base_col, current_group_width})
      1'b0, 1'b1: group_column_increment = group_column_increment_fast;
      default: group_column_increment = group_base_col + current_group_width;
    endcase
  end
  logic [REG_WIDTH-1:0] group_address_increment_fast;
  logic unused_group_address_carry;
  // 分组首地址的高低半段并行求和，低段进位只参与高段结果修正。
  parallel_prefix_add #(.p_width(REG_WIDTH), .p_dsp_split_width(REG_WIDTH/2),
      .p_preserve_groups(1'b1), .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)) u_group_address_next (
      .i_a(group_base_addr), .i_b(group_addr_step_q), .i_carry(1'b0),
      .o_sum(group_address_increment_fast), .o_carry(unused_group_address_carry)
  );
  always_comb begin
    case (^{group_base_addr, group_addr_step_q})
      1'b0, 1'b1: group_address_increment = group_address_increment_fast;
      default: group_address_increment = group_base_addr + group_addr_step_q;
    endcase
  end
  logic column_value_covers_limit, column_next_equals_limit;
  logic last_col_saved_q;
  (* keep = "true" *) logic column_two_ahead_equal;
  logic column_increment_wrap;
  logic column_below_limit, first_group_below_limit, following_group_below_limit;
  logic unused_column_equal, unused_first_group_equal, unused_following_group_equal;
  logic unused_following_group_carry;
  count_t following_group_index, following_group_fast;
  logic [2:0][REG_WIDTH-1:0] cfg_dimension, cfg_rounded_fast, cfg_rounded;
  logic [2:0] unused_cfg_round_carry;
  count_t cfg_normalized_tiles [2];
  logic [1:0] cfg_single_tile;
  count_t normalized_n_rows, normalized_m_cols;
  localparam count_t p_full_valid_count = count_t'(SIZE) == 0 ? count_t'(1) : count_t'(SIZE);

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
  // 归约维度和驻留维度按完整块数与余数组合取整，零计数统一映射为一个分块。
  // 最高块数回绕与输入零值的最低结果位直接形成，独立于高位递增的传播路径。
  for (genvar dimension = 0; dimension < 2; dimension++) begin : g_cfg_normalized_tiles
    if (SIZE > 1 && SIZE <= 1024 && (SIZE & (SIZE-1)) == 0 &&
        SIZE_SHIFT < REG_WIDTH && CNT_W > SIZE_SHIFT) begin : g_power_of_two
      localparam int p_full_width = REG_WIDTH - SIZE_SHIFT;
      localparam int p_tile_width = CNT_W < p_full_width ? CNT_W : p_full_width;
      logic [p_tile_width-1:0] full_tiles;
      logic partial_tile;
      logic [p_tile_width:0] increment_output;
      logic [p_tile_width-1:0] normalized_tiles;
      assign full_tiles = cfg_dimension[dimension][SIZE_SHIFT +: p_tile_width];
      assign partial_tile = |cfg_dimension[dimension][SIZE_SHIFT-1:0];
      kernel_count_increment #(.p_width(p_tile_width+1)) u_round_tiles (
          .i_value({full_tiles, partial_tile}), .o_next(increment_output)
      );
      assign normalized_tiles[0] = (full_tiles[0] ^ partial_tile) ||
          (full_tiles == '0) || (&full_tiles);
      if (p_tile_width > 1) begin : g_upper_tiles
        assign normalized_tiles[p_tile_width-1:1] = increment_output[p_tile_width:2];
      end
      always_comb begin
        case (^cfg_dimension[dimension])
          1'b0, 1'b1: begin
            cfg_normalized_tiles[dimension] = count_t'(normalized_tiles);
            cfg_single_tile[dimension] = (full_tiles == '0) ||
                (full_tiles == p_tile_width'(1) && !partial_tile) || ((&full_tiles) && partial_tile);
          end
          default: begin
            cfg_normalized_tiles[dimension] =
                divide_rounded_pow2(cfg_rounded[dimension], count_t'(SIZE));
            if (cfg_normalized_tiles[dimension] == 0) cfg_normalized_tiles[dimension] = count_t'(1);
            cfg_single_tile[dimension] = cfg_normalized_tiles[dimension] == count_t'(1);
          end
        endcase
      end
    end else begin : g_general
      always_comb begin
        cfg_normalized_tiles[dimension] = divide_rounded_pow2(cfg_rounded[dimension], count_t'(SIZE));
        if (cfg_normalized_tiles[dimension] == 0) cfg_normalized_tiles[dimension] = count_t'(1);
        cfg_single_tile[dimension] = cfg_normalized_tiles[dimension] == count_t'(1);
      end
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
  // 逐字节次序保留未知值传播，已知遍历状态使用同步保存的列尾资格。
  localparam int p_column_groups = (CNT_W+7)/8;
  logic [p_column_groups-1:0] column_group_less, column_group_equal, column_group_greater;
  for (genvar group = 0; group < p_column_groups; group++) begin : g_column_limit
    localparam int p_first = group*8;
    localparam int p_bits = CNT_W-p_first < 8 ? CNT_W-p_first : 8;
    assign column_group_less[group] = load_col_in_group[p_first+:p_bits] < current_group_width[p_first+:p_bits];
    assign column_group_equal[group] = load_col_in_group[p_first+:p_bits] == current_group_width[p_first+:p_bits];
    assign column_group_greater[group] = !column_group_less[group] && !column_group_equal[group];
  end
  assign column_below_limit = column_group_less > column_group_greater;
  assign unused_column_equal = &column_group_equal;
  add_equal #(.p_width(CNT_W), .p_preserve_bits(1'b1)) u_column_two_ahead (
      .i_a(load_col_in_group), .i_b(count_t'(2)), .i_target(current_group_width),
      .i_carry_in(1'b0), .o_equal(column_two_ahead_equal)
  );
  assign column_value_covers_limit = !column_below_limit;

  // 模宽递增的边界判断并行检查大小、相邻相等和回绕条件。
  // 行尾资格在行索引更新边沿保存，行位置输出与分组控制共用同一状态。
  add_equal #(.p_width(CNT_W), .p_preserve_bits(1'b1)) u_row_two_ahead (
      .i_a(load_tile_row), .i_b(count_t'(2)), .i_target(tile_rows_total),
      .i_carry_in(1'b0), .o_equal(row_two_ahead_equal)
  );
  always_comb begin
    case (^{load_tile_row, tile_rows_total})
      1'b0, 1'b1: begin
        last_tile_row = last_row_saved_q;
        row_last_equal_o_equal = last_row_saved_q;
      end
      default: begin
        last_tile_row = (load_tile_row + count_t'(1)) >= tile_rows_total;
        row_last_equal_o_equal = row_last_four_state;
      end
    endcase
  end
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
  logic following_value_less, unused_following_value_equal;
  (* keep = "true" *) logic following_one_equal, following_two_equal;
  logic following_wrap, following_binary;
  logic following_one_parallel, following_one_reference;
  logic [p_column_groups-1:0] following_group_less, following_group_equal, following_group_greater;
  // 前进两组的范围判断并行比较当前次序和两个相邻边界，最高计数单独处理回绕。
  unsigned_compare #(.p_width(CNT_W)) u_following_value_limit (
      .i_a(load_l2), .i_b(l2_groups_total),
      .o_less(following_value_less), .o_equal(unused_following_value_equal)
  );
  (* keep_hierarchy = "yes" *) increment_equal #(
      .p_width(CNT_W), .p_preserve_pairs(1'b1), .p_reduce_group_width(6)
  ) u_following_one_equal (
      .i_a(load_l2), .i_target(l2_groups_total), .o_equal(following_one_parallel)
  );
  add_equal #(.p_width(CNT_W), .p_preserve_bits(1'b1)) u_following_one_reference (
      .i_a(load_l2), .i_b(count_t'(1)), .i_target(l2_groups_total),
      .i_carry_in(1'b0), .o_equal(following_one_reference)
  );
  // 已知计数按相邻位分组比较，未知计数保留完整加法比较的四态结果。
  always_comb begin
      case (^{load_l2, l2_groups_total})
          1'b0, 1'b1: following_one_equal = following_one_parallel;
          default: following_one_equal = following_one_reference;
      endcase
  end
  add_equal #(.p_width(CNT_W), .p_preserve_bits(1'b1)) u_following_two_equal (
      .i_a(load_l2), .i_b(count_t'(2)), .i_target(l2_groups_total),
      .i_carry_in(1'b0), .o_equal(following_two_equal)
  );
  if (CNT_W > 1) begin : g_following_wrap
    assign following_wrap = &load_l2[CNT_W-1:1];
  end else begin : g_single_following_wrap
    assign following_wrap = 1'b1;
  end
  assign following_binary = following_wrap ?
      (l2_groups_total > count_t'(load_l2[0])) :
      (following_value_less && !following_one_equal && !following_two_equal);
  for (genvar group = 0; group < p_column_groups; group++) begin : g_following_four_state
    localparam int p_first = group*8;
    localparam int p_bits = CNT_W-p_first < 8 ? CNT_W-p_first : 8;
    assign following_group_less[group] = following_group_index[p_first+:p_bits] < l2_groups_total[p_first+:p_bits];
    assign following_group_equal[group] = following_group_index[p_first+:p_bits] == l2_groups_total[p_first+:p_bits];
    assign following_group_greater[group] = !following_group_less[group] && !following_group_equal[group];
  end
  assign unused_following_group_equal = &following_group_equal;
  always_comb begin
    case (^{load_l2, l2_groups_total})
      1'b0, 1'b1: following_group_below_limit = following_binary;
      default: following_group_below_limit = following_group_less > following_group_greater;
    endcase
  end
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

    cfg_tile_rows_total        = cfg_normalized_tiles[0];
    cfg_tile_cols_total        = cfg_normalized_tiles[1];
    cfg_output_row_tiles_total = divide_rounded_pow2(cfg_rounded[2], count_t'(SIZE));
    cfg_l2_groups_total = count_t'(cfg_col_groups);
    cfg_repeat_total = count_t'(cfg_row_groups);
    if (cfg_l2_groups_total == 0) cfg_l2_groups_total = count_t'(1);
    if (cfg_repeat_total == 0) cfg_repeat_total = count_t'(1);

    cfg_last_n_rows = count_t'(cfg_n & REG_WIDTH'(SIZE - 1));
    cfg_last_m_cols = count_t'(cfg_m & REG_WIDTH'(SIZE - 1));
    if (cfg_last_n_rows == 0) cfg_last_n_rows = count_t'(SIZE);
    if (cfg_last_m_cols == 0) cfg_last_m_cols = count_t'(SIZE);

    cfg_group_tail_cols = count_t'(cfg_col_tail_tiles);
    cfg_last_group_width = count_t'(cfg_col_tail_tiles);

    first_tile_width = tile_cols_total;
    first_reuse_width = w_reuse_total;
    if (first_tile_width == 0) first_tile_width = count_t'(1);
    if (first_reuse_width == 0) first_reuse_width = count_t'(1);
    if (first_group_below_limit) begin
      first_group_width = first_tile_width;
    end else begin
      first_group_width = first_reuse_width;
    end

    if (!following_group_below_limit) begin
      following_group_width = last_group_width;
    end else begin
      following_group_width = w_reuse_total;
    end

    // 尾项的零值规范化独立完成，晚到的尾部资格只选择完整有效行列数。
    normalized_n_rows = last_n_rows;
    normalized_m_cols = last_m_cols;
    if (normalized_n_rows == 0) normalized_n_rows = count_t'(1);
    if (normalized_m_cols == 0) normalized_m_cols = count_t'(1);
    case (row_last_equal_o_equal)
      1'b0: valid_n_rows = p_full_valid_count;
      1'b1: valid_n_rows = normalized_n_rows;
      default: begin
        valid_n_rows = row_last_equal_o_equal ? last_n_rows : count_t'(SIZE);
        if (valid_n_rows == 0) valid_n_rows = count_t'(1);
      end
    endcase
    case (column_last_equal_o_equal)
      1'b0: valid_m_cols = p_full_valid_count;
      1'b1: valid_m_cols = normalized_m_cols;
      default: begin
        valid_m_cols = column_last_equal_o_equal ? last_m_cols : count_t'(SIZE);
        if (valid_m_cols == 0) valid_m_cols = count_t'(1);
      end
    endcase
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
    if (CNT_W >= 11 && REG_WIDTH >= 11) begin
      // 已知输入使用统一乘积，未知位继续按各移位候选传播。
      case (^col_addr_step)
        1'b0, 1'b1: group_addr_step_next = group_step_product;
        default: begin end
      endcase
    end

    case (^{load_col_in_group, current_group_width})
      1'b0, 1'b1: last_col_in_group = last_col_saved_q;
      default: last_col_in_group = (current_group_width == '0) ||
          (!column_increment_wrap && (column_value_covers_limit || column_next_equals_limit));
    endcase
    final_load_done = load_done && all_loads_issued && load_count_reached;

    load_complete = all_loads_done;

    tile_row_dbg = REG_WIDTH'(load_tile_row);
    tile_col_dbg = REG_WIDTH'(load_tile_col);
    repeat_dbg   = REG_WIDTH'(load_repeat);

    load_weight_req = !clear && load_pending_q && buf_load_ready;
    dma_start       = load_weight_req && load_weight_granted;
    buf_load_start  = dma_start;
    buf_send_start  = !clear && (state == S_RUN) && send_weight_trigger && buf_weight_data_valid;
    ctrl_all_done   = !clear && (state == S_DONE);

    // 权重按列展开，每个 DMA 行对应一个输出列，行内读取连续归约元素。
    // 输入驻留模式复用相同装载顺序，输出位置替代输出通道索引。
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
      .o_equal(row_last_four_state)
  );
  add3_equal #(.p_width(CNT_W)) u_column_last_equal (
      .i_a(column_last_equal_i_a), .i_b(column_last_equal_i_b),
      .i_c(column_last_equal_i_c), .i_target(column_last_equal_i_target),
      .o_equal(column_last_equal_four_state)
  );
  // 相邻两位共同检查加一关系，完整归并结果独立于尾项和描述符选择。
  (* keep_hierarchy = "yes" *)
  (* keep_hierarchy = "yes" *) increment_equal #(.p_width(CNT_W), .p_preserve_pairs(1'b1)) u_saved_column_last_equal (
      .i_a(column_position_q), .i_target(column_last_equal_i_target),
      .o_equal(column_last_equal_fast)
  );
  // 列尾比较使用完整列位置；未知输入保持三操作数逐位比较的传播规则。
  always_comb begin
    case (^{column_last_equal_i_a, column_last_equal_i_b, column_last_equal_i_target})
      1'b0, 1'b1: column_last_equal_o_equal = column_last_equal_fast;
      default: column_last_equal_o_equal = column_last_equal_four_state;
    endcase
  end

  (* keep = "true" *) logic advance_row, advance_group, advance_repeat;
  // 行、分组和重复次数的更新资格独立准备，请求接收只控制寄存使能。
  always_comb begin
    advance_row = 1'b0;
    advance_group = 1'b0;
    advance_repeat = 1'b0;
    if (!last_col_in_group) begin
    end else begin
      advance_row = 1'b1;
      if (!last_tile_row) begin
      end else begin
        advance_group = 1'b1;
        if (!last_l2_group) begin
        end else if (!last_repeat) begin
          advance_repeat = 1'b1;
        end
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state               <= S_IDLE;
      load_pending_q      <= 1'b0;
      load_tile_row       <= '0;
      load_repeat         <= '0;
      load_l2             <= '0;
      load_col_in_group   <= '0;
      pending_loads       <= '0;
      pending_sends       <= '0;
      all_loads_done      <= 1'b0;
      all_loads_issued    <= 1'b0;
      issued_count       <= '0;
      last_col_saved_q   <= 1'b1;
      last_row_saved_q   <= 1'b1;
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
      column_position_q   <= '0;
      group_base_addr     <= '0;
      row_addr_offset     <= '0;
      col_addr_offset     <= '0;
      row_base_address_q  <= '0;
      dma_address_q       <= '0;
    end else if (clear) begin
      // 配置清空当前遍历，下一配置接收边沿更新地址与各维度计数。
      state<=S_IDLE;
      load_pending_q<=1'b0;
      all_loads_done<=1'b0;
      all_loads_issued<=1'b0;
    end else begin
      case (state)
        S_IDLE: begin
          load_pending_q <= 1'b0;
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
            last_col_saved_q   <= 1'b1;
            last_row_saved_q   <= cfg_single_tile[0];
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
            column_position_q   <= '0;
            group_base_addr     <= cfg_rhs_base;
            row_addr_offset     <= '0;
            col_addr_offset     <= '0;
            row_base_address_q  <= cfg_rhs_base;
            dma_address_q       <= cfg_rhs_base;
            state               <= S_INIT;
          end
        end

        S_INIT: begin
          // 列步长和复用次数已在配置接受边沿保存，此周期计算分组步长。
          group_addr_step_q   <= group_addr_step_next;
          current_group_width <= first_group_width;
          last_col_saved_q <= first_group_below_limit ?
              tile_cols_total <= count_t'(1) : w_reuse_total <= count_t'(1);
          group_base_addr     <= base_addr_reg;
          column_position_q   <= '0;
          row_base_address_q  <= base_addr_reg;
          dma_address_q       <= base_addr_reg;
          state               <= S_RUN;
          // 进入运行状态时保存待发资格，接收处直接读取这一位状态。
          load_pending_q      <= !all_loads_issued;
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
            if (last_col_in_group && last_tile_row && last_l2_group && last_repeat) begin
              all_loads_issued <= 1'b1;
              load_pending_q <= 1'b0;
            end
            if (!last_col_in_group) begin
              load_col_in_group <= traversal_o_next[0];
              column_position_q <= column_position_next;
              last_col_saved_q <= column_two_ahead_equal;
              col_addr_offset <= column_offset_increment;
              dma_address_q <= dma_address_increment;
            end else begin
              load_col_in_group <= '0;
              column_position_q <= group_base_col;
              last_col_saved_q <= current_group_width <= count_t'(1);
              col_addr_offset <= '0;
            end
            if (advance_row) begin
              if (!last_tile_row) begin
                load_tile_row <= traversal_o_next[1];
                last_row_saved_q <= row_two_ahead_equal;
                row_addr_offset <= row_offset_increment;
                row_base_address_q <= row_base_address_increment;
                dma_address_q <= row_base_address_increment;
              end else begin
                load_tile_row <= '0;
                last_row_saved_q <= tile_rows_total == count_t'(1);
                row_addr_offset <= '0;
              end
            end
            if (advance_group) begin
              if (!last_l2_group) begin
                load_l2 <= traversal_o_next[2];
                group_base_col <= group_column_increment;
                column_position_q <= group_column_increment;
                current_group_width <= following_group_width;
                last_col_saved_q <= following_group_below_limit ?
                    w_reuse_total <= count_t'(1) : last_group_width <= count_t'(1);
                group_base_addr <= group_address_increment;
                row_base_address_q <= group_address_increment;
                dma_address_q <= group_address_increment;
              end else begin
                load_l2 <= '0;
                group_base_col <= '0;
                column_position_q <= '0;
                current_group_width <= first_group_width;
                last_col_saved_q <= first_group_below_limit ?
              tile_cols_total <= count_t'(1) : w_reuse_total <= count_t'(1);
                group_base_addr <= base_addr_reg;
                row_base_address_q <= base_addr_reg;
                dma_address_q <= base_addr_reg;
              end
            end
            if (advance_repeat) begin
              load_repeat <= traversal_o_next[3];
            end
          end

          if (buf_weight_sending_done) begin
            if (sending_completes_task) begin
              state <= S_DONE;
              load_pending_q <= 1'b0;
            end
          end
        end

        S_DONE: begin
          load_pending_q <= 1'b0;
          if (!cfg_valid) begin
            state <= S_IDLE;
          end
        end

        default: begin
          state <= S_IDLE;
          load_pending_q <= 1'b0;
        end
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
  // 零值和单次发出状态共用高位归零条件，最低位在完成控制末端参与区分。
  // 完整发出计数的高位零值独立归并，再参与有界计数的回绕检查。
  zero_reduce #(.p_width(TOTAL_CNT_W-1)) u_issued_high_zero (
      .i_value(issued_count[TOTAL_CNT_W-1:1]), .o_zero(issued_high_zero)
  );
  assign issued_zero = issued_high_zero && !issued_count[0];
  assign issued_one = issued_high_zero && issued_count[0];
  assign load_count_reached = pending_loads == 1 || (pending_loads == 2 && issued_zero);
  kernel_completion_check u_completion (
      .i_pending_loads(pending_loads), .i_pending_sends(pending_sends),
      .i_issued_zero(issued_zero), .i_issued_one(issued_one),
      .i_all_loads_done(all_loads_done), .i_all_loads_issued(all_loads_issued),
      .i_load_done(load_done), .o_complete(sending_completes_task)
  );

endmodule

`default_nettype wire
