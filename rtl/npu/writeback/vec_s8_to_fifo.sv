`default_nettype none

module vec_s8_to_fifo_full #(
    parameter integer VLEN  = 16,
    parameter integer BANKS = 16,
    parameter integer BUS_WIDTH = 32,
    parameter integer ENABLE_TRANSPOSE = 1,
    // 启用时，合并输出从开始到完成期间须保持 transpose_mode。
    parameter bit p_cyclic_storage = 1'b0,
    parameter bit p_precomputed_watermark = 1'b0
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 start_permitted,
    input  wire                 in_valid,
    input  wire                 in_tile_done,
    input  wire [   VLEN*8-1:0] in_vec_s8,
    output reg                  oa_fifo_req,
    input  wire                 transpose_mode,
    input  wire                 coalesce_enable,
    input  wire                 coalesce_group_start,
    input  wire [31:0]          coalesce_rows,
    input  wire [31:0]          coalesce_cols,
    input  wire [          31:0] reserve_banks,
    input  wire [31:0] i_ready_bank_threshold,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_col,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_row,
    output wire                 output_valid,
    input  wire                 output_ready,
    output wire                 output_row_switch,
    output reg  [BUS_WIDTH/8-1:0] output_mask,
    output reg  [BUS_WIDTH-1:0] output_data,
    output wire                 fifo_full_flag
);

  localparam integer PTR_WIDTH   = (VLEN <= 1) ? 1 : $clog2(VLEN);
  localparam integer COUNT_WIDTH = $clog2(VLEN + 1);
  localparam integer BYTE_PER_BEAT = BUS_WIDTH / 8;
  localparam integer BYTE_SHIFT = $clog2(BYTE_PER_BEAT);
  localparam integer ROW_BEATS = (VLEN + BYTE_PER_BEAT - 1) / BYTE_PER_BEAT;
  localparam integer BEAT_WIDTH  = (ROW_BEATS <= 1) ? 1 : $clog2(ROW_BEATS);
  localparam integer BANK_WIDTH  = (BANKS <= 1) ? 1 : $clog2(BANKS);
  localparam integer BANK_COUNT_WIDTH = (BANKS <= 1) ? 1 : $clog2(BANKS + 1);
  localparam integer ROW_BANKS   = BYTE_PER_BEAT;
  localparam bit p_use_cyclic_storage = p_cyclic_storage && VLEN == 16 &&
      (BUS_WIDTH == 32 || BUS_WIDTH == 64);
  localparam integer MEM_DEPTH = p_use_cyclic_storage ? BANKS * VLEN : BANKS * ROW_BEATS;
  localparam integer p_mem_data_width = p_use_cyclic_storage ? ROW_BEATS * 8 : VLEN * 8;
  localparam integer MEM_ADDR_W  = (MEM_DEPTH <= 1) ? 1 : $clog2(MEM_DEPTH);

  localparam bit p_count_storage = BANKS >= 8 && (BANKS & (BANKS-1)) == 0;
  logic [BANKS-1:0] bank_write_complete, bank_release;

  reg [BANKS-1:0] bank_ready;
  reg [BANK_COUNT_WIDTH-1:0] ready_bank_count_q;
  reg [COUNT_WIDTH-1:0] active_read_count_q;
  logic [COUNT_WIDTH-1:0] last_beat_idx_q;

  reg [BANK_WIDTH-1:0]  write_bank;
  logic [BANKS-1:0] write_bank_mask_q;
  reg [BANK_WIDTH-1:0]  read_bank;
  reg [PTR_WIDTH-1:0]   write_ptr;
  reg [PTR_WIDTH-1:0]   read_ptr;
  reg                   stream_active;
  reg                   data_valid;
  reg [BEAT_WIDTH-1:0]  beat_idx;
  reg [$clog2(VLEN)-1:0] vec_valid_num_col_tmp;
  reg [$clog2(VLEN)-1:0] vec_valid_num_row_tmp;
  reg                   transpose_mode_tmp;
  logic [VLEN*8-1:0] ram_rd_data [ROW_BANKS];
  logic [MEM_ADDR_W-1:0] ram_wr_addr;
  logic [MEM_ADDR_W-1:0] ram_rd_addr [ROW_BANKS];
  logic [PTR_WIDTH-1:0] issue_read_ptr;
  logic [BEAT_WIDTH-1:0] issue_beat_idx;
  logic issue_transpose_mode;
  logic ram_read_en;
  logic refresh_first_mode;
  logic [BANK_WIDTH-1:0] read_issue_bank;
  logic [PTR_WIDTH-1:0] read_issue_row;
  logic [BEAT_WIDTH-1:0] read_issue_beat;
  logic read_issue_transpose;
  logic [p_mem_data_width-1:0] ram_wr_data [ROW_BANKS];
  logic ram_write_en;
  wire transpose_mode_eff = (ENABLE_TRANSPOSE != 0) ? transpose_mode : 1'b0;
  // WS groups arrive as [column tile][R row tiles]. IS groups contain R
  // transposed channel tiles. Both drain as contiguous logical output rows.
  logic co_active, co_data_valid;
  logic [8:0] co_row;
  logic [4:0] co_col;
  logic [BEAT_WIDTH-1:0] co_beat;
  logic [8:0] co_next_row;
  logic [4:0] co_next_col;
  logic [BEAT_WIDTH-1:0] co_next_beat;
  logic [BANK_COUNT_WIDTH-1:0] co_tiles;
  logic [BANK_COUNT_WIDTH-1:0] co_tile_partial [0:4];
  logic [BANK_COUNT_WIDTH-1:0] co_tile_sum [0:2];
  logic [BANK_COUNT_WIDTH-1:0] co_tile_carry [0:2];
  (* use_dsp = "yes" *) logic [BANK_COUNT_WIDTH-1:0] co_tile_product;
  // 部分积在银行计数宽度内保留，进位保存归并只在最后一步传播进位。
  for (genvar term = 0; term < 5; term++) begin : g_co_tile_partial
    assign co_tile_partial[term] =
        (BANK_COUNT_WIDTH'(coalesce_cols[4:0]) << term) &
        {BANK_COUNT_WIDTH{coalesce_rows[term]}};
  end
  assign co_tile_sum[0] = co_tile_partial[0] ^ co_tile_partial[1] ^ co_tile_partial[2];
  assign co_tile_carry[0] = ((co_tile_partial[0] & co_tile_partial[1]) |
      (co_tile_partial[0] & co_tile_partial[2]) |
      (co_tile_partial[1] & co_tile_partial[2])) << 1;
  assign co_tile_sum[1] = co_tile_partial[3] ^ co_tile_partial[4] ^ co_tile_carry[0];
  assign co_tile_carry[1] = ((co_tile_partial[3] & co_tile_partial[4]) |
      (co_tile_partial[3] & co_tile_carry[0]) |
      (co_tile_partial[4] & co_tile_carry[0])) << 1;
  assign co_tile_sum[2] = co_tile_sum[0] ^ co_tile_sum[1] ^ co_tile_carry[1];
  assign co_tile_carry[2] = ((co_tile_sum[0] & co_tile_sum[1]) |
      (co_tile_sum[0] & co_tile_carry[1]) |
      (co_tile_sum[1] & co_tile_carry[1])) << 1;
  assign co_tile_product = co_tile_sum[2] + co_tile_carry[2];
  // 已知输入使用归并结果，含未知位的输入保留乘法的四态传播语义。
  always_comb begin
    co_tiles = BANK_COUNT_WIDTH'(coalesce_rows[4:0] * coalesce_cols[4:0]);
    case (^{coalesce_rows[4:0], coalesce_cols[4:0]})
      1'b0, 1'b1: begin
        co_tiles = co_tile_product;
      end
    endcase
  end
  logic [4:0] co_nonzero_terms;
  // 截断乘积非零时，至少有一对置位输入的位序之和落在保留范围内。
  // 并行判断各行位可影响的列位，启动条件不等待完整乘法结果。
  for (genvar row_bit = 0; row_bit < 5; row_bit++) begin : g_co_tiles_nonzero
    if (row_bit < BANK_COUNT_WIDTH) begin : g_retained
      localparam int p_column_bits = ((BANK_COUNT_WIDTH-row_bit) < 5) ?
          (BANK_COUNT_WIDTH-row_bit) : 5;
      assign co_nonzero_terms[row_bit] = coalesce_rows[row_bit] &&
          (|coalesce_cols[p_column_bits-1:0]);
    end else begin : g_discarded
      assign co_nonzero_terms[row_bit] = 1'b0;
    end
  end
  wire co_start = start_permitted && coalesce_enable && !co_active &&
      ready_bank_count_q != 0 && (|co_nonzero_terms) &&
      (transpose_mode_eff || coalesce_group_start);
  wire co_fire = coalesce_enable && co_active && co_data_valid && output_ready;
  logic [BANK_WIDTH-1:0] co_following_bank;
  logic [BANK_WIDTH-1:0] co_current_bank;
  logic [4:0] co_last_col_q, co_last_tile_row_q;
  wire co_col_last = co_col == co_last_col_q;
  wire co_row_last = co_col_last && co_beat == BEAT_WIDTH'(ROW_BEATS - 1);
  logic co_selected_row_last;
  logic [COUNT_WIDTH-1:0] co_row_limit_q;
  logic [3:0] co_next_row_low;
  assign co_next_row_low = co_row[3:0] + 4'd1;

  // 与行号同周期保存比较上限，四位行号回绕后重新从一开始。
  // 先完成四位回绕，再按计数宽度扩展或截断，保持全部参数的原有行为。
  always_ff @(posedge clk) begin
    if (!rst_n) co_row_limit_q <= COUNT_WIDTH'(1);
    else if (co_start) co_row_limit_q <= COUNT_WIDTH'(1);
    else if (co_fire && co_row_last)
      co_row_limit_q <= COUNT_WIDTH'(co_next_row_low) + COUNT_WIDTH'(1);
  end
  logic bank_count_i_wr_en;
  logic [BANK_WIDTH-1:0] bank_count_i_wr_addr;
  logic [COUNT_WIDTH-1:0] bank_count_i_wr_data;
  logic [1:0][BANK_WIDTH-1:0] bank_count_i_rd_addr;
  logic [1:0][COUNT_WIDTH-1:0] bank_count_o_rd_data;
  logic [COUNT_WIDTH-1:0] read_bank_count, co_bank_count;

  logic co_group_last_result;
  wire co_group_last = co_group_last_result;
  // 行列结束条件并行比较，转置模式按有效行数选择组结束结果。
  assign co_group_last_result = co_row_last &&
      (transpose_mode_eff ? (co_row[3:0] == vec_valid_num_row)
                          : (co_row[8:4] == co_last_tile_row_q && co_selected_row_last));
  wire co_finish = co_fire && co_group_last;
  wire [BANK_WIDTH-1:0] co_bank_after = BANK_WIDTH'((int'(read_bank) + int'(co_tiles)) % BANKS);
  wire co_load_waiting = coalesce_enable && co_active && !co_data_valid && bank_ready[co_current_bank];
  logic co_continue_bank_ready;
  // 继续输出时依据拍号选择银行，组启动条件独立控制首拍。
  assign co_continue_bank_ready = (co_beat == BEAT_WIDTH'(ROW_BEATS - 1)) ?
      bank_ready[co_following_bank] : bank_ready[co_current_bank];
  logic [BANK_WIDTH-1:0] co_issue_bank;
  logic [MEM_ADDR_W-1:0] co_ram_addr;
  always_comb begin
    co_next_row = co_row; co_next_col = co_col; co_next_beat = co_beat;
    if (co_start) begin
      co_next_row = 0; co_next_col = 0; co_next_beat = 0;
    end else if (co_fire) begin
      co_next_beat = co_beat + 1'b1;
      if (co_beat == BEAT_WIDTH'(ROW_BEATS - 1)) begin
        co_next_col = co_col + 1'b1;
        if (co_col_last) begin
          co_next_col = 0;
          co_next_row = co_row + 1'b1;
        end
      end
    end
    co_issue_bank = co_current_bank;
    if (co_start) co_issue_bank = read_bank;
    else if (co_fire && co_beat == BEAT_WIDTH'(ROW_BEATS - 1)) co_issue_bank = co_following_bank;
    co_ram_addr = MEM_ADDR_W'(int'(co_issue_bank) * ROW_BEATS +
        (transpose_mode_eff ? int'(co_next_beat) : ((int'(co_next_row) & 15) >> BYTE_SHIFT)));
  end

  // Prepare the next column's bank before the final beat. The final
  // RAM request uses registered addresses and a bank-ready lookup.
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      co_following_bank <= 0; co_last_col_q <= 0; co_last_tile_row_q <= 0;
    end else begin
      if (co_start) begin
        co_last_col_q <= coalesce_cols[4:0] - 5'd1;
        co_last_tile_row_q <= coalesce_rows[4:0] - 5'd1;
      end
      if (co_active && co_beat != BEAT_WIDTH'(ROW_BEATS - 1)) begin
        if (co_col_last)
          co_following_bank <= transpose_mode_eff ? read_bank :
              BANK_WIDTH'((int'(read_bank) + ((int'(co_row)+1)>>4)) % BANKS);
        else
          co_following_bank <= BANK_WIDTH'((int'(co_current_bank) + int'(coalesce_rows[4:0])) % BANKS);
      end
    end
  end

  function automatic [BANK_WIDTH-1:0] next_bank(input [BANK_WIDTH-1:0] bank);
    begin
      if (bank == BANK_WIDTH'(BANKS - 1)) next_bank = '0;
      else                               next_bank = bank + 1'b1;
    end
  endfunction

  logic [BANKS-1:0] next_write_bank_mask;
  if (BANKS == 1) begin : g_single_write_bank
    assign next_write_bank_mask = 1'b1;
  end else begin : g_multiple_write_banks
    assign next_write_bank_mask = {write_bank_mask_q[BANKS-2:0], write_bank_mask_q[BANKS-1]};
  end
  // 写入银行同时保存独热位置，相邻银行的阻塞判断只需并行选择与归并。
  logic [BANKS-1:0] bank_ready_next, write_bank_mask_next, next_bank_mask_next;
  logic write_bank_blocked_q, next_write_bank_blocked_q;
  wire write_bank_blocked = write_bank_blocked_q;
  wire next_write_bank_blocked = next_write_bank_blocked_q;
`ifdef NPU_SIM_ASSERT
  if (BANKS > 32) begin : g_check_write_capacity
    initial forever @(posedge clk) begin
      if (rst_n && in_valid)
        assert (!write_bank_blocked) else $fatal(1, "S8 output FIFO has no available write bank");
    end
  end
`endif
  logic                   fifo_watermark_full;
  // A temporary valid gap can appear between cached IA slots.  Only the
  // explicit tile_done marker is allowed to publish a bank to the writer.
  wire finish_write_bank = in_valid && in_tile_done;
  always_ff @(posedge clk) begin
    if (!rst_n) write_bank_mask_q <= {{(BANKS-1){1'b0}}, 1'b1};
    else if (finish_write_bank && !write_bank_blocked)
      write_bank_mask_q <= next_write_bank_mask;
  end
  // 银行状态和写入位置共同更新时保存阻塞资格，外部控制直接读取寄存结果。
  always_comb begin
    write_bank_mask_next = write_bank_mask_q;
    if (finish_write_bank && !write_bank_blocked) begin
      write_bank_mask_next = next_write_bank_mask;
    end
  end
  if (BANKS == 1) begin : g_single_next_mask
    assign next_bank_mask_next = 1'b1;
  end else begin : g_rotated_next_mask
    assign next_bank_mask_next = {write_bank_mask_next[BANKS-2:0], write_bank_mask_next[BANKS-1]};
  end
  wire [COUNT_WIDTH-1:0] write_rows_next =
      in_valid ? (COUNT_WIDTH'(write_ptr) + COUNT_WIDTH'(1)) : COUNT_WIDTH'(write_ptr);
  assign co_selected_row_last = co_row_limit_q >= co_bank_count;
  logic selected_read_bank_ready;
  if (p_count_storage) begin : g_read_bank_selection
    // 每层完成四选一，所保存的组合边界限制银行有效位选择的深度。
    localparam integer p_select_levels = (BANK_WIDTH + 1) / 2;
    wire [BANKS-1:0] ready_level [0:p_select_levels];
    assign ready_level[0] = bank_ready;
    for (genvar level = 0; level < p_select_levels; level++) begin : g_level
      localparam integer p_inputs = BANKS >> (2 * level);
      localparam integer p_outputs = (p_inputs + 3) / 4;
      (* keep = 1 *) logic [p_outputs-1:0] ready_group;
      for (genvar group_index = 0; group_index < p_outputs; group_index++) begin : g_group
        if (p_inputs >= 4) begin : g_four
          wire [3:0] group_ready = ready_level[level][group_index*4+:4];
          assign ready_group[group_index] = group_ready[read_bank[level*2+:2]];
        end else begin : g_two
          wire [1:0] group_ready = ready_level[level][1:0];
          assign ready_group[group_index] = group_ready[read_bank[level*2]];
        end
      end
      assign ready_level[level+1] = BANKS'(ready_group);
    end
    assign selected_read_bank_ready = ready_level[p_select_levels][0];
  end else begin : g_direct_read_bank_selection
    assign selected_read_bank_ready = bank_ready[read_bank];
  end

  if (p_count_storage) begin : g_count_memory
    // 计数只在银行完成写入时保存；有效位同时管理复位和银行释放。
    // 两个异步读端口分别服务普通输出和合并输出，读取周期保持不变。
    assign bank_count_i_wr_en = rst_n && finish_write_bank && !write_bank_blocked;
    assign bank_count_i_wr_addr = write_bank;
    assign bank_count_i_wr_data = write_rows_next;
    assign bank_count_i_rd_addr[0] = read_bank;
    assign bank_count_i_rd_addr[1] = co_current_bank;
    assign read_bank_count = selected_read_bank_ready ? bank_count_o_rd_data[0] : '0;
    assign co_bank_count = bank_ready[co_current_bank] ? bank_count_o_rd_data[1] : '0;

    regfile #(
        .p_data_width(COUNT_WIDTH), .p_depth(BANKS), .p_addr_width(BANK_WIDTH),
        .p_write_unit(COUNT_WIDTH), .p_read_ports(2), .p_sync_read(1'b0)
    ) u_bank_count (
        .clk(clk), .i_wr_en(bank_count_i_wr_en), .i_wr_addr(bank_count_i_wr_addr),
        .i_wr_data(bank_count_i_wr_data), .i_wr_mask(1'b1),
        .i_rd_en(2'b11), .i_rd_addr(bank_count_i_rd_addr), .o_rd_data(bank_count_o_rd_data)
    );
  end else begin : g_count_registers
    logic [COUNT_WIDTH-1:0] bank_count [0:BANKS-1];
    assign read_bank_count = bank_count[read_bank];
    assign co_bank_count = bank_count[co_current_bank];
    for (genvar bank=0; bank<BANKS; bank++) begin : g_bank
      always_ff @(posedge clk) begin
        if (!rst_n || bank_release[bank]) bank_count[bank] <= '0;
        else if (bank_write_complete[bank]) bank_count[bank] <= write_rows_next;
      end
    end
  end

  wire [COUNT_WIDTH-1:0] active_read_count = active_read_count_q;
  logic [COUNT_WIDTH-1:0] transpose_row_count_q;
  wire [COUNT_WIDTH-1:0] output_row_count =
      transpose_mode_tmp ? transpose_row_count_q : active_read_count;
  wire [COUNT_WIDTH-1:0] output_col_count =
      transpose_mode_tmp ? active_read_count
                         : (COUNT_WIDTH'(vec_valid_num_col_tmp) + COUNT_WIDTH'(1));
  logic read_bank_ready;
  if (p_count_storage) begin : g_memory_read_qualification
    // 有效位和行数分别完成归并，最终一级生成读取资格。
    (* keep = 1 *) logic read_count_nonzero;
    assign read_count_nonzero = bank_count_o_rd_data[0] != '0;
    assign read_bank_ready = selected_read_bank_ready && read_count_nonzero;
  end else begin : g_register_read_qualification
    assign read_bank_ready = selected_read_bank_ready && (read_bank_count != '0);
  end
  function automatic [COUNT_WIDTH-1:0] last_beat_index(
      input logic transpose,
      input logic [COUNT_WIDTH-1:0] read_count,
      input logic [$clog2(VLEN)-1:0] column_limit
  );
    logic [COUNT_WIDTH-1:0] column_count;
    begin
      column_count = transpose ? read_count :
          (COUNT_WIDTH'(column_limit) + COUNT_WIDTH'(1));
      last_beat_index = (column_count == '0) ? '0 :
          ((column_count - COUNT_WIDTH'(1)) >> BYTE_SHIFT);
    end
  endfunction

  // 保存行列配置时同时计算末拍位置，输出释放判断直接使用已保存的结果。
  wire [COUNT_WIDTH-1:0] last_beat_idx_cur = last_beat_idx_q;
  wire output_fire = output_ready && output_valid;
  wire last_beat_in_row = output_fire &&
                          (COUNT_WIDTH'(beat_idx) == last_beat_idx_cur);
  logic [COUNT_WIDTH-1:0] read_row_limit_q;
  logic [PTR_WIDTH-1:0] read_ptr_increment;
  assign read_ptr_increment = read_ptr + PTR_WIDTH'(1);
  // 行范围比较独立完成，输出握手只参与最终释放条件。
  (* keep = 1 *) logic read_row_count_last;
  (* keep = 1 *) logic read_normal_row_last, read_transpose_row_last;
  if (COUNT_WIDTH > 3) begin : g_split_row_compare
    (* keep = 1 *) logic normal_low_last, transpose_low_last;
    logic normal_combined_last, transpose_combined_last;
    // 低三位先比较，较高位的大小关系与低位结果在后一级合并。
    assign normal_low_last = read_row_limit_q[2:0] >= active_read_count[2:0];
    assign transpose_low_last = read_row_limit_q[2:0] >= transpose_row_count_q[2:0];
    assign normal_combined_last =
        (read_row_limit_q[COUNT_WIDTH-1:3] > active_read_count[COUNT_WIDTH-1:3]) ||
        ((read_row_limit_q[COUNT_WIDTH-1:3] == active_read_count[COUNT_WIDTH-1:3]) &&
         normal_low_last);
    assign transpose_combined_last =
        (read_row_limit_q[COUNT_WIDTH-1:3] > transpose_row_count_q[COUNT_WIDTH-1:3]) ||
        ((read_row_limit_q[COUNT_WIDTH-1:3] == transpose_row_count_q[COUNT_WIDTH-1:3]) &&
         transpose_low_last);
    // 含未知位时保留整体比较语义，已知输入选择分段比较结果。
    always_comb begin
      read_normal_row_last = read_row_limit_q >= active_read_count;
      case (^{read_row_limit_q, active_read_count})
        1'b0, 1'b1: begin
          read_normal_row_last = normal_combined_last;
        end
      endcase
      read_transpose_row_last = read_row_limit_q >= transpose_row_count_q;
      case (^{read_row_limit_q, transpose_row_count_q})
        1'b0, 1'b1: begin
          read_transpose_row_last = transpose_combined_last;
        end
      endcase
    end
  end else begin : g_short_row_compare
    assign read_normal_row_last = read_row_limit_q >= active_read_count;
    assign read_transpose_row_last = read_row_limit_q >= transpose_row_count_q;
  end
  always_comb begin
    read_row_count_last = read_row_limit_q >= output_row_count;
    case (transpose_mode_tmp)
      1'b0: begin
        read_row_count_last = read_normal_row_last;
      end
      1'b1: begin
        read_row_count_last = read_transpose_row_last;
      end
    endcase
  end
  wire last_row_in_bank = last_beat_in_row && read_row_count_last;
  wire start_stream = start_permitted && !stream_active && read_bank_ready;
  wire stream_has_next = output_fire && !last_row_in_bank;
  assign output_valid = coalesce_enable ? (co_active && co_data_valid) : (stream_active && data_valid);
  assign output_row_switch = coalesce_enable ? (co_fire && co_row_last) : last_beat_in_row;
  logic [31:0] watermark_i_reserve;
  logic [BANK_COUNT_WIDTH-1:0] watermark_i_ready_banks;
  logic watermark_i_partial_write, watermark_o_full;
  assign watermark_i_reserve = reserve_banks;
  assign watermark_i_ready_banks = ready_bank_count_q;
  assign watermark_i_partial_write = write_ptr != '0;
  assign fifo_watermark_full = watermark_o_full;
  fifo_bank_watermark #(.p_banks(BANKS), .p_count_width(BANK_COUNT_WIDTH),
      .p_precomputed_threshold(p_precomputed_watermark)) u_watermark (
      .i_reserve(watermark_i_reserve), .i_ready_banks(watermark_i_ready_banks),
      .i_partial_write(watermark_i_partial_write),
      .i_ready_threshold(BANK_COUNT_WIDTH'(i_ready_bank_threshold)), .o_full(watermark_o_full)
  );

  assign fifo_full_flag = write_bank_blocked || fifo_watermark_full ||
      (!coalesce_enable && next_write_bank_blocked);
  // 普通输出首拍等待时，同步重读新方向所需的数据，保持原有配置采样边沿。
  assign refresh_first_mode = p_use_cyclic_storage && !coalesce_enable && stream_active &&
      read_ptr == '0 && beat_idx == '0 && !output_ready && transpose_mode_eff != transpose_mode_tmp;
  assign ram_read_en = coalesce_enable ? (co_start || co_load_waiting ||
       (co_fire && !co_group_last && co_continue_bank_ready))
                                      : (start_stream || stream_has_next || refresh_first_mode);

  always_comb begin
    issue_read_ptr = read_ptr;
    issue_beat_idx = beat_idx;
    issue_transpose_mode = transpose_mode_tmp;

    if (refresh_first_mode) issue_transpose_mode = transpose_mode_eff;
    if (start_stream) begin
      issue_read_ptr = '0;
      issue_beat_idx = '0;
      issue_transpose_mode = transpose_mode_eff;
    end else if (output_fire) begin
      if (last_beat_in_row) begin
        issue_read_ptr = read_ptr + 1'b1;
        issue_beat_idx = '0;
      end else begin
        issue_read_ptr = read_ptr;
        issue_beat_idx = beat_idx + 1'b1;
      end
    end
  end

  assign read_issue_bank = coalesce_enable ? co_issue_bank : read_bank;
  assign read_issue_row = coalesce_enable ? PTR_WIDTH'(co_next_row[3:0]) : issue_read_ptr;
  assign read_issue_beat = coalesce_enable ? co_next_beat : issue_beat_idx;
  assign read_issue_transpose = coalesce_enable ? transpose_mode_eff : issue_transpose_mode;

  generate
    if (p_use_cyclic_storage) begin : g_cyclic_storage
      // 字节所在分组为 (行号+列号)%每拍字节数；所有分组同拍写入一整行。
      // 普通读取使用相同行号，转置读取按分组分别选择行号，随后旋转字节顺序。
      assign ram_wr_addr = MEM_ADDR_W'(int'(write_bank) * VLEN + int'(write_ptr));
      assign ram_write_en = in_valid && !write_bank_blocked;

      // 每组字节先按写入行号循环移动，所有存储体共用各级选择信号。
      logic [BUS_WIDTH-1:0] write_rotation [ROW_BEATS][BYTE_SHIFT+1];
      for (genvar column_group = 0; column_group < ROW_BEATS; column_group++) begin : g_write_group
        assign write_rotation[column_group][0] = in_vec_s8[column_group*BUS_WIDTH+:BUS_WIDTH];
        for (genvar stage = 0; stage < BYTE_SHIFT; stage++) begin : g_rotation
          localparam int p_shift_bits = 8 * (1 << stage);
          assign write_rotation[column_group][stage+1] = write_ptr[stage] ?
              {write_rotation[column_group][stage][BUS_WIDTH-p_shift_bits-1:0],
               write_rotation[column_group][stage][BUS_WIDTH-1:BUS_WIDTH-p_shift_bits]} :
              write_rotation[column_group][stage];
        end
      end

      for (genvar ram_bank = 0; ram_bank < ROW_BANKS; ram_bank++) begin : gen_fifo_ram
        logic [BYTE_SHIFT-1:0] read_row_lane;
        logic [PTR_WIDTH-1:0] read_row;
        logic fifo_ram_i_wr_en, fifo_ram_i_rd_en;
        logic [MEM_ADDR_W-1:0] fifo_ram_i_wr_addr, fifo_ram_i_rd_addr;
        logic [p_mem_data_width-1:0] fifo_ram_i_wr_data, fifo_ram_o_rd_data;

        for (genvar column_group = 0; column_group < ROW_BEATS; column_group++) begin : g_column
          assign ram_wr_data[ram_bank][8*column_group +: 8] =
              write_rotation[column_group][BYTE_SHIFT][8*ram_bank+:8];
        end
        assign read_row_lane = BYTE_SHIFT'(ram_bank) - BYTE_SHIFT'(read_issue_row);
        assign read_row = read_issue_transpose ?
            PTR_WIDTH'(int'(read_issue_beat) * BYTE_PER_BEAT + int'(read_row_lane)) : read_issue_row;
        assign ram_rd_addr[ram_bank] = MEM_ADDR_W'(int'(read_issue_bank) * VLEN + int'(read_row));

        assign fifo_ram_i_wr_en = ram_write_en;
        assign fifo_ram_i_wr_addr = ram_wr_addr;
        assign fifo_ram_i_wr_data = ram_wr_data[ram_bank];
        assign fifo_ram_i_rd_en = ram_read_en;
        assign fifo_ram_i_rd_addr = ram_rd_addr[ram_bank];
        assign ram_rd_data[ram_bank] = (VLEN*8)'(fifo_ram_o_rd_data);
        vec_s8_fifo_row_ram #(
            .DATA_WIDTH(p_mem_data_width), .DEPTH(MEM_DEPTH), .ADDR_WIDTH(MEM_ADDR_W)
        ) u_fifo_ram (
            .clk(clk), .wr_en(fifo_ram_i_wr_en), .wr_addr(fifo_ram_i_wr_addr),
            .wr_data(fifo_ram_i_wr_data), .rd_en(fifo_ram_i_rd_en),
            .rd_addr(fifo_ram_i_rd_addr), .rd_data(fifo_ram_o_rd_data)
        );
      end
    end else begin : g_row_storage
      always_comb begin
        int wr_group;
        int wr_addr_i;

        wr_group = int'(write_ptr) >> BYTE_SHIFT;
        wr_addr_i = (int'(write_bank) * ROW_BEATS) + wr_group;
        ram_wr_addr = MEM_ADDR_W'(wr_addr_i);

        for (int rb = 0; rb < ROW_BANKS; rb++) begin
          int rd_group;
          int rd_addr_i;

          rd_group = issue_transpose_mode ? int'(issue_beat_idx)
                                          : (int'(issue_read_ptr) >> BYTE_SHIFT);
          rd_addr_i = (int'(read_bank) * ROW_BEATS) + rd_group;
          ram_rd_addr[rb] = coalesce_enable ? co_ram_addr : MEM_ADDR_W'(rd_addr_i);
        end
      end

      for (genvar ram_bank = 0; ram_bank < ROW_BANKS; ram_bank++) begin : gen_fifo_ram
        logic fifo_ram_i_wr_en, fifo_ram_i_rd_en;
        logic [MEM_ADDR_W-1:0] fifo_ram_i_wr_addr, fifo_ram_i_rd_addr;
        logic [VLEN*8-1:0] fifo_ram_i_wr_data, fifo_ram_o_rd_data;
        assign fifo_ram_i_wr_en = in_valid && !write_bank_blocked &&
            (BYTE_SHIFT'(write_ptr) == BYTE_SHIFT'(ram_bank));
        assign fifo_ram_i_wr_addr = ram_wr_addr;
        assign fifo_ram_i_wr_data = in_vec_s8;
        assign fifo_ram_i_rd_en = ram_read_en;
        assign fifo_ram_i_rd_addr = ram_rd_addr[ram_bank];
        assign ram_rd_data[ram_bank] = fifo_ram_o_rd_data;

        vec_s8_fifo_row_ram #(
          .DATA_WIDTH(VLEN * 8),
          .DEPTH     (MEM_DEPTH),
          .ADDR_WIDTH(MEM_ADDR_W)
        ) u_fifo_ram (
          .clk    (clk),
          .wr_en  (fifo_ram_i_wr_en),
          .wr_addr(fifo_ram_i_wr_addr),
          .wr_data(fifo_ram_i_wr_data),
          .rd_en  (fifo_ram_i_rd_en),
          .rd_addr(fifo_ram_i_rd_addr),
          .rd_data(fifo_ram_o_rd_data)
        );
      end
    end
  endgenerate

  if (p_count_storage) begin : g_selected_write_state
    logic [BANK_WIDTH-1:0] selected_bank [2];
    logic [1:0] selected_blocked;
    always_comb begin
      selected_bank[0] = write_bank;
      if (finish_write_bank && !write_bank_blocked) begin
        selected_bank[0] = next_bank(write_bank);
      end
      selected_bank[1] = next_bank(selected_bank[0]);
    end
    // 先选定下周期的两个写入位置，再独立判断释放，合并块数无需经过银行状态归并。
    for (genvar position = 0; position < 2; position++) begin : g_position
      wire [BANKS-1:0] selected_mask = position == 0 ? write_bank_mask_next : next_bank_mask_next;
      wire selected_group_release = coalesce_enable && co_finish &&
          (((int'(selected_bank[position]) + BANKS - int'(read_bank)) % BANKS) < int'(co_tiles));
      wire selected_stream_release = !coalesce_enable && output_ready && stream_active && data_valid &&
          (COUNT_WIDTH'(beat_idx) == last_beat_idx_cur) && read_row_count_last &&
          read_bank == selected_bank[position];
      wire selected_write_complete = finish_write_bank && !write_bank_blocked &&
          write_bank == selected_bank[position];
      always_comb begin
        selected_blocked[position] = |(bank_ready & selected_mask);
        if (selected_group_release || selected_stream_release) begin
          selected_blocked[position] = 1'b0;
        end else if (selected_write_complete) begin
          selected_blocked[position] = 1'b1;
        end
      end
    end
    always_ff @(posedge clk) begin
      if (!rst_n) begin
        write_bank_blocked_q <= 1'b0;
        next_write_bank_blocked_q <= 1'b0;
      end else begin
        write_bank_blocked_q <= selected_blocked[0];
        next_write_bank_blocked_q <= selected_blocked[1];
      end
    end
  end else begin : g_parallel_write_state
    always_ff @(posedge clk) begin
      if (!rst_n) begin
        write_bank_blocked_q <= 1'b0;
        next_write_bank_blocked_q <= 1'b0;
      end else begin
        write_bank_blocked_q <= |(bank_ready_next & write_bank_mask_next);
        next_write_bank_blocked_q <= |(bank_ready_next & next_bank_mask_next);
      end
    end
  end

  // 各银行独立计算写入与释放条件，释放在同周期写入完成时保持较高优先级。
  for (genvar bank = 0; bank < BANKS; bank++) begin : g_bank_state
    logic write_complete, group_release, stream_release;
    assign write_complete = finish_write_bank && !write_bank_blocked &&
        write_bank == BANK_WIDTH'(bank);
    assign group_release = coalesce_enable && co_finish &&
        (((bank + BANKS - int'(read_bank)) % BANKS) < int'(co_tiles));
    assign stream_release = !coalesce_enable && output_ready && stream_active && data_valid &&
        (COUNT_WIDTH'(beat_idx) == last_beat_idx_cur) && read_row_count_last &&
        read_bank == BANK_WIDTH'(bank);
    assign bank_write_complete[bank] = write_complete;
    assign bank_release[bank] = group_release || stream_release;
    always_comb begin
      bank_ready_next[bank] = bank_ready[bank];
      if (group_release || stream_release) begin
        bank_ready_next[bank] = 1'b0;
      end else if (write_complete) begin
        bank_ready_next[bank] = 1'b1;
      end
    end
    always_ff @(posedge clk) begin
      if (!rst_n) begin
        bank_ready[bank] <= 1'b0;
      end else begin
        bank_ready[bank] <= bank_ready_next[bank];
      end
    end
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      write_bank   <= '0;
      read_bank    <= '0;
      write_ptr    <= '0;
      read_ptr     <= '0;
      read_row_limit_q <= COUNT_WIDTH'(1);
      co_active <= 0; co_data_valid <= 0; co_current_bank <= 0; co_row <= 0; co_col <= 0; co_beat <= 0;
      stream_active <= 1'b0;
      data_valid   <= 1'b0;
      beat_idx     <= '0;
      vec_valid_num_col_tmp <= '0;
      vec_valid_num_row_tmp <= '0;
      transpose_row_count_q <= COUNT_WIDTH'(1);
      transpose_mode_tmp <= 1'b0;
      oa_fifo_req  <= 1'b0;
      ready_bank_count_q <= '0;
      active_read_count_q <= '0;
      last_beat_idx_q <= '0;
    end else begin
      oa_fifo_req <= coalesce_enable ? (ready_bank_count_q != 0 && co_tiles != 0 && !co_active)
                                     : (read_bank_ready && !stream_active);

      if (finish_write_bank && !write_bank_blocked) begin
        write_ptr <= '0;
        write_bank <= next_bank(write_bank);
        if (!coalesce_enable && !(output_fire && last_row_in_bank)) begin
          ready_bank_count_q <= ready_bank_count_q + BANK_COUNT_WIDTH'(1);
        end
      end else if (in_valid && !write_bank_blocked) begin
        write_ptr <= write_ptr + 1'b1;
      end

      if (coalesce_enable) begin
        if (co_start || co_fire) begin
          co_row <= co_next_row; co_col <= co_next_col; co_beat <= co_next_beat;
          co_current_bank <= co_issue_bank;
        end
        if (co_start) begin
          co_active <= 1;
          co_data_valid <= 1;
        end else if (co_fire) begin
          co_data_valid <= !co_group_last && co_continue_bank_ready;
        end else if (co_load_waiting) co_data_valid <= 1;
        if (co_finish) begin
          co_active <= 0; co_data_valid <= 0;
          read_bank <= co_bank_after;
        end
        case ({finish_write_bank && !write_bank_blocked, co_finish})
          2'b10: ready_bank_count_q <= ready_bank_count_q + 1'b1;
          2'b01: ready_bank_count_q <= ready_bank_count_q - co_tiles;
          2'b11: ready_bank_count_q <= ready_bank_count_q - co_tiles + 1'b1;
          default: ;
        endcase
      end else if (start_stream) begin
        stream_active <= 1'b1;
        data_valid    <= 1'b1;
        beat_idx      <= '0;
        read_ptr      <= '0;
        read_row_limit_q <= COUNT_WIDTH'(1);
        active_read_count_q <= read_bank_count;
        last_beat_idx_q <= last_beat_index(transpose_mode_eff, read_bank_count, vec_valid_num_col);
        vec_valid_num_col_tmp <= vec_valid_num_col;
        vec_valid_num_row_tmp <= vec_valid_num_row;
        transpose_row_count_q <= COUNT_WIDTH'(vec_valid_num_row) + COUNT_WIDTH'(1);
        transpose_mode_tmp <= transpose_mode_eff;

      end else if (stream_active && (read_ptr == '0) && (beat_idx == '0) && !output_ready) begin
        last_beat_idx_q <= last_beat_index(transpose_mode_eff, active_read_count_q, vec_valid_num_col);
        vec_valid_num_col_tmp <= vec_valid_num_col;
        vec_valid_num_row_tmp <= vec_valid_num_row;
        transpose_row_count_q <= COUNT_WIDTH'(vec_valid_num_row) + COUNT_WIDTH'(1);
        transpose_mode_tmp <= transpose_mode_eff;
      end else if (output_fire) begin
        if (last_row_in_bank) begin
          stream_active <= 1'b0;
          data_valid    <= 1'b0;
          read_ptr      <= '0;
          read_row_limit_q <= COUNT_WIDTH'(1);
          beat_idx      <= '0;
          active_read_count_q <= '0;
          last_beat_idx_q <= last_beat_index(transpose_mode_tmp, '0, vec_valid_num_col_tmp);
          read_bank <= next_bank(read_bank);
          if (!(finish_write_bank && !write_bank_blocked)) begin
            ready_bank_count_q <= ready_bank_count_q - BANK_COUNT_WIDTH'(1);
          end
        end else if (last_beat_in_row) begin
          beat_idx <= '0;
          read_ptr <= read_ptr_increment;
          read_row_limit_q <= COUNT_WIDTH'(read_ptr_increment) + COUNT_WIDTH'(1);
        end else begin
          beat_idx <= beat_idx + 1'b1;
        end
      end
    end
  end

  integer valid_cols_i;
  integer beat_col_start_i;
  integer valid_in_beat_i;
  integer out_byte_i;
  integer src_row_i;
  integer read_bank_i;
  logic select_coalesce;
  logic select_transpose;
  logic [31:0] select_row;
  logic [BEAT_WIDTH-1:0] select_beat;
  logic [BYTE_SHIFT-1:0] select_bank;

  // 两种读出方式先选择行列坐标，再共用宽数据选择网络。
  assign select_coalesce = coalesce_enable && co_active;
  assign select_transpose = select_coalesce ? transpose_mode_eff : transpose_mode_tmp;
  assign select_row = select_coalesce ? 32'(co_row[3:0]) : 32'(read_ptr);
  assign select_beat = select_coalesce ? co_beat : beat_idx;
  assign select_bank = select_coalesce ? BYTE_SHIFT'(co_row) : BYTE_SHIFT'(read_ptr);

  logic [BUS_WIDTH-1:0] read_rotation [BYTE_SHIFT+1];
  if (p_use_cyclic_storage) begin : g_read_rotation
    logic [BEAT_WIDTH-1:0] select_column_group;
    assign select_column_group = select_transpose ? BEAT_WIDTH'(select_row >> BYTE_SHIFT) : select_beat;
    for (genvar bank = 0; bank < ROW_BANKS; bank++) begin : g_bank
      assign read_rotation[0][8*bank+:8] = ram_rd_data[bank][8*int'(select_column_group)+:8];
    end
    // 每个存储体先选择同一列组，再按行号恢复输出字节顺序。
    for (genvar stage = 0; stage < BYTE_SHIFT; stage++) begin : g_rotation
      localparam int p_shift_bits = 8 * (1 << stage);
      assign read_rotation[stage+1] = select_bank[stage] ?
          {read_rotation[stage][p_shift_bits-1:0], read_rotation[stage][BUS_WIDTH-1:p_shift_bits]} :
          read_rotation[stage];
    end
  end

  always_comb begin
    src_row_i = 0;
    read_bank_i = 0;
    output_data = '0;
    output_mask = '0;
    valid_cols_i = int'(output_col_count);
    beat_col_start_i = int'(beat_idx) * BYTE_PER_BEAT;
    valid_in_beat_i = valid_cols_i - beat_col_start_i;

    if (select_coalesce || stream_active) begin
      if (p_use_cyclic_storage) begin
        for (out_byte_i = 0; out_byte_i < BYTE_PER_BEAT; out_byte_i = out_byte_i + 1) begin
          src_row_i = int'(select_beat) * BYTE_PER_BEAT + out_byte_i;
          if (!select_transpose || select_coalesce || src_row_i < active_read_count) begin
            output_data[out_byte_i*8+:8] = read_rotation[BYTE_SHIFT][out_byte_i*8+:8];
          end
        end
      end else begin
        if (select_transpose) begin
          for (out_byte_i = 0; out_byte_i < BYTE_PER_BEAT; out_byte_i = out_byte_i + 1) begin
            src_row_i = int'(select_beat) * BYTE_PER_BEAT + out_byte_i;
            if (select_coalesce || src_row_i < active_read_count) begin
              output_data[out_byte_i*8+:8] =
                  ram_rd_data[out_byte_i][int'(select_row)*8+:8];
            end
          end
        end else begin
          read_bank_i = int'(select_bank);
          output_data = ram_rd_data[read_bank_i][int'(select_beat)*BUS_WIDTH+:BUS_WIDTH];
        end
      end
      if (select_coalesce) begin
        output_mask = '1;
      end else begin
        // 每个字节直接与本拍剩余的有效列数比较。
        for (int byte_lane = 0; byte_lane < BYTE_PER_BEAT; ++byte_lane) begin
          output_mask[byte_lane] = byte_lane < valid_in_beat_i;
        end
      end
    end
  end

endmodule

module vec_s8_to_fifo_linear #(
    parameter integer VLEN  = 16,
    parameter integer BANKS = 16,
    parameter integer BUS_WIDTH = 32,
    parameter bit p_precomputed_watermark = 1'b0
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 in_valid,
    input  wire                 in_tile_done,
    input  wire [   VLEN*8-1:0] in_vec_s8,
    output logic                oa_fifo_req,
    input  wire [          31:0] reserve_banks,
    input  wire [31:0] i_ready_bank_threshold,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_col,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_row,
    output wire                 output_valid,
    input  wire                 output_ready,
    output wire                 output_row_switch,
    output logic [BUS_WIDTH/8-1:0] output_mask,
    output logic [BUS_WIDTH-1:0] output_data,
    output wire                 fifo_full_flag
);

  localparam integer PTR_WIDTH   = (VLEN <= 1) ? 1 : $clog2(VLEN);
  localparam integer COUNT_WIDTH = $clog2(VLEN + 1);
  localparam integer BYTE_PER_BEAT = BUS_WIDTH / 8;
  localparam integer BYTE_SHIFT = $clog2(BYTE_PER_BEAT);
  localparam integer ROW_BEATS = (VLEN + BYTE_PER_BEAT - 1) / BYTE_PER_BEAT;
  localparam integer BEAT_WIDTH  = (ROW_BEATS <= 1) ? 1 : $clog2(ROW_BEATS);
  localparam integer BANK_WIDTH  = (BANKS <= 1) ? 1 : $clog2(BANKS);
  localparam integer BANK_COUNT_WIDTH = (BANKS <= 1) ? 1 : $clog2(BANKS + 1);
  localparam integer MEM_DEPTH   = BANKS * VLEN;
  localparam integer MEM_ADDR_W  = (MEM_DEPTH <= 1) ? 1 : $clog2(MEM_DEPTH);

  function automatic [BANK_WIDTH-1:0] next_bank(input [BANK_WIDTH-1:0] bank);
    begin
      if (bank == BANK_WIDTH'(BANKS - 1)) next_bank = '0;
      else                               next_bank = bank + 1'b1;
    end
  endfunction

  reg [COUNT_WIDTH-1:0] bank_count [0:BANKS-1];
  reg [BANKS-1:0] bank_ready;
  reg [BANK_COUNT_WIDTH-1:0] ready_bank_count_q;
  reg [COUNT_WIDTH-1:0] active_read_count_q;

  reg [BANK_WIDTH-1:0] write_bank;
  reg [BANK_WIDTH-1:0] read_bank;
  reg [PTR_WIDTH-1:0]  write_ptr;
  reg [PTR_WIDTH-1:0]  read_ptr;
  reg [BEAT_WIDTH-1:0] beat_idx;
  reg [$clog2(VLEN)-1:0] vec_valid_num_col_tmp;
  reg                   stream_active;
  reg                   data_valid;
  reg                   ram_read_valid_q;

  logic [VLEN*8-1:0] ram_rd_data;
  logic [MEM_ADDR_W-1:0] ram_wr_addr;
  logic [MEM_ADDR_W-1:0] ram_rd_addr;
  logic [PTR_WIDTH-1:0]  next_read_row;
  logic fifo_watermark_full;

  wire write_bank_blocked = bank_ready[write_bank];
  wire next_write_bank_blocked = bank_ready[next_bank(write_bank)];
`ifdef NPU_SIM_ASSERT
  if (BANKS > 32) begin : g_check_write_capacity
    initial forever @(posedge clk) begin
      if (rst_n && in_valid)
        assert (!write_bank_blocked) else $fatal(1, "S8 output FIFO has no available write bank");
    end
  end
`endif
  wire finish_write_bank = in_valid && in_tile_done;
  wire [COUNT_WIDTH-1:0] write_rows_next =
      in_valid ? (COUNT_WIDTH'(write_ptr) + COUNT_WIDTH'(1)) : COUNT_WIDTH'(write_ptr);
  wire read_bank_ready = bank_ready[read_bank] && (bank_count[read_bank] != '0);
  wire start_stream = !stream_active && read_bank_ready;
  wire [COUNT_WIDTH-1:0] output_row_count = active_read_count_q;
  wire [COUNT_WIDTH-1:0] output_col_count =
      COUNT_WIDTH'(vec_valid_num_col_tmp) + COUNT_WIDTH'(1);
  wire [COUNT_WIDTH-1:0] last_beat_idx_cur =
      (output_col_count == '0) ? '0 : ((output_col_count - COUNT_WIDTH'(1)) >> BYTE_SHIFT);
  wire output_fire = output_ready && output_valid;
  wire last_beat_in_row = output_fire &&
                          (COUNT_WIDTH'(beat_idx) == last_beat_idx_cur);
  wire last_row_in_bank = last_beat_in_row &&
                          ((COUNT_WIDTH'(read_ptr) + COUNT_WIDTH'(1)) >= output_row_count);
  wire read_next_row = last_beat_in_row && !last_row_in_bank;
  wire ram_read_en = start_stream || read_next_row;

  assign output_valid = stream_active && data_valid;
  assign output_row_switch = last_beat_in_row;

  logic [31:0] watermark_i_reserve;
  logic [BANK_COUNT_WIDTH-1:0] watermark_i_ready_banks;
  logic watermark_i_partial_write, watermark_o_full;
  assign watermark_i_reserve = reserve_banks;
  assign watermark_i_ready_banks = ready_bank_count_q;
  assign watermark_i_partial_write = write_ptr != '0;
  assign fifo_watermark_full = watermark_o_full;
  fifo_bank_watermark #(.p_banks(BANKS), .p_count_width(BANK_COUNT_WIDTH),
      .p_precomputed_threshold(p_precomputed_watermark)) u_watermark (
      .i_reserve(watermark_i_reserve), .i_ready_banks(watermark_i_ready_banks),
      .i_partial_write(watermark_i_partial_write),
      .i_ready_threshold(BANK_COUNT_WIDTH'(i_ready_bank_threshold)), .o_full(watermark_o_full)
  );

  assign fifo_full_flag = write_bank_blocked || next_write_bank_blocked || fifo_watermark_full;

  always_comb begin
    next_read_row = start_stream ? '0 : (read_ptr + 1'b1);
    ram_wr_addr = MEM_ADDR_W'((int'(write_bank) * VLEN) + int'(write_ptr));
    ram_rd_addr = MEM_ADDR_W'((int'(read_bank) * VLEN) + int'(next_read_row));
  end

  vec_s8_fifo_row_ram #(
    .DATA_WIDTH(VLEN * 8),
    .DEPTH     (MEM_DEPTH),
    .ADDR_WIDTH(MEM_ADDR_W)
  ) u_linear_ram (
    .clk    (clk),
    .wr_en  (in_valid && !write_bank_blocked),
    .wr_addr(ram_wr_addr),
    .wr_data(in_vec_s8),
    .rd_en  (ram_read_en),
    .rd_addr(ram_rd_addr),
    .rd_data(ram_rd_data)
  );

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      write_bank <= '0;
      read_bank  <= '0;
      write_ptr  <= '0;
      read_ptr   <= '0;
      beat_idx   <= '0;
      vec_valid_num_col_tmp <= '0;
      stream_active <= 1'b0;
      data_valid <= 1'b0;
      ram_read_valid_q <= 1'b0;
      oa_fifo_req <= 1'b0;
      bank_ready <= '0;
      ready_bank_count_q <= '0;
      active_read_count_q <= '0;
      for (int bank_idx = 0; bank_idx < BANKS; bank_idx++) begin
        bank_count[bank_idx] <= '0;
      end
    end else begin
      oa_fifo_req <= read_bank_ready && !stream_active;
      ram_read_valid_q <= ram_read_en;

      // The writer publishes the next tile width after its DMA response.
      // Keep the first waiting beat's mask synchronized with that descriptor.
      if (stream_active && read_ptr == '0 && beat_idx == '0 && !output_ready)
        vec_valid_num_col_tmp <= vec_valid_num_col;

      if (finish_write_bank && !write_bank_blocked) begin
        bank_count[write_bank] <= write_rows_next;
        bank_ready[write_bank] <= 1'b1;
        write_ptr <= '0;
        write_bank <= next_bank(write_bank);
        if (!last_row_in_bank) begin
          ready_bank_count_q <= ready_bank_count_q + BANK_COUNT_WIDTH'(1);
        end
      end else if (in_valid && !write_bank_blocked) begin
        write_ptr <= write_ptr + 1'b1;
      end

      if (start_stream) begin
        stream_active <= 1'b1;
        data_valid <= 1'b0;
        read_ptr <= '0;
        beat_idx <= '0;
        active_read_count_q <= bank_count[read_bank];
        vec_valid_num_col_tmp <= vec_valid_num_col;
      end else if (stream_active && !data_valid && ram_read_valid_q) begin
        data_valid <= 1'b1;
      end else if (output_fire) begin
        if (last_row_in_bank) begin
          stream_active <= 1'b0;
          data_valid <= 1'b0;
          read_ptr <= '0;
          beat_idx <= '0;
          active_read_count_q <= '0;
          bank_ready[read_bank] <= 1'b0;
          bank_count[read_bank] <= '0;
          read_bank <= next_bank(read_bank);
          if (!(finish_write_bank && !write_bank_blocked)) begin
            ready_bank_count_q <= ready_bank_count_q - BANK_COUNT_WIDTH'(1);
          end
        end else if (last_beat_in_row) begin
          beat_idx <= '0;
          read_ptr <= read_ptr + 1'b1;
        end else begin
          beat_idx <= beat_idx + 1'b1;
        end
      end
    end
  end

  integer valid_cols_i;
  integer beat_col_start_i;
  integer valid_in_beat_i;

  always_comb begin
    output_data = '0;
    output_mask = '0;
    valid_cols_i = int'(output_col_count);
    beat_col_start_i = int'(beat_idx) * BYTE_PER_BEAT;
    valid_in_beat_i = valid_cols_i - beat_col_start_i;
    if (valid_in_beat_i > BYTE_PER_BEAT) valid_in_beat_i = BYTE_PER_BEAT;
    if (valid_in_beat_i < 0) valid_in_beat_i = 0;

    if (stream_active && data_valid) begin
      output_data = ram_rd_data[int'(beat_idx)*BUS_WIDTH+:BUS_WIDTH];
      for (int byte_lane = 0; byte_lane < BYTE_PER_BEAT; ++byte_lane)
        output_mask[byte_lane] = byte_lane < valid_in_beat_i;
    end
  end

  wire unused_vec_valid_num_row = |vec_valid_num_row;

endmodule

module vec_s8_to_fifo #(
    parameter integer VLEN  = 16,
    parameter integer BANKS = 16,
    parameter integer BUS_WIDTH = 32,
    parameter integer ENABLE_TRANSPOSE = 1,
    // 启用时，合并输出从开始到完成期间须保持 transpose_mode。
    parameter bit p_cyclic_storage = 1'b0,
    parameter bit p_precomputed_watermark = 1'b0
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 in_valid,
    input  wire                 in_tile_done,
    input  wire [   VLEN*8-1:0] in_vec_s8,
    output wire                 oa_fifo_req,
    input  wire                 transpose_mode,
    input  wire                 coalesce_enable,
    input  wire                 coalesce_group_start,
    input  wire [31:0]          coalesce_rows,
    input  wire [31:0]          coalesce_cols,
    input  wire [          31:0] reserve_banks,
    input  wire [31:0] i_ready_bank_threshold,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_col,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_row,
    output wire                 output_valid,
    input  wire                 output_ready,
    output wire                 output_row_switch,
    output wire [BUS_WIDTH/8-1:0] output_mask,
    output wire [BUS_WIDTH-1:0] output_data,
    output wire                 fifo_full_flag
);

  generate
    if (ENABLE_TRANSPOSE == 0) begin : g_linear
      wire unused_transpose_mode = transpose_mode;
      vec_s8_to_fifo_linear #(
        .VLEN (VLEN),
        .BANKS(BANKS),
        .BUS_WIDTH(BUS_WIDTH),
        .p_precomputed_watermark(p_precomputed_watermark)
      ) u_linear (
        .clk              (clk),
        .rst_n            (rst_n),
        .in_valid         (in_valid),
        .in_tile_done     (in_tile_done),
        .in_vec_s8        (in_vec_s8),
        .oa_fifo_req      (oa_fifo_req),
        .reserve_banks    (reserve_banks),
        .i_ready_bank_threshold(i_ready_bank_threshold),
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid     (output_valid),
        .output_ready     (output_ready),
        .output_row_switch(output_row_switch),
        .output_mask      (output_mask),
        .output_data      (output_data),
        .fifo_full_flag   (fifo_full_flag)
      );

    end else begin : g_full
      // Two register entries isolate the RAM read controls from DMA READY.
      // Start a new tile only after the previous tile's entries drain, so
      // the writer has advanced the tail dimensions before they are sampled.
      localparam integer SKID_WIDTH = BUS_WIDTH + BUS_WIDTH/8 + 1;
      logic [SKID_WIDTH-1:0] skid[2];
      logic skid_rd, skid_wr;
      logic [1:0] skid_count;
      wire inner_req, inner_valid, inner_switch;
      wire [BUS_WIDTH/8-1:0] inner_mask;
      wire [BUS_WIDTH-1:0] inner_data;
      logic writer_ready_q;
      always_ff @(posedge clk) begin
        if(!rst_n) writer_ready_q<=0;
        else writer_ready_q<=output_ready;
      end
      wire inner_ready=writer_ready_q && skid_count<2;
      wire put=inner_valid && inner_ready;
      wire take=output_valid && output_ready;
      assign oa_fifo_req=inner_req || inner_valid || skid_count!=0;
      assign output_valid=skid_count!=0;
      assign output_data=skid[skid_rd][BUS_WIDTH-1:0];
      assign output_mask=skid[skid_rd][BUS_WIDTH+:BUS_WIDTH/8];
      assign output_row_switch=take && skid[skid_rd][SKID_WIDTH-1];
      always_ff @(posedge clk) begin
        if(!rst_n) begin skid_rd<=0;skid_wr<=0;skid_count<=0;end
        else begin
          case({put,take})
            2'b10: skid_count<=skid_count+1'b1;
            2'b01: skid_count<=skid_count-1'b1;
            default:;
          endcase
          if(put) begin skid[skid_wr]<={inner_switch,inner_mask,inner_data};skid_wr<=!skid_wr;end
          if(take) skid_rd<=!skid_rd;
        end
      end
      vec_s8_to_fifo_full #(
        .VLEN (VLEN),
        .BANKS(BANKS),
        .BUS_WIDTH(BUS_WIDTH),
        .ENABLE_TRANSPOSE(ENABLE_TRANSPOSE),
        .p_cyclic_storage(p_cyclic_storage),
        .p_precomputed_watermark(p_precomputed_watermark)
      ) u_full (
        .clk              (clk),
        .rst_n            (rst_n),
        .start_permitted   (skid_count==0),
        .in_valid         (in_valid),
        .in_tile_done     (in_tile_done),
        .in_vec_s8        (in_vec_s8),
        .oa_fifo_req      (inner_req),
        .transpose_mode   (transpose_mode),
        .coalesce_enable  (coalesce_enable),
        .coalesce_group_start(coalesce_group_start),
        .coalesce_rows    (coalesce_rows),
        .coalesce_cols    (coalesce_cols),
        .reserve_banks    (reserve_banks),
        .i_ready_bank_threshold(i_ready_bank_threshold),
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid     (inner_valid),
        .output_ready     (inner_ready),
        .output_row_switch(inner_switch),
        .output_mask      (inner_mask),
        .output_data      (inner_data),
        .fifo_full_flag   (fifo_full_flag)
      );

    end
  endgenerate

endmodule

module vec_s8_fifo_row_ram #(
    parameter int unsigned DATA_WIDTH = 128,
    parameter int unsigned DEPTH = 16,
    parameter int unsigned ADDR_WIDTH = 4,
    parameter [8*16-1:0] p_ram_style = "auto"
) (
    input  wire logic                  clk,
    input  wire logic                  wr_en,
    input  wire logic [ADDR_WIDTH-1:0] wr_addr,
    input  wire logic [DATA_WIDTH-1:0] wr_data,
    input  wire logic                  rd_en,
    input  wire logic [ADDR_WIDTH-1:0] rd_addr,
    output logic [DATA_WIDTH-1:0] rd_data
);

    logic storage_i_wr_en, storage_i_rd_en;
    logic [ADDR_WIDTH-1:0] storage_i_wr_addr, storage_i_rd_addr;
    logic [DATA_WIDTH-1:0] storage_i_wr_data, storage_o_rd_data;
    assign storage_i_wr_en = wr_en;
    assign storage_i_wr_addr = wr_addr;
    assign storage_i_wr_data = wr_data;
    assign storage_i_rd_en = rd_en;
    assign storage_i_rd_addr = rd_addr;
    assign rd_data = storage_o_rd_data;
`ifdef ASIC_SRAM
    logic [DATA_WIDTH-1:0] storage_i_wr_mask;
    assign storage_i_wr_mask = '1;
    smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)) u_storage (
        .clk(clk), .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
        .write_data(storage_i_wr_data), .write_mask(storage_i_wr_mask),
        .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr), .read_data(storage_o_rd_data)
    );
`else
    logic storage_i_wr_mask;
    assign storage_i_wr_mask = 1'b1;
    regfile #(
        .p_data_width(DATA_WIDTH), .p_depth(DEPTH), .p_addr_width(ADDR_WIDTH),
        .p_write_unit(DATA_WIDTH), .p_ram_style(p_ram_style)
    ) u_storage (
        .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
        .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
        .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
    );
`endif

endmodule

// 普通预留量与两个饱和值并行比较，写入位置仅参与最后一级进位。
module fifo_bank_watermark #(
    parameter int p_banks = 16,
    parameter int p_count_width = (p_banks <= 1) ? 1 : $clog2(p_banks + 1),
    parameter bit p_precomputed_threshold = 1'b0
) (
    input  wire logic [31:0] i_reserve,
    input  wire logic [p_count_width-1:0] i_ready_banks,
    input  wire logic i_partial_write,
    input  wire logic [p_count_width-1:0] i_ready_threshold,
    output logic o_full
);
    if (p_precomputed_threshold) begin : g_precomputed_threshold
        logic count_overflow, ready_above, ready_at;

        // 配置阶段已经保存可用银行阈值，运行期间只比较完整占用数量。
        assign count_overflow = i_partial_write && (&i_ready_banks);
        assign ready_above = i_ready_banks > i_ready_threshold;
        assign ready_at = i_ready_banks == i_ready_threshold;
        assign o_full = !count_overflow && (ready_above || (i_partial_write && ready_at));
    end else if (p_banks > 0 && p_count_width >= $clog2(p_banks+1)) begin : g_parallel_compare
        localparam int p_sum_width = p_count_width + 1;
        localparam logic [p_sum_width-1:0] p_negative_capacity = ~p_sum_width'(p_banks);
        logic [p_sum_width-1:0] ready_count, reserve_count;
        logic [p_sum_width-1:0] sum_bits, carry_bits, shifted_carry, unused_sum;
        logic unused_high_carry, normal_full, zero_full, saturated_full;
        logic count_overflow, reserve_zero, reserve_saturated;

        assign ready_count = {1'b0, i_ready_banks};
        assign reserve_count = p_sum_width'(p_count_width'(i_reserve));
        assign sum_bits = ready_count ^ reserve_count ^ p_negative_capacity;
        assign carry_bits = (ready_count & reserve_count) |
            ((ready_count | reserve_count) & p_negative_capacity);
        assign {unused_high_carry, shifted_carry} = {carry_bits, 1'b0};
        parallel_prefix_add #(
            .p_width(p_sum_width), .p_group_width(4), .p_preserve_groups(1'b1)
        ) u_capacity_compare (
            .i_a(sum_bits), .i_b(shifted_carry), .i_carry(i_partial_write),
            .o_sum(unused_sum), .o_carry(normal_full)
        );
        assign zero_full = (i_ready_banks > p_count_width'(p_banks-1)) ||
            (i_partial_write && i_ready_banks == p_count_width'(p_banks-1));
        assign saturated_full = (|i_ready_banks) || i_partial_write;
        assign reserve_zero = i_reserve == 32'd0;
        localparam int p_capacity_bits = $clog2(p_banks+1);
        localparam int p_capacity_low_bit = $clog2(p_banks & -p_banks);
        localparam int p_capacity_prefix = p_banks >> p_capacity_low_bit;
        if ((p_capacity_prefix & (p_capacity_prefix+1)) == 0 && p_capacity_bits <= 32) begin : g_prefix_capacity
            // 容量为连续高位一和低位零时，比较仅需高位非零与有效位归约。
            assign reserve_saturated = (|(i_reserve >> p_capacity_bits)) ||
                (&i_reserve[p_capacity_bits-1:p_capacity_low_bit]);
        end else begin : g_arbitrary_capacity
            assign reserve_saturated = i_reserve >= 32'(p_banks);
        end
        // 部分写入使计数回绕时，保持有限位宽占用计数的结果。
        assign count_overflow = i_partial_write && (&i_ready_banks);
        assign o_full = !count_overflow && ((reserve_zero && zero_full) ||
            (!reserve_zero && reserve_saturated && saturated_full) ||
            (!reserve_zero && !reserve_saturated && normal_full));
    end else begin : g_narrow_count
        logic [p_count_width-1:0] reserve_count, ready_threshold;
        logic ready_above, ready_at, count_overflow;

        assign reserve_count = (i_reserve == 32'd0) ? p_count_width'(1) :
            ((i_reserve >= 32'(p_banks)) ? p_count_width'(p_banks) : p_count_width'(i_reserve));
        assign ready_threshold = p_count_width'(p_banks) - reserve_count;
        assign ready_above = i_ready_banks > ready_threshold;
        assign ready_at = i_ready_banks == ready_threshold;
        assign count_overflow = i_partial_write && (&i_ready_banks);
        assign o_full = !count_overflow && (ready_above || (i_partial_write && ready_at));
    end
endmodule

`default_nettype wire
