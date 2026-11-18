/*
 * bias_loader_buffer — 双 bank 数据存储
 * ============================================================
 */

module bias_loader_buffer #(
    parameter int unsigned SIZE       = 8,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned DMA_DATA_WIDTH = 8,
    parameter int unsigned BUS_WIDTH  = 32,
    parameter int unsigned REG_WIDTH  = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
    parameter int unsigned GROUP_BLOCKS_MAX = 1
) (
    input  logic clk,
    input  logic rst_n,

    input  logic                 init_cfg,
    input  logic                 load_start,
    input  logic                 load_bank,
    input  logic [COUNT_WIDTH-1:0] load_block_idx,
    input  logic [COUNT_WIDTH-1:0] load_blocks_count,
    input  logic [COUNT_WIDTH-1:0] group_blocks_needed,
    input  logic                 load_word_valid [BUS_WIDTH/8],
    input  logic [REG_WIDTH-1:0] load_word_row,
    input  logic [$clog2(SIZE * (DATA_WIDTH / 8))-1:0] load_word_col_base,
    input  logic signed [DMA_DATA_WIDTH-1:0] load_word_data [BUS_WIDTH/8],
    input  logic                 load_done,

    input  logic                 active_bank,
    input  logic [COUNT_WIDTH-1:0] current_block_idx,

    input  logic                 is_mode,
    input  logic                 group_read_start,
    input  logic [$clog2(GROUP_BLOCKS_MAX * SIZE)-1:0] group_read_idx,
    output logic                 bias_valid,
    output logic                 load_block_valid,
    output logic                 load_block_bank,
    output logic signed [DATA_WIDTH-1:0] data_out [SIZE],
    output logic signed [DATA_WIDTH-1:0] group_data_scalar
);

  localparam int BYTES_PER_WORD = DATA_WIDTH / 8;
  localparam int BYTE_SHIFT = $clog2(BYTES_PER_WORD);
  localparam int GROUP_ELEMS = GROUP_BLOCKS_MAX * SIZE;
  localparam int CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;

  logic                         bank_loaded [2];
  logic [CNT_W-1:0]             bank_block_idx [2];
  logic [CNT_W-1:0]             bank_blocks_count [2];
  logic                         load_bank_q;
  logic                         load_word_valid_q [BUS_WIDTH/8];
  logic [REG_WIDTH-1:0]         load_word_row_q;
  logic [$clog2(SIZE * (DATA_WIDTH / 8))-1:0] load_word_col_base_q;
  logic signed [DMA_DATA_WIDTH-1:0] load_word_data_q [BUS_WIDTH/8];
  logic                         load_done_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      load_bank_q          <= 1'b0;
      load_word_row_q      <= '0;
      load_word_col_base_q <= '0;
      load_done_q          <= 1'b0;
      for (int i = 0; i < BUS_WIDTH/8; i++) begin
        load_word_valid_q[i] <= 1'b0;
        load_word_data_q[i]  <= '0;
      end
    end else begin
      load_bank_q          <= load_bank;
      if (GROUP_BLOCKS_MAX == 1) begin
        load_word_row_q    <= '0;
      end else begin
        load_word_row_q    <= load_word_row;
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
        bank_blocks_count[b] <= '0;
      end
    end else if (init_cfg) begin
      for (int b = 0; b < 2; b++) begin
        bank_loaded[b]    <= 1'b0;
        bank_block_idx[b] <= '0;
        bank_blocks_count[b] <= '0;
      end
    end else begin
      if (load_start) begin
        bank_loaded[load_bank]    <= 1'b0;
        bank_block_idx[load_bank] <= load_block_idx;
        bank_blocks_count[load_bank] <= load_blocks_count;
      end else if (load_done_q) begin
        bank_loaded[load_bank_q] <= 1'b1;
      end
    end
  end

  //! 1. Residency and Read Context
  //! -----------------------------

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

  logic [1:0] load_window_hit;
  logic resident_current;
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

  for (genvar b = 0; b < 2; b++) begin : gen_window_hit
    assign load_window_hit[b] = bank_loaded[b] &&
        load_block_idx >= bank_block_idx[b] &&
        {1'b0, load_block_idx} + {1'b0, group_blocks_needed} <=
        {1'b0, bank_block_idx[b]} + {1'b0, bank_blocks_count[b]};
  end
  assign resident_current = bank_loaded[active_bank] &&
      current_block_idx >= bank_block_idx[active_bank] &&
      {1'b0, current_block_idx} + {1'b0, group_blocks_needed} <=
      {1'b0, bank_block_idx[active_bank]} + {1'b0, bank_blocks_count[active_bank]};
  assign load_block_valid = |load_window_hit;
  assign load_block_bank = !load_window_hit[0];
  assign current_block_offset = BLOCK_ADDR_W'(
      current_block_idx - bank_block_idx[active_bank]);
  assign current_word_base = GROUP_ADDR_W'(current_block_offset) * GROUP_ADDR_W'(SIZE);
  assign ws_cache_hit = ws_cache_valid && ws_cache_bank == active_bank &&
      ws_cache_block == current_block_offset;
  assign bias_valid = resident_current && (is_mode || ws_cache_hit);

  // Capture the executing group independently from command-side prefetch.
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

  assign write_row_valid = (GROUP_BLOCKS_MAX == 1) ||
      (load_word_row_q < REG_WIDTH'(GROUP_BLOCKS_MAX));
  assign write_address = {load_bank_q,
      BANK_ADDR_W'((GROUP_BLOCKS_MAX == 1 ? REG_WIDTH'(0) : load_word_row_q) *
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

  (* ram_style = "block" *) logic [RAM_WIDTH-1:0] bias_words [2*(1<<BANK_ADDR_W)];
  always_ff @(posedge clk) begin
    for (int byte_i = 0; byte_i < RAM_BYTES; byte_i++) begin
      if (write_enable[byte_i])
        bias_words[write_address][byte_i*8 +: 8] <= write_data[byte_i*8 +: 8];
    end
    if (read_enable)
      read_data <= bias_words[read_address];
  end

  assign ws_read_start = !is_mode && resident_current && !ws_cache_hit &&
      !ws_busy && !ws_loading;
  assign ws_read_issue = !is_mode && (ws_read_start ||
      (ws_busy && ws_issue_count < READ_COUNT_W'(READS_PER_BLOCK)));
  assign ws_issue_index = ws_read_start ? '0 : READ_INDEX_W'(ws_issue_count);
  assign read_enable = !init_cfg && (is_mode || ws_read_issue);
  assign read_address = is_mode ?
      {scalar_request_bank, BANK_ADDR_W'(scalar_request_word / WORDS_PER_READ)} :
      {ws_read_start ? active_bank : ws_cache_bank,
       BANK_ADDR_W'((ws_read_start ? BANK_ADDR_W'(current_block_offset) *
                     BANK_ADDR_W'(READS_PER_BLOCK) : ws_read_base) +
                    BANK_ADDR_W'(ws_issue_index))};
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

  for (genvar pair_i = 0; pair_i < READS_PER_BLOCK; pair_i++) begin : gen_ws_pair
    for (genvar byte_i = 0; byte_i < RAM_BYTES; byte_i++) begin : gen_ws_byte
      always_ff @(posedge clk) begin
        if (!init_cfg && !load_start && !is_mode) begin
          if (ws_loading && load_word_row_q == '0 &&
              write_address[BANK_ADDR_W-1:0] == BANK_ADDR_W'(pair_i) &&
              write_enable[byte_i])
            ws_cache_pair[pair_i][byte_i*8 +: 8] <= write_data[byte_i*8 +: 8];
          else if (ws_response_valid && ws_response_index == READ_INDEX_W'(pair_i))
            ws_cache_pair[pair_i][byte_i*8 +: 8] <= read_data[byte_i*8 +: 8];
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
