// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按存储区保存八位行向量，并按总线拍顺序输出有效字节与行结束标志。
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
  // 开始输出或当前行最后一拍被接收时读取目标行，其余拍复用同一行数据。
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

      // 写回模块在 DMA 响应后提供下一分块的宽度。
      // 等待首个输出拍时同步保存该宽度，用于生成对应的字节掩码。
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

`default_nettype wire
