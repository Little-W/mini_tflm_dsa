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

  (* ram_style = "distributed" *) logic [DATA_WIDTH-1:0] bank0_words [GROUP_ELEMS];
  (* ram_style = "distributed" *) logic [DATA_WIDTH-1:0] bank1_words [GROUP_ELEMS];
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

  always_ff @(posedge clk) begin

    if (!init_cfg && !load_start) begin

      for(int beat_word=0;beat_word<BUS_WIDTH/DATA_WIDTH;beat_word++)
      if (load_word_valid_q[beat_word*BYTES_PER_WORD]) begin
        automatic int byte_offset;
        automatic int word_idx;
        automatic logic [DATA_WIDTH-1:0] packed_word;

        byte_offset = int'(load_word_col_base_q) + beat_word*BYTES_PER_WORD;
        if (GROUP_BLOCKS_MAX == 1) begin
          word_idx = byte_offset >> BYTE_SHIFT;
        end else begin
          word_idx = (int'(load_word_row_q) * SIZE) + (byte_offset >> BYTE_SHIFT);
        end

        packed_word = '0;
        for (int byte_i = 0; byte_i < BYTES_PER_WORD; byte_i++) begin
          packed_word[byte_i*8 +: 8] = load_word_data_q[beat_word*BYTES_PER_WORD+byte_i][7:0];
        end

        if (word_idx < GROUP_ELEMS) begin
          if (load_bank_q) begin
            bank1_words[word_idx] <= packed_word;
          end else begin
            bank0_words[word_idx] <= packed_word;
          end
        end
      end
    end
  end

  logic [1:0] load_window_hit;
  logic [$clog2(GROUP_ELEMS)-1:0] current_word_base, scalar_word_idx;
  logic [$clog2(GROUP_ELEMS)-1:0] scalar_word_base;
  logic scalar_bank;
  for (genvar b = 0; b < 2; b++) begin : gen_window_hit
    assign load_window_hit[b] = bank_loaded[b] &&
        load_block_idx >= bank_block_idx[b] &&
        {1'b0, load_block_idx} + {1'b0, group_blocks_needed} <=
        {1'b0, bank_block_idx[b]} + {1'b0, bank_blocks_count[b]};
  end
  assign bias_valid = bank_loaded[active_bank] &&
      current_block_idx >= bank_block_idx[active_bank] &&
      {1'b0, current_block_idx} + {1'b0, group_blocks_needed} <=
      {1'b0, bank_block_idx[active_bank]} + {1'b0, bank_blocks_count[active_bank]};
  assign load_block_valid = |load_window_hit;
  assign load_block_bank = !load_window_hit[0];
  assign current_word_base = $clog2(GROUP_ELEMS)'(
      current_block_idx - bank_block_idx[active_bank]) << $clog2(SIZE);
  // The scalar port follows the executing IS group while the command side
  // selects and prepares subsequent groups in the same resident window.
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
  assign scalar_word_idx = scalar_word_base + group_read_idx;
  assign group_data_scalar = scalar_bank
                           ? $signed(bank1_words[scalar_word_idx])
                           : $signed(bank0_words[scalar_word_idx]);

  always_comb begin
    for (int i = 0; i < SIZE; i++) begin
      data_out[i] = active_bank ? $signed(bank1_words[int'(current_word_base)+i]) :
                                 $signed(bank0_words[int'(current_word_base)+i]);
    end
  end

endmodule
