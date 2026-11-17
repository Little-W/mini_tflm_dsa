/*
 * ia_loader_cache_mgr — 缓存管理、对角化输出与控制信号生成
 * ============================================================
 * 功能：
 *   1. 管理 SIZE 组同步读写 RAM，每组物理容量为 CACHE_BLOCKS × SIZE × DATA_WIDTH bit
 *   2. 将 AXI DMA 解包后的数据写入指定 slot/row/col
 *   3. 接收发送命令后，按对角化时序从 RAM 读出数据
 *   4. 生成延迟对齐的 ia_row_valid[j], ia_is_init_data[j], ia_calc_done[j]
 *   5. 在所有列输出完毕后产生 send_done 脉冲
 *
 * 对角化读取原理：
 *   发送计数器 diag_step 从 0 递增到 valid_rows + SIZE - 2
 *   第 j 列 RAM bank 在 diag_step ∈ [j, j + valid_rows - 1] 时读出
 *   rd_addr[j] = slot * SIZE + (diag_step - j)
 */

module ia_loader_cache_mgr #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 4,
    parameter int unsigned COMPACT_S8 = 1,
    parameter bit EXTERNAL_RAM = 1'b0,
    parameter int unsigned RAM_WORD_ADDR_WIDTH = 10,
    localparam int unsigned SLOT_BLOCKS =
        ((COMPACT_S8 != 0) && (DATA_WIDTH == 16)) ? 2 * CACHE_BLOCKS : CACHE_BLOCKS
) (
    input  logic clk,
    input  logic rst_n,
    input  logic compact_mode = 1'b0,
    input  logic signed [DATA_WIDTH-1:0] compact_offset = '0,
    input  logic [31:0] cfg_cache_blocks = 32'd0,

    output logic [1:0] ram_port_wr_en,
    output logic [RAM_WORD_ADDR_WIDTH-1:0] ram_port_wr_addr [0:1],
    output logic [127:0] ram_port_wr_data [0:1],
    output logic [15:0] ram_port_wr_mask [0:1],
    output logic [1:0] ram_port_rd_en,
    output logic [RAM_WORD_ADDR_WIDTH-1:0] ram_port_rd_addr [0:1],
    input  logic [127:0] ram_port_rd_data [0:1] = '{default:'0},

    // ---- 写入端 ----
    input  logic [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0]      wr_slot,
    input  logic [$clog2(SIZE)-1:0]              wr_row,
    input  logic [$clog2(SIZE)-1:0]              wr_col_base,
    input  logic signed [DATA_WIDTH-1:0]         wr_data  [BUS_WIDTH/8],  // 最多 BYTE_PER_BEAT 个
    input  logic                                 wr_valid [BUS_WIDTH/8],
    input  logic                                 wr_use_16bits,

    // ---- L1组对角化发送控制 ----
    // ctrl 一次性指定 L1 组的起始/终止 slot，cache_mgr 自主完成整组输出
    input  logic                              l1_start,        // L1组发送启动脉冲
    input  logic [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0]   l1_slot_start,   // 起始 slot
    input  logic [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0]   l1_slot_end,     // 终止 slot（含，支持回绕）
    input  logic                              l1_is_init,      // L1组 is_init 标记
    input  logic                              l1_calc_done,    // L1组 calc_done 标记
    input  logic [$clog2(SIZE + 1)-1:0]       slot_rows [SLOT_BLOCKS], // 每 slot 有效行数
    output logic                              tile_done,       // 单 tile 输出完成
    output logic                              l1_done,         // L1组全部输出完成
    output logic                              ia_tile_start,   // 单 tile 首行到达输出端

    // ---- 输出到脉动阵列（SIZE 维数据 + 最后一列指示信号）----
    output logic signed [DATA_WIDTH-1:0]         ia_out          [SIZE],
    output logic                                 ia_row_valid,     // 最大延迟（第 SIZE-1 列）
    output logic                                 ia_is_init_data,  // 同上
    output logic                                 ia_calc_done      // 同上
);

  // =====================================================================
  // 局部参数
  // =====================================================================
  localparam int BYTE_PER_BEAT = BUS_WIDTH / 8;
  localparam int LOG2_SIZE     = $clog2(SIZE);
  localparam int RAM_DEPTH     = SLOT_BLOCKS * SIZE;
  localparam int ADDR_W        = $clog2(RAM_DEPTH);
  localparam int PHYSICAL_ADDR_W = $clog2(CACHE_BLOCKS * SIZE);

  // =====================================================================
  // Each 16-bit lane contains two 8-bit banks of CACHE_BLOCKS * SIZE entries.
  // Compact S8 selects one bank with the high slot bit; wide S16 uses both.
  // =====================================================================
  // 写端口：LOAD 阶段从 AXI DMA 响应写入
  // 读端口：SEND 阶段对角化读出
  logic              ram_wr_en   [SIZE];
  logic [ADDR_W-1:0] ram_wr_addr [SIZE];
  logic signed [DATA_WIDTH-1:0] ram_wr_data [SIZE];

  logic              ram_rd_en   [SIZE];
  logic              ram_rd_en_d1 [SIZE];
  logic [ADDR_W-1:0] ram_rd_addr [SIZE];
  logic signed [DATA_WIDTH-1:0] ram_rd_data [SIZE];

  generate if (!EXTERNAL_RAM) begin : g_local_ram
    assign ram_port_wr_en = '0;
    assign ram_port_rd_en = '0;
    assign ram_port_wr_addr = '{default:'0};
    assign ram_port_wr_data = '{default:'0};
    assign ram_port_wr_mask = '{default:'0};
    assign ram_port_rd_addr = '{default:'0};
    for (genvar j = 0; j < SIZE; j++) begin : g_ram_bank
      if ((COMPACT_S8 != 0) && (DATA_WIDTH == 16)) begin : g_byte_banks
        logic [7:0] bank_data [2];
        logic read_bank_q;
        wire [7:0] original_s8 = 8'(ram_wr_data[j] - compact_offset);
        wire [7:0] selected_byte = read_bank_q ? bank_data[1] : bank_data[0];
        always_ff @(posedge clk) begin
          if (!rst_n) read_bank_q <= 1'b0;
          else if (ram_rd_en[j]) read_bank_q <= ram_rd_addr[j][PHYSICAL_ADDR_W];
        end
        for (genvar b = 0; b < 2; b++) begin : g_bank
          wire write_enable = ram_wr_en[j] &&
              (!compact_mode || ram_wr_addr[j][PHYSICAL_ADDR_W] == 1'(b));
          wire read_enable = ram_rd_en[j] &&
              (!compact_mode || ram_rd_addr[j][PHYSICAL_ADDR_W] == 1'(b));
          wire [7:0] write_byte = compact_mode ? original_s8 : ram_wr_data[j][b*8 +: 8];
          pseudo_dual_port_ram #(.DATA_WIDTH(8), .ADDR_WIDTH(PHYSICAL_ADDR_W)) u_ram (
              .clk(clk), .ena(write_enable), .enb(read_enable), .wea(1'b1),
              .addra(ram_wr_addr[j][PHYSICAL_ADDR_W-1:0]), .dia(write_byte),
              .addrb(ram_rd_addr[j][PHYSICAL_ADDR_W-1:0]), .dob(bank_data[b]));
        end
        assign ram_rd_data[j] = compact_mode
            ? DATA_WIDTH'($signed(selected_byte) + $signed(compact_offset))
            : {bank_data[1], bank_data[0]};
      end else begin : g_word_bank
        pseudo_dual_port_ram #(.DATA_WIDTH(DATA_WIDTH), .ADDR_WIDTH(ADDR_W)) u_ram (
            .clk(clk), .ena(ram_wr_en[j]), .enb(ram_rd_en[j]), .wea(1'b1),
            .addra(ram_wr_addr[j]), .dia(ram_wr_data[j]),
            .addrb(ram_rd_addr[j]), .dob(ram_rd_data[j]));
      end
    end
  end else begin : g_external_ram
    wire [RAM_WORD_ADDR_WIDTH-1:0] write_row_word =
        RAM_WORD_ADDR_WIDTH'({wr_slot, wr_row}) << (compact_mode ? 0 : 1);
    wire [RAM_WORD_ADDR_WIDTH-1:0] read_row_word =
        RAM_WORD_ADDR_WIDTH'(ram_rd_addr[0]) << (compact_mode ? 0 : 1);
    logic signed [DATA_WIDTH-1:0] row_data [SIZE];
    always_comb begin
      ram_port_wr_en = '0;
      ram_port_wr_addr[0] = write_row_word;
      ram_port_wr_addr[1] = write_row_word + RAM_WORD_ADDR_WIDTH'(1);
      ram_port_wr_data = '{default:'0};
      ram_port_wr_mask = '{default:'0};
      for (int i = 0; i < BYTE_PER_BEAT; i++) begin
        automatic int column = int'(wr_col_base) + i;
        automatic int port_index = compact_mode ? 0 : (column >> 3);
        automatic int byte_index = compact_mode ? column : ((column & 7) << 1);
        if (wr_valid[i] && column < SIZE) begin
          ram_port_wr_en[port_index] = 1'b1;
          ram_port_wr_mask[port_index][byte_index] = 1'b1;
          if (compact_mode)
            ram_port_wr_data[port_index][byte_index*8 +: 8] =
                8'(wr_data[i] - compact_offset);
          else begin
            ram_port_wr_mask[port_index][byte_index+1] = 1'b1;
            ram_port_wr_data[port_index][byte_index*8 +: 16] = wr_data[i];
          end
        end
      end
      ram_port_rd_en = {ram_rd_en[0] && !compact_mode, ram_rd_en[0]};
      ram_port_rd_addr[0] = read_row_word;
      ram_port_rd_addr[1] = read_row_word + RAM_WORD_ADDR_WIDTH'(1);
      for (int lane = 0; lane < SIZE; lane++) begin
        row_data[lane] = compact_mode ?
            DATA_WIDTH'($signed(ram_port_rd_data[0][lane*8 +: 8]) + $signed(compact_offset)) :
            ram_port_rd_data[lane/8][(lane%8)*16 +: 16];
      end
    end
    for (genvar lane = 0; lane < SIZE; lane++) begin : g_diagonal
      if (lane == 0) begin : g_first
        assign ram_rd_data[lane] = row_data[lane];
      end else begin : g_delay
        logic signed [DATA_WIDTH-1:0] values [0:lane-1];
        always_ff @(posedge clk) begin
          values[0] <= ram_rd_en_d1[0] ? row_data[lane] : '0;
          for (int stage = 1; stage < lane; stage++)
            values[stage] <= values[stage-1];
        end
        assign ram_rd_data[lane] = values[lane-1];
      end
    end
`ifndef SYNTHESIS
    initial begin
      assert (SIZE == 16 && DATA_WIDTH == 16)
        else $fatal(1, "External IA RAM requires sixteen 16-bit lanes");
    end
`endif
  end endgenerate

  // =====================================================================
  // 写逻辑：将 wr_data/wr_valid 分派到对应的 RAM bank
  // =====================================================================
  always_comb begin
    for (int j = 0; j < SIZE; j++) begin
      ram_wr_en[j]   = 1'b0;
      ram_wr_addr[j] = '0;
      ram_wr_data[j] = '0;
    end

    for (int i = 0; i < BYTE_PER_BEAT; i++) begin
      automatic int col = int'(wr_col_base) + i;
      if (wr_valid[i] && col < SIZE) begin
        ram_wr_en[col]   = 1'b1;
        ram_wr_addr[col] = ADDR_W'({wr_slot, wr_row});
        ram_wr_data[col] = wr_data[i];
      end
    end
  end

  // =====================================================================
  // L1 组对角化输出控制（col0 发射 + 多列移位管线）
  // =====================================================================
  //
  // 思路：
  //   1) 只在“初始列(col0)”做发射调度：决定本拍是否发射一行(row)
  //   2) 将 col0 的 rd_en/rd_addr 通过移位寄存器送往各列
  //      第 j 列天然获得 j 拍延迟，实现对角化
  //   3) L1 组内 slot 连续发射。compute_core/ps_buffer 将整组看成一条
  //      tall stream，de-diagonalizer 在输出侧按 tile_start 标记切分。
  //
  localparam int SLOT_W = (SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS);
  localparam int ROW_CNT_W = $clog2(SIZE + 1);
  wire [31:0] active_cache_blocks = cfg_cache_blocks == 0 ? 32'(CACHE_BLOCKS) : cfg_cache_blocks;
  wire [SLOT_W-1:0] slot_mask =
      ((COMPACT_S8 != 0) && (DATA_WIDTH == 16) && compact_mode)
      ? SLOT_W'((active_cache_blocks << 1) - 1) : SLOT_W'(active_cache_blocks - 1);


  logic l1_issue_active;                  // 仍有行需要在 col0 发射
  logic [SLOT_W-1:0] issue_slot_r;       // 当前正在发射的 slot
  logic [SLOT_W-1:0] l1_slot_end_r;
  logic [ROW_CNT_W-1:0] issue_row_idx_r; // 当前 slot 下一次发射的行号
  logic [ROW_CNT_W-1:0] issue_rows_r;    // 当前 slot 总有效行数
  logic send_is_init_r;
  logic send_calc_done_r;
  localparam int unsigned ISSUE_GAP_CYCLES = 0;
  localparam int unsigned GAP_CNT_W = (ISSUE_GAP_CYCLES < 2) ? 1 :
                                      $clog2(ISSUE_GAP_CYCLES + 1);
  logic [GAP_CNT_W-1:0] issue_gap_cnt;
  logic                 issue_gap_active;
  assign issue_gap_active = (issue_gap_cnt != '0);

  // col0 源信号（每拍最多发射 1 行）
  logic              src_rd_en;
  logic [ADDR_W-1:0] src_rd_addr;
  logic              src_tile_last;
  logic              src_tile_first;
  logic              src_l1_last;

  logic              start_issue_now;
  logic [SLOT_W-1:0] issue_slot_now;
  logic [ROW_CNT_W-1:0] issue_row_idx_now;
  logic [ROW_CNT_W-1:0] issue_rows_now;
  logic [ROW_CNT_W-1:0] issue_row_idx_inc_now;
  logic [ROW_CNT_W-1:0] slot_rows_start_now;
  logic [ROW_CNT_W-1:0] slot_rows_next_now;
  logic [SLOT_W-1:0]   l1_slot_end_now;
  logic [SLOT_W-1:0]   next_issue_slot_now;

  always_comb begin
    start_issue_now   = l1_start && !l1_issue_active;
    issue_slot_now    = start_issue_now ? l1_slot_start : issue_slot_r;
    issue_row_idx_now = start_issue_now ? '0 : issue_row_idx_r;
    slot_rows_start_now = ROW_CNT_W'(slot_rows[l1_slot_start]);
    l1_slot_end_now   = start_issue_now ? l1_slot_end : l1_slot_end_r;
    next_issue_slot_now = (SLOT_BLOCKS <= 1) ? '0 : ((issue_slot_now + SLOT_W'(1)) & slot_mask);
    slot_rows_next_now = ROW_CNT_W'(slot_rows[next_issue_slot_now]);
    issue_rows_now    = start_issue_now ? slot_rows_start_now : issue_rows_r;
    issue_row_idx_inc_now = issue_row_idx_now + ROW_CNT_W'(1);

    src_rd_en       = 1'b0;
    src_rd_addr     = '0;
    src_tile_last   = 1'b0;
    src_tile_first  = 1'b0;
    src_l1_last     = 1'b0;

    if (start_issue_now || (l1_issue_active && !issue_gap_active)) begin
      src_rd_en     = 1'b1;
      src_rd_addr   = ADDR_W'({issue_slot_now, LOG2_SIZE'(issue_row_idx_now)});
      src_tile_last = (issue_row_idx_inc_now == issue_rows_now);
      src_tile_first= (issue_row_idx_now == '0);
      src_l1_last   = src_tile_last && (issue_slot_now == l1_slot_end_now);
    end
  end

  // 各列移位管线
  logic              rd_en_pipe      [SIZE];
  logic [ADDR_W-1:0] rd_addr_pipe    [SIZE];
  logic              tile_last_pipe  [SIZE];
  logic              l1_last_pipe    [SIZE];

  // 下一 slot（自然回绕）
  logic [SLOT_W-1:0] next_issue_slot;
  assign next_issue_slot = (SLOT_BLOCKS <= 1) ? '0 : ((issue_slot_r + SLOT_W'(1)) & slot_mask);

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      l1_issue_active <= 1'b0;
      issue_slot_r    <= '0;
      l1_slot_end_r   <= '0;
      issue_row_idx_r <= '0;
      issue_rows_r    <= '0;
      send_is_init_r  <= 1'b0;
      send_calc_done_r<= 1'b0;
      issue_gap_cnt   <= '0;
      tile_done       <= 1'b0;
      l1_done         <= 1'b0;
      for (int j = 0; j < SIZE; j++) begin
        rd_en_pipe[j]     <= 1'b0;
        rd_addr_pipe[j]   <= '0;
        tile_last_pipe[j] <= 1'b0;
        l1_last_pipe[j]   <= 1'b0;
      end
    end else begin
      tile_done     <= 1'b0;
      l1_done       <= 1'b0;

      if (issue_gap_cnt != '0) begin
        issue_gap_cnt <= issue_gap_cnt - 1'b1;
      end

      // 启动新的 L1 组发射
      if (l1_start && !l1_issue_active) begin
        l1_issue_active <= 1'b1;
        issue_slot_r    <= l1_slot_start;
        l1_slot_end_r   <= l1_slot_end;
        issue_rows_r    <= slot_rows_start_now;
        send_is_init_r  <= l1_is_init;
        send_calc_done_r<= l1_calc_done;

        if (start_issue_now) begin
          if (slot_rows_start_now == ROW_CNT_W'(1)) begin
            if (l1_slot_start == l1_slot_end) begin
              l1_issue_active <= 1'b0;
            end else begin
              issue_slot_r    <= next_issue_slot_now;
              issue_row_idx_r <= '0;
              issue_rows_r    <= slot_rows_next_now;
              issue_gap_cnt   <= GAP_CNT_W'(ISSUE_GAP_CYCLES);
            end
          end else begin
            issue_row_idx_r <= ROW_CNT_W'(1);
          end
        end else begin
          issue_row_idx_r <= '0;
        end
      end

      // col0 发射调度
      if (l1_issue_active && !issue_gap_active) begin
        if ((issue_row_idx_r + ROW_CNT_W'(1)) == issue_rows_r) begin
          // 当前 tile 最后一行在 col0 发射
          if (issue_slot_r == l1_slot_end_r) begin
            // L1 最后一个 tile 的最后一行
            l1_issue_active <= 1'b0;
          end else begin
            // 切到下一个 tile（下一拍若 valid 则立刻发射）
            issue_slot_r    <= next_issue_slot;
            issue_row_idx_r <= '0;
            issue_rows_r    <= ROW_CNT_W'(slot_rows[next_issue_slot]);
            issue_gap_cnt   <= GAP_CNT_W'(ISSUE_GAP_CYCLES);
          end
        end else begin
          issue_row_idx_r <= issue_row_idx_r + 1;
        end
      end

      // 移位管线更新
      rd_en_pipe[0]     <= src_rd_en;
      rd_addr_pipe[0]   <= src_rd_addr;
      tile_last_pipe[0] <= src_tile_last;
      l1_last_pipe[0]   <= src_l1_last;
      for (int j = 1; j < SIZE; j++) begin
        rd_en_pipe[j]     <= rd_en_pipe[j-1];
        rd_addr_pipe[j]   <= rd_addr_pipe[j-1];
        tile_last_pipe[j] <= tile_last_pipe[j-1];
        l1_last_pipe[j]   <= l1_last_pipe[j-1];
      end

      // tile/l1 完成脉冲：最后一行 token 到达最后一列时拉高
      if (rd_en_pipe[SIZE-1] && tile_last_pipe[SIZE-1])
        tile_done <= 1'b1;
      if (rd_en_pipe[SIZE-1] && l1_last_pipe[SIZE-1])
        l1_done <= 1'b1;
    end
  end

  // =====================================================================
  // RAM 读地址生成（由移位管线直接驱动）
  // =====================================================================
  always_comb begin
    for (int j = 0; j < SIZE; j++) begin
      ram_rd_en[j]   = rd_en_pipe[j];
      ram_rd_addr[j] = rd_addr_pipe[j];
    end
  end

  // =====================================================================
  // 输出数据：RAM 读出数据直接作为 ia_out（RAM 寄存器输出，延迟 1 拍）
  // =====================================================================
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      for (int j = 0; j < SIZE; j++)
        ram_rd_en_d1[j] <= 1'b0;
	    end else begin
	      for (int j = 0; j < SIZE; j++)
	        ram_rd_en_d1[j] <= ram_rd_en[j];
	    end
	  end

  // ia_out: 对角化时序保持不变；无效期间 gate 为 0
  always_comb begin
    for (int j = 0; j < SIZE; j++)
      ia_out[j] = ram_rd_en_d1[j] ? ram_rd_data[j] : '0;
  end

  // ia_row_valid: 最大延迟列（SIZE-1）的 rd_en
	  assign ia_row_valid = ram_rd_en_d1[SIZE-1];
	  // Early burst start: col0 issue begins here for every tile in the L1
	  // stream.  This is intentionally ahead of ia_row_valid so ps_buffer replay
	  // can absorb the cache/systolic delay even when adjacent slots are
	  // emitted without a valid bubble.
	  assign ia_tile_start = src_rd_en & src_tile_first;

  // =====================================================================
  // ia_is_init_data / ia_calc_done
  // =====================================================================
  // send_is_init_r / send_calc_done_r 在整个 L1 组期间不变，无需额外延迟链
  assign ia_is_init_data = ram_rd_en_d1[SIZE-1] & send_is_init_r;
  assign ia_calc_done    = ram_rd_en_d1[SIZE-1] & send_calc_done_r;

endmodule
