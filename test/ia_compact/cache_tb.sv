// 通过独立共享端口模型验证 IA 缓存数据及行控制。
module ia_compact_cache_tb #(
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
    logic [1:0] ram_port_wr_en, ram_port_rd_en;
    logic [RAM_WORD_ADDR_WIDTH-1:0] ram_port_wr_addr [0:1], ram_port_rd_addr [0:1];
    logic [127:0] ram_port_wr_data [0:1], ram_port_rd_data [0:1];
    logic [15:0] ram_port_wr_mask [0:1];
    logic [127:0] ram_shared_wr_data;
    ia_shared_ram_model #(
        .WORD_COUNT(CACHE_BLOCKS*SIZE*SIZE*DATA_WIDTH/128),
        .ADDRESS_WIDTH(RAM_WORD_ADDR_WIDTH)
    ) u_memory (.*);
    ia_loader_cache_mgr #(
        .DATA_WIDTH(DATA_WIDTH), .SIZE(SIZE), .BUS_WIDTH(BUS_WIDTH), .DMA_LANES(DMA_LANES),
        .REG_WIDTH(REG_WIDTH), .CACHE_BLOCKS(CACHE_BLOCKS), .COMPACT_S8(COMPACT_S8),
        .RAM_WORD_ADDR_WIDTH(RAM_WORD_ADDR_WIDTH), .p_compact_offset_width(p_compact_offset_width),
        .p_dma_source_layout(p_dma_source_layout), .p_shared_write_stage(p_shared_write_stage),
        .p_precomputed_slot_mask(p_precomputed_slot_mask), .p_indexed_slot_rows(p_indexed_slot_rows)
    ) u_manager (.*);
endmodule
