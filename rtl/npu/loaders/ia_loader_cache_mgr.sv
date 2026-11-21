/* IA cache with synchronous, complete-row reads for the DiP array.
 * All lanes use the same slot and row address. A group streams its active
 * rows consecutively, including a partial final tile. The early tile marker
 * starts PS replay two cycles before the corresponding array input row.
 */

module ia_loader_cache_mgr #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned DMA_LANES    = BUS_WIDTH / 8,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 4,
    parameter int unsigned COMPACT_S8 = 1,
    parameter bit EXTERNAL_RAM = 1'b0,
    parameter int unsigned RAM_WORD_ADDR_WIDTH = 10,
    parameter int unsigned p_compact_offset_width = DATA_WIDTH,
    // 生产 DMA 的 S8 起点按八列排列，S16 每次最多提供四个有效通道。
    parameter bit p_dma_source_layout = 1'b0,
    // 在写命令寄存级提前选择第二个物理存储块的数据。
    parameter bit p_shared_write_stage = 1'b0,
    localparam int unsigned SLOT_BLOCKS =
        ((COMPACT_S8 != 0) && (DATA_WIDTH == 16)) ? 2 * CACHE_BLOCKS : CACHE_BLOCKS
) (
    input  logic clk,
    input  logic rst_n,
    input  logic compact_mode = 1'b0,
    input  logic signed [DATA_WIDTH-1:0] compact_offset = '0,
    input  logic [31:0] cfg_cache_blocks = 32'd0,
    input  logic [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] slot_base = '0,

    output logic [1:0] ram_port_wr_en,
    output logic [RAM_WORD_ADDR_WIDTH-1:0] ram_port_wr_addr [0:1],
    output logic [127:0] ram_port_wr_data [0:1],
    output logic [15:0] ram_port_wr_mask [0:1],
    output logic [127:0] ram_shared_wr_data,
    output logic [1:0] ram_port_rd_en,
    output logic [RAM_WORD_ADDR_WIDTH-1:0] ram_port_rd_addr [0:1],
    input  logic [127:0] ram_port_rd_data [0:1] = '{default:'0},

    // ---- 写入端 ----
    input  logic [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0]      wr_slot,
    input  logic [$clog2(SIZE)-1:0]              wr_row,
    input  logic [$clog2(SIZE)-1:0]              wr_col_base,
    input  logic signed [DATA_WIDTH-1:0]         wr_data  [DMA_LANES],
    input  logic                                 wr_valid [DMA_LANES],
    input  logic                                 wr_use_16bits,

    // ---- L1 group row-stream control ----
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

    // ---- Complete row and associated metadata ----
    output logic signed [DATA_WIDTH-1:0]         ia_out          [SIZE],
    output logic                                 ia_row_valid,
    output logic                                 ia_is_init_data,
    output logic                                 ia_calc_done
);

  // =====================================================================
  // 局部参数
  // =====================================================================
  localparam int LOG2_SIZE     = $clog2(SIZE);
  localparam int RAM_DEPTH     = SLOT_BLOCKS * SIZE;
  localparam int ADDR_W        = $clog2(RAM_DEPTH);
  localparam int PHYSICAL_ADDR_W = $clog2(CACHE_BLOCKS * SIZE);

  // =====================================================================
  // Each 16-bit lane contains two 8-bit banks of CACHE_BLOCKS * SIZE entries.
  // Compact S8 selects one bank with the high slot bit; wide S16 uses both.
  // =====================================================================
  // 写端口：LOAD 阶段从 AXI DMA 响应写入
  // Read every lane of the selected row in the same cycle.
  logic              ram_wr_en   [SIZE];
  logic [ADDR_W-1:0] ram_wr_addr [SIZE];
  logic signed [DATA_WIDTH-1:0] ram_wr_data [SIZE];

  logic              ram_rd_en   [SIZE];
  logic              ram_rd_en_d1 [SIZE];
  logic [ADDR_W-1:0] ram_rd_addr [SIZE];
  logic signed [DATA_WIDTH-1:0] ram_rd_data [SIZE];
  logic [7:0] compact_read_byte [SIZE];
  logic signed [DATA_WIDTH-1:0] compact_read_data [SIZE];

  // 偏移有效位宽由调用者给出，默认保留完整输入位宽。
  // 有符号字节与偏移先在足够的结果位宽中相加，再扩展为阵列数据位宽。
  localparam int unsigned p_restore_width =
      ((p_compact_offset_width > 8) ? p_compact_offset_width : 8) + 1;
  if (p_restore_width <= 12) begin : g_compact_read_packed
    logic restore_i_zero, restore_i_one;
    assign restore_i_zero = 1'b0;
    assign restore_i_one = 1'b1;
    for (genvar group_index = 0; group_index < (SIZE+3)/4; group_index++) begin : g_group
      logic signed [47:0] packed_lhs, packed_rhs, packed_sum;

      // 四个字节独立恢复有符号值，每个 12 位通道保留完整和及符号。
      for (genvar group_lane = 0; group_lane < 4; group_lane++) begin : g_lane
        localparam int p_lane = 4 * group_index + group_lane;
        if (p_lane < SIZE) begin : g_data
          assign packed_lhs[group_lane*12 +: 12] = 12'($signed(compact_read_byte[p_lane]));
          assign packed_rhs[group_lane*12 +: 12] =
              12'($signed(compact_offset[p_compact_offset_width-1:0]));
          assign compact_read_data[p_lane] =
              DATA_WIDTH'($signed(packed_sum[group_lane*12 +: p_restore_width]));
        end else begin : g_padding
          assign packed_lhs[group_lane*12 +: 12] = '0;
          assign packed_rhs[group_lane*12 +: 12] = '0;
        end
      end
      select_add #(.p_width(48), .p_split_12bit(1'b1)) u_restore (
        .i_lhs(packed_lhs), .i_rhs0(packed_rhs), .i_rhs1(packed_rhs),
        .i_rhs_select(restore_i_zero), .i_add_enable(restore_i_one), .o_sum(packed_sum)
      );
    end
  end else begin : g_compact_read_wide
    for (genvar lane = 0; lane < SIZE; lane++) begin : g_lane
      logic signed [p_restore_width:0] byte_extended, offset_extended;
      logic signed [p_restore_width-1:0] restored_sum;
      logic unused_restore_carry;

      assign byte_extended = (p_restore_width + 1)'($signed(compact_read_byte[lane]));
      assign offset_extended =
          (p_restore_width + 1)'($signed(compact_offset[p_compact_offset_width-1:0]));
      assign {unused_restore_carry, restored_sum} = byte_extended + offset_extended;
      assign compact_read_data[lane] = DATA_WIDTH'($signed(restored_sum));
    end
  end

  generate if (!EXTERNAL_RAM) begin : g_local_ram
    assign ram_shared_wr_data = '0;
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
        assign compact_read_byte[j] = selected_byte;
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
            ? compact_read_data[j]
            : {bank_data[1], bank_data[0]};
      end else begin : g_word_bank
        assign compact_read_byte[j] = '0;
        pseudo_dual_port_ram #(.DATA_WIDTH(DATA_WIDTH), .ADDR_WIDTH(ADDR_W)) u_ram (
            .clk(clk), .ena(ram_wr_en[j]), .enb(ram_rd_en[j]), .wea(1'b1),
            .addra(ram_wr_addr[j]), .dia(ram_wr_data[j]),
            .addrb(ram_rd_addr[j]), .dob(ram_rd_data[j]));
      end
    end
  end else begin : g_external_ram
    localparam int p_compact_lanes = (DMA_LANES < SIZE) ? DMA_LANES : SIZE;
    logic [1:0] write_en;
    logic [RAM_WORD_ADDR_WIDTH-1:0] write_addr [0:1];
    logic [127:0] write_data [0:1];
    logic [15:0] write_mask [0:1];
    logic [7:0] compact_empty_byte;
    logic [SIZE*8-1:0] compact_source_bytes, compact_shifted_bytes;
    logic [7:0] compact_input_byte [p_compact_lanes];
    logic [7:0] compact_write_byte [SIZE];

    // 紧凑字节先完成偏移运算，再按列位置排列。
    // 排列后的写掩码选择数据字节或零数据对应的紧凑字节。
    assign compact_empty_byte = 8'(0 - compact_offset);
    for (genvar lane = 0; lane < p_compact_lanes; lane++) begin : g_compact_add
      // 字节模加法保留低八位结果，由综合工具直接推断短进位结构。
      assign compact_input_byte[lane] = 8'(wr_data[lane][7:0] + compact_empty_byte);
    end
    for (genvar lane = 0; lane < SIZE; lane++) begin : g_compact_write
      if (lane < DMA_LANES) begin : g_source
        assign compact_source_bytes[lane*8 +: 8] = compact_input_byte[lane];
      end else begin : g_unused_source
        assign compact_source_bytes[lane*8 +: 8] = 8'd0;
      end
      assign compact_write_byte[lane] = ram_wr_en[lane] ?
          compact_shifted_bytes[lane*8 +: 8] : compact_empty_byte;
    end
    if (p_dma_source_layout && SIZE == 16 && DATA_WIDTH == 16 && BUS_WIDTH == 64 && DMA_LANES == 8) begin : g_dma_compact_layout
      logic [87:0] compact_group_low, compact_group_data;

      // S16 的四个输入字节先在八列范围内移动，最高位置为第十列。
      // S8 的后四个字节占据第四至第七列，再统一选择整行的前后八列。
      assign compact_group_low =
          88'(compact_source_bytes[31:0]) << (int'(wr_col_base[2:0]) * 8);
      assign compact_group_data[31:0] = compact_group_low[31:0];
      assign compact_group_data[63:32] = (|wr_col_base[2:0]) ?
          compact_group_low[63:32] : compact_source_bytes[63:32];
      assign compact_group_data[87:64] = compact_group_low[87:64];
      assign compact_shifted_bytes =
          128'(compact_group_data) << (int'(wr_col_base[3]) * 64);
    end else begin : g_general_compact_layout
      assign compact_shifted_bytes = compact_source_bytes << (int'(wr_col_base) * 8);
    end
    // 写命令在同一时钟沿保存地址、数据与掩码，未写入的端口保持原命令。
    always_ff @(posedge clk) begin
      if(!rst_n) ram_port_wr_en<='0;
      else ram_port_wr_en<=write_en;
      for(int port_index=0;port_index<2;port_index++) begin
        if(write_en[port_index]) begin
          ram_port_wr_addr[port_index]<=write_addr[port_index];
          ram_port_wr_data[port_index]<=write_data[port_index];
          ram_port_wr_mask[port_index]<=write_mask[port_index];
        end
      end
    end

    if (p_shared_write_stage && SIZE == 16 && DATA_WIDTH == 16) begin : g_shared_write_stage
      (* keep = 1 *) logic [127:0] compact_shared_data;
      logic [127:0] wide_shared_data;
      logic [127:0] selected_shared_data;

      // 紧凑字节排列与宽数据端口选择分别完成，存储格式只选择最终结果。
      for (genvar lane = 0; lane < 8; lane++) begin : g_data
        assign compact_shared_data[lane*16 +: 16] =
            {compact_write_byte[lane*2+1], compact_write_byte[lane*2]};
        assign wide_shared_data[lane*16 +: 16] = write_en[1] ?
            ram_wr_data[lane+8] : ram_wr_data[lane];
      end
      always_comb begin
        case (compact_mode)
          1'b0: selected_shared_data = wide_shared_data;
          1'b1: selected_shared_data = compact_shared_data;
          default: selected_shared_data = write_en[1] ? write_data[1] : write_data[0];
        endcase
      end
      always_ff @(posedge clk) begin
        if (|write_en) begin
          ram_shared_wr_data <= selected_shared_data;
        end
      end
    end else begin : g_general_write_stage
      assign ram_shared_wr_data = '0;
    end

    wire [RAM_WORD_ADDR_WIDTH-1:0] write_row_word =
        RAM_WORD_ADDR_WIDTH'({wr_slot, wr_row}) << (compact_mode ? 0 : 1);
    wire [RAM_WORD_ADDR_WIDTH-1:0] read_row_word =
        RAM_WORD_ADDR_WIDTH'(ram_rd_addr[0]) << (compact_mode ? 0 : 1);
    logic signed [DATA_WIDTH-1:0] row_data [SIZE];
    assign write_addr[0] = write_row_word;
    assign write_addr[1] = write_row_word + RAM_WORD_ADDR_WIDTH'(1);
    assign ram_port_rd_en = {ram_rd_en[0] && !compact_mode, ram_rd_en[0]};
    assign ram_port_rd_addr[0] = read_row_word;
    assign ram_port_rd_addr[1] = read_row_word + RAM_WORD_ADDR_WIDTH'(1);
    // 常量列区间提前判断输入通道属于哪个端口，写使能不等待完整掩码排列。
    if (SIZE == 16 && DATA_WIDTH == 16) begin : g_write_port_range
      logic [SIZE-1:0] write_first_half, write_second_half, write_compact_row;

      for (genvar lane = 0; lane < SIZE; lane++) begin : g_lane
        if (lane < DMA_LANES) begin : g_input
          assign write_compact_row[lane] = wr_valid[lane] && wr_col_base <= LOG2_SIZE'(SIZE-1-lane);
          if (lane < 8) begin : g_first_source
            assign write_first_half[lane] = wr_valid[lane] && wr_col_base <= LOG2_SIZE'(7-lane);
            assign write_second_half[lane] = wr_valid[lane] &&
                wr_col_base >= LOG2_SIZE'(8-lane) && wr_col_base <= LOG2_SIZE'(15-lane);
          end else begin : g_second_source
            assign write_first_half[lane] = 1'b0;
            assign write_second_half[lane] = wr_valid[lane] && wr_col_base <= LOG2_SIZE'(15-lane);
          end
        end else begin : g_unused_source
          assign write_first_half[lane] = 1'b0;
          assign write_second_half[lane] = 1'b0;
          assign write_compact_row[lane] = 1'b0;
        end
      end
      assign write_en[0] = compact_mode ? (|write_compact_row) : (|write_first_half);
      assign write_en[1] = !compact_mode && (|write_second_half);
    end else begin : g_write_port_mask
      assign write_en[0] = |write_mask[0];
      assign write_en[1] = |write_mask[1];
    end
    for (genvar lane = 0; lane < SIZE; lane++) begin : g_write_lane
      if (lane < 8) begin : g_first_half
        assign write_data[0][lane*16 +: 16] = compact_mode ?
            {compact_write_byte[lane*2+1], compact_write_byte[lane*2]} : ram_wr_data[lane];
        assign write_mask[0][lane*2 +: 2] = compact_mode ?
            {ram_wr_en[lane*2+1], ram_wr_en[lane*2]} : {2{ram_wr_en[lane]}};
      end else begin : g_second_half
        assign write_data[1][(lane-8)*16 +: 16] = ram_wr_data[lane];
        assign write_mask[1][(lane-8)*2 +: 2] = {2{ram_wr_en[lane] && !compact_mode}};
      end
      assign compact_read_byte[lane] = ram_port_rd_data[0][lane*8 +: 8];
      assign row_data[lane] = compact_mode ? compact_read_data[lane] :
          ram_port_rd_data[lane/8][(lane%8)*16 +: 16];
    end
    for (genvar lane = 0; lane < SIZE; lane++) begin : g_row
      assign ram_rd_data[lane] = row_data[lane];
    end
`ifdef NPU_SIM_ASSERT
    initial begin
      assert (SIZE == 16 && DATA_WIDTH == 16)
        else $fatal(1, "External IA RAM requires sixteen 16-bit lanes");
    end
`endif
  end endgenerate

  // =====================================================================
  // 写逻辑：将 wr_data/wr_valid 分派到对应的 RAM bank
  // =====================================================================
  localparam int p_row_data_width = SIZE * DATA_WIDTH;
  logic [p_row_data_width-1:0] write_source_data;
  logic [p_row_data_width-1:0] write_shifted_data;
  logic [SIZE-1:0] write_source_mask;
  logic [SIZE-1:0] write_shifted_mask;

  // 一次列偏移同时排列整组数据与有效位，超出当前行的数据自然移出。
  for (genvar lane = 0; lane < SIZE; lane++) begin : g_write_source
    if (lane < DMA_LANES) begin : g_input
      assign write_source_data[lane*DATA_WIDTH+:DATA_WIDTH] = wr_valid[lane] ? wr_data[lane] : '0;
      assign write_source_mask[lane] = wr_valid[lane];
    end else begin : g_padding
      assign write_source_data[lane*DATA_WIDTH+:DATA_WIDTH] = '0;
      assign write_source_mask[lane] = 1'b0;
    end
  end
  if (p_dma_source_layout && SIZE == 16 && DATA_WIDTH == 16 && BUS_WIDTH == 64 && DMA_LANES == 8) begin : g_dma_write_layout
    logic [175:0] write_group_low, write_group_data;

    // S16 只移动前四个有效通道；S8 的后四个通道直接放入同组高半部。
    // 局部列偏移与跨八列偏移分别处理，越过第十五列的数据自然移出。
    assign write_group_low =
        176'(write_source_data[63:0]) << (int'(wr_col_base[2:0]) * 16);
    assign write_group_data[63:0] = write_group_low[63:0];
    assign write_group_data[127:64] = (|wr_col_base[2:0]) ?
        write_group_low[127:64] : write_source_data[127:64];
    assign write_group_data[175:128] = write_group_low[175:128];
    assign write_shifted_data =
        256'(write_group_data) << (int'(wr_col_base[3]) * 128);
  end else begin : g_general_write_layout
    assign write_shifted_data = write_source_data << (int'(wr_col_base) * DATA_WIDTH);
  end
  assign write_shifted_mask = write_source_mask << wr_col_base;
  for (genvar col = 0; col < SIZE; col++) begin : g_write_select
    assign ram_wr_en[col] = write_shifted_mask[col];
    assign ram_wr_addr[col] = ADDR_W'({wr_slot, wr_row});
    assign ram_wr_data[col] = write_shifted_data[col*DATA_WIDTH+:DATA_WIDTH];
  end

  // =====================================================================
  // Consecutive complete rows across all slots of one L1 group.
  // =====================================================================
  //
  // The common read address is registered once before the synchronous RAM.
  //
  localparam int SLOT_W = (SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS);
  localparam int ROW_CNT_W = $clog2(SIZE + 1);
  (* ram_style = "block" *) logic [ROW_CNT_W-1:0] slot_written_cols [SLOT_BLOCKS];
  logic [ROW_CNT_W-1:0] write_extent, read_extent_q;
  logic any_lane_write;
  logic [SIZE-1:0] write_last_column;
  assign any_lane_write = |write_shifted_mask;
  // 有效位已经排列到物理列，最高有效列直接编码本次写入范围。
  for (genvar col = 0; col < SIZE; col++) begin : g_write_extent_last
    if (col + 1 < SIZE) begin : g_has_later_column
      assign write_last_column[col] = write_shifted_mask[col] && !(|write_shifted_mask[SIZE-1:col+1]);
    end else begin : g_final_column
      assign write_last_column[col] = write_shifted_mask[col];
    end
  end
  for (genvar bit_index = 0; bit_index < ROW_CNT_W; bit_index++) begin : g_write_extent_bit
    logic [SIZE-1:0] column_matches;

    for (genvar col = 0; col < SIZE; col++) begin : g_column
      assign column_matches[col] = write_last_column[col] && (((col + 1) >> bit_index) & 1) != 0;
    end
    assign write_extent[bit_index] = |column_matches;
  end
  always_ff @(posedge clk) begin
    if (rst_n && any_lane_write && wr_row=='0)
      slot_written_cols[wr_slot]<=write_extent;
    if (!rst_n) read_extent_q<='0;
    else if (ram_rd_en[0])
      read_extent_q<=slot_written_cols[SLOT_W'(ram_rd_addr[0] >> LOG2_SIZE)];
  end
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
    slot_rows_start_now = ROW_CNT_W'(slot_rows[(l1_slot_start - slot_base) & slot_mask]);
    l1_slot_end_now   = start_issue_now ? l1_slot_end : l1_slot_end_r;
    next_issue_slot_now = (SLOT_BLOCKS <= 1) ? '0 : ((issue_slot_now + SLOT_W'(1)) & slot_mask);
    slot_rows_next_now = ROW_CNT_W'(slot_rows[(next_issue_slot_now - slot_base) & slot_mask]);
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

  // Registered read controls are identical for every lane.
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
            // 发射期间 next_issue_slot_now 与 next_issue_slot 相同，复用行数选择结果。
            issue_rows_r    <= slot_rows_next_now;
            issue_gap_cnt   <= GAP_CNT_W'(ISSUE_GAP_CYCLES);
          end
        end else begin
          issue_row_idx_r <= issue_row_idx_r + 1;
        end
      end

      for (int j = 0; j < SIZE; j++) begin
        rd_en_pipe[j]     <= src_rd_en;
        rd_addr_pipe[j]   <= src_rd_addr;
        tile_last_pipe[j] <= src_tile_last;
        l1_last_pipe[j]   <= src_l1_last;
      end

      // Completion accompanies the last synchronous RAM output row.
      if (rd_en_pipe[0] && tile_last_pipe[0])
        tile_done <= 1'b1;
      if (rd_en_pipe[0] && l1_last_pipe[0])
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

  // Inactive cycles present zero values to every PE input.
  always_comb begin
    for (int j = 0; j < SIZE; j++)
      ia_out[j] = ram_rd_en_d1[j] && ROW_CNT_W'(j)<read_extent_q ? ram_rd_data[j] : '0;
  end

  assign ia_row_valid = ram_rd_en_d1[0];
  assign ia_tile_start = src_rd_en & src_tile_first;

  // =====================================================================
  // ia_is_init_data / ia_calc_done
  // =====================================================================
  // send_is_init_r / send_calc_done_r 在整个 L1 组期间不变，无需额外延迟链
  assign ia_is_init_data = ram_rd_en_d1[0] & send_is_init_r;
  assign ia_calc_done    = ram_rd_en_d1[0] & send_calc_done_r;

endmodule
