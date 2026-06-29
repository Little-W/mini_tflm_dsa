/*
 * tile_loader — ICB 总线读取引擎
 * ============================================================
 * 功能：
 *   接收一次 tile 加载命令（base_addr, rows, burst_len, slot_id），
 *   通过 ICB 总线逐行读取数据，解包后写入 cache_mgr 的 RAM bank。
 *   完成后产生 tile_done 脉冲。
 *
 * 接口约定：
 *   - start 为单拍脉冲启动加载（仅在 idle 时接受）
 *   - ICB cmd/rsp 直连外部 unalign_bridge
 *   - 写端口直连 cache_mgr
 */

module tile_loader #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 4
) (
    input  logic clk,
    input  logic rst_n,

    // ---- 加载命令 ----
    input  logic                        start,          // 单拍脉冲
    input  logic [REG_WIDTH-1:0]        tile_base_addr, // tile 首字节地址
    input  logic [REG_WIDTH-1:0]        row_stride,     // 行间步长（字节）
    input  logic [REG_WIDTH-1:0]        rows_to_read,   // 本 tile 需要读的行数
    input  logic [3:0]                  burst_len_m1,   // ICB burst 长度 - 1
    input  logic [$clog2(CACHE_BLOCKS)-1:0] slot_id,   // 写入的 cache slot
    input  logic                        use_16bits,
    input  logic signed [REG_WIDTH-1:0] lhs_zp,        // 零点偏移
    output logic                        busy,           // 正在加载
    output logic                        tile_done,      // 加载完成脉冲

    // ---- ICB 主接口 ----
    output logic                        icb_cmd_valid,
    input  logic                        icb_cmd_ready,
    output logic                        icb_cmd_read,
    output logic [REG_WIDTH-1:0]        icb_cmd_addr,
    output logic [3:0]                  icb_cmd_len,
    input  logic                        icb_rsp_valid,
    output logic                        icb_rsp_ready,
    input  logic [BUS_WIDTH-1:0]        icb_rsp_rdata,
    input  logic                        icb_rsp_err,

    // ---- 写入 cache_mgr ----
    output logic [$clog2(CACHE_BLOCKS)-1:0]    wr_slot,
    output logic [$clog2(SIZE)-1:0]            wr_row,
    output logic [$clog2(SIZE)-1:0]            wr_col_base,
    output logic signed [DATA_WIDTH-1:0]       wr_data  [BUS_WIDTH/8],
    output logic                               wr_valid [BUS_WIDTH/8],
    output logic                               wr_use_16bits
);

  // =====================================================================
  // 局部参数
  // =====================================================================
  localparam int BYTE_PER_BEAT      = BUS_WIDTH / 8;
  localparam int LOG2_SIZE          = $clog2(SIZE);
  localparam int ELEM_PER_BEAT_S8   = BYTE_PER_BEAT;
  localparam int ELEM_PER_BEAT_S16  = BYTE_PER_BEAT >> 1;

  // =====================================================================
  // 内部信号
  // =====================================================================
  wire cmd_hs = icb_cmd_valid && icb_cmd_ready;
  wire rsp_hs = icb_rsp_valid && icb_rsp_ready;

  // 锁存命令参数
  logic [REG_WIDTH-1:0]                cfg_base_addr;
  logic [REG_WIDTH-1:0]                cfg_row_stride;
  logic [REG_WIDTH-1:0]                cfg_rows;
  logic [3:0]                          cfg_burst_len_m1;
  logic [$clog2(CACHE_BLOCKS)-1:0]     cfg_slot;
  logic                                cfg_use_16bits;
  logic signed [REG_WIDTH-1:0]         cfg_zp;

  // 行地址追踪
  logic [REG_WIDTH-1:0] current_row_addr;
  logic [REG_WIDTH-1:0] cmd_row_cnt;     // 已发出命令的行数

  // 响应追踪
  logic [REG_WIDTH-1:0] rsp_row_cnt;
  logic [REG_WIDTH-1:0] rsp_beat_cnt;

  // 数据解包延迟寄存器（打一拍，降低组合逻辑延时）
  // 在 ICB 响应握手时锁存总线数据与地址信息，下一拍再进行 s8/s16 解包与零点补偿，
  // 分离了关键路径，使数据通路的组合延时从"握手+解包"改为单纯的"寄存器输出+解包"
  logic [BUS_WIDTH-1:0]        rsp_data_r;
  logic [REG_WIDTH-1:0]        rsp_row_r;
  logic [$clog2(SIZE)-1:0]     rsp_col_base_r;
  logic                        rsp_valid_r;  // 标志当前有有效数据需要解包

  // =====================================================================
  // 主控 FSM
  // =====================================================================
  logic active;  // 正在执行加载

  assign busy = active;
  assign icb_cmd_read = 1'b1;
  assign icb_cmd_len  = cfg_burst_len_m1;
  assign wr_use_16bits = cfg_use_16bits;
  assign wr_slot       = cfg_slot;

  // tile_done 脉冲：最后一行的最后一个 beat 被接收
  wire last_rsp_beat = rsp_hs
                     && (rsp_beat_cnt == {28'd0, cfg_burst_len_m1} )
                     && (rsp_row_cnt  == cfg_rows - 1);
  
  // 由于数据解包延迟一拍，tile_done 也需要延迟以与最后一拍数据写入同步
  logic tile_done_r;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tile_done_r <= 1'b0;
    end else begin
      tile_done_r <= active && last_rsp_beat;
    end
  end
  assign tile_done = tile_done_r;

  // =====================================================================
  // 参数锁存
  // =====================================================================
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      active           <= 1'b0;
      cfg_base_addr    <= '0;
      cfg_row_stride   <= '0;
      cfg_rows         <= '0;
      cfg_burst_len_m1 <= '0;
      cfg_slot         <= '0;
      cfg_use_16bits   <= 1'b0;
      cfg_zp           <= '0;
    end else if (start && !active) begin
      active           <= 1'b1;
      cfg_base_addr    <= tile_base_addr;
      cfg_row_stride   <= row_stride;
      cfg_rows         <= rows_to_read;
      cfg_burst_len_m1 <= burst_len_m1;
      cfg_slot         <= slot_id;
      cfg_use_16bits   <= use_16bits;
      cfg_zp           <= lhs_zp;
    end else if (tile_done_r) begin
      // tile_done_r 拉高时清除 active 标志（考虑到数据解包延迟）
      active <= 1'b0;
    end
  end

  // =====================================================================
  // ICB 命令发送：逐行 burst
  // =====================================================================
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      icb_cmd_valid    <= 1'b0;
      icb_cmd_addr     <= '0;
      current_row_addr <= '0;
      cmd_row_cnt      <= '0;
    end else if (start && !active) begin
      // 启动时立即发出第一行命令
      icb_cmd_valid    <= 1'b1;
      icb_cmd_addr     <= tile_base_addr;
      current_row_addr <= tile_base_addr + row_stride;
      cmd_row_cnt      <= 1;
    end else if (active) begin
      if (tile_done) begin
        icb_cmd_valid    <= 1'b0;
        cmd_row_cnt      <= '0;
      end else if (cmd_row_cnt < cfg_rows) begin
        if (!icb_cmd_valid || cmd_hs) begin
          icb_cmd_valid    <= 1'b1;
          icb_cmd_addr     <= current_row_addr;
          current_row_addr <= current_row_addr + cfg_row_stride;
          cmd_row_cnt      <= cmd_row_cnt + 1;
        end
      end else begin
        // 所有行命令已发出
        if (cmd_hs || !icb_cmd_valid) begin
          icb_cmd_valid <= 1'b0;
        end
      end
    end else begin
      icb_cmd_valid <= 1'b0;
    end
  end

  // =====================================================================
  // ICB 响应接收与数据锁存
  // =====================================================================
  logic [$clog2(SIZE)-1:0] rsp_col_base_comb;
  assign rsp_col_base_comb = cfg_use_16bits
                           ? rsp_beat_cnt[$clog2(SIZE)-1:0] << $clog2(ELEM_PER_BEAT_S16)
                           : rsp_beat_cnt[$clog2(SIZE)-1:0] << $clog2(ELEM_PER_BEAT_S8);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rsp_row_cnt   <= '0;
      rsp_beat_cnt  <= '0;
      icb_rsp_ready <= 1'b0;
      rsp_valid_r   <= 1'b0;
      rsp_data_r    <= '0;
      rsp_row_r     <= '0;
      rsp_col_base_r <= '0;
    end else if (start && !active) begin
      rsp_row_cnt   <= '0;
      rsp_beat_cnt  <= '0;
      icb_rsp_ready <= 1'b1;
      rsp_valid_r   <= 1'b0;
    end else if (active) begin
      icb_rsp_ready <= 1'b1;
      if (rsp_hs) begin
        // 响应握手时立即锁存数据，用于下一拍的解包
        rsp_data_r    <= icb_rsp_rdata;
        rsp_row_r     <= rsp_row_cnt[$clog2(SIZE)-1:0];
        rsp_col_base_r <= rsp_col_base_comb;
        rsp_valid_r   <= 1'b1;  // 标志下一拍有有效数据
        
        if (rsp_beat_cnt == {28'd0, cfg_burst_len_m1}) begin
          rsp_beat_cnt <= '0;
          if (rsp_row_cnt == cfg_rows - 1)
            rsp_row_cnt <= '0;
          else
            rsp_row_cnt <= rsp_row_cnt + 1;
        end else begin
          rsp_beat_cnt <= rsp_beat_cnt + 1;
        end
      end else begin
        rsp_valid_r <= 1'b0;
      end
    end else begin
      icb_rsp_ready <= 1'b0;
      rsp_row_cnt   <= '0;
      rsp_beat_cnt  <= '0;
      rsp_valid_r   <= 1'b0;
    end
  end

  // =====================================================================
  // 数据解包 → cache_mgr 写端口（基于锁存的数据，延时一拍）
  // =====================================================================
  assign wr_row      = rsp_row_r;
  assign wr_col_base = rsp_col_base_r;

  always_comb begin
    for (int i = 0; i < BYTE_PER_BEAT; i++) begin
      wr_data[i]  = '0;
      wr_valid[i] = 1'b0;
    end

    // 基于上一拍锁存的数据进行解包，减少组合逻辑延时
    if (rsp_valid_r) begin
      if (cfg_use_16bits) begin
        for (int i = 0; i < ELEM_PER_BEAT_S16; i++) begin
          if (rsp_col_base_r + i < SIZE) begin
            wr_data[i]  = DATA_WIDTH'($signed(rsp_data_r[i*16 +: 16]) + cfg_zp[15:0]);
            wr_valid[i] = 1'b1;
          end
        end
      end else begin
        for (int i = 0; i < ELEM_PER_BEAT_S8; i++) begin
          if (rsp_col_base_r + i < SIZE) begin
            wr_data[i]  = DATA_WIDTH'($signed({{8{rsp_data_r[i*8+7]}}, rsp_data_r[i*8 +: 8]}) + cfg_zp[15:0]);
            wr_valid[i] = 1'b1;
          end
        end
      end
    end
  end

endmodule
