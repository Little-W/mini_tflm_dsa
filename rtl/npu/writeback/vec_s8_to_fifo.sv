module vec_s8_to_fifo_full #(
    parameter integer VLEN  = 16,
    parameter integer BANKS = 16,
    parameter integer ENABLE_TRANSPOSE = 1
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
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_col,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_row,
    output wire                 output_valid,
    input  wire                 output_ready,
    output wire                 output_row_switch,
    output reg  [          3:0] output_mask,
    output reg  [         31:0] output_data,
    output wire                 fifo_full_flag
);

  localparam integer PTR_WIDTH   = (VLEN <= 1) ? 1 : $clog2(VLEN);
  localparam integer COUNT_WIDTH = $clog2(VLEN + 1);
  localparam integer ROW_BEATS   = (VLEN + 3) >> 2;
  localparam integer BEAT_WIDTH  = (ROW_BEATS <= 1) ? 1 : $clog2(ROW_BEATS);
  localparam integer BANK_WIDTH  = (BANKS <= 1) ? 1 : $clog2(BANKS);
  localparam integer BANK_COUNT_WIDTH = (BANKS <= 1) ? 1 : $clog2(BANKS + 1);
  localparam integer ROW_BANKS   = 4;
  localparam integer MEM_DEPTH   = BANKS * ROW_BEATS;
  localparam integer MEM_ADDR_W  = (MEM_DEPTH <= 1) ? 1 : $clog2(MEM_DEPTH);

  reg [COUNT_WIDTH-1:0] bank_count [0:BANKS-1];
  reg [BANKS-1:0] bank_ready;
  reg [BANK_COUNT_WIDTH-1:0] ready_bank_count_q;
  reg [COUNT_WIDTH-1:0] active_read_count_q;

  reg [BANK_WIDTH-1:0]  write_bank;
  reg [BANK_WIDTH-1:0]  read_bank;
  reg [PTR_WIDTH-1:0]   write_ptr;
  reg [PTR_WIDTH-1:0]   read_ptr;
  reg                   stream_active;
  reg                   data_valid;
  reg [BEAT_WIDTH-1:0]  beat_idx;
  reg [$clog2(VLEN)-1:0] vec_valid_num_col_tmp;
  reg [$clog2(VLEN)-1:0] vec_valid_num_row_tmp;
  reg                   transpose_mode_tmp;
  logic [VLEN*8-1:0]    ram_rd_data [ROW_BANKS];
  logic [MEM_ADDR_W-1:0] ram_wr_addr;
  logic [MEM_ADDR_W-1:0] ram_rd_addr [ROW_BANKS];
  logic [PTR_WIDTH-1:0] issue_read_ptr;
  logic [BEAT_WIDTH-1:0] issue_beat_idx;
  logic issue_transpose_mode;
  logic ram_read_en;
  wire transpose_mode_eff = (ENABLE_TRANSPOSE != 0) ? transpose_mode : 1'b0;
  // WS groups arrive as [column tile][R row tiles]. IS groups contain R
  // transposed channel tiles. Both drain as contiguous logical output rows.
  logic co_active, co_data_valid;
  logic [8:0] co_row;
  logic [4:0] co_col;
  logic [1:0] co_beat;
  logic [8:0] co_next_row;
  logic [4:0] co_next_col;
  logic [1:0] co_next_beat;
  wire [BANK_COUNT_WIDTH-1:0] co_tiles = BANK_COUNT_WIDTH'(coalesce_rows[4:0] * coalesce_cols[4:0]);
  wire co_start = start_permitted && coalesce_enable && !co_active &&
      ready_bank_count_q != 0 && co_tiles != 0 &&
      (transpose_mode_eff || coalesce_group_start);
  wire co_fire = coalesce_enable && co_active && co_data_valid && output_ready;
  logic [BANK_WIDTH-1:0] co_following_bank;
  logic [BANK_WIDTH-1:0] co_current_bank;
  logic [4:0] co_last_col_q, co_last_tile_row_q;
  wire co_col_last = co_col == co_last_col_q;
  wire co_row_last = co_col_last && co_beat == 3;
  wire co_group_last = co_row_last &&
      (transpose_mode_eff ? (co_row[3:0] == vec_valid_num_row)
                          : (co_row[8:4] == co_last_tile_row_q &&
                             COUNT_WIDTH'(co_row[3:0]) + COUNT_WIDTH'(1) >= bank_count[co_current_bank]));
  wire co_finish = co_fire && co_group_last;
  wire [BANK_WIDTH-1:0] co_bank_after = BANK_WIDTH'((int'(read_bank) + int'(co_tiles)) % BANKS);
  wire co_load_waiting = coalesce_enable && co_active && !co_data_valid && bank_ready[co_current_bank];
  logic [BANK_WIDTH-1:0] co_issue_bank;
  logic [MEM_ADDR_W-1:0] co_ram_addr;
  always_comb begin
    co_next_row = co_row; co_next_col = co_col; co_next_beat = co_beat;
    if (co_start) begin
      co_next_row = 0; co_next_col = 0; co_next_beat = 0;
    end else if (co_fire) begin
      co_next_beat = co_beat + 1'b1;
      if (co_beat == 3) begin
        co_next_col = co_col + 1'b1;
        if (co_col_last) begin
          co_next_col = 0;
          co_next_row = co_row + 1'b1;
        end
      end
    end
    co_issue_bank = co_current_bank;
    if (co_start) co_issue_bank = read_bank;
    else if (co_fire && co_beat == 3) co_issue_bank = co_following_bank;
    co_ram_addr = MEM_ADDR_W'(int'(co_issue_bank) * ROW_BEATS +
        (transpose_mode_eff ? int'(co_next_beat) : ((int'(co_next_row) & 15) >> 2)));
  end

  // Prepare the next column's bank during its first three beats. The
  // fourth-beat RAM request then uses only registers and a bank-ready lookup.
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      co_following_bank <= 0; co_last_col_q <= 0; co_last_tile_row_q <= 0;
    end else begin
      if (co_start) begin
        co_last_col_q <= coalesce_cols[4:0] - 5'd1;
        co_last_tile_row_q <= coalesce_rows[4:0] - 5'd1;
      end
      if (co_active && co_beat != 3) begin
        if (co_col_last)
          co_following_bank <= transpose_mode_eff ? read_bank :
              BANK_WIDTH'((int'(read_bank) + ((int'(co_row)+1)>>4)) % BANKS);
        else
          co_following_bank <= BANK_WIDTH'((int'(co_current_bank) + int'(coalesce_rows[4:0])) % BANKS);
      end
    end
  end

`ifndef SYNTHESIS
  bit                   oa_trace_en;
`else
  localparam bit        oa_trace_en = 1'b0;
`endif

  function automatic [BANK_WIDTH-1:0] next_bank(input [BANK_WIDTH-1:0] bank);
    begin
      if (bank == BANK_WIDTH'(BANKS - 1)) next_bank = '0;
      else                               next_bank = bank + 1'b1;
    end
  endfunction

  wire write_bank_blocked = bank_ready[write_bank];
  wire next_write_bank_blocked = bank_ready[next_bank(write_bank)];
  logic [BANK_COUNT_WIDTH-1:0] reserve_bank_count;
  logic [BANK_COUNT_WIDTH-1:0] used_bank_count;
  logic [BANK_COUNT_WIDTH-1:0] free_bank_count;
  logic                   fifo_watermark_full;
  // A temporary valid gap can appear between cached IA slots.  Only the
  // explicit tile_done marker is allowed to publish a bank to the writer.
  wire finish_write_bank = in_valid && in_tile_done;
  wire [COUNT_WIDTH-1:0] write_rows_next =
      in_valid ? (COUNT_WIDTH'(write_ptr) + COUNT_WIDTH'(1)) : COUNT_WIDTH'(write_ptr);
  wire [COUNT_WIDTH-1:0] active_read_count = active_read_count_q;
  wire [COUNT_WIDTH-1:0] output_row_count =
      transpose_mode_tmp ? (COUNT_WIDTH'(vec_valid_num_row_tmp) + COUNT_WIDTH'(1))
                         : active_read_count;
  wire [COUNT_WIDTH-1:0] output_col_count =
      transpose_mode_tmp ? active_read_count
                         : (COUNT_WIDTH'(vec_valid_num_col_tmp) + COUNT_WIDTH'(1));
  wire read_bank_ready = bank_ready[read_bank] && (bank_count[read_bank] != '0);
  wire [COUNT_WIDTH-1:0] last_beat_idx_cur =
      (output_col_count == '0) ? '0 : ((output_col_count - COUNT_WIDTH'(1)) >> 2);
  wire output_fire = output_ready && output_valid;
  wire last_beat_in_row = output_fire &&
                          (COUNT_WIDTH'(beat_idx) == last_beat_idx_cur);
  wire last_row_in_bank = last_beat_in_row &&
                          ((COUNT_WIDTH'(read_ptr) + COUNT_WIDTH'(1)) >= output_row_count);
  wire start_stream = start_permitted && !stream_active && read_bank_ready;
  wire stream_has_next = output_fire && !last_row_in_bank;

  // Compatibility debug names used by existing testbenches.
  wire write_sel = write_bank[0];
  wire read_sel  = read_bank[0];
  wire bank_ready0 = bank_ready[0];
  wire bank_ready1 = (BANKS > 1) ? bank_ready[1] : 1'b0;
  wire [COUNT_WIDTH-1:0] bank_count0 = bank_count[0];
  wire [COUNT_WIDTH-1:0] bank_count1 = (BANKS > 1) ? bank_count[1] : '0;

  assign output_valid = coalesce_enable ? (co_active && co_data_valid) : (stream_active && data_valid);
  assign output_row_switch = coalesce_enable ? (co_fire && co_row_last) : last_beat_in_row;
  always_comb begin
    if (reserve_banks == 32'd0) begin
      reserve_bank_count = BANK_COUNT_WIDTH'(1);
    end else if (reserve_banks >= 32'(BANKS)) begin
      reserve_bank_count = BANK_COUNT_WIDTH'(BANKS);
    end else begin
      reserve_bank_count = BANK_COUNT_WIDTH'(reserve_banks);
    end

    used_bank_count = ready_bank_count_q + ((write_ptr != '0) ? BANK_COUNT_WIDTH'(1) : BANK_COUNT_WIDTH'(0));
    free_bank_count = (used_bank_count >= BANK_COUNT_WIDTH'(BANKS))
                    ? '0
                    : (BANK_COUNT_WIDTH'(BANKS) - used_bank_count);
    fifo_watermark_full = (free_bank_count < reserve_bank_count);
  end

  assign fifo_full_flag = write_bank_blocked || fifo_watermark_full ||
      (!coalesce_enable && next_write_bank_blocked);
  assign ram_read_en = coalesce_enable ? (co_start || co_load_waiting ||
       (co_fire && !co_group_last && bank_ready[co_issue_bank]))
                                      : (start_stream || stream_has_next);

  always_comb begin
    issue_read_ptr = read_ptr;
    issue_beat_idx = beat_idx;
    issue_transpose_mode = transpose_mode_tmp;

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

  always_comb begin
    int wr_group;
    int wr_addr_i;

    wr_group = int'(write_ptr) >> 2;
    wr_addr_i = (int'(write_bank) * ROW_BEATS) + wr_group;
    ram_wr_addr = MEM_ADDR_W'(wr_addr_i);

    for (int rb = 0; rb < ROW_BANKS; rb++) begin
      int rd_group;
      int rd_addr_i;

      rd_group = issue_transpose_mode ? int'(issue_beat_idx)
                                      : (int'(issue_read_ptr) >> 2);
      rd_addr_i = (int'(read_bank) * ROW_BEATS) + rd_group;
      ram_rd_addr[rb] = coalesce_enable ? co_ram_addr : MEM_ADDR_W'(rd_addr_i);
    end
  end

  genvar ram_bank;
  generate
    for (ram_bank = 0; ram_bank < ROW_BANKS; ram_bank++) begin : gen_fifo_ram
      wire row_wr_en = in_valid && !write_bank_blocked && (2'(write_ptr) == 2'(ram_bank));

      vec_s8_fifo_row_ram #(
        .DATA_WIDTH(VLEN * 8),
        .DEPTH     (MEM_DEPTH),
        .ADDR_WIDTH(MEM_ADDR_W)
      ) u_fifo_ram (
        .clk    (clk),
        .wr_en  (row_wr_en),
        .wr_addr(ram_wr_addr),
        .wr_data(in_vec_s8),
        .rd_en  (ram_read_en),
        .rd_addr(ram_rd_addr[ram_bank]),
        .rd_data(ram_rd_data[ram_bank])
      );
    end
  endgenerate

`ifndef SYNTHESIS
  initial begin
    oa_trace_en = 1'b0;
    if ($test$plusargs("NPU_OA_TRACE")) oa_trace_en = 1'b1;
  end
`endif

  always @(posedge clk) begin
    if (!rst_n) begin
      write_bank   <= '0;
      read_bank    <= '0;
      write_ptr    <= '0;
      read_ptr     <= '0;
      co_active <= 0; co_data_valid <= 0; co_current_bank <= 0; co_row <= 0; co_col <= 0; co_beat <= 0;
      stream_active <= 1'b0;
      data_valid   <= 1'b0;
      beat_idx     <= '0;
      vec_valid_num_col_tmp <= '0;
      vec_valid_num_row_tmp <= '0;
      transpose_mode_tmp <= 1'b0;
      oa_fifo_req  <= 1'b0;
      bank_ready   <= '0;
      ready_bank_count_q <= '0;
      active_read_count_q <= '0;
      for (int bank_idx = 0; bank_idx < BANKS; bank_idx++) begin
        bank_count[bank_idx] <= '0;
      end
    end else begin
      oa_fifo_req <= coalesce_enable ? (ready_bank_count_q != 0 && co_tiles != 0 && !co_active)
                                     : (read_bank_ready && !stream_active);

      if (finish_write_bank && !write_bank_blocked) begin
        bank_count[write_bank] <= write_rows_next;
        bank_ready[write_bank] <= 1'b1;
        if (oa_trace_en) begin
          $display("[OA_TRACE] time=%0t fifo_bank_ready bank=%0d rows=%0d transpose=%0d vcol=%0d vrow=%0d",
                   $time, write_bank, write_rows_next, transpose_mode_eff,
                   vec_valid_num_col, vec_valid_num_row);
        end
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
          co_data_valid <= !co_group_last && bank_ready[co_issue_bank];
        end else if (co_load_waiting) co_data_valid <= 1;
        if (co_finish) begin
          co_active <= 0; co_data_valid <= 0;
          read_bank <= co_bank_after;
          for (int cb = 0; cb < BANKS; cb++) begin
            if (((cb + BANKS - int'(read_bank)) % BANKS) < int'(co_tiles)) begin
              bank_ready[cb] <= 0;
              bank_count[cb] <= 0;
            end
          end
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
        active_read_count_q <= bank_count[read_bank];
        vec_valid_num_col_tmp <= vec_valid_num_col;
        vec_valid_num_row_tmp <= vec_valid_num_row;
        transpose_mode_tmp <= transpose_mode_eff;
        if (oa_trace_en) begin
          $display("[OA_TRACE] time=%0t fifo_stream_start bank=%0d rows=%0d transpose=%0d vcol=%0d vrow=%0d",
                   $time, read_bank, bank_count[read_bank], transpose_mode_eff,
                   vec_valid_num_col, vec_valid_num_row);
        end
      end else if (stream_active && (read_ptr == '0) && (beat_idx == '0) && !output_ready) begin
        vec_valid_num_col_tmp <= vec_valid_num_col;
        vec_valid_num_row_tmp <= vec_valid_num_row;
        transpose_mode_tmp <= transpose_mode_eff;
      end else if (output_fire) begin
        if (last_row_in_bank) begin
          stream_active <= 1'b0;
          data_valid    <= 1'b0;
          read_ptr      <= '0;
          beat_idx      <= '0;
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
  integer out_byte_i;
  integer src_row_i;
  integer read_bank_i;

  always @(*) begin
    output_data = 32'b0;
    output_mask = 4'b0;
    valid_cols_i = int'(output_col_count);
    beat_col_start_i = beat_idx * 4;
    valid_in_beat_i = valid_cols_i - beat_col_start_i;
    if (valid_in_beat_i > 4) valid_in_beat_i = 4;
    if (valid_in_beat_i < 0) valid_in_beat_i = 0;

    if (coalesce_enable && co_active) begin
      if (transpose_mode_eff) begin
        for (out_byte_i = 0; out_byte_i < 4; out_byte_i = out_byte_i + 1)
          output_data[out_byte_i*8+:8] = ram_rd_data[out_byte_i][co_row[3:0]*8+:8];
      end else begin
        output_data = ram_rd_data[co_row[1:0]][co_beat*32+:32];
      end
      output_mask = 4'b1111;
    end else if (stream_active) begin
      if (transpose_mode_tmp) begin
        for (out_byte_i = 0; out_byte_i < 4; out_byte_i = out_byte_i + 1) begin
          src_row_i = beat_col_start_i + out_byte_i;
          if (src_row_i < active_read_count) begin
            output_data[out_byte_i*8+:8] =
                ram_rd_data[out_byte_i][int'(read_ptr)*8+:8];
          end
        end
      end else begin
        read_bank_i = int'(2'(read_ptr));
        output_data = ram_rd_data[read_bank_i][beat_idx*32+:32];
      end

      case (valid_in_beat_i)
        1: output_mask = 4'b0001;
        2: output_mask = 4'b0011;
        3: output_mask = 4'b0111;
        4: output_mask = 4'b1111;
        default: output_mask = 4'b0000;
      endcase
    end
  end

  always @(posedge clk) begin
    if (rst_n && oa_trace_en && output_valid && output_ready) begin
      $display("[OA_TRACE] time=%0t fifo_out bank=%0d row=%0d beat=%0d mask=%b data=%08x rows=%0d cols=%0d transpose=%0d",
               $time, read_bank, read_ptr, beat_idx, output_mask, output_data,
               output_row_count, output_col_count, transpose_mode_tmp);
    end
  end

endmodule

module vec_s8_to_fifo_linear #(
    parameter integer VLEN  = 16,
    parameter integer BANKS = 16
) (
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 in_valid,
    input  wire                 in_tile_done,
    input  wire [   VLEN*8-1:0] in_vec_s8,
    output logic                oa_fifo_req,
    input  wire [          31:0] reserve_banks,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_col,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_row,
    output wire                 output_valid,
    input  wire                 output_ready,
    output wire                 output_row_switch,
    output logic [          3:0] output_mask,
    output logic [         31:0] output_data,
    output wire                 fifo_full_flag
);

  localparam integer PTR_WIDTH   = (VLEN <= 1) ? 1 : $clog2(VLEN);
  localparam integer COUNT_WIDTH = $clog2(VLEN + 1);
  localparam integer ROW_BEATS   = (VLEN + 3) >> 2;
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
  logic [BANK_COUNT_WIDTH-1:0] reserve_bank_count;
  logic [BANK_COUNT_WIDTH-1:0] used_bank_count;
  logic [BANK_COUNT_WIDTH-1:0] free_bank_count;
  logic fifo_watermark_full;

  wire write_bank_blocked = bank_ready[write_bank];
  wire next_write_bank_blocked = bank_ready[next_bank(write_bank)];
  wire finish_write_bank = in_valid && in_tile_done;
  wire [COUNT_WIDTH-1:0] write_rows_next =
      in_valid ? (COUNT_WIDTH'(write_ptr) + COUNT_WIDTH'(1)) : COUNT_WIDTH'(write_ptr);
  wire read_bank_ready = bank_ready[read_bank] && (bank_count[read_bank] != '0);
  wire start_stream = !stream_active && read_bank_ready;
  wire [COUNT_WIDTH-1:0] output_row_count = active_read_count_q;
  wire [COUNT_WIDTH-1:0] output_col_count =
      COUNT_WIDTH'(vec_valid_num_col_tmp) + COUNT_WIDTH'(1);
  wire [COUNT_WIDTH-1:0] last_beat_idx_cur =
      (output_col_count == '0) ? '0 : ((output_col_count - COUNT_WIDTH'(1)) >> 2);
  wire output_fire = output_ready && output_valid;
  wire last_beat_in_row = output_fire &&
                          (COUNT_WIDTH'(beat_idx) == last_beat_idx_cur);
  wire last_row_in_bank = last_beat_in_row &&
                          ((COUNT_WIDTH'(read_ptr) + COUNT_WIDTH'(1)) >= output_row_count);
  wire read_next_row = last_beat_in_row && !last_row_in_bank;
  wire ram_read_en = start_stream || read_next_row;

  assign output_valid = stream_active && data_valid;
  assign output_row_switch = last_beat_in_row;

  always_comb begin
    if (reserve_banks == 32'd0) begin
      reserve_bank_count = BANK_COUNT_WIDTH'(1);
    end else if (reserve_banks >= 32'(BANKS)) begin
      reserve_bank_count = BANK_COUNT_WIDTH'(BANKS);
    end else begin
      reserve_bank_count = BANK_COUNT_WIDTH'(reserve_banks);
    end

    used_bank_count = ready_bank_count_q +
                      ((write_ptr != '0) ? BANK_COUNT_WIDTH'(1) : BANK_COUNT_WIDTH'(0));
    free_bank_count = (used_bank_count >= BANK_COUNT_WIDTH'(BANKS))
                    ? '0
                    : (BANK_COUNT_WIDTH'(BANKS) - used_bank_count);
    fifo_watermark_full = (free_bank_count < reserve_bank_count);
  end

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
    output_data = 32'b0;
    output_mask = 4'b0;
    valid_cols_i = int'(output_col_count);
    beat_col_start_i = int'(beat_idx) * 4;
    valid_in_beat_i = valid_cols_i - beat_col_start_i;
    if (valid_in_beat_i > 4) valid_in_beat_i = 4;
    if (valid_in_beat_i < 0) valid_in_beat_i = 0;

    if (stream_active && data_valid) begin
      output_data = ram_rd_data[int'(beat_idx)*32+:32];
      case (valid_in_beat_i)
        1: output_mask = 4'b0001;
        2: output_mask = 4'b0011;
        3: output_mask = 4'b0111;
        4: output_mask = 4'b1111;
        default: output_mask = 4'b0000;
      endcase
    end
  end

  wire unused_vec_valid_num_row = |vec_valid_num_row;

endmodule

module vec_s8_to_fifo #(
    parameter integer VLEN  = 16,
    parameter integer BANKS = 16,
    parameter integer ENABLE_TRANSPOSE = 1
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
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_col,
    input  wire [$clog2(VLEN)-1:0] vec_valid_num_row,
    output wire                 output_valid,
    input  wire                 output_ready,
    output wire                 output_row_switch,
    output wire [          3:0] output_mask,
    output wire [         31:0] output_data,
    output wire                 fifo_full_flag
);

`ifndef SYNTHESIS
  localparam integer COUNT_WIDTH = $clog2(VLEN + 1);
  wire stream_active;
  wire write_sel;
  wire read_sel;
  wire bank_ready0;
  wire bank_ready1;
  wire [COUNT_WIDTH-1:0] bank_count0;
  wire [COUNT_WIDTH-1:0] bank_count1;
`endif

  generate
    if (ENABLE_TRANSPOSE == 0) begin : g_linear
      wire unused_transpose_mode = transpose_mode;
      vec_s8_to_fifo_linear #(
        .VLEN (VLEN),
        .BANKS(BANKS)
      ) u_linear (
        .clk              (clk),
        .rst_n            (rst_n),
        .in_valid         (in_valid),
        .in_tile_done     (in_tile_done),
        .in_vec_s8        (in_vec_s8),
        .oa_fifo_req      (oa_fifo_req),
        .reserve_banks    (reserve_banks),
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid     (output_valid),
        .output_ready     (output_ready),
        .output_row_switch(output_row_switch),
        .output_mask      (output_mask),
        .output_data      (output_data),
        .fifo_full_flag   (fifo_full_flag)
      );
`ifndef SYNTHESIS
      assign stream_active = u_linear.stream_active;
      assign write_sel = u_linear.write_bank[0];
      assign read_sel = u_linear.read_bank[0];
      assign bank_ready0 = u_linear.bank_ready[0];
      assign bank_ready1 = (BANKS > 1) ? u_linear.bank_ready[1] : 1'b0;
      assign bank_count0 = u_linear.bank_count[0];
      assign bank_count1 = (BANKS > 1) ? u_linear.bank_count[1] : '0;
`endif
    end else begin : g_full
      // Two register entries isolate the RAM read controls from DMA READY.
      // Start a new tile only after the previous tile's entries drain, so
      // the writer has advanced the tail dimensions before they are sampled.
      logic [36:0] skid[2];
      logic skid_rd, skid_wr;
      logic [1:0] skid_count;
      wire inner_req, inner_valid, inner_switch;
      wire [3:0] inner_mask;
      wire [31:0] inner_data;
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
      assign output_data=skid[skid_rd][31:0];
      assign output_mask=skid[skid_rd][35:32];
      assign output_row_switch=take && skid[skid_rd][36];
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
        .ENABLE_TRANSPOSE(ENABLE_TRANSPOSE)
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
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid     (inner_valid),
        .output_ready     (inner_ready),
        .output_row_switch(inner_switch),
        .output_mask      (inner_mask),
        .output_data      (inner_data),
        .fifo_full_flag   (fifo_full_flag)
      );
`ifndef SYNTHESIS
      assign stream_active = u_full.stream_active;
      assign write_sel = u_full.write_sel;
      assign read_sel = u_full.read_sel;
      assign bank_ready0 = u_full.bank_ready0;
      assign bank_ready1 = u_full.bank_ready1;
      assign bank_count0 = u_full.bank_count0;
      assign bank_count1 = u_full.bank_count1;
`endif
    end
  endgenerate

endmodule

module vec_s8_fifo_row_ram #(
    parameter int unsigned DATA_WIDTH = 128,
    parameter int unsigned DEPTH = 16,
    parameter int unsigned ADDR_WIDTH = 4
) (
    input  logic                  clk,
    input  logic                  wr_en,
    input  logic [ADDR_WIDTH-1:0] wr_addr,
    input  logic [DATA_WIDTH-1:0] wr_data,
    input  logic                  rd_en,
    input  logic [ADDR_WIDTH-1:0] rd_addr,
    output logic [DATA_WIDTH-1:0] rd_data
);

`ifdef ASIC_SRAM
  smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)) u_sram (
    .clk(clk), .write_enable(wr_en), .write_address(wr_addr), .write_data(wr_data),
    .write_mask({DATA_WIDTH{1'b1}}), .read_enable(rd_en), .read_address(rd_addr), .read_data(rd_data));
`else
  (* ram_style = "block" *) logic [DATA_WIDTH-1:0] mem [0:DEPTH-1];

  always_ff @(posedge clk) begin
    if (wr_en) begin
      mem[wr_addr] <= wr_data;
    end
    if (rd_en) begin
      rd_data <= mem[rd_addr];
    end
  end

`endif

endmodule
