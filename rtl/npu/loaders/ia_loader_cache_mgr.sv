// IA 缓存按完整行连续读取，所有通道使用相同的槽位与行地址。
// 紧凑功能启用时，RAM 输出先寄存，再恢复有符号偏移。
// tile 起始标记始终提前两个周期启动 PS 数据读取。

module ia_loader_cache_mgr #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned DMA_LANES    = BUS_WIDTH / 8,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned CACHE_BLOCKS = 4,
    parameter int unsigned COMPACT_S8 = 1,
    parameter int unsigned RAM_WORD_ADDR_WIDTH = 10,
    parameter int unsigned p_compact_offset_width = DATA_WIDTH,
    // 八通道 DMA 按列起点的低三位和高一位分别排列数据。
    parameter bit p_dma_source_layout = 1'b0,
    // 在写命令寄存级提前选择第二个物理存储块的数据。
    parameter bit p_shared_write_stage = 1'b0,
    parameter bit p_precomputed_slot_mask = 1'b0,
    parameter bit p_indexed_slot_rows = 1'b0,
    localparam int unsigned SLOT_BLOCKS =
        ((COMPACT_S8 != 0) && (DATA_WIDTH == 16)) ? 2 * CACHE_BLOCKS : CACHE_BLOCKS
) (
    input  logic clk,
    input  logic rst_n,
    input  logic compact_mode = 1'b0,
    input  logic signed [DATA_WIDTH-1:0] compact_offset = '0,
    input  logic [31:0] cfg_cache_blocks = 32'd0,
    input logic [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] cfg_slot_mask = '0,
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
    output logic [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] row_table_index [3],
    input logic [$clog2(SIZE+1)-1:0] row_table_value [3] = '{default:'0},
    output logic                              tile_done,       // 单 tile 输出完成
    output logic                              l1_done,         // L1组全部输出完成
    output logic                              ia_tile_start,   // 提前两个周期指示单 tile 首行

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
  localparam bit p_compact_supported = (COMPACT_S8 != 0) && (DATA_WIDTH == 16);
  localparam int unsigned p_read_stages = p_compact_supported ? 3 : 2;
  logic compact_active;
  assign compact_active = p_compact_supported && compact_mode;

  // 行属性随读请求传递，连续发送不同 L1 组时仍对应各自的数据。
  typedef struct packed {
    logic valid;
    logic tile_first;
    logic tile_last;
    logic group_last;
    logic is_init;
    logic calc_done;
    logic compact;
    logic signed [p_compact_offset_width-1:0] offset;
  } read_metadata_t;
  read_metadata_t read_metadata_q [p_read_stages];

  // =====================================================================
  // 两个 128 位端口访问共享存储，紧凑格式每行使用一个存储字。
  // 普通格式每行使用两个连续存储字，元数据单独保存有效列范围。
  // =====================================================================
  // 写端口：LOAD 阶段从 AXI DMA 响应写入
  // Read every lane of the selected row in the same cycle.
  logic              ram_wr_en   [SIZE];
  logic signed [DATA_WIDTH-1:0] ram_wr_data [SIZE];

  logic              ram_rd_en   [SIZE];
  logic [ADDR_W-1:0] ram_rd_addr [SIZE];
  logic signed [DATA_WIDTH-1:0] ram_rd_raw_data [SIZE];
  logic signed [DATA_WIDTH-1:0] ram_rd_data [SIZE];

  // 紧凑路径只保留结果所需的有效位，普通路径复用同一数据寄存级。
  // 编译关闭紧凑功能时，数据直接使用同步 RAM 输出。
  localparam int unsigned p_sum_width =
      ((p_compact_offset_width > 8) ? p_compact_offset_width : 8) + 1;
  localparam int unsigned p_restore_width =
      (p_sum_width < DATA_WIDTH) ? p_sum_width : DATA_WIDTH;
  if (p_compact_supported) begin : g_read_register
    for (genvar lane = 0; lane < SIZE; lane++) begin : g_lane
      logic signed [DATA_WIDTH-1:0] data_q;
      logic [p_restore_width-1:0] restore_lhs, restore_rhs, restore_sum;
      (* use_dsp = "simd" *) logic [p_restore_width-1:0] restore_native_sum;

      always_ff @(posedge clk) begin
        if (read_metadata_q[1].valid) data_q <= ram_rd_raw_data[lane];
      end
      assign restore_lhs = p_restore_width'($signed(data_q[7:0]));
      assign restore_rhs = p_restore_width'(read_metadata_q[p_read_stages-1].offset);
      // 各通道的定宽加法独立描述，综合时允许共享硬件算术通道。
      assign restore_native_sum = restore_lhs + restore_rhs;
`ifdef SYNTHESIS
      assign restore_sum = restore_native_sum;
`else
      logic [p_restore_width-1:0] restore_logic_sum;
      logic unused_restore_carry;
      parallel_prefix_add #(.p_width(p_restore_width), .p_group_width(4)) u_restore (
        .i_a(restore_lhs), .i_b(restore_rhs), .i_carry(1'b0),
        .o_sum(restore_logic_sum), .o_carry(unused_restore_carry)
      );
      // 四态仿真保留分段进位传播，未受未知位影响的低位仍可确定。
      always_comb begin
        restore_sum = restore_logic_sum;
        case (^{restore_lhs, restore_rhs})
          1'b0, 1'b1: restore_sum = restore_native_sum;
          default: ;
        endcase
      end
`endif
      assign ram_rd_data[lane] = read_metadata_q[p_read_stages-1].compact ?
          DATA_WIDTH'($signed(restore_sum)) : data_q;
    end
  end else begin : g_read_direct
    assign ram_rd_data = ram_rd_raw_data;
  end

  generate if (1) begin : g_external_ram
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
      logic [119:0] compact_group_data;

      // 八个紧凑字节支持任意列起点，跨过半行的部分保留到第二次移位。
      assign compact_group_data =
          120'(compact_source_bytes[63:0]) << (int'(wr_col_base[2:0]) * 8);
      assign compact_shifted_bytes =
          128'(compact_group_data) << (int'(wr_col_base[3]) * 64);
    end else begin : g_general_compact_layout
      assign compact_shifted_bytes = compact_source_bytes << (int'(wr_col_base) * 8);
    end
    // 写命令在同一时钟沿保存地址与掩码，未写入的端口保持原命令。
    always_ff @(posedge clk) begin
      if(!rst_n) ram_port_wr_en<='0;
      else ram_port_wr_en<=write_en;
      for(int port_index=0;port_index<2;port_index++) begin
        if(write_en[port_index]) begin
          ram_port_wr_addr[port_index]<=write_addr[port_index];
          if (!(p_shared_write_stage && SIZE == 16 && DATA_WIDTH == 16))
            ram_port_wr_mask[port_index]<=write_mask[port_index];
        end
      end
    end

    if (p_shared_write_stage && SIZE == 16 && DATA_WIDTH == 16) begin : g_port_write_stage
      logic [255:0] input_data, input_data_q, wide_source, wide_row;
      logic [15:0] input_mask, input_mask_q, row_mask;
      logic [3:0] column_q;
      logic [7:0] empty_byte_q;
      logic compact_q;
      logic [127:0] compact_source, compact_row, compact_data;

      // 两个写端口共用同一拍输入，原始数据与格式每拍保存。
      // 端口写使能、地址和字节掩码共同决定本拍实际写入的内容。
      for (genvar lane = 0; lane < 16; lane++) begin : g_lane
        (* use_dsp = "simd" *) logic [7:0] shifted_compact_byte;

        if (lane < DMA_LANES) begin : g_input
          assign input_data[lane*16 +: 16] = wr_data[lane];
          assign input_mask[lane] = wr_valid[lane];
          assign compact_source[lane*8 +: 8] = input_data_q[lane*16 +: 8] + empty_byte_q;
        end else begin : g_padding
          assign input_data[lane*16 +: 16] = 16'd0;
          assign input_mask[lane] = 1'b0;
          assign compact_source[lane*8 +: 8] = 8'd0;
        end
        assign wide_source[lane*16 +: 16] = input_mask_q[lane] ?
            input_data_q[lane*16 +: 16] : 16'd0;
        // 普通与紧凑格式共用列排列结果，紧凑偏移在选定列的低字节上完成。
        assign shifted_compact_byte = wide_row[lane*16 +: 8] + empty_byte_q;
        always_comb begin
          compact_data[lane*8 +: 8] = row_mask[lane] ?
              compact_row[lane*8 +: 8] : empty_byte_q;
          // 未知控制位使用通道偏移后排列的表达式，保留四态选择顺序。
          case (^{column_q, input_mask_q})
            1'b0, 1'b1: compact_data[lane*8 +: 8] = row_mask[lane] ?
                shifted_compact_byte : empty_byte_q;
            default: ;
          endcase
        end
      end
      always_ff @(posedge clk) begin
        input_data_q <= input_data;
        input_mask_q <= input_mask;
        column_q <= wr_col_base;
        empty_byte_q <= compact_empty_byte;
        compact_q <= compact_active;
      end
      // 字节掩码与数据共同使用本拍保存的原始通道和列位置。
      // ram_port_wr_en 指定有效写命令，两个物理端口在同一周期接收掩码和数据。
      for (genvar lane = 0; lane < 8; lane++) begin : g_byte_mask
        assign ram_port_wr_mask[0][lane*2 +: 2] = compact_q ?
            row_mask[lane*2 +: 2] : {2{row_mask[lane]}};
        assign ram_port_wr_mask[1][lane*2 +: 2] =
            {2{row_mask[lane+8] && !compact_q}};
      end
      assign wide_row = wide_source << (int'(column_q) * 16);
      assign row_mask = input_mask_q << column_q;
      assign compact_row = compact_source << (int'(column_q) * 8);
      assign ram_port_wr_data[0] = compact_q ? compact_data : wide_row[127:0];
      assign ram_port_wr_data[1] = wide_row[255:128];
      assign ram_shared_wr_data = ram_port_wr_en[1] ? ram_port_wr_data[1] : ram_port_wr_data[0];
    end else begin : g_port_data_register
      for (genvar port_index = 0; port_index < 2; port_index++) begin : g_port
        always_ff @(posedge clk) begin
          if (write_en[port_index]) ram_port_wr_data[port_index] <= write_data[port_index];
        end
      end
      assign ram_shared_wr_data = '0;
    end

    wire [RAM_WORD_ADDR_WIDTH-1:0] write_row_word =
        RAM_WORD_ADDR_WIDTH'({wr_slot, wr_row}) << (compact_active ? 0 : 1);
    wire [RAM_WORD_ADDR_WIDTH-1:0] read_row_word =
        RAM_WORD_ADDR_WIDTH'(ram_rd_addr[0]) << (read_metadata_q[0].compact ? 0 : 1);
    assign write_addr[0] = write_row_word;
    assign write_addr[1] = write_row_word + RAM_WORD_ADDR_WIDTH'(1);
    assign ram_port_rd_en = {ram_rd_en[0] && !read_metadata_q[0].compact, ram_rd_en[0]};
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
      assign write_en[0] = compact_active ? (|write_compact_row) : (|write_first_half);
      assign write_en[1] = !compact_active && (|write_second_half);
    end else begin : g_write_port_mask
      assign write_en[0] = |write_mask[0];
      assign write_en[1] = |write_mask[1];
    end
    for (genvar lane = 0; lane < SIZE; lane++) begin : g_write_lane
      if (lane < 8) begin : g_first_half
        assign write_data[0][lane*16 +: 16] = compact_active ?
            {compact_write_byte[lane*2+1], compact_write_byte[lane*2]} : ram_wr_data[lane];
        assign write_mask[0][lane*2 +: 2] = compact_active ?
            {ram_wr_en[lane*2+1], ram_wr_en[lane*2]} : {2{ram_wr_en[lane]}};
      end else begin : g_second_half
        assign write_data[1][(lane-8)*16 +: 16] = ram_wr_data[lane];
        assign write_mask[1][(lane-8)*2 +: 2] = {2{ram_wr_en[lane] && !compact_active}};
      end
      assign ram_rd_raw_data[lane] = read_metadata_q[1].compact ?
          {8'd0, ram_port_rd_data[0][lane*8 +: 8]} :
          ram_port_rd_data[lane/8][(lane%8)*16 +: 16];
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
    logic [239:0] write_group_data;

    // 八个输入通道同时移动，完整保留卷积输出的所有有效元素。
    // 局部列偏移与跨八列偏移分别处理，越过第十五列的数据自然移出。
    assign write_group_data =
        240'(write_source_data[127:0]) << (int'(wr_col_base[2:0]) * 16);
    assign write_shifted_data =
        256'(write_group_data) << (int'(wr_col_base[3]) * 128);
  end else begin : g_general_write_layout
    assign write_shifted_data = write_source_data << (int'(wr_col_base) * DATA_WIDTH);
  end
  assign write_shifted_mask = write_source_mask << wr_col_base;
  for (genvar col = 0; col < SIZE; col++) begin : g_write_select
    assign ram_wr_en[col] = write_shifted_mask[col];
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
  logic [ROW_CNT_W-1:0] write_extent, write_extent_physical, read_extent_q, output_extent;
  logic any_lane_write, physical_lane_write;
  logic [SIZE-1:0] write_last_column;
  assign physical_lane_write = |write_shifted_mask;
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
    assign write_extent_physical[bit_index] = |column_matches;
  end
  if (SIZE <= 32 && DMA_LANES < SIZE) begin : g_input_write_extent
    localparam int p_extent_width = LOG2_SIZE + 1;
    logic [DMA_LANES-1:0] eligible_lane, last_lane;
    logic [DMA_LANES-1:0][p_extent_width-1:0] lane_extent;
    logic [ROW_CNT_W-1:0] encoded_extent;

    // 每个原始通道并行计算结束列，返回有效位仅选择最高有效通道。
    // 行外通道不参与编码，任意有效掩码均保留相同的最后写入列。
    for (genvar lane = 0; lane < DMA_LANES; lane++) begin : g_lane
      assign lane_extent[lane] = {1'b0, wr_col_base} + p_extent_width'(lane + 1);
      // 通道是否位于当前行直接比较起点，结束列加法与接收条件并行计算。
      assign eligible_lane[lane] = wr_valid[lane] && wr_col_base <= LOG2_SIZE'(SIZE-1-lane);
      if (lane + 1 < DMA_LANES) begin : g_has_later_lane
        assign last_lane[lane] = eligible_lane[lane] && !(|eligible_lane[DMA_LANES-1:lane+1]);
      end else begin : g_final_lane
        assign last_lane[lane] = eligible_lane[lane];
      end
    end
    for (genvar bit_index = 0; bit_index < ROW_CNT_W; bit_index++) begin : g_bit
      logic [DMA_LANES-1:0] lane_matches;
      for (genvar lane = 0; lane < DMA_LANES; lane++) begin : g_lane
        assign lane_matches[lane] = last_lane[lane] && lane_extent[lane][bit_index];
      end
      assign encoded_extent[bit_index] = |lane_matches;
    end
    // 已知列偏移直接使用原始通道编码，未知偏移保留完整移位表达式。
    always_comb begin
      write_extent = write_extent_physical;
      any_lane_write = physical_lane_write;
      case (5'(wr_col_base))
        5'd0, 5'd1, 5'd2, 5'd3, 5'd4, 5'd5, 5'd6, 5'd7,
        5'd8, 5'd9, 5'd10, 5'd11, 5'd12, 5'd13, 5'd14, 5'd15,
        5'd16, 5'd17, 5'd18, 5'd19, 5'd20, 5'd21, 5'd22, 5'd23,
        5'd24, 5'd25, 5'd26, 5'd27, 5'd28, 5'd29, 5'd30, 5'd31:
          begin
            write_extent = encoded_extent;
            any_lane_write = |eligible_lane;
          end
        default: ;
      endcase
    end
  end else begin : g_physical_write_extent
    assign write_extent = write_extent_physical;
    assign any_lane_write = physical_lane_write;
  end
  always_ff @(posedge clk) begin
    if (rst_n && any_lane_write && wr_row=='0)
      slot_written_cols[wr_slot]<=write_extent;
    if (!rst_n) read_extent_q<='0;
    else if (ram_rd_en[0])
      read_extent_q<=slot_written_cols[SLOT_W'(ram_rd_addr[0] >> LOG2_SIZE)];
  end
  wire [31:0] active_cache_blocks = cfg_cache_blocks == 0 ? 32'(CACHE_BLOCKS) : cfg_cache_blocks;
  // 预计算掩码与上层配置同时更新，读写槽号共用此映射。
  wire [SLOT_W-1:0] slot_mask = p_precomputed_slot_mask ? cfg_slot_mask :
      compact_active
      ? SLOT_W'((active_cache_blocks << 1) - 1) : SLOT_W'(active_cache_blocks - 1);

  logic l1_issue_active;                  // 仍有行需要在 col0 发射
  logic [SLOT_W-1:0] issue_slot_r;       // 当前正在发射的 slot
  logic [SLOT_W-1:0] l1_slot_end_r;
  logic [ROW_CNT_W-1:0] issue_row_idx_r; // 当前 slot 下一次发射的行号
  logic [ROW_CNT_W-1:0] issue_rows_r;    // 当前 slot 总有效行数
  logic send_is_init_r;
  logic send_calc_done_r;

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
  logic [SLOT_W-1:0] next_issue_slot, start_next_slot;
  logic [ROW_CNT_W-1:0] start_next_rows, active_next_rows;
  logic issue_row_is_last;
  // 行末直接检查加一等式，输入位进位和比较并行求解。
  add_equal #(.p_width(ROW_CNT_W)) u_issue_row_end (
    .i_a(issue_row_idx_r), .i_b(ROW_CNT_W'(0)), .i_carry_in(1'b1),
    .i_target(issue_rows_r), .o_equal(issue_row_is_last)
  );
  // 起始组和正在发送的组并行读取下一槽行数，状态选择只位于末级。
  // 固定加一的每一位只取决于低位全一条件，起始槽和当前槽并行计算。
  for (genvar bit_index = 0; bit_index < SLOT_W; bit_index++) begin : g_next_slot
    if (SLOT_BLOCKS <= 1) begin : g_single
      assign start_next_slot[bit_index] = 1'b0;
      assign next_issue_slot[bit_index] = 1'b0;
    end else if (bit_index == 0) begin : g_first
      assign start_next_slot[bit_index] = slot_mask[bit_index] && !l1_slot_start[bit_index];
      assign next_issue_slot[bit_index] = slot_mask[bit_index] && !issue_slot_r[bit_index];
    end else begin : g_upper
      assign start_next_slot[bit_index] = slot_mask[bit_index] &&
          (l1_slot_start[bit_index] ^ (&l1_slot_start[bit_index-1:0]));
      assign next_issue_slot[bit_index] = slot_mask[bit_index] &&
          (issue_slot_r[bit_index] ^ (&issue_slot_r[bit_index-1:0]));
    end
  end
  assign row_table_index[0] = (l1_slot_start - slot_base) & slot_mask;
  assign row_table_index[1] = (start_next_slot - slot_base) & slot_mask;
  assign row_table_index[2] = (next_issue_slot - slot_base) & slot_mask;
  if (p_indexed_slot_rows) begin : g_indexed_rows
    assign slot_rows_start_now = row_table_value[0];
    assign start_next_rows = row_table_value[1];
    assign active_next_rows = row_table_value[2];
  end else begin : g_parallel_rows
    assign slot_rows_start_now = ROW_CNT_W'(slot_rows[row_table_index[0]]);
    assign start_next_rows = ROW_CNT_W'(slot_rows[row_table_index[1]]);
    assign active_next_rows = ROW_CNT_W'(slot_rows[row_table_index[2]]);
  end

  always_comb begin
    start_issue_now   = l1_start && !l1_issue_active;
    issue_slot_now    = start_issue_now ? l1_slot_start : issue_slot_r;
    issue_row_idx_now = start_issue_now ? '0 : issue_row_idx_r;
    l1_slot_end_now   = start_issue_now ? l1_slot_end : l1_slot_end_r;
    next_issue_slot_now = (SLOT_BLOCKS <= 1) ? '0 : ((issue_slot_now + SLOT_W'(1)) & slot_mask);
    slot_rows_next_now = start_issue_now ? start_next_rows : active_next_rows;
    issue_rows_now    = start_issue_now ? slot_rows_start_now : issue_rows_r;
    issue_row_idx_inc_now = issue_row_idx_now + ROW_CNT_W'(1);

    src_rd_en       = 1'b0;
    src_rd_addr     = '0;
    src_tile_last   = 1'b0;
    src_tile_first  = 1'b0;
    src_l1_last     = 1'b0;

    if (start_issue_now || (l1_issue_active)) begin
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


  always_ff @(posedge clk) begin
    if (!rst_n) begin
      l1_issue_active <= 1'b0;
      issue_slot_r    <= '0;
      l1_slot_end_r   <= '0;
      issue_row_idx_r <= '0;
      issue_rows_r    <= '0;
      send_is_init_r  <= 1'b0;
      send_calc_done_r<= 1'b0;
      for (int j = 0; j < SIZE; j++) begin
        rd_en_pipe[j]     <= 1'b0;
        rd_addr_pipe[j]   <= '0;
      end
    end else begin


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
            end
          end else begin
            issue_row_idx_r <= ROW_CNT_W'(1);
          end
        end else begin
          issue_row_idx_r <= '0;
        end
      end

      // col0 发射调度
      if (l1_issue_active) begin
        if (issue_row_is_last) begin
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
          end
        end else begin
          issue_row_idx_r <= issue_row_idx_r + 1;
        end
      end

      for (int j = 0; j < SIZE; j++) begin
        rd_en_pipe[j]     <= src_rd_en;
        rd_addr_pipe[j]   <= src_rd_addr;
      end

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

  // 行属性与数据使用相同的寄存器级数，复位立即清空有效位。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      for (int stage = 0; stage < p_read_stages; stage++)
        read_metadata_q[stage] <= '0;
    end else begin
      read_metadata_q[0].valid <= src_rd_en;
      read_metadata_q[0].tile_first <= src_tile_first;
      read_metadata_q[0].tile_last <= src_tile_last;
      read_metadata_q[0].group_last <= src_l1_last;
      read_metadata_q[0].is_init <= start_issue_now ? l1_is_init : send_is_init_r;
      read_metadata_q[0].calc_done <= start_issue_now ? l1_calc_done : send_calc_done_r;
      read_metadata_q[0].compact <= compact_active;
      read_metadata_q[0].offset <= p_compact_supported ?
          compact_offset[p_compact_offset_width-1:0] : '0;
      for (int stage = 1; stage < p_read_stages; stage++)
        read_metadata_q[stage] <= read_metadata_q[stage-1];
    end
  end

  if (p_compact_supported) begin : g_extent_register
    logic [ROW_CNT_W-1:0] extent_q;
    always_ff @(posedge clk) begin
      if (read_metadata_q[1].valid) extent_q <= read_extent_q;
    end
    assign output_extent = extent_q;
    assign ia_tile_start = read_metadata_q[0].valid && read_metadata_q[0].tile_first;
  end else begin : g_extent_direct
    assign output_extent = read_extent_q;
    assign ia_tile_start = src_rd_en && src_tile_first;
  end

  // 无效周期输出零，未写入列不参与阵列计算。
  for (genvar lane = 0; lane < SIZE; lane++) begin : g_output
    assign ia_out[lane] = ia_row_valid && ROW_CNT_W'(lane) < output_extent ?
        ram_rd_data[lane] : '0;
  end
  assign ia_row_valid = read_metadata_q[p_read_stages-1].valid;
  assign ia_is_init_data = ia_row_valid && read_metadata_q[p_read_stages-1].is_init;
  assign ia_calc_done = ia_row_valid && read_metadata_q[p_read_stages-1].calc_done;
  assign tile_done = ia_row_valid && read_metadata_q[p_read_stages-1].tile_last;
  assign l1_done = ia_row_valid && read_metadata_q[p_read_stages-1].group_last;

endmodule
