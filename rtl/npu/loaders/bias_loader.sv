/*
 * bias_loader — 顶层汇聚
 * ============================================================
 * 复用 npu_top 的共享 AXI block_dma 做一维块读取，ctrl 负责顺序/切换，buffer 负责 bank 存储。
 * 每个 bias block 采用一次 burst 连续读取，避免单 beat 访问开销。
 */

module bias_loader #(
	    parameter int unsigned SIZE       = 8,
	    parameter int unsigned DATA_WIDTH = 32,
	    parameter int unsigned BUS_WIDTH  = 32,
	    parameter int unsigned REG_WIDTH  = 32,
	    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
	    parameter int unsigned GROUP_BLOCKS_MAX = 1
	) (
    input logic clk /* 工作时钟 */,
    input logic rst_n /* 低有效复位 */,

    input logic                 init_cfg /* 接收任务参数并初始化当前模块 */,
    input logic [REG_WIDTH-1:0] bias_base /* 偏置数组的首字节地址，零表示不使用偏置 */,
    input logic [REG_WIDTH-1:0] k /* 输出矩阵行数 */,
    input logic [REG_WIDTH-1:0] m /* 输出矩阵列数 */,
    input logic [REG_WIDTH-1:0] bias_step_blocks /* 每次偏置切换前进的偏置块数 */,
    input logic                 bias_switch /* 切换到下一偏置分组 */,
    input logic                 bias_sleep /* 当前输入分组无需使用偏置数据 */,
    input logic                 bias_last_loop /* 当前任务已进入最后一个偏置复用循环 */,

    output logic load_bias_req /* 请求共享 DMA 装载偏置分组 */,
    input  logic load_bias_granted /* 偏置装载请求已获得共享 DMA 授予 */,

    output logic                         bias_valid /* 当前并行偏置向量已经就绪 */,
    output logic                         bias_group_valid /* 当前整组偏置已驻留并可读取 */,
    output logic                         load_bias_done /* 当前偏置分组装载完成 */,
    input  logic                         is_mode = 1'b0 /* 偏置采用输入驻留数据流的读取方式 */,
    input  logic                         group_read_start = 1'b0 /* 启动整组偏置的按索引读取 */,
    input  logic [$clog2(GROUP_BLOCKS_MAX * SIZE)-1:0] group_read_idx /* 待读取偏置在当前分组内的元素索引 */,
    output logic signed [DATA_WIDTH-1:0] data_out  [SIZE] /* 提供给阵列的并行有符号偏置向量 */,
    output logic signed [DATA_WIDTH-1:0] group_data_scalar /* 按分组索引同步读出的单个偏置值 */,

		    // ---- 共享 AXI block_dma 客户端接口 ----
	    output logic                 ext_dma_start /* 共享 DMA 接口：启动本次块传输 */,
	    output logic                 ext_dma_is_write /* 共享 DMA 接口：块传输方向选择，置位表示写入 */,
	    output logic                 ext_dma_linear_read_mode /* 共享 DMA 接口：启用逐行单拍读取模式 */,
	    output logic [REG_WIDTH-1:0] ext_dma_base_addr /* 共享 DMA 接口：本次传输的首字节地址 */,
	    output logic [REG_WIDTH-1:0] ext_dma_row_stride /* 共享 DMA 接口：相邻传输行的字节步长 */,
	    output logic [REG_WIDTH-1:0] ext_dma_rows_to_read /* 共享 DMA 接口：本次块传输的行数 */,
	    output logic [7:0]           ext_dma_burst_len_m1 /* 共享 DMA 接口：每行突发传输拍数减一 */,
	    output logic                 ext_dma_slot_id /* 共享 DMA 接口：读取结果写入的缓存槽号 */,
	    output logic                 ext_dma_use_16bits /* 共享 DMA 接口：输入元素采用16 位格式 */,
	    output logic signed [REG_WIDTH-1:0] ext_dma_lhs_zp /* 共享 DMA 接口：输入元素的有符号零点 */,
	    input  logic                 ext_dma_busy /* 共享 DMA 接口：块传输正在执行 */,
	    input  logic                 ext_dma_done /* 共享 DMA 接口：本次块传输完成 */,
	    input  logic                 ext_dma_wr_slot /* 共享 DMA 接口：返回数据所属的缓存槽号 */,
	    input  logic [$clog2(SIZE * (DATA_WIDTH / 8))-1:0] ext_dma_wr_row /* 共享 DMA 接口：返回数据在矩阵块内的行号 */,
	    input  logic [$clog2(SIZE * (DATA_WIDTH / 8))-1:0] ext_dma_wr_col_base /* 共享 DMA 接口：返回数据首通道在矩阵块内的列号 */,
	    input  logic signed [7:0]    ext_dma_wr_data [BUS_WIDTH/8] /* 共享 DMA 接口：写入缓存的解包元素数组 */,
	    input  logic                 ext_dma_wr_valid[BUS_WIDTH/8] /* 共享 DMA 接口：解包元素各通道的写入有效标记 */,
	    input  logic                 ext_dma_wr_use_16bits /* 共享 DMA 接口：返回元素采用16 位格式 */
	);

    localparam int DMA_SIZE = SIZE * (DATA_WIDTH / 8);
    localparam int CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
    typedef logic [CNT_W-1:0] count_t;

    logic                               ctrl_dma_start;
    logic        [       REG_WIDTH-1:0] ctrl_dma_base_addr;
    logic        [       REG_WIDTH-1:0] ctrl_dma_rows_to_read;
    logic        [                     7:0] ctrl_dma_burst_len_m1;
    count_t                             ctrl_dma_row_offset;
    logic                               ctrl_load_group_done;
    logic                               ctrl_load_bank;
    count_t                             ctrl_current_block_idx;
    count_t                             ctrl_load_block_idx;
    count_t                             ctrl_group_blocks_needed;
    count_t                             ctrl_o_current_block_idx_nxt;
    count_t                             ctrl_o_group_blocks_needed_nxt;
    count_t                             buffer_i_current_block_idx_nxt;
    count_t                             buffer_i_group_blocks_needed_nxt;
    count_t                             ctrl_load_blocks_count;
    logic                               ctrl_active_bank;
    logic                               ctrl_switch_pending;
    logic                               ctrl_load_block_valid;
    logic                               ctrl_load_block_bank;
    logic                               buffer_bias_valid;
    logic signed [DATA_WIDTH-1:0]       buffer_data_out [SIZE];
    logic signed [DATA_WIDTH-1:0]       buffer_group_data_scalar;

    logic                               dma_busy;
    logic                               dma_done;
    assign buffer_i_current_block_idx_nxt = ctrl_o_current_block_idx_nxt;
    assign buffer_i_group_blocks_needed_nxt = ctrl_o_group_blocks_needed_nxt;
    assign load_bias_done = ctrl_load_group_done;
    logic        [       $clog2(2)-1:0] dma_wr_slot;
    logic        [$clog2(DMA_SIZE)-1:0] dma_wr_row;
	    logic        [$clog2(DMA_SIZE)-1:0] dma_wr_col_base;
	    logic signed [                7:0] dma_wr_data            [BUS_WIDTH/8];
	    logic                               dma_wr_valid           [BUS_WIDTH/8];
	    logic                               dma_wr_use_16bits;

	    assign ext_dma_start            = ctrl_dma_start;
	    assign ext_dma_is_write         = 1'b0;
	    assign ext_dma_linear_read_mode = 1'b0;
	    assign ext_dma_base_addr        = ctrl_dma_base_addr;
	    assign ext_dma_row_stride       = REG_WIDTH'(SIZE * (DATA_WIDTH / 8));
	    assign ext_dma_rows_to_read     = ctrl_dma_rows_to_read;
	    assign ext_dma_burst_len_m1     = ctrl_dma_burst_len_m1;
	    assign ext_dma_slot_id          = ctrl_load_bank;
	    assign ext_dma_use_16bits       = 1'b0;
	    assign ext_dma_lhs_zp           = '0;

    bias_loader_ctrl #(.BUS_WIDTH(BUS_WIDTH),
        .SIZE     (SIZE),
        .REG_WIDTH(REG_WIDTH),
        .COUNT_WIDTH(COUNT_WIDTH),
        .GROUP_BLOCKS_MAX(GROUP_BLOCKS_MAX)
    ) u_ctrl (
        .clk              (clk),
        .rst_n            (rst_n),
        .init_cfg         (init_cfg),
        .bias_base        (bias_base),
        .m                (m),
        .bias_step_blocks (bias_step_blocks),
        .bias_switch      (bias_switch),
        .bias_last_loop   (bias_last_loop),
        .load_bias_req    (load_bias_req),
        .load_bias_granted(load_bias_granted),
        .dma_busy         (dma_busy),
        .dma_done         (dma_done),
        .load_block_valid (ctrl_load_block_valid),
        .load_block_bank  (ctrl_load_block_bank),
        .dma_start        (ctrl_dma_start),
        .dma_base_addr    (ctrl_dma_base_addr),
        .dma_rows_to_read (ctrl_dma_rows_to_read),
        .dma_burst_len_m1 (ctrl_dma_burst_len_m1),
        .dma_row_offset   (ctrl_dma_row_offset),
        .load_group_done  (ctrl_load_group_done),
        .load_bank        (ctrl_load_bank),
        .current_block_idx(ctrl_current_block_idx),
        .load_block_idx   (ctrl_load_block_idx),
        .group_blocks_needed(ctrl_group_blocks_needed),
        .o_current_block_idx_nxt(ctrl_o_current_block_idx_nxt),
        .o_group_blocks_needed_nxt(ctrl_o_group_blocks_needed_nxt),
        .load_blocks_count(ctrl_load_blocks_count),
        .active_bank      (ctrl_active_bank),
        .switch_pending   (ctrl_switch_pending)
    );

	    assign dma_busy          = ext_dma_busy;
	    assign dma_done          = ext_dma_done;
	    assign dma_wr_slot       = ext_dma_wr_slot;
	    assign dma_wr_row        = ext_dma_wr_row;
	    assign dma_wr_col_base   = ext_dma_wr_col_base;
	    assign dma_wr_use_16bits = ext_dma_wr_use_16bits;

	    generate
	        for (genvar dma_i = 0; dma_i < BUS_WIDTH/8; dma_i++) begin : gen_ext_wr
	            assign dma_wr_data[dma_i]  = ext_dma_wr_data[dma_i];
	            assign dma_wr_valid[dma_i] = ext_dma_wr_valid[dma_i];
	        end
	    endgenerate

     wire [REG_WIDTH-1:0] load_word_row =
        REG_WIDTH'(dma_wr_row) + REG_WIDTH'(ctrl_dma_row_offset);

    bias_loader_buffer #(.BUS_WIDTH(BUS_WIDTH),
        .SIZE           (SIZE),
        .DATA_WIDTH     (DATA_WIDTH),
        .DMA_DATA_WIDTH (8),
        .REG_WIDTH      (REG_WIDTH),
        .COUNT_WIDTH    (COUNT_WIDTH),
        .GROUP_BLOCKS_MAX(GROUP_BLOCKS_MAX),
        .p_share_load_index(1'b1),
        .p_register_current_range(1'b1)
    ) u_buffer (
        .clk               (clk),
        .rst_n             (rst_n),
        .init_cfg          (init_cfg),
        .load_start        (ctrl_dma_start && (ctrl_dma_row_offset == '0)),
        .load_bank         (ctrl_load_bank),
        .load_block_idx    (ctrl_load_block_idx),
        .load_blocks_count (ctrl_load_blocks_count),
        .group_blocks_needed(ctrl_group_blocks_needed),
        .load_word_valid   (dma_wr_valid),
        .load_word_row     (load_word_row),
        .load_word_col_base(dma_wr_col_base),
        .load_word_data    (dma_wr_data),
        .load_done         (ctrl_load_group_done),
        .active_bank       (ctrl_active_bank),
        .current_block_idx (ctrl_current_block_idx),
        .i_current_block_idx_nxt(buffer_i_current_block_idx_nxt),
        .i_group_blocks_needed_nxt(buffer_i_group_blocks_needed_nxt),
        .is_mode           (is_mode),
        .group_read_start  (group_read_start),
        .group_read_idx    (group_read_idx),
        .bias_valid        (buffer_bias_valid),
        .load_block_valid  (ctrl_load_block_valid),
        .load_block_bank   (ctrl_load_block_bank),
        .data_out          (buffer_data_out),
        .group_data_scalar (buffer_group_data_scalar)
    );

    assign bias_valid       = buffer_bias_valid;
    assign bias_group_valid = buffer_bias_valid && !ctrl_switch_pending;
    assign group_data_scalar = buffer_group_data_scalar;

    generate
        for (genvar out_i = 0; out_i < SIZE; out_i++) begin : gen_data_out
            assign data_out[out_i] = buffer_data_out[out_i];
        end
    endgenerate

endmodule
