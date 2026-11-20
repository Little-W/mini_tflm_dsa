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
  count_t last_group_width;
  count_t following_group_width;
  count_t row_last_equal_i_a, row_last_equal_i_b, row_last_equal_i_target;
  logic row_last_equal_i_carry_in;
  logic row_last_equal_o_equal;
  count_t column_last_equal_i_a, column_last_equal_i_b, column_last_equal_i_c;
  count_t column_last_equal_i_target;
  logic column_last_equal_o_equal;

  function automatic count_t ceil_div_pow2(input logic [REG_WIDTH-1:0] a,
                                           input count_t pow2);
    logic [REG_WIDTH-1:0] biased;
    begin
      biased = a + REG_WIDTH'(pow2) - REG_WIDTH'(1);
      unique case (pow2)
        count_t'(1):    ceil_div_pow2 = count_t'(biased);
        count_t'(2):    ceil_div_pow2 = count_t'(biased >> 1);
        count_t'(4):    ceil_div_pow2 = count_t'(biased >> 2);
        count_t'(8):    ceil_div_pow2 = count_t'(biased >> 3);
        count_t'(16):   ceil_div_pow2 = count_t'(biased >> 4);
        count_t'(32):   ceil_div_pow2 = count_t'(biased >> 5);
        count_t'(64):   ceil_div_pow2 = count_t'(biased >> 6);
        count_t'(128):  ceil_div_pow2 = count_t'(biased >> 7);
        count_t'(256):  ceil_div_pow2 = count_t'(biased >> 8);
        count_t'(512):  ceil_div_pow2 = count_t'(biased >> 9);
        count_t'(1024): ceil_div_pow2 = count_t'(biased >> 10);
        default:        ceil_div_pow2 = count_t'(biased);
      endcase
    end
  endfunction

  always_comb begin
    ia_reuse_norm = (cfg_ia_reuse_num == 0) ? count_t'(1) : count_t'(cfg_ia_reuse_num);
    w_reuse_norm  = (cfg_w_reuse_num  == 0) ? count_t'(1) : count_t'(cfg_w_reuse_num);

    cfg_tile_rows_total        = ceil_div_pow2(cfg_n, count_t'(SIZE));
    cfg_tile_cols_total        = ceil_div_pow2(cfg_m, count_t'(SIZE));
    cfg_output_row_tiles_total = ceil_div_pow2(cfg_k, count_t'(SIZE));
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

    if (tile_cols_total < w_reuse_total) begin
      first_group_width = tile_cols_total;
    end else begin
      first_group_width = w_reuse_total;
    end
    if (first_group_width == 0) first_group_width = count_t'(1);

    if ((load_l2 + count_t'(2)) >= l2_groups_total) begin
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
      count_t'(25):   group_addr_step_next = (col_addr_step << 4) + (col_addr_step << 3) + col_addr_step;
      count_t'(32):   group_addr_step_next = col_addr_step << 5;
      count_t'(64):   group_addr_step_next = col_addr_step << 6;
      count_t'(128):  group_addr_step_next = col_addr_step << 7;
      count_t'(256):  group_addr_step_next = col_addr_step << 8;
      count_t'(512):  group_addr_step_next = col_addr_step << 9;
      count_t'(1024): group_addr_step_next = col_addr_step << 10;
      default:          group_addr_step_next = col_addr_step;
    endcase

    last_col_in_group = (load_col_in_group + count_t'(1) >= current_group_width);
    last_tile_row     = (load_tile_row + count_t'(1) >= tile_rows_total);
    last_l2_group     = (load_l2 + count_t'(1) >= l2_groups_total);
    last_repeat       = (load_repeat + count_t'(1) >= repeat_total);
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
    dma_tile_base_addr = group_base_addr + row_addr_offset + col_addr_offset;
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
              load_col_in_group <= load_col_in_group + 1'b1;
              col_addr_offset   <= col_addr_offset + col_addr_step;
            end else begin
              load_col_in_group <= '0;
              col_addr_offset   <= '0;
              if (!last_tile_row) begin
                load_tile_row   <= load_tile_row + 1'b1;
                row_addr_offset <= row_addr_offset + row_addr_step;
              end else begin
                load_tile_row   <= '0;
                row_addr_offset <= '0;
                if (!last_l2_group) begin
                  load_l2             <= load_l2 + 1'b1;
                  group_base_col      <= group_base_col + current_group_width;
                  current_group_width <= following_group_width;
                  group_base_addr     <= group_base_addr + group_addr_step_q;
                end else begin
                  load_l2             <= '0;
                  group_base_col      <= '0;
                  current_group_width <= first_group_width;
                  group_base_addr     <= base_addr_reg;
                  if (!last_repeat) begin
                    load_repeat <= load_repeat + 1'b1;
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
            issued_chunk_carry_q[part] <= !issued_count[0] && (&issued_count[p_low-1:1]);
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

// FPGA 比较器并行计算四十七位差值，符号和零值由同一 DSP 提供。
module kernel_count_compare #(
    parameter int p_width = 48,
    parameter int p_chunk_width = 8
) (
    input  wire logic [p_width-1:0] i_lhs,
    input  wire logic [p_width-1:0] i_rhs,
    output logic o_ge
);
`ifdef SYNTHESIS
`ifdef ASIC_SYNTHESIS
    localparam bit p_fpga_compare = 1'b0;
`else
    localparam bit p_fpga_compare = 1'b1;
`endif
`else
    localparam bit p_fpga_compare = 1'b0;
`endif
    localparam int p_compare_width = p_fpga_compare ? 47 : p_chunk_width;
    localparam int p_chunks = (p_width + p_compare_width - 1) / p_compare_width;
    localparam int p_leaves = 1 << $clog2(p_chunks);
    logic [2*p_leaves-1:1] equal_tree;
    logic [2*p_leaves-1:1] greater_tree;

    for (genvar part = 0; part < p_leaves; part++) begin : g_compare
        if (part < p_chunks) begin : g_value
            localparam int p_low = part * p_compare_width;
            localparam int p_part_width = ((p_width - p_low) < p_compare_width) ?
                p_width - p_low : p_compare_width;
            if (p_fpga_compare) begin : g_dsp
                logic [47:0] rhs_extended;
                logic [29:0] dsp_i_a, dsp_i_acin;
                logic [17:0] dsp_i_b, dsp_i_bcin;
                logic [47:0] dsp_i_c, dsp_i_pcin, dsp_o_p;
                logic [24:0] dsp_i_d;
                logic [6:0] dsp_i_opmode;
                logic [4:0] dsp_i_inmode;
                logic [3:0] dsp_i_alumode;
                logic [2:0] dsp_i_carryinsel;
                logic dsp_i_zero, dsp_o_equal;
                logic [29:0] unused_acout;
                logic [17:0] unused_bcout;
                logic [47:0] unused_pcout;
                logic [3:0] unused_carryout;
                logic unused_carrycascout, unused_multsignout;
                logic unused_overflow, unused_underflow, unused_patternbdetect;

                assign rhs_extended = 48'(i_rhs[p_low +: p_part_width]);
                assign dsp_i_a = rhs_extended[47:18];
                assign dsp_i_b = rhs_extended[17:0];
                assign dsp_i_c = 48'(i_lhs[p_low +: p_part_width]);
                assign dsp_i_acin = 30'd0;
                assign dsp_i_bcin = 18'd0;
                assign dsp_i_pcin = 48'd0;
                assign dsp_i_d = 25'd0;
                assign dsp_i_opmode = 7'b0110011;
                assign dsp_i_inmode = 5'd0;
                assign dsp_i_alumode = 4'b0011;
                assign dsp_i_carryinsel = 3'd0;
                assign dsp_i_zero = 1'b0;
                assign equal_tree[p_leaves + part] = dsp_o_equal;
                assign greater_tree[p_leaves + part] = !dsp_o_p[47] && !dsp_o_equal;

                DSP48E1 #(
                    .A_INPUT("DIRECT"), .B_INPUT("DIRECT"), .USE_DPORT("FALSE"),
                    .USE_MULT("NONE"), .USE_SIMD("ONE48"),
                    .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .CREG(0), .DREG(0),
                    .ADREG(0), .MREG(0), .PREG(0), .INMODEREG(0), .OPMODEREG(0),
                    .ALUMODEREG(0), .CARRYINREG(0), .CARRYINSELREG(0),
                    .USE_PATTERN_DETECT("PATDET"), .MASK(48'd0), .PATTERN(48'd0)
                ) u_dsp (
                    .A(dsp_i_a), .B(dsp_i_b), .C(dsp_i_c), .D(dsp_i_d),
                    .ACIN(dsp_i_acin), .BCIN(dsp_i_bcin), .PCIN(dsp_i_pcin),
                    .ALUMODE(dsp_i_alumode), .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode),
                    .CARRYIN(dsp_i_zero), .CARRYINSEL(dsp_i_carryinsel),
                    .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero), .CLK(dsp_i_zero),
                    .CEA1(dsp_i_zero), .CEA2(dsp_i_zero), .CEB1(dsp_i_zero), .CEB2(dsp_i_zero),
                    .CEC(dsp_i_zero), .CED(dsp_i_zero), .CEAD(dsp_i_zero), .CEM(dsp_i_zero),
                    .CEP(dsp_i_zero), .CEINMODE(dsp_i_zero), .CECTRL(dsp_i_zero),
                    .CEALUMODE(dsp_i_zero), .CECARRYIN(dsp_i_zero),
                    .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
                    .RSTM(dsp_i_zero), .RSTP(dsp_i_zero), .RSTINMODE(dsp_i_zero),
                    .RSTCTRL(dsp_i_zero), .RSTALUMODE(dsp_i_zero), .RSTALLCARRYIN(dsp_i_zero),
                    .P(dsp_o_p), .CARRYOUT(unused_carryout),
                    .ACOUT(unused_acout), .BCOUT(unused_bcout), .PCOUT(unused_pcout),
                    .CARRYCASCOUT(unused_carrycascout), .MULTSIGNOUT(unused_multsignout),
                    .OVERFLOW(unused_overflow), .UNDERFLOW(unused_underflow),
                    .PATTERNDETECT(dsp_o_equal), .PATTERNBDETECT(unused_patternbdetect)
                );
            end else begin : g_logic
                assign equal_tree[p_leaves + part] =
                    i_lhs[p_low +: p_part_width] == i_rhs[p_low +: p_part_width];
                assign greater_tree[p_leaves + part] =
                    i_lhs[p_low +: p_part_width] > i_rhs[p_low +: p_part_width];
            end
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

`default_nettype wire
