`default_nettype none

/*
 * 保存两组偏置数据，维护驻留范围并提供向量和标量读取。
 * ============================================================
 */

module bias_loader_buffer #(
    parameter int unsigned SIZE       = 8,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned DMA_DATA_WIDTH = 8,
    parameter int unsigned BUS_WIDTH  = 32,
    parameter int unsigned REG_WIDTH  = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
    parameter int unsigned GROUP_BLOCKS_MAX = 1,
    parameter bit p_share_load_index = 1'b0,
    parameter bit p_register_current_range = 1'b0
) (
    input  wire logic clk, // 偏置存储与读取控制的工作时钟。
    input  wire logic rst_n, // 低有效异步复位。

    input  wire logic                 init_cfg, // 清除两组偏置的驻留状态并初始化读取上下文。
    input  wire logic                 load_start, // 开始向指定存储体装载一组偏置。
    input  wire logic                 load_bank, // 当前装载使用的存储体编号。
    input  wire logic [COUNT_WIDTH-1:0] load_block_idx, // 当前装载范围的起始偏置块索引。
    input  wire logic [COUNT_WIDTH-1:0] load_blocks_count, // 当前装载范围包含的偏置块数。
    input  wire logic [COUNT_WIDTH-1:0] group_blocks_needed, // 当前请求需要连续驻留的偏置块数。
    input  wire logic                 load_word_valid [BUS_WIDTH/8], // DMA 返回各字节通道的写入有效标志。
    input  wire logic [REG_WIDTH-1:0] load_word_row, // DMA 返回数据所属的偏置块行号。
    input  wire logic [$clog2(SIZE * (DATA_WIDTH / 8))-1:0] load_word_col_base, // DMA 返回数据在当前偏置行内的起始字节位置。
    input  wire logic signed [DMA_DATA_WIDTH-1:0] load_word_data [BUS_WIDTH/8], // DMA 返回各通道的偏置字节数据。
    input  wire logic                 load_done, // 当前偏置装载传输完成。

    input  wire logic                 active_bank, // 当前执行使用的偏置存储体编号。
    input  wire logic [COUNT_WIDTH-1:0] current_block_idx, // 当前执行分组的起始偏置块索引。
    input  wire logic [COUNT_WIDTH-1:0] i_current_block_idx_nxt = '0, // 下一周期当前分组的起始偏置块索引。
    input  wire logic [COUNT_WIDTH-1:0] i_group_blocks_needed_nxt = '0, // 下一周期当前分组需要驻留的偏置块数。

    input  wire logic                 is_mode, // 选择输入驻留模式的逐行标量偏置读取。
    input  wire logic                 group_read_start, // 保存当前分组的标量读取基址和存储体。
    input  wire logic [$clog2(GROUP_BLOCKS_MAX * SIZE)-1:0] group_read_idx, // 当前分组内的标量偏置元素索引。
    output logic                 bias_valid, // 当前执行所需偏置已经驻留且读取结果可用。
    output logic                 load_block_valid, // 待装载的完整偏置范围已经驻留。
    output logic                 load_block_bank, // 已驻留装载范围所在的存储体编号。
    output logic signed [DATA_WIDTH-1:0] data_out [SIZE], // 权重驻留模式下当前块的偏置向量。
    output logic signed [DATA_WIDTH-1:0] group_data_scalar // 输入驻留模式下同步读出的标量偏置。
);

  localparam int BYTES_PER_WORD = DATA_WIDTH / 8;
  localparam int BYTE_SHIFT = $clog2(BYTES_PER_WORD);
  localparam int GROUP_ELEMS = GROUP_BLOCKS_MAX * SIZE;
  localparam int CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
  localparam int RAM_WIDTH = 64;
  localparam int RAM_BYTES = RAM_WIDTH / 8;
  localparam int WORDS_PER_READ = RAM_WIDTH / DATA_WIDTH;
  localparam int READS_PER_BLOCK = (SIZE + WORDS_PER_READ - 1) / WORDS_PER_READ;
  localparam int BANK_WORDS = GROUP_BLOCKS_MAX * READS_PER_BLOCK;
  localparam int BANK_ADDR_W = (BANK_WORDS > 1) ? $clog2(BANK_WORDS) : 1;
  localparam int RAM_ADDR_W = BANK_ADDR_W + 1;
  localparam int READ_INDEX_W = (READS_PER_BLOCK > 1) ? $clog2(READS_PER_BLOCK) : 1;
  localparam int READ_COUNT_W = $clog2(READS_PER_BLOCK + 1);
  localparam int WORD_INDEX_W = (WORDS_PER_READ > 1) ? $clog2(WORDS_PER_READ) : 1;
  localparam int GROUP_ADDR_W = $clog2(GROUP_ELEMS);
  localparam int BLOCK_ADDR_W = (GROUP_BLOCKS_MAX > 1) ? $clog2(GROUP_BLOCKS_MAX) : 1;

  logic                         bank_loaded [2];
  logic [CNT_W-1:0]             bank_block_idx [2];
  // 接收装载命令时保存扩展一位的末端位置，读取驻留判断直接使用该位置。
  logic [CNT_W:0] bank_end_q [2];
  logic [CNT_W:0] bank_end_i_a, bank_end_i_b, bank_end_o_sum;
  logic bank_end_i_carry, bank_end_o_carry;
  logic [GROUP_ADDR_W-1:0] collision_scalar_word;
  logic [RAM_ADDR_W-1:0] collision_scalar_first, collision_scalar_next;
  logic [RAM_ADDR_W-1:0] collision_ws_first, collision_ws_next;
  // 各读取分支先完成同址比较，晚到的组首资格只选择已经完成的结果。
  (* keep = 1'b1 *) logic [3:0] collision_equal;
  logic collision_scalar_next_equal;
  logic collision_selected;
  logic collision_other, collision_scalar_selected;
  logic storage_read_selected;
  logic storage_write_accepted;
  // 完整存储体末端包含扩展位，分组进位计算缩短命令接收边沿的数据路径。
  assign bank_end_i_a = {1'b0, load_block_idx};
  assign bank_end_i_b = {1'b0, load_blocks_count};
  assign bank_end_i_carry = 1'b0;
  parallel_prefix_add #(.p_width(CNT_W + 1)) u_bank_end (
      .i_a(bank_end_i_a), .i_b(bank_end_i_b), .i_carry(bank_end_i_carry),
      .o_sum(bank_end_o_sum), .o_carry(bank_end_o_carry)
  );

  logic                         load_bank_q;
  logic                         load_word_valid_q [BUS_WIDTH/8];
  logic [BANK_ADDR_W-1:0]      load_row_index_q;
  logic                        load_row_high_zero_q;
  logic [$clog2(SIZE * (DATA_WIDTH / 8))-1:0] load_word_col_base_q;
  logic signed [DMA_DATA_WIDTH-1:0] load_word_data_q [BUS_WIDTH/8];
  logic                         load_done_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      load_bank_q          <= 1'b0;
      load_row_index_q     <= '0;
      load_row_high_zero_q <= 1'b1;
      load_word_col_base_q <= '0;
      load_done_q          <= 1'b0;
      for (int i = 0; i < BUS_WIDTH/8; i++) begin
        load_word_valid_q[i] <= 1'b0;
        load_word_data_q[i]  <= '0;
      end
    end else begin
      load_bank_q          <= load_bank;
      if (GROUP_BLOCKS_MAX == 1) begin
        load_row_index_q     <= '0;
        load_row_high_zero_q <= 1'b1;
      end else begin
        load_row_index_q     <= BANK_ADDR_W'(load_word_row);
        load_row_high_zero_q <= (load_word_row >> BANK_ADDR_W) == '0;
      end
      load_word_col_base_q <= load_word_col_base;
      load_done_q          <= load_done;
      for (int i = 0; i < BUS_WIDTH/8; i++) begin
        load_word_valid_q[i] <= load_word_valid[i] && !load_start && !init_cfg;
        load_word_data_q[i]  <= load_word_data[i];
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int b = 0; b < 2; b++) begin
        bank_loaded[b]    <= 1'b0;
        bank_block_idx[b] <= '0;
        bank_end_q[b] <= '0;
      end
    end else if (init_cfg) begin
      for (int b = 0; b < 2; b++) begin
        bank_loaded[b]    <= 1'b0;
        bank_block_idx[b] <= '0;
        bank_end_q[b] <= '0;
      end
    end else begin
      if (load_start) begin
        bank_loaded[load_bank]    <= 1'b0;
        bank_block_idx[load_bank] <= load_block_idx;
        bank_end_q[load_bank] <= bank_end_o_sum;
      end else if (load_done_q) begin
        bank_loaded[load_bank_q] <= 1'b1;
      end
    end
  end

  //! 1. Residency and Read Context
  //! -----------------------------

  localparam int RANGE_WIDTH = CNT_W + 1;
  logic [1:0][1:0] window_end_valid;
  logic [CNT_W-1:0] load_request_idx;
  logic [1:0] load_window_hit;
  logic [1:0] current_window_hit;
  logic resident_current;
  logic [1:0] resident_by_bank;
  logic [BLOCK_ADDR_W-1:0] current_block_offset;
  logic [GROUP_ADDR_W-1:0] current_word_base;
  logic [GROUP_ADDR_W-1:0] scalar_word_base;
  logic scalar_bank;
  logic [GROUP_ADDR_W-1:0] scalar_request_word;
  logic scalar_request_bank;
  logic [WORD_INDEX_W-1:0] scalar_half_q;
  logic [RAM_ADDR_W-1:0] read_address;
  logic read_enable;
  logic [RAM_WIDTH-1:0] read_data;
  logic [RAM_ADDR_W-1:0] write_address;
  logic [RAM_WIDTH-1:0] write_data;
  logic [RAM_BYTES-1:0] write_enable;
  logic write_row_valid;
  logic ws_cache_valid;
  logic ws_cache_bank;
  logic [BLOCK_ADDR_W-1:0] ws_cache_block;
  logic ws_cache_hit;
  logic ws_loading;
  logic ws_busy;
  logic [READ_COUNT_W-1:0] ws_issue_count;
  logic ws_read_start;
  logic ws_read_issue;
  logic ws_response_valid;
  logic [READ_INDEX_W-1:0] ws_response_index;
  logic [READ_INDEX_W-1:0] ws_issue_index;
  logic [BANK_ADDR_W-1:0] ws_read_base;
  logic [RAM_WIDTH-1:0] ws_cache_pair [READS_PER_BLOCK];
  logic [RAM_WIDTH-1:0] ws_cache_update_data;

  // 顶层控制器只在命令阶段使用装载命中，此时两个请求的块索引相同。
  // 通用缓冲区默认分别处理两个索引，集成控制器时可共享范围比较。
  assign load_request_idx = p_share_load_index ? current_block_idx : load_block_idx;

  // 请求起点、请求长度与存储体末端先合并为两组位向量，再统一判断完整扩展范围。
  for (genvar request_i = 0; request_i < 2; request_i++) begin : g_range_request
    logic [RANGE_WIDTH-1:0] request_base;
    logic [RANGE_WIDTH-1:0] request_count;
    assign request_base = {1'b0, request_i == 0 ? load_request_idx : current_block_idx};
    assign request_count = {1'b0, group_blocks_needed};
    for (genvar bank_i = 0; bank_i < 2; bank_i++) begin : g_range_bank
      logic [RANGE_WIDTH-1:0] sum_bits;
      logic [RANGE_WIDTH-1:0] carry_bits;
      logic [RANGE_WIDTH-1:0] shifted_carry;
      logic [RANGE_WIDTH-1:0] unused_range_sum;
      logic range_i_carry;
      logic range_overflow;
      logic unused_high_carry;
      assign sum_bits = request_base ^ request_count ^ ~bank_end_q[bank_i];
      assign carry_bits = (request_base & request_count) |
          ((request_base | request_count) & ~bank_end_q[bank_i]);
      assign {unused_high_carry, shifted_carry} = {carry_bits, 1'b0};
      assign range_i_carry = 1'b0;
      parallel_prefix_add #(.p_width(RANGE_WIDTH)) u_range_end (
          .i_a(sum_bits), .i_b(shifted_carry), .i_carry(range_i_carry),
          .o_sum(unused_range_sum), .o_carry(range_overflow)
      );
      assign window_end_valid[request_i][bank_i] = ~range_overflow;
    end
  end
  for (genvar b = 0; b < 2; b++) begin : gen_window_hit
    // 两个存储体同时比较完整请求范围，起点和末端条件独立计算。
    assign load_window_hit[b] = bank_loaded[b] &&
        (load_request_idx >= bank_block_idx[b]) && window_end_valid[0][b];
    assign current_window_hit[b] = bank_loaded[b] &&
        (current_block_idx >= bank_block_idx[b]) && window_end_valid[1][b];
  end
  if (p_register_current_range) begin : g_registered_current
    logic [1:0] resident_bank;
    for (genvar b = 0; b < 2; b++) begin : g_bank
      logic [COUNT_WIDTH-1:0] range_end_i_base, range_end_i_count;
      logic [RANGE_WIDTH-1:0] range_end_i_end;
      logic range_end_o_outside;
      logic range_overflow;
      logic bank_loaded_nxt;
      logic resident_qualify_i_clear, resident_qualify_i_loaded;
      logic resident_qualify_i_below_start, resident_qualify_i_above_end;
      logic resident_qualify_o_valid;
      logic range_start_o_less, range_start_o_equal;
      logic [CNT_W-1:0] range_start_i_a, range_start_i_b;

      // 下一分组的范围在本边沿前完成比较，存储体选择在边沿后使用当前控制状态。
      assign range_end_i_base = i_current_block_idx_nxt;
      assign range_end_i_count = i_group_blocks_needed_nxt;
      assign range_end_i_end = bank_end_q[b];
      assign range_overflow = range_end_o_outside;
      bias_request_end_compare #(.p_count_width(COUNT_WIDTH)) u_range_end (
          .i_base(range_end_i_base), .i_count(range_end_i_count), .i_end(range_end_i_end),
          .o_outside(range_end_o_outside)
      );
      // 新装载先撤销对应存储体的有效状态；完成通知仅在没有新装载时生效。
      assign bank_loaded_nxt = load_start ?
          (bank_loaded[b] && load_bank != 1'(b)) :
          (bank_loaded[b] || (load_done_q && load_bank_q == 1'(b)));
      assign range_start_i_a = i_current_block_idx_nxt;
      assign range_start_i_b = bank_block_idx[b];
      (* keep_hierarchy = "yes" *)
      parallel_unsigned_compare #(
          .p_width(CNT_W), .p_preserve_groups(1'b1)
      ) u_range_start (
          .i_a(range_start_i_a), .i_b(range_start_i_b),
          .o_less(range_start_o_less), .o_equal(range_start_o_equal)
      );
      // 初始化和完整范围结果在寄存器输入处共同形成驻留资格。
      assign resident_qualify_i_clear = init_cfg;
      assign resident_qualify_i_loaded = bank_loaded_nxt;
      assign resident_qualify_i_below_start = range_start_o_less;
      assign resident_qualify_i_above_end = range_overflow;
      bias_resident_qualify u_resident_qualify (
          .i_clear(resident_qualify_i_clear), .i_loaded(resident_qualify_i_loaded),
          .i_below_start(resident_qualify_i_below_start),
          .i_above_end(resident_qualify_i_above_end), .o_valid(resident_qualify_o_valid)
      );
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
          resident_bank[b] <= 1'b0;
        end else begin
          resident_bank[b] <= resident_qualify_o_valid;
        end
      end
    end
    assign resident_current = resident_bank[active_bank];
    assign resident_by_bank = resident_bank;
    // 共用请求索引时，装载命中和当前驻留复用同一组同步范围结果。
    assign load_block_valid = p_share_load_index ? |resident_bank : |load_window_hit;
    assign load_block_bank = p_share_load_index ? !resident_bank[0] : !load_window_hit[0];
  end else begin : g_combinational_current
    assign resident_current = current_window_hit[active_bank];
    assign resident_by_bank = current_window_hit;
    assign load_block_valid = |load_window_hit;
    assign load_block_bank = !load_window_hit[0];
  end
  assign current_block_offset = BLOCK_ADDR_W'(
      current_block_idx - bank_block_idx[active_bank]);
  assign current_word_base = GROUP_ADDR_W'(current_block_offset) * GROUP_ADDR_W'(SIZE);
  logic [1:0][BLOCK_ADDR_W-1:0] cache_bank_block;
  for (genvar bank = 0; bank < 2; bank++) begin : g_cache_bank_block
    assign cache_bank_block[bank] = BLOCK_ADDR_W'(bank_block_idx[bank]);
  end
  // 存储体范围和向量缓存命中并行准备，当前执行编号只选择完整读取资格。
  bias_bank_readiness #(.p_block_width(BLOCK_ADDR_W)) u_bank_readiness (
      .i_bank_block(cache_bank_block), .i_current_block(BLOCK_ADDR_W'(current_block_idx)),
      .i_cache_block(ws_cache_block), .i_resident(resident_by_bank),
      .i_cache_valid(ws_cache_valid), .i_cache_bank(ws_cache_bank),
      .i_active_bank(active_bank), .i_is_mode(is_mode),
      .o_cache_hit(ws_cache_hit), .o_bias_valid(bias_valid)
  );

  // 执行分组的读取上下文独立保存，后台预取不会改写当前标量读取位置。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      scalar_word_base <= '0;
      scalar_bank <= 1'b0;
    end else if (init_cfg) begin
      scalar_word_base <= '0;
      scalar_bank <= 1'b0;
    end else if (group_read_start) begin
      scalar_word_base <= current_word_base;
      scalar_bank <= active_bank;
    end
  end
  assign scalar_request_word = group_read_start ? current_word_base :
      scalar_word_base + group_read_idx;
  assign scalar_request_bank = group_read_start ? active_bank : scalar_bank;

  //! 2. Synchronous Storage
  //! ----------------------

  // 低位保存物理地址计算所需的模值，高位零标志保留完整行号的范围资格。
  assign write_row_valid = (GROUP_BLOCKS_MAX == 1) ||
      (load_row_high_zero_q && REG_WIDTH'(load_row_index_q) < REG_WIDTH'(GROUP_BLOCKS_MAX));
  assign write_address = {load_bank_q,
      BANK_ADDR_W'(REG_WIDTH'(load_row_index_q) *
                   REG_WIDTH'(READS_PER_BLOCK) +
                   REG_WIDTH'(load_word_col_base_q) / REG_WIDTH'(RAM_BYTES))};
  for (genvar byte_i = 0; byte_i < RAM_BYTES; byte_i++) begin : gen_write_byte
    assign write_data[byte_i*8 +: 8] = load_word_data_q[byte_i % (BUS_WIDTH/8)][7:0];
    if (BUS_WIDTH >= RAM_WIDTH) begin : gen_full_bus
      assign write_enable[byte_i] = !init_cfg && !load_start && write_row_valid &&
          load_word_valid_q[byte_i];
    end else begin : gen_narrow_bus
      assign write_enable[byte_i] = !init_cfg && !load_start && write_row_valid &&
          load_word_valid_q[byte_i % (BUS_WIDTH/8)] &&
          (load_word_col_base_q[$clog2(RAM_BYTES)-1:$clog2(BUS_WIDTH/8)] ==
           ($clog2(RAM_BYTES)-$clog2(BUS_WIDTH/8))'(byte_i / (BUS_WIDTH/8)));
    end
  end

  // 两个 bank 分别承担装载和执行，按字节写入并同步读取。
  // 同地址写入时保持存储输出，字节掩码由存储器统一处理。
  logic storage_i_wr_en, storage_i_rd_en;
  logic [RAM_ADDR_W-1:0] storage_i_wr_addr, storage_i_rd_addr;
  logic [RAM_WIDTH-1:0] storage_i_wr_data, storage_o_rd_data;
  logic [RAM_BYTES-1:0] storage_i_wr_mask;
  assign storage_i_wr_en = |write_enable;
  assign storage_i_wr_addr = write_address;
  assign storage_i_wr_data = write_data;
  assign storage_i_wr_mask = write_enable;
  assign collision_scalar_word = scalar_word_base + group_read_idx;
  assign collision_scalar_first = {active_bank,
      BANK_ADDR_W'(current_word_base / WORDS_PER_READ)};
  assign collision_scalar_next = {scalar_bank,
      BANK_ADDR_W'(collision_scalar_word / WORDS_PER_READ)};
  assign collision_ws_first = {active_bank,
      BANK_ADDR_W'(current_block_offset) * BANK_ADDR_W'(READS_PER_BLOCK)};
  assign collision_ws_next = {ws_cache_bank,
      BANK_ADDR_W'(ws_read_base + BANK_ADDR_W'(READ_INDEX_W'(ws_issue_count)))};
  assign collision_equal[0] = collision_scalar_first == write_address;
  // 后续标量地址直接检查模加结果，避免先生成完整进位和值再比较。
  bias_scalar_word_match #(
      .p_sum_width(GROUP_ADDR_W), .p_address_width(BANK_ADDR_W),
      .p_words_per_read(WORDS_PER_READ)
  ) u_scalar_word_match (
      .i_base(scalar_word_base), .i_index(group_read_idx),
      .i_word_address(write_address[BANK_ADDR_W-1:0]),
      .o_equal(collision_scalar_next_equal)
  );
  assign collision_equal[1] = (scalar_bank == write_address[RAM_ADDR_W-1]) &&
      collision_scalar_next_equal;
  assign collision_equal[2] = collision_ws_first == write_address;
  assign collision_equal[3] = collision_ws_next == write_address;
  always_comb begin
    case (^{is_mode, group_read_start, ws_read_start})
      1'b0, 1'b1: begin
        collision_selected = is_mode ?
            (group_read_start ? collision_equal[0] : collision_equal[1]) :
            (ws_read_start ? collision_equal[2] : collision_equal[3]);
      end
      default: collision_selected = read_address == write_address;
    endcase
  end
  // 各分支的选择条件并行形成，后续标量碰撞结果只经过最终读取使能。
  assign collision_scalar_selected = is_mode && !group_read_start;
  assign collision_other = (is_mode && group_read_start && collision_equal[0]) ||
      (!is_mode && ws_read_start && collision_equal[2]) ||
      (!is_mode && !ws_read_start && collision_equal[3]);
  bias_read_enable_select u_read_enable (
      .i_enable(read_enable), .i_write(storage_write_accepted),
      .i_scalar_next(collision_scalar_selected), .i_scalar_collision(collision_equal[1]),
      .i_other_collision(collision_other), .o_enable(storage_read_selected)
  );
  // 有效字节与有效地址共同确认实际写入，同址写入保持同步读输出。
  always_comb begin
    storage_write_accepted = 1'b0;
    if (storage_i_wr_en) begin
      if ({1'b0, storage_i_wr_addr} < (RAM_ADDR_W+1)'(2*(1<<BANK_ADDR_W))) begin
        for (int byte_index = 0; byte_index < RAM_BYTES; byte_index++) begin
          if (storage_i_wr_mask[byte_index]) storage_write_accepted = 1'b1;
        end
      end
    end
    storage_i_rd_en = read_enable;
    if (storage_write_accepted) begin
      if (collision_selected) storage_i_rd_en = 1'b0;
    end
    // 确定的控制使用并行资格，未知值保留同步存储原有的条件写入语义。
    case (^{read_enable, storage_write_accepted, is_mode, group_read_start,
            ws_read_start, collision_equal})
      1'b0, 1'b1: storage_i_rd_en = storage_read_selected;
      default: ;
    endcase
  end
  assign storage_i_rd_addr = read_address;
  assign read_data = storage_o_rd_data;
  regfile #(
      .p_data_width(RAM_WIDTH), .p_depth(2*(1<<BANK_ADDR_W)),
      .p_addr_width(RAM_ADDR_W), .p_write_unit(8), .p_no_change_collision(1'b0)
  ) u_storage (
      .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
      .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
      .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
  );

  assign ws_read_start = !is_mode && resident_current && !ws_cache_hit &&
      !ws_busy && !ws_loading;
  assign ws_read_issue = !is_mode && (ws_read_start ||
      (ws_busy && ws_issue_count < READ_COUNT_W'(READS_PER_BLOCK)));
  assign ws_issue_index = ws_read_start ? '0 : READ_INDEX_W'(ws_issue_count);
  assign read_enable = !init_cfg && (is_mode || ws_read_issue);
  // 首次读取直接选择块起点，后续地址独立递增，资格判断只选择最终地址。
  assign read_address = is_mode ?
      {scalar_request_bank, BANK_ADDR_W'(scalar_request_word / WORDS_PER_READ)} :
      (ws_read_start ?
       {active_bank, BANK_ADDR_W'(current_block_offset) * BANK_ADDR_W'(READS_PER_BLOCK)} :
       {ws_cache_bank, BANK_ADDR_W'(ws_read_base + BANK_ADDR_W'(ws_issue_index))});
  always_ff @(posedge clk) begin
    if (is_mode && !init_cfg)
      scalar_half_q <= WORD_INDEX_W'(scalar_request_word % WORDS_PER_READ);
  end

  //! 3. WS Vector Preparation
  //! ------------------------

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ws_cache_valid <= 1'b0;
      ws_cache_bank <= 1'b0;
      ws_cache_block <= '0;
      ws_loading <= 1'b0;
      ws_busy <= 1'b0;
      ws_issue_count <= '0;
      ws_response_valid <= 1'b0;
      ws_response_index <= '0;
      ws_read_base <= '0;
    end else if (init_cfg) begin
      ws_cache_valid <= 1'b0;
      ws_cache_bank <= 1'b0;
      ws_cache_block <= '0;
      ws_loading <= 1'b0;
      ws_busy <= 1'b0;
      ws_issue_count <= '0;
      ws_response_valid <= 1'b0;
      ws_response_index <= '0;
      ws_read_base <= '0;
    end else begin
      ws_response_valid <= ws_read_issue;
      if (ws_read_issue) ws_response_index <= ws_issue_index;
      if (load_start && !is_mode) begin
        ws_cache_valid <= 1'b0;
        ws_cache_bank <= load_bank;
        ws_cache_block <= '0;
        ws_loading <= 1'b1;
        ws_busy <= 1'b0;
        ws_response_valid <= 1'b0;
      end else if (ws_loading && load_done_q) begin
        ws_cache_valid <= 1'b1;
        ws_loading <= 1'b0;
      end else if (ws_read_start) begin
        ws_cache_valid <= 1'b0;
        ws_cache_bank <= active_bank;
        ws_cache_block <= current_block_offset;
        ws_read_base <= BANK_ADDR_W'(current_block_offset) * BANK_ADDR_W'(READS_PER_BLOCK);
        ws_busy <= 1'b1;
        ws_issue_count <= READ_COUNT_W'(1);
      end else if (ws_read_issue) begin
        ws_issue_count <= ws_issue_count + READ_COUNT_W'(1);
      end
      if (ws_response_valid &&
          ws_response_index == READ_INDEX_W'(READS_PER_BLOCK-1)) begin
        ws_cache_valid <= 1'b1;
        ws_busy <= 1'b0;
      end
    end
  end

  // DMA 装载与存储返回分别占用准备阶段，所有偏置数据对共用数据源选择。
  assign ws_cache_update_data = ws_loading ? write_data : read_data;
  for (genvar pair_i = 0; pair_i < READS_PER_BLOCK; pair_i++) begin : gen_ws_pair
    for (genvar byte_i = 0; byte_i < RAM_BYTES; byte_i++) begin : gen_ws_byte
      always_ff @(posedge clk) begin
        if (!init_cfg && !load_start && !is_mode) begin
          if (ws_loading && load_row_high_zero_q && load_row_index_q == '0 &&
              write_address[BANK_ADDR_W-1:0] == BANK_ADDR_W'(pair_i) &&
              write_enable[byte_i])
            ws_cache_pair[pair_i][byte_i*8 +: 8] <= ws_cache_update_data[byte_i*8 +: 8];
          else if (ws_response_valid && ws_response_index == READ_INDEX_W'(pair_i))
            ws_cache_pair[pair_i][byte_i*8 +: 8] <= ws_cache_update_data[byte_i*8 +: 8];
        end
      end
    end
  end
  for (genvar lane = 0; lane < SIZE; lane++) begin : gen_ws_lane
    assign data_out[lane] = $signed(ws_cache_pair[lane / WORDS_PER_READ]
        [(lane % WORDS_PER_READ)*DATA_WIDTH +: DATA_WIDTH]);
  end
  assign group_data_scalar = $signed(read_data[scalar_half_q*DATA_WIDTH +: DATA_WIDTH]);

endmodule

`default_nettype wire
