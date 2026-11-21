/*
 * IA tile loading, grouped reuse and complete-row array input.
 * CACHE_BLOCKS specifies physical DATA_WIDTH-bit tile storage. For 16-bit
 * storage, compact S8 uses two independent byte banks and twice as many slots.
 * Active slots must hold two groups of ia_reuse_num tiles. A preserved slot is
 * reusable only after its complete DMA request has finished successfully.
 */

module ia_loader #(
    parameter int unsigned DATA_WIDTH   = 16,
    parameter int unsigned SIZE         = 16,
    parameter int unsigned BUS_WIDTH    = 32,
    parameter int unsigned DMA_LANES    = BUS_WIDTH / 8,
    parameter int unsigned REG_WIDTH    = 32,
    parameter int unsigned COUNT_WIDTH  = REG_WIDTH,
    parameter int unsigned CACHE_BLOCKS = 4,
    parameter int unsigned COMPACT_S8 = 1,
    parameter bit EXTERNAL_RAM = 1'b0,
    // Job configuration is fixed until cache_flush; tile origins are SIZE aligned.
    parameter bit ORDERED_JOB = 1'b0,
    parameter int unsigned RAM_WORD_ADDR_WIDTH = 10,
    localparam int unsigned SLOT_BLOCKS =
        ((COMPACT_S8 != 0) && (DATA_WIDTH == 16)) ? 2 * CACHE_BLOCKS : CACHE_BLOCKS,
    parameter int unsigned PS_FRAME_COUNT = SIZE,
    // 使用生产 DMA 的 S8 列排列和 S16 有效通道范围。
    parameter bit p_dma_source_layout = 1'b0,
    // 共享块写数据与原写命令在同一寄存级产生。
    parameter bit p_shared_write_stage = 1'b0
) (
    input logic clk,
    input logic rst_n,

    // ---- 配置与控制 ----
    input  logic init_cfg,
    // Select a matrix-block request generated from the original image by DMA.
    // This loader does not own image geometry, an input cache or an AXI path.
    input  logic cfg_im2col = 1'b0,
    input  logic cfg_tile_packed = 1'b0,
    input  logic cfg_compact = 1'b0,
    input  logic signed [REG_WIDTH-1:0] cfg_compact_offset = '0,
    input  logic [31:0] cfg_cache_blocks = 32'd0,
    input  logic cfg_preserve_cache = 1'b0,
    input  logic cache_flush = 1'b0,
    input  logic [REG_WIDTH-1:0] cfg_p0_base = '0,
    input  logic [REG_WIDTH-1:0] cfg_q0_base = '0,
    input  logic [REG_WIDTH-1:0] cfg_cache_slot_base = '0,
    input  logic cfg_prefetch_enable = 1'b0,
    input  logic [REG_WIDTH-1:0] cfg_global_reduction = '0,
    output logic prefetch_idle,
    output logic load_ia_req,
    input  logic load_ia_granted,
    input  logic send_ia_trigger,

    // ---- 矩阵尺寸（init_cfg 高时须稳定）----
    input logic        [REG_WIDTH-1:0] k,
    input logic        [REG_WIDTH-1:0] n,
    input logic        [REG_WIDTH-1:0] m,
    input logic        [REG_WIDTH-1:0] lhs_base,
    input logic        [REG_WIDTH-1:0] lhs_row_stride_b,
    input logic signed [REG_WIDTH-1:0] lhs_zp,
    input logic                        use_16bits,
    input logic                        bias_by_row_mode,
    input logic                        bias_at_end = 1'b0,

    // ---- 复用控制（init_cfg 高时须稳定）----
    input logic [REG_WIDTH-1:0] ia_reuse_num,  // R
    input logic [REG_WIDTH-1:0] w_reuse_num,   // W
    input logic [REG_WIDTH-1:0] row_groups,
    input logic [REG_WIDTH-1:0] row_tail_tiles,
    input logic [REG_WIDTH-1:0] col_groups,
    input logic [REG_WIDTH-1:0] col_tail_tiles,

    // ---- 共享 AXI block_dma 客户端接口 ----
    output logic                                   ext_dma_start,
    output logic                                   ext_dma_is_write,
    output logic                                   ext_dma_linear_read_mode,
    output logic                                   ext_dma_im2col,
    output logic        [           REG_WIDTH-1:0] ext_dma_p0,
    output logic        [           REG_WIDTH-1:0] ext_dma_q0,
    output logic        [           REG_WIDTH-1:0] ext_dma_group,
    output logic        [           REG_WIDTH-1:0] ext_dma_base_addr,
    output logic        [           REG_WIDTH-1:0] ext_dma_row_stride,
    output logic        [           REG_WIDTH-1:0] ext_dma_rows_to_read,
    output logic        [                     7:0] ext_dma_burst_len_m1,
    output logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] ext_dma_slot_id,
    output logic                                   ext_dma_use_16bits,
    output logic signed [           REG_WIDTH-1:0] ext_dma_lhs_zp,
    input  logic                                   ext_dma_busy,
    input  logic                                   ext_dma_done,
    input  logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] ext_dma_wr_slot,
    input  logic        [        $clog2(SIZE)-1:0] ext_dma_wr_row,
    input  logic        [        $clog2(SIZE)-1:0] ext_dma_wr_col_base,
    input  logic signed [          DATA_WIDTH-1:0] ext_dma_wr_data         [DMA_LANES],
    input  logic                                   ext_dma_wr_valid        [DMA_LANES],
    input  logic                                   ext_dma_wr_use_16bits,

    output logic [1:0] ram_port_wr_en,
    output logic [RAM_WORD_ADDR_WIDTH-1:0] ram_port_wr_addr [0:1],
    output logic [127:0] ram_port_wr_data [0:1],
    output logic [15:0] ram_port_wr_mask [0:1],
    output logic [127:0] ram_shared_wr_data,
    output logic [1:0] ram_port_rd_en,
    output logic [RAM_WORD_ADDR_WIDTH-1:0] ram_port_rd_addr [0:1],
    input  logic [127:0] ram_port_rd_data [0:1] = '{default:'0},

    // ---- 输出到脉动阵列（SIZE 维数据 + 最后一列指示信号）----
    output logic signed [DATA_WIDTH-1:0] ia_out         [SIZE],
    output logic                         ia_row_valid,           // Complete input row is valid.
    output logic                         ia_is_init_data,        // 同上
    output logic                         ia_calc_done,           // 同上
    output logic                         ia_tile_start,          // 单 tile 首行到达输出端
    output logic                         ia_sending_done,
    output logic                         ia_data_valid,
    output logic [31:0]                 ps_frame_rows,
    output logic [31:0]                 ps_frame_id,
    output logic                        ps_frame_init,
    output logic                        ps_frame_final,
    output logic                         ia_output_pending,
    output logic                         bias_sleep,
    output logic                         bias_load_sleep,
    output logic                         bias_switch,
    output logic                         bias_last_loop,
    output logic                         ia_l1_switch
);

    // =======================================================================
    // 局部参数
    // =======================================================================
    localparam int BYTE_PER_BEAT = BUS_WIDTH / 8;
    localparam int LOG2_SIZE = $clog2(SIZE);
    localparam int LOG2_BYTE_PER_BEAT = $clog2(BYTE_PER_BEAT);
    localparam int ROW_CNT_W = $clog2(SIZE + 1);
    localparam int unsigned CACHE_SLOT_W = (SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS);
    localparam int p_frame_count_width = COUNT_WIDTH > 0 ? COUNT_WIDTH : 1;

    // =======================================================================
    // 状态机
    // =======================================================================
    typedef enum logic [1:0] {
        IDLE = 2'b00,
        INIT = 2'b11,
        RUN  = 2'b01
    } state_t;

    (* fsm_encoding = "sequential" *) state_t state;
    state_t state_nxt;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= IDLE;
        else state <= state_nxt;
    end

    // ctrl 完成信号
    logic ctrl_all_done;
    logic cfg_valid;  // 参数已就绪

    always_comb begin
        state_nxt = state;
        case (state)
            IDLE: if (init_cfg) state_nxt = INIT;
            INIT: if (cfg_valid) state_nxt = RUN;
            RUN: if (ctrl_all_done) state_nxt = IDLE;
            default: state_nxt = IDLE;
        endcase
    end

    // =======================================================================
    // 配置寄存器（init_cfg 锁存）
    // =======================================================================
    logic [REG_WIDTH-1:0] cfg_k, cfg_n, cfg_m;
    logic signed [REG_WIDTH-1:0] cfg_lhs_zp;
    logic [REG_WIDTH-1:0] cfg_lhs_row_stride_b, cfg_lhs_base;
    logic                 cfg_use_16bits;
    logic                 tile_packed_q;
    logic cfg_compact_q;
    logic signed [DATA_WIDTH-1:0] compact_offset_q;
    logic preserve_cache_q;
    logic prefetch_enable_q;
    logic [REG_WIDTH-1:0] global_reduction_q;
    logic [REG_WIDTH-1:0] packed_k_tiles_q;
    logic [REG_WIDTH-1:0] packed_reduction_nxt;
    logic [REG_WIDTH-1:0] packed_k_tiles_nxt;
    logic unused_packed_tiles_carry;
    logic [REG_WIDTH-1:0] p0_base_q, q0_base_q;
    logic [REG_WIDTH-1:0] next_cols;
    logic [REG_WIDTH-1:0] next_cols_comb;
    logic [REG_WIDTH-1:0] next_remaining_cols;
    logic [CACHE_SLOT_W-1:0] cache_slot_base_q;
    logic [31:0] cache_blocks_q;
    wire [31:0] incoming_cache_blocks = cfg_cache_blocks == 0 ? 32'(CACHE_BLOCKS) : cfg_cache_blocks;
    logic [CACHE_SLOT_W-1:0] cache_slot_mask;
    wire compact_config_valid = (COMPACT_S8 != 0) && (DATA_WIDTH == 16) &&
        cfg_compact && ($signed(cfg_compact_offset) >= -127) &&
        ($signed(cfg_compact_offset) <= 128);
    wire [CACHE_SLOT_W-1:0] incoming_slot_mask =
        CACHE_SLOT_W'((compact_config_valid ? incoming_cache_blocks << 1 : incoming_cache_blocks) - 1);
    logic                 cfg_bias_by_row_mode;
    logic                 cfg_bias_at_end;
    logic [REG_WIDTH-1:0] cfg_ia_reuse_num;
    logic [REG_WIDTH-1:0] cfg_w_reuse_num;

    // 分块数与 reduction 在同一配置边沿保存；忙碌期间重新配置时，n 保持原值。
    // 取整在配置接收前完成，控制器随后只计算字节步长与复用组步长。
    assign packed_reduction_nxt = (cfg_global_reduction != '0) ? cfg_global_reduction :
        ((state == IDLE) ? n : cfg_n);
    assign {unused_packed_tiles_carry, packed_k_tiles_nxt} =
        {1'b0, (packed_reduction_nxt >> LOG2_SIZE)} +
        {1'b0, REG_WIDTH'((packed_reduction_nxt & REG_WIDTH'(SIZE - 1)) != '0)};

    // 配置接收时先求出下一列分块的有效宽度，供后续预取描述符生成使用。
    // 减法保留 REG_WIDTH 位模运算；二的幂尺寸只保存尾部所需的有效低位。
    logic [REG_WIDTH-1:0] next_cols_inverse, next_cols_constant;
    logic [REG_WIDTH-1:0] next_cols_sum, next_cols_carry;
    logic unused_next_cols_carry;
    assign next_cols_inverse = ~cfg_q0_base;
    assign next_cols_constant = REG_WIDTH'(1) - REG_WIDTH'(SIZE);
    assign next_cols_sum = cfg_global_reduction ^ next_cols_inverse ^ next_cols_constant;
    assign next_cols_carry = ((cfg_global_reduction & next_cols_inverse) |
        (cfg_global_reduction & next_cols_constant) | (next_cols_inverse & next_cols_constant)) << 1;
    parallel_prefix_add #(.p_width(REG_WIDTH), .p_preserve_groups(1'b1)) u_next_cols (
        .i_a(next_cols_sum), .i_b(next_cols_carry), .i_carry(1'b0),
        .o_sum(next_remaining_cols), .o_carry(unused_next_cols_carry)
    );
    if ((SIZE > 1) && ((SIZE & (SIZE - 1)) == 0) && (REG_WIDTH > LOG2_SIZE)) begin : g_prefetch_tail
        assign next_cols_comb = (|next_remaining_cols[REG_WIDTH-1:LOG2_SIZE]) ?
            REG_WIDTH'(SIZE) : REG_WIDTH'(next_remaining_cols[LOG2_SIZE-1:0]);
    end else begin : g_prefetch_general_tail
        assign next_cols_comb = (next_remaining_cols >= REG_WIDTH'(SIZE)) ?
            REG_WIDTH'(SIZE) : next_remaining_cols;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_compact_q <= 1'b0;
            compact_offset_q <= '0;
            preserve_cache_q <= 1'b0;
            prefetch_enable_q <= 1'b0;
            global_reduction_q <= '0;
            packed_k_tiles_q <= '0;
            p0_base_q <= '0;
            q0_base_q <= '0;
            next_cols <= ((REG_WIDTH'(0) - REG_WIDTH'(SIZE)) >= REG_WIDTH'(SIZE)) ?
                REG_WIDTH'(SIZE) : (REG_WIDTH'(0) - REG_WIDTH'(SIZE));
            cache_slot_base_q <= '0;
            cache_slot_mask <= CACHE_SLOT_W'(CACHE_BLOCKS - 1);
            cache_blocks_q <= 32'(CACHE_BLOCKS);
        end else if (init_cfg) begin
            cfg_compact_q <= compact_config_valid;
            compact_offset_q <= DATA_WIDTH'(cfg_compact_offset);
            cache_blocks_q <= incoming_cache_blocks;
            cache_slot_mask <= incoming_slot_mask;
            preserve_cache_q <= cfg_preserve_cache;
            prefetch_enable_q <= cfg_prefetch_enable && cfg_preserve_cache &&
                (n != 0) && (n <= SIZE) && (k != 0) &&
                (row_groups == 1) && (col_groups == 1) && (w_reuse_num == 1) &&
                (ia_reuse_num != 0) &&
                (ia_reuse_num <= REG_WIDTH'(compact_config_valid ? incoming_cache_blocks << 1 : incoming_cache_blocks) / 2) &&
                (k <= (ia_reuse_num << LOG2_SIZE));
            global_reduction_q <= cfg_global_reduction;
            packed_k_tiles_q <= packed_k_tiles_nxt;
            p0_base_q <= cfg_p0_base;
            q0_base_q <= cfg_q0_base;
            next_cols <= next_cols_comb;
            cache_slot_base_q <= CACHE_SLOT_W'(cfg_cache_slot_base) &
                CACHE_SLOT_W'((compact_config_valid ? incoming_cache_blocks << 1 : incoming_cache_blocks) - 1);
        end
    end

    // =======================================================================
    // 派生参数
    // =======================================================================
    logic [REG_WIDTH-1:0] horizontal_tile_num;
    logic [REG_WIDTH-1:0] vertical_tile_num;
    logic [REG_WIDTH-1:0] l2_group_num;
    logic [REG_WIDTH-1:0] l1_per_l2;
    logic [REG_WIDTH-1:0] ia_reuse_num_act;
    logic [REG_WIDTH-1:0] output_col_tile_num;
    logic [REG_WIDTH-1:0] w_groups_total;
    logic [REG_WIDTH-1:0] w_group_last_width;
    logic [REG_WIDTH-1:0] rsp_beats_per_row_normal;
    logic [REG_WIDTH-1:0] rsp_beats_per_row_last;
    logic [REG_WIDTH-1:0] rsp_rows_last_tile;
    logic [31:0] frame_last_rows_q;
    logic [31:0] frame_last_rows_next;
    logic [p_frame_count_width-1:0] frame_last_tiles;

    // =======================================================================
    // 派生参数计算通路（使用连续赋值）
    // =======================================================================
    logic [REG_WIDTH-1:0] vtn_tmp;
    logic [REG_WIDTH-1:0] r_mod;
    logic [REG_WIDTH-1:0] ia_reuse_num_safe;
    logic [REG_WIDTH-1:0] w_reuse_num_safe;
    logic [REG_WIDTH-1:0] ia_reuse_num_act_comb;
    logic [REG_WIDTH-1:0] l2_group_num_comb;
    logic [REG_WIDTH-1:0] output_col_tile_num_comb;
    logic [REG_WIDTH-1:0] w_groups_total_comb;
    logic [REG_WIDTH-1:0] w_group_last_width_comb;

    logic [REG_WIDTH-1:0] last_cols_comb;
    logic [REG_WIDTH-1:0] rsp_beats_per_row_last_comb;

    logic [REG_WIDTH-1:0] tmp_col_rem;
    logic [REG_WIDTH-1:0] rsp_rows_last_tile_comb;

    // 基于输入参数计算派生值
    assign vtn_tmp = (k + SIZE - 1) >> LOG2_SIZE;
    assign ia_reuse_num_safe = (ia_reuse_num == 0) ? REG_WIDTH'(1) : ia_reuse_num;
    assign w_reuse_num_safe = (w_reuse_num == 0) ? REG_WIDTH'(1) : w_reuse_num;
    assign ia_reuse_num_act_comb = row_tail_tiles;
    assign l2_group_num_comb = row_groups;
    assign output_col_tile_num_comb = (m == 0) ? REG_WIDTH'(1) : ((m + SIZE - 1) >> LOG2_SIZE);
    assign w_groups_total_comb = col_groups;
    assign w_group_last_width_comb = col_tail_tiles;

    if ((SIZE > 1) && ((SIZE & (SIZE - 1)) == 0)) begin : g_power_two_tail
        // 分块尺寸为二的幂时，低位余数直接给出尾部行列数，零余数表示完整分块。
        // 位宽扩展发生在余数选择之后，配置寄存器保持原有接收边沿。
        assign last_cols_comb = (n[LOG2_SIZE-1:0] == '0) ?
            REG_WIDTH'(SIZE) : REG_WIDTH'(n[LOG2_SIZE-1:0]);
        assign rsp_rows_last_tile_comb = (k[LOG2_SIZE-1:0] == '0) ?
            REG_WIDTH'(SIZE) : REG_WIDTH'(k[LOG2_SIZE-1:0]);
    end else begin : g_general_tail
        assign last_cols_comb = SIZE - ((((n + SIZE - 1) >> LOG2_SIZE) << LOG2_SIZE) - n);
        assign rsp_rows_last_tile_comb = SIZE - tmp_col_rem;
    end
    assign rsp_beats_per_row_last_comb = ((last_cols_comb << (use_16bits ? 1 : 0)) + BYTE_PER_BEAT - 1) >> LOG2_BYTE_PER_BEAT;

    assign tmp_col_rem = (((k + SIZE - 1) >> LOG2_SIZE) << LOG2_SIZE) - k;

    // 尾组行数与原始配置在同一边沿保存，完整保留计数位宽和三十二位回绕。
    assign frame_last_tiles = p_frame_count_width'(ia_reuse_num_act_comb);
    if ((SIZE > 1) && ((SIZE & (SIZE - 1)) == 0) && (LOG2_SIZE < 32)) begin : g_frame_rows_power_two
        localparam int p_high_width = 32 - LOG2_SIZE;
        logic [p_high_width-1:0] last_high;

        assign last_high = p_high_width'(frame_last_tiles) -
            p_high_width'(|k[LOG2_SIZE-1:0]);
        assign frame_last_rows_next = {last_high, k[LOG2_SIZE-1:0]};
    end else begin : g_frame_rows_general
        assign frame_last_rows_next = (32'(frame_last_tiles) << LOG2_SIZE) -
            (32'(SIZE) - 32'(rsp_rows_last_tile_comb));
    end

    // =======================================================================
    // 配置参数锁存与派生参数计算（IDLE -> INIT）
    // =======================================================================
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_k                    <= '0;
            cfg_n                    <= '0;
            cfg_m                    <= '0;
            cfg_lhs_zp               <= '0;
            cfg_lhs_row_stride_b     <= '0;
            cfg_lhs_base             <= '0;
            cfg_use_16bits           <= '0;
            tile_packed_q            <= 1'b0;
            cfg_bias_by_row_mode     <= 1'b0;
            cfg_bias_at_end          <= 1'b0;
            cfg_ia_reuse_num         <= '0;
            cfg_w_reuse_num          <= '0;

            horizontal_tile_num      <= '0;
            vertical_tile_num        <= '0;

            l2_group_num             <= '0;
            l1_per_l2                <= '0;
            ia_reuse_num_act         <= '0;
            output_col_tile_num      <= '0;
            w_groups_total           <= '0;
            w_group_last_width       <= '0;

            rsp_beats_per_row_normal <= '0;
            rsp_beats_per_row_last   <= '0;
            rsp_rows_last_tile       <= '0;
            frame_last_rows_q        <= 32'd0 - 32'(SIZE);

            cfg_valid                <= 1'b0;
        end else if (state == IDLE && init_cfg) begin
            cfg_k <= k;
            cfg_n <= n;
            cfg_m <= m;
            cfg_lhs_zp <= lhs_zp;
            cfg_lhs_row_stride_b <= lhs_row_stride_b;
            cfg_lhs_base <= lhs_base;
            cfg_use_16bits <= use_16bits;
            tile_packed_q <= cfg_tile_packed;
            cfg_bias_by_row_mode <= bias_by_row_mode;
            cfg_bias_at_end <= bias_at_end;
            cfg_ia_reuse_num <= ia_reuse_num_safe;
            cfg_w_reuse_num <= w_reuse_num_safe;

            horizontal_tile_num <= (n + SIZE - 1) >> LOG2_SIZE;
            vertical_tile_num <= (k + SIZE - 1) >> LOG2_SIZE;

            l1_per_l2 <= (n + SIZE - 1) >> LOG2_SIZE;
            output_col_tile_num <= output_col_tile_num_comb;
            rsp_beats_per_row_normal <= ((SIZE << (use_16bits ? 1 : 0)) + BYTE_PER_BEAT - 1) >> LOG2_BYTE_PER_BEAT;
            rsp_beats_per_row_last <= rsp_beats_per_row_last_comb;
            rsp_rows_last_tile <= rsp_rows_last_tile_comb;
            frame_last_rows_q <= frame_last_rows_next;

            l2_group_num <= l2_group_num_comb;
            ia_reuse_num_act <= ia_reuse_num_act_comb;
            w_groups_total <= w_groups_total_comb;
            w_group_last_width <= w_group_last_width_comb;
            cfg_valid <= 1'b1;
        end else if (state == INIT) begin
            cfg_valid <= 1'b0;
        end
    end

    // =======================================================================
    // 子模块间连线
    // =======================================================================

    // ---- ctrl ↔ block_dma ----
    logic                                   tl_start;
    logic [REG_WIDTH-1:0]                    unused_tl_p0, unused_tl_q0;
    logic [REG_WIDTH-1:0]                    tl_group;
    logic        [           REG_WIDTH-1:0] tl_base_addr;
    logic        [           REG_WIDTH-1:0] tl_row_stride;
    logic        [           REG_WIDTH-1:0] tl_rows_to_read;
    logic        [           REG_WIDTH-1:0] tl_valid_cols;
    logic        [                     7:0] tl_burst_len_m1;
	    logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] tl_slot_id;
    logic                                   tl_use_16bits;
    logic signed [           REG_WIDTH-1:0] tl_lhs_zp;
    logic                                   tl_busy;
    logic                                   tl_tile_done;

    // ---- ctrl ↔ cache_mgr （L1组级接口）----
    logic                                   cache_l1_start;
	    logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] cache_l1_slot_start;
	    logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] cache_l1_slot_end;
    logic                                   cache_l1_is_init;
    logic                                   cache_l1_calc_done;
    logic        [           ROW_CNT_W-1:0] cache_slot_rows     [ SLOT_BLOCKS];
    logic [CACHE_SLOT_W-1:0] cache_row_index [3];
    logic [ROW_CNT_W-1:0] cache_row_value [3];
    logic                                   cache_tile_done;
    logic                                   cache_l1_done;
    logic                                   cache_l1_start_q;
    logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] cache_l1_slot_start_q;
    logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] cache_l1_slot_end_q;
    logic                                   cache_l1_is_init_q;
    logic                                   cache_l1_calc_done_q;

    // ---- tile_loader ↔ cache_mgr（写端口）----
	    logic        [((SLOT_BLOCKS <= 1) ? 1 : $clog2(SLOT_BLOCKS))-1:0] tl_wr_slot;
    logic        [        $clog2(SIZE)-1:0] tl_wr_row;
    logic        [        $clog2(SIZE)-1:0] tl_wr_col_base;
    logic signed [          DATA_WIDTH-1:0] tl_wr_data          [DMA_LANES];
    logic                                   tl_wr_valid         [DMA_LANES];
    logic                                   tl_wr_use_16bits;

    // ctrl init_start 信号
    logic                                   ctrl_init_start;
    logic [REG_WIDTH-1:0]                    ctrl_i_packed_k_tiles;
    assign ctrl_init_start          = cfg_valid;
    assign ctrl_i_packed_k_tiles     = packed_k_tiles_q;

    logic im2col_q;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) im2col_q <= 1'b0;
        else if (init_cfg) im2col_q <= cfg_im2col;
    end

    // 标签覆盖缓存中的全部数据及 K 维尾部补零，图像参数在当前任务内保持。
    // cache_flush 统一清除有效位，数据阵列保持原有内容。
    localparam int unsigned ORDERED_TAG_W = 2 * (REG_WIDTH - LOG2_SIZE) + $clog2(SIZE + 1);
    localparam int unsigned CACHE_TAG_W = ORDERED_JOB ? ORDERED_TAG_W :
        8 * REG_WIDTH + DATA_WIDTH + 12;
    typedef struct packed {
        logic [REG_WIDTH-1:0] base_addr, row_stride, rows, cols, zp;
        logic [REG_WIDTH-1:0] p0, q0, group;
        logic [DATA_WIDTH-1:0] offset;
        logic [7:0] burst;
        logic use16, im2col, compact, tile_packed;
        logic [CACHE_SLOT_W-1:0] slot;
    } dma_descriptor_t;

    function automatic logic [CACHE_TAG_W-1:0] descriptor_tag(input dma_descriptor_t d);
        if (ORDERED_JOB)
            return CACHE_TAG_W'({d.p0[REG_WIDTH-1:LOG2_SIZE], d.q0[REG_WIDTH-1:LOG2_SIZE],
                                 d.rows[$clog2(SIZE + 1)-1:0]});
        return CACHE_TAG_W'({d.base_addr, d.row_stride, d.rows, d.cols, d.zp,
                d.p0, d.q0, d.group, d.offset, d.burst, d.use16, d.im2col, d.compact, d.tile_packed});
    endfunction

    logic ctrl_load_req, ctrl_load_granted, ctrl_request_valid;
    logic [REG_WIDTH-1:0] request_base_addr, request_p0, request_q0;
    logic [REG_WIDTH-1:0] demand_p0_q, demand_q0_q;
    logic [CACHE_SLOT_W-1:0] demand_slot_q, demand_slot_next;
    logic [CACHE_SLOT_W-1:0] demand_slot_base_next, demand_slot_mask_next;
    (* use_dsp = "yes" *) logic [REG_WIDTH-1:0] demand_p0_nxt, demand_q0_nxt;
    (* use_dsp = "yes" *) logic [REG_WIDTH-1:0] request_p0_absolute, request_q0_absolute;
    logic unused_demand_p0_carry, unused_demand_q0_carry;
    logic [REG_WIDTH-1:0] request_group, request_rows, request_cols;
    logic [7:0] request_burst_len_m1;
    logic [CACHE_SLOT_W-1:0] request_slot;
    dma_descriptor_t demand_descriptor, request_descriptor, dma_descriptor;
    dma_descriptor_t prefetch_descriptor, prefetch_dma_descriptor;
    // 两个同步读取端口使用块存储，写入完成周期由有效位屏蔽同址查询。
    (* ram_style = "block" *) logic [CACHE_TAG_W-1:0] cache_tags [SLOT_BLOCKS];
    logic [SLOT_BLOCKS-1:0] cache_tags_valid;
    logic [CACHE_TAG_W-1:0] fill_tag;
    logic [CACHE_SLOT_W-1:0] fill_slot;
    logic fill_pending, fill_is_prefetch, cache_hit_done;
    logic [CACHE_TAG_W-1:0] request_tag_q, prefetch_tag_q;
    logic [CACHE_TAG_W-1:0] request_lookup_q, prefetch_lookup_q;
    logic [CACHE_SLOT_W-1:0] request_lookup_slot_q, prefetch_lookup_slot_q;
    logic request_lookup_valid, prefetch_lookup_valid;
    logic request_lookup_match;
    logic request_q0_matches;
    logic request_lookup_ready;
    (* keep = 1 *) logic request_tag_match;

    always_ff @(posedge clk) begin
        request_tag_q <= cache_tags[request_descriptor.slot];
        prefetch_tag_q <= cache_tags[prefetch_descriptor.slot];
        request_lookup_q <= descriptor_tag(request_descriptor);
        prefetch_lookup_q <= descriptor_tag(prefetch_descriptor);
        request_lookup_slot_q <= request_descriptor.slot;
        prefetch_lookup_slot_q <= prefetch_descriptor.slot;
        if (rst_n && !cache_flush && !(init_cfg &&
            (!cfg_preserve_cache || (compact_config_valid != cfg_compact_q)))) begin
            request_lookup_valid <= !(ext_dma_done && fill_pending &&
                                      fill_slot == request_descriptor.slot);
            prefetch_lookup_valid <= !(ext_dma_done && fill_pending &&
                                       fill_slot == prefetch_descriptor.slot);
        end else begin
            request_lookup_valid <= 1'b0;
            prefetch_lookup_valid <= 1'b0;
        end
    end
    logic prefetch_pending, prefetch_start;
    logic [REG_WIDTH-1:0] prefetch_rows_left;
    logic [REG_WIDTH-1:0] prefetch_group_p0, prefetch_group_rows;
    logic [REG_WIDTH-1:0] prefetch_group_base, prefetch_group_r;
    logic [CACHE_SLOT_W-1:0] prefetch_group_slot;
    logic [REG_WIDTH-1:0] prefetch_previous_q0;

    // 在控制器保存分块请求的同一边沿保存绝对坐标，供后续命中判断与 DMA 使用。
    // 配置同拍更新时使用新基址，保持配置切换和未使能周期的坐标值一致。
    assign {unused_demand_p0_carry, demand_p0_nxt} = {1'b0, request_p0} +
        {1'b0, (init_cfg ? cfg_p0_base : p0_base_q)};
    assign {unused_demand_q0_carry, demand_q0_nxt} = {1'b0, request_q0} +
        {1'b0, (init_cfg ? cfg_q0_base : q0_base_q)};

    // 物理槽号与控制器的分块槽号共用接收边沿，配置同拍更新时使用新映射。
    always_comb begin
        demand_slot_mask_next = cache_slot_mask;
        demand_slot_base_next = cache_slot_base_q;
        if (init_cfg) begin
            demand_slot_mask_next = incoming_slot_mask;
            demand_slot_base_next = CACHE_SLOT_W'(cfg_cache_slot_base) & incoming_slot_mask;
        end
    end
    assign demand_slot_next = (request_slot + demand_slot_base_next) & demand_slot_mask_next;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) demand_slot_q <= '0;
        else demand_slot_q <= demand_slot_next;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            demand_p0_q <= '0;
            demand_q0_q <= '0;
        end else begin
            demand_p0_q <= demand_p0_nxt;
            demand_q0_q <= demand_q0_nxt;
        end
    end

    assign request_p0_absolute = request_p0 + p0_base_q;
    assign request_q0_absolute = request_q0 + q0_base_q;

    always_comb begin
        demand_descriptor.base_addr = tl_base_addr;
        demand_descriptor.row_stride = tl_row_stride;
        demand_descriptor.rows = tl_rows_to_read;
        demand_descriptor.cols = tl_valid_cols;
        demand_descriptor.zp = tl_lhs_zp;
        demand_descriptor.p0 = demand_p0_q;
        demand_descriptor.q0 = demand_q0_q;
        demand_descriptor.group = tl_group;
        demand_descriptor.offset = compact_offset_q;
        demand_descriptor.burst = tl_burst_len_m1;
        demand_descriptor.use16 = tl_use_16bits;
        demand_descriptor.im2col = im2col_q;
        demand_descriptor.compact = cfg_compact_q;
        demand_descriptor.tile_packed = tile_packed_q;
        demand_descriptor.slot = demand_slot_q;
        request_descriptor = demand_descriptor;
        request_descriptor.base_addr = request_base_addr;
        request_descriptor.row_stride = tile_packed_q ?
            (REG_WIDTH'(SIZE) << cfg_use_16bits) : cfg_lhs_row_stride_b;
        request_descriptor.rows = request_rows;
        request_descriptor.cols = request_cols;
        request_descriptor.zp = cfg_lhs_zp;
        request_descriptor.p0 = request_p0_absolute;
        request_descriptor.q0 = request_q0_absolute;
        request_descriptor.group = request_group;
        request_descriptor.burst = request_burst_len_m1;
        request_descriptor.use16 = cfg_use_16bits;
        request_descriptor.slot = (request_slot + cache_slot_base_q) & cache_slot_mask;
        dma_descriptor = prefetch_start ? prefetch_dma_descriptor : demand_descriptor;
    end

    // 有序任务并行比较坐标高位与行数，低位进位和首个高位等式共同完成。
    if (ORDERED_JOB) begin : g_ordered_request_match
        localparam int unsigned p_coord_width = REG_WIDTH - LOG2_SIZE;
        localparam int unsigned p_rows_width = $clog2(SIZE + 1);
        logic [REG_WIDTH-1:0] request_p0_equal_i_a_full, request_p0_equal_i_b_full;
        logic [REG_WIDTH-1:0] request_q0_equal_i_a_full, request_q0_equal_i_b_full;
        logic [p_coord_width-1:0] request_p0_equal_i_target;
        logic [p_coord_width-1:0] request_q0_equal_i_target;
        (* keep = 1 *) logic request_p0_equal_o_equal;
        (* keep = 1 *) logic request_q0_equal_o_equal;

        assign request_p0_equal_i_a_full = request_p0;
        assign request_p0_equal_i_b_full = p0_base_q;
        assign request_q0_equal_i_a_full = request_q0;
        assign request_q0_equal_i_b_full = q0_base_q;
        assign request_p0_equal_i_target = request_lookup_q[CACHE_TAG_W-1 -: p_coord_width];
        assign request_q0_equal_i_target = request_lookup_q[p_rows_width +: p_coord_width];
        ia_ordered_coordinate_equal #(
            .p_width(REG_WIDTH), .p_low_width(LOG2_SIZE)
        ) u_request_p0_equal (
            .i_a(request_p0_equal_i_a_full), .i_b(request_p0_equal_i_b_full),
            .i_target(request_p0_equal_i_target),
            .o_equal(request_p0_equal_o_equal)
        );
        assign request_q0_equal_o_equal = request_q0_matches;
        logic request_rows_match;
        logic request_slot_match;
        logic request_filter_ready;

        // 行数与槽位先完成比较，坐标等式在末级合并。
        assign request_rows_match =
            (request_lookup_q[p_rows_width-1:0] == request_rows[p_rows_width-1:0]);
        assign request_slot_match = (request_lookup_slot_q == request_descriptor.slot);
        assign request_filter_ready = request_lookup_valid && request_rows_match && request_slot_match;
        assign request_lookup_match = request_p0_equal_o_equal && request_q0_equal_o_equal && request_rows_match;
        assign request_lookup_ready = request_filter_ready && request_p0_equal_o_equal && request_q0_equal_o_equal;
    end else begin : g_generic_request_match
        assign request_lookup_match = (request_lookup_q == descriptor_tag(request_descriptor));
        assign request_lookup_ready = request_lookup_valid &&
            (request_lookup_slot_q == request_descriptor.slot) && request_lookup_match;
    end

    // 查询就绪已确认标记与描述符相等，两个命中判断共用已保存标记的比较。
    localparam int p_tag_compare_groups = (CACHE_TAG_W + 2) / 3;
    localparam int p_tag_compare_parts = (p_tag_compare_groups + 5) / 6;
    (* keep = 1 *) logic [p_tag_compare_groups-1:0] request_tag_group_equal;
    (* keep = 1 *) logic [p_tag_compare_parts-1:0] request_tag_part_equal;
    // 每组比较三对标记位，再分两级归并比较结果。
    for (genvar group_index = 0; group_index < p_tag_compare_groups; group_index++) begin : g_tag_group
        localparam int p_first = group_index * 3;
        localparam int p_width = CACHE_TAG_W - p_first < 3 ? CACHE_TAG_W - p_first : 3;
        assign request_tag_group_equal[group_index] =
            request_tag_q[p_first +: p_width] == request_lookup_q[p_first +: p_width];
    end
    for (genvar part = 0; part < p_tag_compare_parts; part++) begin : g_tag_part
        localparam int p_first = part * 6;
        localparam int p_width = p_tag_compare_groups - p_first < 6 ? p_tag_compare_groups - p_first : 6;
        assign request_tag_part_equal[part] = &request_tag_group_equal[p_first +: p_width];
    end
    assign request_tag_match = &request_tag_part_equal;
    wire prefetch_lookup_ready = prefetch_lookup_valid &&
        (prefetch_lookup_slot_q == prefetch_descriptor.slot) &&
        (prefetch_lookup_q == descriptor_tag(prefetch_descriptor));
    logic request_cache_eligible;
    assign request_cache_eligible = preserve_cache_q &&
        cache_tags_valid[request_descriptor.slot] && request_tag_match;
    wire cache_hit_event = tl_start && preserve_cache_q && request_lookup_valid &&
        (request_lookup_slot_q == demand_descriptor.slot) &&
        (request_lookup_q == descriptor_tag(demand_descriptor)) && cache_tags_valid[request_lookup_slot_q] &&
        request_tag_match && !cache_flush && !init_cfg;
    wire prefetch_cached = prefetch_lookup_ready && cache_tags_valid[prefetch_descriptor.slot] &&
        (prefetch_tag_q == prefetch_lookup_q);
    wire prefetch_inflight = (fill_pending && fill_is_prefetch) || prefetch_start;
    wire prefetch_done = ext_dma_done && fill_pending && fill_is_prefetch;
    wire dma_available = !fill_pending && !ext_dma_busy && !tl_start && !prefetch_start;
    wire prefetch_request = prefetch_pending && prefetch_lookup_ready && !prefetch_cached && dma_available &&
        !ctrl_load_req && !cache_hit_done && !init_cfg && !cache_flush;
    wire prefetch_issue = prefetch_request && load_ia_granted;
    wire prefetch_advance = prefetch_pending &&
        (prefetch_done || (!prefetch_inflight && prefetch_cached && !init_cfg && !cache_flush));

    // 缓存资格和请求条件先独立计算，查询就绪仅进入请求与授予的末级组合。
    logic request_without_lookup, request_with_lookup;
    logic grant_without_lookup, grant_with_lookup;
    logic prefetch_grant_enabled;
    assign request_without_lookup = prefetch_enable_q ?
        prefetch_request :
        ((ctrl_load_req && !ctrl_request_valid) || prefetch_start);
    assign request_with_lookup = prefetch_enable_q ?
        (ctrl_request_valid && !request_cache_eligible && dma_available && !init_cfg && !cache_flush) :
        ctrl_load_req;
    assign prefetch_grant_enabled = ctrl_load_req && !tl_busy && !init_cfg && !cache_flush;
    assign grant_without_lookup = !ctrl_request_valid &&
        (prefetch_enable_q ? prefetch_grant_enabled : load_ia_granted);
    assign grant_with_lookup = prefetch_enable_q ?
        (prefetch_grant_enabled && (request_cache_eligible || (dma_available && load_ia_granted))) :
        load_ia_granted;
    assign load_ia_req = request_without_lookup || (request_lookup_ready && request_with_lookup) ||
                             (prefetch_enable_q && ext_dma_start);
    assign ctrl_load_granted = grant_without_lookup || (request_lookup_ready && grant_with_lookup);
    assign prefetch_idle = !prefetch_pending && !prefetch_inflight;

    // A following command may consume the prefetched K group or reuse its
    // predecessor. Any other source/slot mapping cancels unissued requests.
    // Issued reads finish with their captured descriptor before job reconfiguration.
    localparam int p_context_groups = (REG_WIDTH + 2) / 3;
    localparam int p_context_parts = (p_context_groups + 5) / 6;
    logic [4:0][REG_WIDTH-1:0] context_left, context_right;
    logic [4:0] context_equal;
    assign context_left = {cfg_p0_base, k, ia_reuse_num, cfg_q0_base, cfg_q0_base};
    assign context_right = {prefetch_group_p0, prefetch_group_rows, prefetch_group_r,
        prefetch_descriptor.q0, prefetch_previous_q0};
    // 配置与归约坐标独立比较，预取保留资格只归并保存字段的比较结果。
    for (genvar value = 0; value < 5; value++) begin : g_prefetch_context
        (* keep = 1 *) logic [p_context_groups-1:0] groups_equal;
        (* keep = 1 *) logic [p_context_parts-1:0] parts_equal;
        for (genvar part = 0; part < p_context_groups; part++) begin : g_group
            localparam int p_first = part * 3;
            localparam int p_width = REG_WIDTH - p_first < 3 ? REG_WIDTH - p_first : 3;
            assign groups_equal[part] = context_left[value][p_first +: p_width] ==
                context_right[value][p_first +: p_width];
        end
        for (genvar part = 0; part < p_context_parts; part++) begin : g_part
            localparam int p_first = part * 6;
            localparam int p_width = p_context_groups - p_first < 6 ? p_context_groups - p_first : 6;
            assign parts_equal[part] = &groups_equal[p_first +: p_width];
        end
        assign context_equal[value] = &parts_equal;
    end
    wire prefetch_context_matches = cfg_prefetch_enable && cfg_preserve_cache &&
        (&context_equal[4:2]) && (context_equal[1] || context_equal[0]) &&
        (ORDERED_JOB || (
        (lhs_base + ((prefetch_descriptor.q0 - cfg_q0_base) <<
          ((cfg_tile_packed ? LOG2_SIZE : 0) + (use_16bits ? 1 : 0))) == prefetch_group_base) &&
        ((cfg_tile_packed ? (REG_WIDTH'(SIZE) << use_16bits) : lhs_row_stride_b) ==
         prefetch_descriptor.row_stride) &&
        (cfg_tile_packed == prefetch_descriptor.tile_packed) &&
        (lhs_zp == prefetch_descriptor.zp) &&
        (use_16bits == prefetch_descriptor.use16) &&
        (cfg_im2col == prefetch_descriptor.im2col) &&
        (compact_config_valid == prefetch_descriptor.compact) &&
        (DATA_WIDTH'(cfg_compact_offset) == prefetch_descriptor.offset) &&
        (incoming_cache_blocks == cache_blocks_q) &&
        (cfg_global_reduction == global_reduction_q))) &&
        (((CACHE_SLOT_W'(cfg_cache_slot_base) +
           (context_equal[1] ? CACHE_SLOT_W'(0) :
             CACHE_SLOT_W'(ia_reuse_num))) & incoming_slot_mask) == prefetch_group_slot);
    (* use_dsp = "yes" *) wire [REG_WIDTH-1:0] next_q0 = q0_base_q + REG_WIDTH'(SIZE);
    wire [REG_WIDTH-1:0] next_beats =
        (((tile_packed_q ? REG_WIDTH'(SIZE) : next_cols) << cfg_use_16bits) +
         REG_WIDTH'(BYTE_PER_BEAT - 1)) >> LOG2_BYTE_PER_BEAT;
    (* use_dsp = "yes" *) wire [REG_WIDTH-1:0] packed_prefetch_k_tiles =
        (global_reduction_q >> LOG2_SIZE) +
        REG_WIDTH'((global_reduction_q & REG_WIDTH'(SIZE-1)) != 0);
    wire [REG_WIDTH-1:0] prefetch_next_k_bytes = REG_WIDTH'(SIZE) <<
        ((tile_packed_q ? LOG2_SIZE : 0) + (cfg_use_16bits ? 1 : 0));

    (* use_dsp = "yes" *) logic [REG_WIDTH-1:0] prefetch_advanced_base, prefetch_first_base;
    assign prefetch_advanced_base = prefetch_descriptor.base_addr +
        (prefetch_descriptor.tile_packed ?
         (packed_prefetch_k_tiles << (2*LOG2_SIZE + (prefetch_descriptor.use16 ? 1 : 0))) :
         (prefetch_descriptor.row_stride << LOG2_SIZE));
    assign prefetch_first_base = cfg_lhs_base + prefetch_next_k_bytes;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            prefetch_pending <= 1'b0;
            prefetch_start <= 1'b0;
            prefetch_descriptor <= '0;
            prefetch_dma_descriptor <= '0;
            prefetch_rows_left <= '0;
            prefetch_group_p0 <= '0;
            prefetch_group_rows <= '0;
            prefetch_group_base <= '0;
            prefetch_group_r <= '0;
            prefetch_group_slot <= '0;
            prefetch_previous_q0 <= REG_WIDTH'(0) - REG_WIDTH'(SIZE);
        end else begin
            prefetch_start <= prefetch_issue;
            if (prefetch_issue) prefetch_dma_descriptor <= prefetch_descriptor;
            if (prefetch_advance) begin
                if (prefetch_rows_left <= REG_WIDTH'(SIZE)) prefetch_pending <= 1'b0;
                else begin
                    prefetch_rows_left <= prefetch_rows_left - REG_WIDTH'(SIZE);
                    prefetch_descriptor.base_addr <= prefetch_advanced_base;
                    prefetch_descriptor.p0 <= prefetch_descriptor.p0 + REG_WIDTH'(SIZE);
                    prefetch_descriptor.rows <= (prefetch_rows_left >= REG_WIDTH'(2 * SIZE)) ?
                        REG_WIDTH'(SIZE) : prefetch_rows_left - REG_WIDTH'(SIZE);
                    prefetch_descriptor.slot <= (prefetch_descriptor.slot + CACHE_SLOT_W'(1)) & cache_slot_mask;
                end
            end
            if (cache_l1_start && prefetch_enable_q && !prefetch_pending && !prefetch_inflight &&
                (next_q0 > q0_base_q) && (next_q0 < global_reduction_q)) begin
                prefetch_pending <= 1'b1;
                prefetch_rows_left <= cfg_k;
                prefetch_group_p0 <= p0_base_q;
                prefetch_group_rows <= cfg_k;
                prefetch_group_base <= prefetch_first_base;
                prefetch_group_r <= cfg_ia_reuse_num;
                prefetch_group_slot <= (cache_slot_base_q + CACHE_SLOT_W'(cfg_ia_reuse_num)) & cache_slot_mask;
                prefetch_descriptor.base_addr <= prefetch_first_base;
                prefetch_descriptor.row_stride <= tile_packed_q ?
                    (REG_WIDTH'(SIZE) << cfg_use_16bits) : cfg_lhs_row_stride_b;
                prefetch_descriptor.rows <= cfg_k >= REG_WIDTH'(SIZE) ? REG_WIDTH'(SIZE) : cfg_k;
                prefetch_descriptor.cols <= next_cols;
                prefetch_descriptor.zp <= cfg_lhs_zp;
                prefetch_descriptor.p0 <= p0_base_q;
                prefetch_descriptor.q0 <= next_q0;
                // 同一边沿保存当前列坐标及其前一分块坐标，重配置时直接比较。
                prefetch_previous_q0 <= q0_base_q;
                prefetch_descriptor.group <= '0;
                prefetch_descriptor.offset <= compact_offset_q;
                prefetch_descriptor.burst <= 8'(next_beats - REG_WIDTH'(1));
                prefetch_descriptor.use16 <= cfg_use_16bits;
                prefetch_descriptor.im2col <= im2col_q;
                prefetch_descriptor.compact <= cfg_compact_q;
                prefetch_descriptor.tile_packed <= tile_packed_q;
                prefetch_descriptor.slot <= (cache_slot_base_q + CACHE_SLOT_W'(cfg_ia_reuse_num)) & cache_slot_mask;
            end
            if (cache_flush || (init_cfg && !prefetch_context_matches)) prefetch_pending <= 1'b0;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fill_tag <= '0;
            fill_slot <= '0;
            fill_pending <= 1'b0;
            fill_is_prefetch <= 1'b0;
            cache_hit_done <= 1'b0;
        end else begin
            cache_hit_done <= cache_hit_event;
            if (cache_flush || (init_cfg &&
                (!cfg_preserve_cache || (compact_config_valid != cfg_compact_q)))) begin
                fill_pending <= 1'b0;
                cache_hit_done <= 1'b0;
            end else begin
                if (ext_dma_done && fill_pending) begin
                    fill_pending <= 1'b0;
                end
                if (ext_dma_start) begin
                    fill_tag <= descriptor_tag(dma_descriptor);
                    fill_slot <= dma_descriptor.slot;
                    fill_pending <= 1'b1;
                    fill_is_prefetch <= prefetch_start;
                end
            end
        end
    end

    for (genvar slot_index = 0; slot_index < SLOT_BLOCKS; slot_index++) begin : g_cache_valid
        (* keep = 1 *) logic demand_slot_selected, prefetch_slot_selected;
        logic invalidate_slot;
        // 两个已保存槽号先独立解码，启动条件只参与当前槽的最终写使能。
        assign demand_slot_selected = demand_descriptor.slot == CACHE_SLOT_W'(slot_index);
        assign prefetch_slot_selected = prefetch_dma_descriptor.slot == CACHE_SLOT_W'(slot_index);
        assign invalidate_slot = prefetch_start ? prefetch_slot_selected :
            (tl_start && !cache_hit_event && demand_slot_selected);
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n)
                cache_tags_valid[slot_index] <= 1'b0;
            else if (cache_flush || (init_cfg &&
                     (!cfg_preserve_cache || (compact_config_valid != cfg_compact_q))))
                cache_tags_valid[slot_index] <= 1'b0;
            else begin
                if (ext_dma_done && fill_pending && fill_slot == CACHE_SLOT_W'(slot_index))
                    cache_tags_valid[slot_index] <= 1'b1;
                if (invalidate_slot)
                    cache_tags_valid[slot_index] <= 1'b0;
            end
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && !cache_flush &&
            !(init_cfg && (!cfg_preserve_cache || (compact_config_valid != cfg_compact_q))) &&
            ext_dma_done && fill_pending)
            cache_tags[fill_slot] <= fill_tag;
    end

    assign ext_dma_start            = (tl_start && !cache_hit_event) || prefetch_start;
    assign ext_dma_is_write         = 1'b0;
    assign ext_dma_linear_read_mode = 1'b0;
    assign ext_dma_im2col           = dma_descriptor.im2col;
    assign ext_dma_p0               = dma_descriptor.p0;
    assign ext_dma_q0               = dma_descriptor.q0;
    assign ext_dma_group            = dma_descriptor.group;
    assign ext_dma_base_addr        = dma_descriptor.base_addr;
    assign ext_dma_row_stride       = dma_descriptor.row_stride;
    assign ext_dma_rows_to_read     = dma_descriptor.rows;
    assign ext_dma_burst_len_m1      = dma_descriptor.burst;
    assign ext_dma_slot_id          = dma_descriptor.slot;
    assign ext_dma_use_16bits       = dma_descriptor.use16;
    assign ext_dma_lhs_zp           = dma_descriptor.zp;

`ifdef NPU_SIM_ASSERT
    initial forever @(posedge clk) if (rst_n) begin
        if (ext_dma_start)
            assert (!fill_pending && !ext_dma_busy)
                else $fatal(1, "IA DMA descriptors overlap");
        if (prefetch_inflight && init_cfg)
            assert (cfg_preserve_cache && (compact_config_valid == cfg_compact_q) &&
                    (DATA_WIDTH'(cfg_compact_offset) == compact_offset_q))
                else $fatal(1, "IA job reconfiguration must wait for prefetch_idle");
        if (cache_flush)
            assert (prefetch_idle) else $fatal(1, "IA flush must wait for prefetch_idle");
    end
`endif

    // =======================================================================
    // ia_loader_ctrl 例化
    // =======================================================================
    ia_loader_ctrl #(
        .DATA_WIDTH  (DATA_WIDTH),
        .SIZE        (SIZE),
        .BUS_WIDTH   (BUS_WIDTH),
        .REG_WIDTH   (REG_WIDTH),
        .COUNT_WIDTH (COUNT_WIDTH),
        .CACHE_BLOCKS(CACHE_BLOCKS),
        .COMPACT_S8(COMPACT_S8),
        .PS_FRAME_COUNT(PS_FRAME_COUNT),
        .p_precomputed_packed_tiles(1'b1),
        .p_precomputed_frame_rows(1'b1),
        .p_precomputed_slot_mask(1'b1),
        .p_indexed_slot_rows(1'b1),
        .p_parallel_request_match(ORDERED_JOB)
    ) u_ctrl (
        .clk  (clk),
        .rst_n(rst_n),

        .cfg_valid           (ctrl_init_start),
        .cfg_compact         (cfg_compact_q),
        .cfg_cache_blocks    (cache_blocks_q),
        .cfg_slot_mask(cache_slot_mask),
        .cfg_k               (cfg_k),
        .cfg_n               (cfg_n),
        .cfg_use_16bits      (cfg_use_16bits),
        .cfg_tile_packed     (tile_packed_q),
        .cfg_packed_reduction(global_reduction_q),
        .cfg_packed_k_tiles  (ctrl_i_packed_k_tiles),
        .cfg_bias_by_row_mode(cfg_bias_by_row_mode),
        .cfg_bias_at_end    (cfg_bias_at_end),
        .cfg_lhs_base        (cfg_lhs_base),
        .cfg_lhs_row_stride_b(cfg_lhs_row_stride_b),
        .cfg_lhs_zp          (cfg_lhs_zp),
        .cfg_ia_reuse_num    (cfg_ia_reuse_num),
        .cfg_w_reuse_num     (cfg_w_reuse_num),

        .horizontal_tile_num     (horizontal_tile_num),
        .vertical_tile_num       (vertical_tile_num),
        .l2_group_num            (l2_group_num),
        .l1_per_l2               (l1_per_l2),
        .ia_reuse_num_act        (ia_reuse_num_act),
        .output_col_tile_num     (output_col_tile_num),
        .w_groups_total          (w_groups_total),
        .w_group_last_width      (w_group_last_width),
        .rsp_beats_per_row_normal(rsp_beats_per_row_normal),
        .rsp_beats_per_row_last  (rsp_beats_per_row_last),
        .rsp_rows_last_tile      (rsp_rows_last_tile),
        .cfg_frame_rows_last      (frame_last_rows_q),

        .init_start     (ctrl_init_start),
        .load_ia_req    (ctrl_load_req),
        .load_ia_granted(ctrl_load_granted),
        .send_ia_trigger(send_ia_trigger),
        .ia_data_valid  (ia_data_valid),
        .ps_frame_rows  (ps_frame_rows),
        .ps_frame_id    (ps_frame_id),
        .ps_frame_init  (ps_frame_init),
        .ps_frame_final (ps_frame_final),
        .ia_sending_done(ia_sending_done),
        .ia_l1_switch   (ia_l1_switch),
        .bias_sleep     (bias_sleep),
        .bias_load_sleep(bias_load_sleep),
        .bias_switch    (bias_switch),
        .bias_last_loop (bias_last_loop),
        .all_done       (ctrl_all_done),

        .tl_start       (tl_start),
        .tl_base_addr   (tl_base_addr),
        .tl_p0          (unused_tl_p0),
        .tl_q0          (unused_tl_q0),
        .tl_group       (tl_group),
        .tl_row_stride  (tl_row_stride),
        .tl_rows_to_read(tl_rows_to_read),
        .tl_valid_cols  (tl_valid_cols),
        .tl_burst_len_m1(tl_burst_len_m1),
        .tl_slot_id     (tl_slot_id),
        .tl_use_16bits  (tl_use_16bits),
        .tl_lhs_zp      (tl_lhs_zp),
        .tl_busy        (tl_busy),
        .tl_tile_done   (tl_tile_done),
        .request_valid(ctrl_request_valid),
        .request_base_addr(request_base_addr),
        .request_p0(request_p0), .request_q0(request_q0), .request_group(request_group),
        .request_q0_base(q0_base_q[REG_WIDTH-1:LOG2_SIZE]),
        .request_q0_target(request_lookup_q[$clog2(SIZE + 1) +: REG_WIDTH-LOG2_SIZE]),
        .request_q0_matches(request_q0_matches),
        .request_rows(request_rows), .request_cols(request_cols),
        .request_burst_len_m1(request_burst_len_m1), .request_slot(request_slot),

        .cache_l1_start     (cache_l1_start),
        .cache_l1_slot_start(cache_l1_slot_start),
        .cache_l1_slot_end  (cache_l1_slot_end),
        .cache_l1_is_init   (cache_l1_is_init),
        .cache_l1_calc_done (cache_l1_calc_done),
        .cache_slot_rows    (cache_slot_rows),
        .cache_row_index(cache_row_index), .cache_row_value(cache_row_value),
        .cache_tile_done    (cache_tile_done),
        .cache_l1_done      (cache_l1_done)
    );

    assign ia_output_pending = cache_l1_calc_done;

    // Stage the L1 launch command between ctrl and cache_mgr.  The command is
    // not throughput-critical (one pulse per L1 group), and this breaks a long
    // blk_valid/send_ready -> diagonalizer start path at high cache counts.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cache_l1_start_q      <= 1'b0;
            cache_l1_slot_start_q <= '0;
            cache_l1_slot_end_q   <= '0;
            cache_l1_is_init_q    <= 1'b0;
            cache_l1_calc_done_q  <= 1'b0;
        end else begin
            cache_l1_start_q <= cache_l1_start;
            if (cache_l1_start) begin
                cache_l1_slot_start_q <= (cache_l1_slot_start + cache_slot_base_q) & cache_slot_mask;
                cache_l1_slot_end_q   <= (cache_l1_slot_end + cache_slot_base_q) & cache_slot_mask;
                cache_l1_is_init_q    <= cache_l1_is_init;
                cache_l1_calc_done_q  <= cache_l1_calc_done;
            end
        end
    end

    // =======================================================================
    // DMA 接入：通过 npu_top 的共享 AXI block_dma 写入本地 cache
    // =======================================================================
    logic [REG_WIDTH-1:0] active_valid_cols;
    localparam int p_column_values = 1 << LOG2_SIZE;
    localparam int p_valid_mask_width = p_column_values + DMA_LANES - 1;
    localparam int p_element_width = $clog2(p_valid_mask_width);
    logic [p_valid_mask_width-1:0] active_column_mask;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active_valid_cols <= REG_WIDTH'(SIZE);
        end else if (ext_dma_start) begin
            active_valid_cols <= (dma_descriptor.cols == '0) ? REG_WIDTH'(SIZE) : dma_descriptor.cols;
        end
    end

    if (REG_WIDTH >= p_element_width) begin : g_column_mask
        // 描述符接收时保存所有可到达列的有效位，写入周期直接选择对应列。
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                for (int col = 0; col < p_valid_mask_width; col++)
                    active_column_mask[col] <= REG_WIDTH'(col) < REG_WIDTH'(SIZE);
            end else if (ext_dma_start) begin
                for (int col = 0; col < p_valid_mask_width; col++)
                    active_column_mask[col] <= dma_descriptor.cols == '0 ?
                        REG_WIDTH'(col) < REG_WIDTH'(SIZE) : REG_WIDTH'(col) < dma_descriptor.cols;
            end
        end
    end else begin : g_narrow_column_mask
        assign active_column_mask = '0;
    end

    // Every read, including im2col, returns through the ordinary shared DMA
    // matrix-block interface. DMA owns input fetching, padding and correction.
    assign tl_busy = tl_start || cache_hit_done ||
        (prefetch_enable_q ? (fill_pending && !fill_is_prefetch) :
                            (ext_dma_busy || fill_pending || prefetch_start));
    assign tl_tile_done = (ext_dma_done && !fill_is_prefetch) || cache_hit_done;
    assign tl_wr_slot       = ext_dma_wr_slot;
    assign tl_wr_row        = ext_dma_wr_row;
    assign tl_wr_col_base   = ext_dma_wr_col_base;
    assign tl_wr_use_16bits = ext_dma_wr_use_16bits;

    generate
        for (genvar dma_i = 0; dma_i < DMA_LANES; dma_i++) begin : gen_ext_wr
            localparam int unsigned DMA_I = dma_i;
            wire [REG_WIDTH-1:0] elem_col =
                REG_WIDTH'(ext_dma_wr_col_base) + REG_WIDTH'(DMA_I);
            logic elem_in_tile, elem_valid;
            if (REG_WIDTH >= p_element_width) begin : g_direct_column
                logic [p_column_values-1:0] lane_valid_columns;

                // 通道偏移选择固定的位区间，动态索引只包含原始写入列。
                assign lane_valid_columns = active_column_mask[DMA_I+:p_column_values];
                assign elem_valid = lane_valid_columns[ext_dma_wr_col_base];
                if (DMA_I < SIZE) begin : g_in_tile
                    assign elem_in_tile = REG_WIDTH'(ext_dma_wr_col_base) < REG_WIDTH'(SIZE-DMA_I);
                end else begin : g_outside_tile
                    assign elem_in_tile = 1'b0;
                end
            end else begin : g_wrapped_column
                assign elem_in_tile = elem_col < REG_WIDTH'(SIZE);
                assign elem_valid = elem_col < active_valid_cols;
            end
            assign tl_wr_data[dma_i] = elem_valid ? ext_dma_wr_data[dma_i] : '0;
            assign tl_wr_valid[dma_i] = ext_dma_wr_valid[dma_i] && elem_in_tile;
        end
    endgenerate

    // =======================================================================
    // 缓存管理子模块例化
    // 紧凑模式仅接受 -127 到 128 的偏移，读出重建使用九位有符号偏移。
    // =======================================================================
    ia_loader_cache_mgr #(
        .DATA_WIDTH  (DATA_WIDTH),
        .SIZE        (SIZE),
        .BUS_WIDTH   (BUS_WIDTH),
        .DMA_LANES   (DMA_LANES),
        .REG_WIDTH   (REG_WIDTH),
        .CACHE_BLOCKS(CACHE_BLOCKS),
        .COMPACT_S8(COMPACT_S8),
        .EXTERNAL_RAM(EXTERNAL_RAM),
        .RAM_WORD_ADDR_WIDTH(RAM_WORD_ADDR_WIDTH),
        .p_compact_offset_width((DATA_WIDTH == 16) ? 9 : DATA_WIDTH),
        .p_dma_source_layout(p_dma_source_layout),
        .p_shared_write_stage(p_shared_write_stage),
        .p_precomputed_slot_mask(1'b1),
        .p_indexed_slot_rows(1'b1)
    ) u_cache_mgr (
        .clk  (clk),
        .rst_n(rst_n),

        .compact_mode (cfg_compact_q),
        .compact_offset(compact_offset_q),
        .cfg_cache_blocks(cache_blocks_q),
        .cfg_slot_mask(cache_slot_mask),
        .slot_base(cache_slot_base_q),
        .ram_port_wr_en, .ram_port_wr_addr, .ram_port_wr_data, .ram_port_wr_mask,
        .ram_shared_wr_data,
        .ram_port_rd_en, .ram_port_rd_addr, .ram_port_rd_data,

        // ---- 写入端（来自 tile_loader）----
        .wr_slot      (tl_wr_slot),
        .wr_row       (tl_wr_row),
        .wr_col_base  (tl_wr_col_base),
        .wr_data      (tl_wr_data),
        .wr_valid     (tl_wr_valid),
        .wr_use_16bits(tl_wr_use_16bits),

        // ---- L1组发送控制（来自 ctrl）----
        .l1_start     (cache_l1_start_q),
        .l1_slot_start(cache_l1_slot_start_q),
        .l1_slot_end  (cache_l1_slot_end_q),
        .l1_is_init   (cache_l1_is_init_q),
        .l1_calc_done (cache_l1_calc_done_q),
        .slot_rows    (cache_slot_rows),
        .row_table_index(cache_row_index), .row_table_value(cache_row_value),
        .tile_done    (cache_tile_done),
        .l1_done      (cache_l1_done),
        .ia_tile_start(ia_tile_start),

        // ---- 输出到脉动阵列 ----
        .ia_out         (ia_out),
        .ia_row_valid   (ia_row_valid),
        .ia_is_init_data(ia_is_init_data),
        .ia_calc_done   (ia_calc_done)
    );

endmodule

// 比较坐标加法结果的高位，结果保留 p_width 位。
module ia_ordered_coordinate_equal #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_low_width = 4,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_lut = 1'b0
`elsif XILINX_FPGA
    parameter bit p_use_lut = 1'b1
`else
    parameter bit p_use_lut = 1'b0
`endif
) (
    input  logic [p_width-1:0] i_a,
    input  logic [p_width-1:0] i_b,
    input  logic [p_width-p_low_width-1:0] i_target,
    output logic o_equal
);
    //! 0. 辅助定义
    //! -----------

    localparam int unsigned p_high_width = p_width - p_low_width;
    logic carry_in;

    //! 1. 计算坐标进位条件
    //! -------------------

    if (p_low_width > 0) begin : g_low_carry
        logic [p_low_width-1:0] unused_low_sum;
        // 只消费低位进位，分组生成条件避免先计算完整低位和值。
        parallel_prefix_add #(
            .p_width(p_low_width), .p_group_width(3), .p_preserve_groups(1'b1)
        ) u_low_carry (
            .i_a(i_a[p_low_width-1:0]), .i_b(i_b[p_low_width-1:0]), .i_carry(1'b0),
            .o_sum(unused_low_sum), .o_carry(carry_in)
        );
    end else begin : g_no_low_carry
        assign carry_in = 1'b0;
    end
    //! 2. 生成坐标比较结果
    //! -------------------

    // 相邻两位的进位一致性并行计算，公共比较器保留每位实际计算结果。
    add_equal #(.p_width(p_high_width), .p_use_lut(p_use_lut)) u_high_equal (
        .i_a(i_a[p_width-1:p_low_width]), .i_b(i_b[p_width-1:p_low_width]),
        .i_target(i_target), .i_carry_in(carry_in), .o_equal(o_equal)
    );
endmodule
