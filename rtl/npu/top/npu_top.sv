`default_nettype none

`ifndef GEMMORA_PS_POOL_BYTES
`define GEMMORA_PS_POOL_BYTES 12288
`endif
// NPU 顶层模块：矩阵/卷积算子的分块计算、量化和写回数据通路
module npu_top #(
    parameter int unsigned WEIGHT_WIDTH = 16,  // 权重数据宽度；WS 下 s8 符号扩展，IS+s16 下使用 16bit LHS
    parameter int unsigned DATA_WIDTH = 16,  // IA数据宽度
    parameter int unsigned SIZE = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH = 32,  // 总线宽度
    parameter int unsigned REG_WIDTH = 32,  // 寄存器宽度
    parameter int unsigned ADDR_WIDTH = 19,  // AXI 地址宽度
    parameter int unsigned IA_CACHE_BLOCKS = 4,  // 16 位输入分块的物理缓存容量。
    parameter int unsigned IA_COMPACT_ENABLE = 0,
    parameter int unsigned SHARED_IA_PS_ENABLE = 1,
    parameter bit p_fixed_ps_channels =
`ifdef ASIC_SYNTHESIS
        1'b0,
`elsif ASIC_SRAM
        1'b0,
`else
        1'b1,
`endif
    parameter int unsigned SHARED_BANK_BYTES = 2048,
    parameter int unsigned SHARED_BANK_COUNT = 0,
    parameter int unsigned SHARED_TOTAL_BYTES = SHARED_BANK_COUNT != 0 ?
        SHARED_BANK_COUNT * SHARED_BANK_BYTES :
        IA_CACHE_BLOCKS * SIZE * SIZE * DATA_WIDTH / 8 + `GEMMORA_PS_POOL_BYTES,
    parameter bit FRAME_PREFETCH_ENABLE = 1'b1,
    parameter int unsigned OPERAND_CACHE_ENABLE = 0,
    parameter int unsigned IM2COL_CACHE_BYTES = 4096,
    parameter int unsigned CONV_CACHE_WAYS = 2,
    parameter int unsigned CONV_LINE_BYTES = 128,
    parameter int unsigned CONV_CACHE_SETS = IM2COL_CACHE_BYTES / (CONV_CACHE_WAYS * CONV_LINE_BYTES),
    parameter int unsigned CONV_CACHE_POLICY = 3,
    parameter int unsigned ENABLE_DW_POOL = 1,
    parameter int unsigned DW_PE_COUNT = (SIZE < 16) ? SIZE : 16,
    parameter int unsigned ENABLE_VECTOR_ENGINE = ENABLE_DW_POOL,
    parameter int unsigned VECTOR_PE_COUNT = DW_PE_COUNT,
    parameter int unsigned WINDOW_LANES = VECTOR_PE_COUNT >= 16 ? 16 : BUS_WIDTH / 8,
    parameter int unsigned DW_MAX_TAPS = 49,
    parameter int unsigned POOL_MAX_TAPS = 256,
    parameter int unsigned PS_FRAME_COUNT = SIZE,  // PS buffer 可保留的输出列 tile 数
    parameter int unsigned PS_STORAGE_ROWS = ((3*SIZE)-1)*(PS_FRAME_COUNT+1),
    parameter int unsigned OA_S16_FIFO_BANKS_MAX = 4,
    parameter int unsigned OPERAND_STREAM_BYTES = (PS_FRAME_COUNT >= 16) ? 65536 : 262144,
    parameter int unsigned DMA_MAX_BYTES = 256*(BUS_WIDTH/8),
    parameter int unsigned AXI_READ_OUTSTANDING = 4,  // AXI 读通道最多提前排队的 burst 数
    parameter int unsigned AXI_WRITE_OUTSTANDING = AXI_READ_OUTSTANDING,  // AXI 写通道最多提前排队的 burst 数
    parameter int unsigned ENABLE_IS_MODE = 1,  // 置 0 时综合裁剪 IS 转置/分组 bias 支持
    parameter int unsigned ENABLE_PER_CHANNEL = 1,  // 置 0 时综合裁剪 per-channel 量化装载路径
    parameter int unsigned OA_FIFO_BANKS_MAX = 0  // 0 表示按最大输入分组选择容量。
) (
    //==== 时钟与复位 ====
    input wire logic clk,   // 系统时钟
    input wire logic rst_n, // 异步复位，低有效

    //==== 外部控制接口 ====
    input wire logic cfg_operand_fetch64, // 0：16 字节扇区；1：64 字节读取范围。
    input wire logic cfg_lhs_tile_packed = 1'b0,
    input wire logic cfg_rhs_tile_packed = 1'b0,
    input wire logic cfg_conv_enable = 1'b0,
    input wire conv_im2col_pkg::conv_cfg_t cfg_conv = '0,
    input wire logic cfg_vector_enable = 1'b0,
    input wire vector_engine_pkg::vector_engine_cfg_t cfg_vector = '0,
    input wire logic calc_start,  // 计算开始信号
    input wire logic cfg_16bits_ia,  // 使用16位IA数据
    input wire logic cfg_16x8,  // TFLM 16 位激活、8 位权重、32 位偏置和 16 位输出。
    input wire logic cfg_dataflow_mode,  // 0: WS, 1: IS
    input wire logic [REG_WIDTH-1:0] cfg_ia_reuse_num,  // IA L1 组复用深度，ABI 2: 外部写入最终生效值，0 非法
    input wire logic [REG_WIDTH-1:0] cfg_w_reuse_num,   // W 侧复用窗口，ABI 2: 外部写入最终生效值，0 非法
    input wire logic [REG_WIDTH-1:0] cfg_row_groups,
    input wire logic [REG_WIDTH-1:0] cfg_row_tail_tiles,
    input wire logic [REG_WIDTH-1:0] cfg_col_groups,
    input wire logic [REG_WIDTH-1:0] cfg_col_tail_tiles,
    input wire logic [31:0] cfg_ps_control = 32'd0,
    input wire logic [31:0] cfg_shared_ia_banks = 32'd0,
    output logic sa_ready,  // 系统就绪信号

    //==== 完成握手接口 ====
    output logic       done_valid,  // 任务完成有效信号
    input wire logic       done_ready,  // 任务完成接收就绪信号
    output logic [1:0] err_code,  // 完成状态码

    // 张量起始地址
    input wire logic [REG_WIDTH-1:0] lhs_base,  // A 起始地址（MULT_LHS_PTR）
    input wire logic [REG_WIDTH-1:0] rhs_base,  // B 起始地址（MULT_RHS_PTR），8 位数据按 N × K 行优先存储。
    input wire logic [REG_WIDTH-1:0] dst_base,  // C 起始地址（MULT_DST_PTR）
    input wire logic [REG_WIDTH-1:0] bias_base, // 32 位偏置起始地址，0 表示不使用偏置（MULT_BIAS_PTR）。

    // 量化参数和零点
    input wire logic signed [REG_WIDTH-1:0] lhs_zp,          // A 零点（MULT_LHS_OFFSET）
    input wire logic signed [REG_WIDTH-1:0] rhs_zp,          // B 零点（MULT_RHS_OFFSET）
    input wire logic signed [REG_WIDTH-1:0] dst_zp,          // C 零点（MULT_DST_OFFSET）
    input wire logic signed [REG_WIDTH-1:0] q_mult_pt,       // 逐张量量化乘数（MULT_DST_MULT）
    input wire logic signed [REG_WIDTH-1:0] q_shift_pt,      // 逐张量量化移位量
    // MULT_DST_SHIFT：正值表示右移位数。
    input wire logic                        use_per_channel, // 1：逐通道量化；0：逐张量量化。

    // 矩阵尺寸
    input wire logic [REG_WIDTH-1:0] k,  // IA矩阵行数
    input wire logic [REG_WIDTH-1:0] n,  // IA矩阵列数 = W矩阵行数
    input wire logic [REG_WIDTH-1:0] m,  // W矩阵列数

    // 行列步长，单位均为字节。
    input wire logic [REG_WIDTH-1:0] lhs_row_stride_b,  // A 行步长（MULT_LHS_COLS_OFFSET）
    input wire logic [REG_WIDTH-1:0] dst_row_stride_b,  // C 行步长（MULT_ROW_ADDR_OFFSET）
    input wire logic [REG_WIDTH-1:0] rhs_col_stride_b,  // 转置后 B 的列步长（MULT_RHS_ROW_STRIDE）

    // 激活范围
    input wire logic signed [REG_WIDTH-1:0] act_min,  // (MULT_ACT_MIN)
    input wire logic signed [REG_WIDTH-1:0] act_max,  // (MULT_ACT_MAX)

    //==== AXI4 master 接口 ====
    output logic                   m_axi_arvalid,
    input wire logic                   m_axi_arready,
    output logic [  REG_WIDTH-1:0] m_axi_araddr,
    output logic [            7:0] m_axi_arlen,
    output logic [            2:0] m_axi_arsize,
    output logic [            1:0] m_axi_arburst,
    input wire logic                   m_axi_rvalid,
    output logic                   m_axi_rready,
    input wire logic [  BUS_WIDTH-1:0] m_axi_rdata,
    input wire logic [            1:0] m_axi_rresp,
    input wire logic                   m_axi_rlast,

    output logic                   m_axi_awvalid,
    input wire logic                   m_axi_awready,
    output logic [  REG_WIDTH-1:0] m_axi_awaddr,
    output logic [            7:0] m_axi_awlen,
    output logic [            2:0] m_axi_awsize,
    output logic [            1:0] m_axi_awburst,
    output logic                   m_axi_wvalid,
    input wire logic                   m_axi_wready,
    output logic [  BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic                   m_axi_wlast,
    input wire logic                   m_axi_bvalid,
    output logic                   m_axi_bready,
    input wire logic [            1:0] m_axi_bresp
);

`ifdef GEMMORA_INT8_PROFILE
    localparam int unsigned IA_DATA_WIDTH = DATA_WIDTH;
`endif
`ifndef GEMMORA_INT8_PROFILE
    localparam int unsigned IA_DATA_WIDTH =
    (DATA_WIDTH < 16) ? 16 : DATA_WIDTH;
`endif
`ifdef GEMMORA_INT8_PROFILE
    localparam int unsigned KERNEL_DATA_WIDTH = WEIGHT_WIDTH;
`endif
`ifndef GEMMORA_INT8_PROFILE
    localparam int unsigned KERNEL_DATA_WIDTH =
    (WEIGHT_WIDTH < 16) ? 16 : WEIGHT_WIDTH;
`endif
`ifdef GEMMORA_INT8_PROFILE
    localparam bit VECTOR_ENGINE_CAPABLE = 1'b0;
`endif
`ifndef GEMMORA_INT8_PROFILE
    localparam bit VECTOR_ENGINE_CAPABLE = ENABLE_VECTOR_ENGINE != 0 && (BUS_WIDTH == 32 || BUS_WIDTH == 64) && REG_WIDTH == 32 &&
    SIZE >= 2 && SIZE <= 64 && ((SIZE & (SIZE-1)) == 0) &&
    DW_MAX_TAPS >= 1 && DW_MAX_TAPS <= 255 &&
    POOL_MAX_TAPS >= 1 && POOL_MAX_TAPS <= 65535 && VECTOR_PE_COUNT >= 1 &&
    VECTOR_PE_COUNT <= SIZE && ((VECTOR_PE_COUNT & (VECTOR_PE_COUNT-1)) == 0);
`endif
    localparam int unsigned SIZE_SHIFT = $clog2(SIZE);
    localparam int unsigned BIAS_DMA_SIZE = SIZE * 4;
    localparam int unsigned SHARED_DMA_SIZE =
    (BIAS_DMA_SIZE > SIZE) ? BIAS_DMA_SIZE : SIZE;
    localparam int unsigned MATRIX_INPUT_LANES =
    WINDOW_LANES > BUS_WIDTH/8 ? WINDOW_LANES : BUS_WIDTH/8;
`ifdef GEMPACT_PS_COMPRESS
    localparam bit SHARED_RAM_ENABLED = SHARED_IA_PS_ENABLE != 0 &&
    SIZE == 16 && DATA_WIDTH == 16 && (BUS_WIDTH == 32 || BUS_WIDTH == 64) &&
    (SHARED_BANK_BYTES == 2048 || SHARED_BANK_BYTES == 4096 || SHARED_BANK_BYTES == 8192) &&
    SHARED_TOTAL_BYTES >= 6 * SHARED_BANK_BYTES &&
    SHARED_TOTAL_BYTES <= 9 * SHARED_BANK_BYTES &&
    SHARED_TOTAL_BYTES % SHARED_BANK_BYTES == 0;
`endif
`ifndef GEMPACT_PS_COMPRESS
    localparam bit SHARED_RAM_ENABLED = 1'b0;
`endif
    localparam int unsigned SHARED_PHYSICAL_BANKS = SHARED_TOTAL_BYTES / SHARED_BANK_BYTES;
    localparam int unsigned REQUANT_COMPUTE_LANES =
    SHARED_RAM_ENABLED && SHARED_PHYSICAL_BANKS < 8 && SIZE > 2 && (SIZE % 2) == 0 ? 2 : SIZE;
    localparam bit DW_SHARED_QUANT_ENABLE = REQUANT_COMPUTE_LANES == SIZE;
    localparam int unsigned SHARED_PHYSICAL_BANKS_WIDTH =
    ($clog2(SHARED_PHYSICAL_BANKS+1) > 0) ? $clog2(SHARED_PHYSICAL_BANKS+1) : 1;
    localparam int unsigned SHARED_MAX_IA_BANKS =
    SHARED_PHYSICAL_BANKS >= 8 ? 4 : 2;
    localparam int unsigned IA_MAX_CACHE_BLOCKS = SHARED_RAM_ENABLED ?
    SHARED_MAX_IA_BANKS * SHARED_BANK_BYTES / (SIZE * SIZE * IA_DATA_WIDTH / 8) : IA_CACHE_BLOCKS;
    localparam int unsigned SHARED_IA_ADDR_WIDTH =
    ($clog2(SHARED_TOTAL_BYTES / 16) > 0) ? $clog2(SHARED_TOTAL_BYTES / 16) : 1;
    localparam int unsigned SHARED_PS_ADDR_WIDTH =
    SHARED_RAM_ENABLED ? SHARED_IA_ADDR_WIDTH :
    (($clog2(`GEMMORA_PS_POOL_BYTES / 64) > 0) ? $clog2(`GEMMORA_PS_POOL_BYTES / 64) : 1);
    localparam int unsigned SHARED_PS_DIRECTORY_ROWS = 1024;
    localparam int unsigned VECTOR_SHARED_IA_BANKS =
    DW_MAX_TAPS * SIZE <= SHARED_BANK_BYTES ? 1 :
    DW_MAX_TAPS * SIZE <= 2 * SHARED_BANK_BYTES ? 2 : 4;
`ifdef GEMPACT_PS_COMPRESS
    localparam bit FRAME_EXEC_ENABLED = SIZE == 16;
`endif
`ifndef GEMPACT_PS_COMPRESS
    localparam bit FRAME_EXEC_ENABLED = 1'b0;
`endif
    localparam int unsigned PS_FRAME_ID_W = (PS_FRAME_COUNT > 1) ? $clog2(PS_FRAME_COUNT) : 1;
    localparam int unsigned IA_SLOT_BLOCKS =
    ((IA_COMPACT_ENABLE != 0) && (IA_DATA_WIDTH == 16))
    ? 2 * IA_MAX_CACHE_BLOCKS : IA_MAX_CACHE_BLOCKS;
    localparam int unsigned IA_CACHE_SLOT_W = (IA_SLOT_BLOCKS <= 1) ? 1 : $clog2(IA_SLOT_BLOCKS);

`ifdef GEMMORA_INT8_PROFILE
    // 该配置使用零偏移的 INT8 操作数，任务开始时检查输入。

`else

`endif
    typedef enum logic [1:0] {AB_IDLE, AB_DRAIN, AB_RESET, AB_DONE} abort_t;
    abort_t abort_state;

    // 中止资格与状态转换同时保存，DMA 接收控制直接读取该寄存结果。
    logic abort_pending_q;
    logic core_rst_n;
    logic [1:0] abort_error_code;
    logic [31:0] conv_range_base [4];
    logic [32:0] conv_range_end [4];
    logic task_fault;
    logic load_ia_granted;
    logic task_accept_ready;
    logic task_accept_conditions;

    // 任务接收后保持卷积配置；AXI-Lite 接口在任务执行期间禁止修改配置。
    logic run_conv;
    logic run_vector;
    logic vector_rejected;
    logic run_lhs_tile_packed;
    logic run_rhs_tile_packed;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin run_lhs_tile_packed <= 0; run_rhs_tile_packed <= 0; end
        else if (calc_start && sa_ready) begin
            run_lhs_tile_packed <= cfg_lhs_tile_packed;
            run_rhs_tile_packed <= cfg_rhs_tile_packed;
        end
    end
    logic [31:0] ps_control_q;
    logic vector_engine_ready;
    logic vector_engine_done;
    logic vector_start_fire;
    logic vector_shared_store_o_idle;
    logic vector_shared_store_o_error;
    logic [1:0] vector_engine_error;
    logic normal_done_valid;
    logic task_completion_pending;
    logic task_completion_accept;
    logic [1:0] normal_err_code;
    logic vector_dma_cfg_valid;
    logic vector_dma_conv_enable;
    logic vector_dma_range_enable;

`ifdef NPU_SIM_ASSERT
    initial begin : check_im2col_capacity
        if (IM2COL_CACHE_BYTES < 512 || IM2COL_CACHE_BYTES > 65536 ||
            (IM2COL_CACHE_BYTES & (IM2COL_CACHE_BYTES - 1)) != 0)
            $fatal(1, "IM2COL_CACHE_BYTES must be a power of two from 512 to 65536");
    end
`endif

    conv_im2col_pkg::conv_cfg_t vector_dma_conv_cfg;

    logic [31:0] vector_dma_range_base [4];
    logic [31:0] selected_range_base [4];
    logic [32:0] vector_dma_range_end [4];
    logic [32:0] selected_range_end [4];

    assign vector_start_fire = VECTOR_ENGINE_CAPABLE && calc_start && sa_ready &&
        cfg_vector_enable && !cfg_conv_enable;
    // 后台通道全部空闲后保存接收资格，接收新任务的边沿立即清除该状态。
    // 当前故障和中止状态继续直接禁止接收，任务字段仅在公开握手时保存。
    assign sa_ready = task_accept_ready && abort_state == AB_IDLE && !task_fault;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            task_accept_ready <= 1'b0;
        end else if ((calc_start && sa_ready) || abort_state != AB_IDLE) begin
            task_accept_ready <= 1'b0;
        end else begin
            task_accept_ready <= task_accept_conditions;
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            run_vector <= 1'b0;
            vector_rejected <= 1'b0;
        end else begin
            if (calc_start && sa_ready) begin
                run_vector <= cfg_vector_enable;
                vector_rejected <= cfg_vector_enable && (!VECTOR_ENGINE_CAPABLE || cfg_conv_enable);
            end else if (run_vector && done_valid && done_ready) begin
                run_vector <= 1'b0;
                vector_rejected <= 1'b0;
            end
        end
    end
    // 排空判断完成后保存一次完成事件，外部背压期间保持，接收后清除。
    // 子模块的完成握手与公开握手使用同一个寄存事件。
    always_ff @(posedge clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            task_completion_pending <= 1'b0;
        end else if (abort_state != AB_IDLE || task_fault || (calc_start && sa_ready)) begin
            task_completion_pending <= 1'b0;
        end else if (task_completion_pending) begin
            if (done_ready) task_completion_pending <= 1'b0;
        end else begin
            task_completion_pending <= run_vector ?
                (vector_rejected || (vector_engine_done && vector_shared_store_o_idle)) : normal_done_valid;
        end
    end
    assign done_valid = (abort_state == AB_DONE) ||
                        ((abort_state == AB_IDLE) && !task_fault && task_completion_pending);
    assign task_completion_accept = task_completion_pending && done_ready &&
        (abort_state == AB_IDLE) && !task_fault;
    assign err_code = (abort_state == AB_DONE) ? abort_error_code :
                      run_vector ? (vector_rejected ? 2'b01 : vector_engine_error) : normal_err_code;
    for (genvar r = 0; r < 4; r++) begin : g_dma_ranges
        assign selected_range_base[r] = run_vector ? vector_dma_range_base[r] : conv_range_base[r];
        assign selected_range_end[r] = run_vector ? vector_dma_range_end[r] : conv_range_end[r];
    end
    conv_im2col_pkg::conv_cfg_t conv_cfg_q;

    logic conv_error;
    logic conv_busy;
    logic dma_bus_error;
    logic dma_idle;
    logic conv_cfg_ready;
    logic operand_cache_idle;
    logic ia_prefetch_idle;
    logic kernel_prefetch_idle;
    logic block_dma_arbiter_o_kernel_eligible;
    logic frame_prefetch_idle;

    assign frame_prefetch_idle = ia_prefetch_idle && kernel_prefetch_idle;

    // 图像描述符可在预取期间完成，整层完成和下一任务接收仍等待实际读取结束。
    logic conv_task_idle;

    assign conv_task_idle = !run_conv || (dma_idle && !conv_busy);

    logic arbiter_ia_granted;
    logic legacy_axi_arvalid;
    logic legacy_axi_arready;
    logic legacy_axi_rvalid;
    logic legacy_axi_rready;
    logic legacy_axi_rlast;
    logic [REG_WIDTH-1:0] legacy_axi_araddr;
    logic [BUS_WIDTH-1:0] legacy_axi_rdata;
    logic [7:0] legacy_axi_arlen;
    logic [2:0] legacy_axi_arsize;
    logic [1:0] legacy_axi_arburst;
    logic [1:0] legacy_axi_rresp;
    logic abort_pending;

    assign abort_pending = abort_pending_q;

    assign core_rst_n = rst_n && (abort_state != AB_RESET);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            run_conv <= 1'b0; conv_cfg_q <= '0; abort_state <= AB_IDLE;
            abort_pending_q <= 1'b0;
            ps_control_q <= '0;
            abort_error_code <= 2'b11;

        end else begin
            if (calc_start && sa_ready) begin
                run_conv <= cfg_conv_enable && !cfg_vector_enable;
                conv_cfg_q <= cfg_conv;
                ps_control_q <= cfg_ps_control;

            end
            case (abort_state)
                AB_IDLE: if (task_fault) begin
                    abort_state <= AB_DRAIN;
                    abort_pending_q <= 1'b1;
                    abort_error_code <= (dma_bus_error || ((run_conv || run_vector) && conv_error))
                                        ? 2'b11 : 2'b10;
                end
                AB_DRAIN: begin
                    if (dma_bus_error) abort_error_code <= 2'b11;
                    if (dma_idle && !conv_busy && operand_cache_idle) abort_state <= AB_RESET;
                end
                AB_RESET: abort_state <= AB_DONE;
                AB_DONE: if (done_ready) begin
                    abort_state <= AB_IDLE;
                    abort_pending_q <= 1'b0;
                    run_conv <= 1'b0;
                end
                default: begin
                    abort_state <= AB_IDLE;
                    abort_pending_q <= 1'b0;
                end
            endcase
        end
    end
    // 两个操作数加载器共用矩阵分块 DMA，其读取端管理 im2col、图像缓存和读取仲裁。
    assign load_ia_granted = arbiter_ia_granted;
    assign m_axi_arvalid = legacy_axi_arvalid;
    assign legacy_axi_arready = m_axi_arready;
    assign m_axi_araddr = legacy_axi_araddr;
    assign m_axi_arlen = legacy_axi_arlen;
    assign m_axi_arsize = legacy_axi_arsize;
    assign m_axi_arburst = legacy_axi_arburst;
    assign legacy_axi_rvalid = m_axi_rvalid;
    assign m_axi_rready = legacy_axi_rready;
    assign legacy_axi_rdata = m_axi_rdata;
    assign legacy_axi_rresp = m_axi_rresp;
    assign legacy_axi_rlast = m_axi_rlast;

    // 配置数据按阶段保存；有效位决定各阶段的接收与提交。
    logic [2:0] cfg_valid_q;
    logic cfg_use16_q [0:2];
    logic cfg_16x8_q [0:2];
    logic [REG_WIDTH-1:0] cfg_stream_k_q [0:2];
    logic [REG_WIDTH-1:0] cfg_stream_m_q [0:2];
    logic [REG_WIDTH-1:0] cfg_ia_reuse_q [0:2];
    logic [REG_WIDTH-1:0] cfg_w_reuse_q [0:2];
    logic cfg_dataflow_mode_eff;

    assign cfg_dataflow_mode_eff = (ENABLE_IS_MODE != 0 && !cfg_16x8)
                              ? cfg_dataflow_mode : 1'b0;

    logic cfg_stage2_fire;
    logic operand_loader_flush_q;

    // 配置提交后先清除操作数缓存，控制器随后发出各加载器的初始化事件。
    // 清除事件独立寄存，避免容量相位和就绪条件直接驱动加载器内部控制。
    always_ff @(posedge clk or negedge core_rst_n) begin
        if (!core_rst_n) operand_loader_flush_q <= 1'b0;
        else operand_loader_flush_q <= cfg_stage2_fire;
    end
    logic cache_axi_arvalid;
    logic cache_axi_arready;
    logic cache_axi_rvalid;
    logic cache_axi_rready;
    logic cache_axi_rlast;
    logic [REG_WIDTH-1:0] cache_axi_araddr;
    logic [7:0] cache_axi_arlen;
    logic [2:0] cache_axi_arsize;
    logic [1:0] cache_axi_arburst;
    logic [1:0] cache_axi_rresp;
    logic [BUS_WIDTH-1:0] cache_axi_rdata;

    //========================================
    // 内部信号定义
    //========================================


    // 权重按最大卷积核尺寸分配 IA 存储块，剩余空间至少保留四个 PS 端口。

    logic engine_o_weight_read_en;
    logic engine_o_weight_write_en;
    logic [SHARED_IA_ADDR_WIDTH-1:0] engine_o_weight_read_addr;
    logic [SHARED_IA_ADDR_WIDTH-1:0] engine_o_weight_write_addr;
    logic [127:0] engine_o_weight_write_data;
    logic [127:0] engine_i_weight_read_data;
    logic [15:0] engine_o_weight_write_mask;
    logic engine_i_weight_read_valid;
    logic engine_o_ps_read_en;
    logic engine_o_ps_write_en;
    logic [SHARED_IA_ADDR_WIDTH-1:0] engine_o_ps_read_addr;
    logic [SHARED_IA_ADDR_WIDTH-1:0] engine_o_ps_write_addr;
    logic [511:0] engine_o_ps_write_data;
    logic [511:0] engine_i_ps_read_data;
    logic engine_i_ps_read_valid;
    logic engine_i_storage_error;
    logic engine_i_done_ready;
    logic shared_ram_capacity_fault;

    assign engine_i_done_ready = task_completion_accept && run_vector;
    assign engine_i_storage_error = vector_shared_store_o_error || shared_ram_capacity_fault;
    logic [31:0] shared_ia_banks_q;
    logic shared_allocation_invalid;
    logic [1:0] ia_ram_write_en;
    logic [1:0] ia_ram_read_en;
    logic [SHARED_IA_ADDR_WIDTH-1:0] ia_ram_write_addr [0:1];
    logic [SHARED_IA_ADDR_WIDTH-1:0] ia_ram_read_addr [0:1];
    logic [127:0] ia_ram_write_data [0:1];
    logic [127:0] ia_ram_read_data [0:1];
    logic [127:0] ia_ram_shared_write_data;
    logic [15:0] ia_ram_write_mask [0:1];
    logic [3:0] ps_ram_write_en;
    logic [3:0] ps_ram_read_en;
    logic [SHARED_PS_ADDR_WIDTH-1:0] ps_ram_write_addr [0:3];
    logic [SHARED_PS_ADDR_WIDTH-1:0] ps_ram_read_addr [0:3];
    logic [127:0] ps_ram_write_data [0:3];
    logic [127:0] ps_ram_read_data [0:3];

    // 输入加载器接口
    logic load_ia_req;

    logic frame_mode_q;
    logic frame_scheduler_ready;
    logic inner_done_valid;
    logic [1:0] inner_err_code;

    // 权重加载器接口
    logic load_weight_req;
    logic load_weight_granted;

    // 偏置加载器接口
    logic load_bias_req;
    logic load_bias_granted;

    // 阵列累加输出

    // 量化接口
    logic load_quant_req;
    logic load_quant_granted;
    logic signed [7:0] requant_out [SIZE];

    // 输出缓冲接口

    // 输出写回接口
    logic write_oa_req;
    logic write_oa_granted;

    // 共享 DMA 客户端接口
    logic ia_dma_start;
    logic ia_dma_linear_read_mode;
    logic ia_dma_im2col;
    logic [REG_WIDTH-1:0] ia_dma_p0;
    logic [REG_WIDTH-1:0] ia_dma_q0;
    logic [REG_WIDTH-1:0] ia_dma_group;
    logic [REG_WIDTH-1:0] ia_dma_base_addr;
    logic [REG_WIDTH-1:0] ia_dma_row_stride;
    logic [REG_WIDTH-1:0] ia_dma_rows_to_read;
    logic [7:0] ia_dma_burst_len_m1;

    logic [IA_CACHE_SLOT_W-1:0] ia_dma_slot_id;
    logic ia_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] ia_dma_lhs_zp;
    logic ia_dma_busy;
    logic ia_dma_done;
    logic [IA_CACHE_SLOT_W-1:0] ia_dma_wr_slot;
    logic [$clog2(SIZE)-1:0] ia_dma_wr_row;
    logic [$clog2(SIZE)-1:0] ia_dma_wr_col_base;
    logic signed [IA_DATA_WIDTH-1:0] ia_dma_wr_data [MATRIX_INPUT_LANES];
    logic ia_dma_wr_valid [MATRIX_INPUT_LANES];
    logic ia_dma_wr_use_16bits;
    logic kernel_dma_start;
    logic kernel_dma_linear_read_mode;
    logic kernel_dma_im2col;
    logic [REG_WIDTH-1:0] kernel_dma_p0;
    logic [REG_WIDTH-1:0] kernel_dma_q0;
    logic [REG_WIDTH-1:0] kernel_dma_group;
    logic [REG_WIDTH-1:0] kernel_dma_base_addr;
    logic [REG_WIDTH-1:0] kernel_dma_row_stride;
    logic [REG_WIDTH-1:0] kernel_dma_rows_to_read;
    logic [7:0] kernel_dma_burst_len_m1;
    logic kernel_dma_slot_id;
    logic kernel_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] kernel_dma_lhs_zp;
    logic kernel_dma_busy;
    logic kernel_dma_done;
    logic kernel_dma_wr_slot;
    logic [$clog2(SIZE)-1:0] kernel_dma_wr_row;
    logic [$clog2(SIZE)-1:0] kernel_dma_wr_col_base;
    logic signed [KERNEL_DATA_WIDTH-1:0] kernel_dma_wr_data [MATRIX_INPUT_LANES];
    logic kernel_dma_wr_valid [MATRIX_INPUT_LANES];
    logic bias_dma_start;
    logic bias_dma_linear_read_mode;
    logic [REG_WIDTH-1:0] bias_dma_base_addr;
    logic [REG_WIDTH-1:0] bias_dma_row_stride;
    logic [REG_WIDTH-1:0] bias_dma_rows_to_read;
    logic [7:0] bias_dma_burst_len_m1;
    logic bias_dma_slot_id;
    logic bias_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] bias_dma_lhs_zp;
    logic bias_dma_busy;
    logic bias_dma_done;
    logic bias_dma_wr_slot;
    logic bias_dma_wr_use_16bits;
    logic [$clog2(BIAS_DMA_SIZE)-1:0] bias_dma_wr_row;
    logic [$clog2(BIAS_DMA_SIZE)-1:0] bias_dma_wr_col_base;
    logic signed [7:0] bias_dma_wr_data [BUS_WIDTH/8];
    logic bias_dma_wr_valid [BUS_WIDTH/8];
    logic quant_dma_start;
    logic quant_dma_linear_read_mode;
    logic [REG_WIDTH-1:0] quant_dma_base_addr;
    logic [REG_WIDTH-1:0] quant_dma_row_stride;
    logic [REG_WIDTH-1:0] quant_dma_rows_to_read;
    logic [7:0] quant_dma_burst_len_m1;
    logic quant_dma_slot_id;
    logic quant_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] quant_dma_lhs_zp;
    logic quant_dma_busy;
    logic quant_dma_done;
    logic [BUS_WIDTH-1:0] quant_dma_raw_data;
    logic quant_dma_raw_valid;
    logic oa_dma_start;
    logic [REG_WIDTH-1:0] oa_dma_base_addr;
    logic [REG_WIDTH-1:0] oa_dma_row_stride;
    logic [REG_WIDTH-1:0] oa_dma_rows_to_read;
    logic [7:0] oa_dma_burst_len_m1;
    logic [BUS_WIDTH-1:0] oa_dma_src_wdata;
    logic [BUS_WIDTH/8-1:0] oa_dma_src_wmask;
    logic oa_dma_src_wvalid;
    logic oa_dma_src_wready;
    logic oa_dma_busy;
    logic oa_dma_done;
    logic win_req_valid;
    logic win_req_ready;
    logic win_rsp_valid;
    logic win_rsp_ready;
    logic [31:0] win_req_p0;
    logic [31:0] win_req_q0;
    logic [31:0] win_req_cols;
    logic [31:0] win_rsp_col;
    logic [1:0] win_req_tag;
    logic [1:0] win_rsp_tag;
    logic signed [15:0] win_rsp_data [WINDOW_LANES];
    logic [WINDOW_LANES-1:0] win_rsp_mask;
    logic win_rsp_last;
    logic win_rsp_error;
    logic win_busy;
    logic dw_rd_req;
    logic dw_rd_granted;
    logic dw_rd_start;
    logic dw_rd_im2col;
    logic dw_rd_use_16bits;
    logic [31:0] dw_rd_p0;
    logic [31:0] dw_rd_q0;
    logic [31:0] dw_rd_base_addr;
    logic [31:0] dw_rd_row_stride;
    logic [31:0] dw_rd_rows_to_read;
    logic [31:0] dw_rd_valid_cols;
    logic [7:0] dw_rd_burst_len_m1;
    logic dw_rd_busy;
    logic dw_rd_done;
    logic dw_rd_error;
    logic signed [IA_DATA_WIDTH-1:0] vector_dma_data [BUS_WIDTH/8];
    logic signed [15:0] dw_rd_data [BUS_WIDTH/8];
    logic dw_rd_valid [BUS_WIDTH/8];
    logic [$clog2(SHARED_DMA_SIZE)-1:0] dw_rd_col_base;
    logic [BUS_WIDTH-1:0] dw_rd_raw_data;
    logic dw_rd_raw_valid;
    logic dw_wr_req;
    logic dw_wr_granted;
    logic dw_wr_start;
    logic [31:0] dw_wr_base_addr;
    logic [31:0] dw_wr_row_stride;
    logic [31:0] dw_wr_rows_to_write;
    logic [7:0] dw_wr_burst_len_m1;
    logic [BUS_WIDTH-1:0] dw_src_wdata;
    logic [BUS_WIDTH/8-1:0] dw_src_wmask;
    logic dw_src_wvalid;
    logic dw_src_wready;
    logic dw_wr_busy;
    logic dw_wr_done;
    logic dw_wr_error;
    logic dw_quant_req_valid;
    logic dw_quant_req_ready;
    logic dw_quant_req_tag;
    logic signed [31:0] dw_quant_accumulator [SIZE];
    logic signed [31:0] dw_quant_multiplier [SIZE];
    logic [5:0] dw_quant_right [SIZE];
    logic [SIZE-1:0] dw_quant_mask;
    logic signed [31:0] dw_quant_offset;
    logic signed [31:0] dw_quant_minimum;
    logic signed [31:0] dw_quant_maximum;
    logic dw_quant_rsp_valid;
    logic dw_quant_rsp_tag;

    generate if (VECTOR_ENGINE_CAPABLE) begin : g_vector_engine
        for (genvar lane = 0; lane < BUS_WIDTH/8; lane++) begin : g_data
            assign dw_rd_data[lane] = 16'($signed(vector_dma_data[lane]));
        end
        vector_engine #(.BUS_WIDTH(BUS_WIDTH),.TILE(SIZE), .DMA_SIZE(SHARED_DMA_SIZE),
            .WINDOW_LANES(WINDOW_LANES),
            .SHARED_QUANT_ENABLE(DW_SHARED_QUANT_ENABLE),
            .SHARED_STORAGE_ENABLE(SHARED_RAM_ENABLED),
            .SHARED_STORAGE_ADDR_WIDTH(SHARED_IA_ADDR_WIDTH),
            .PE_COUNT(VECTOR_PE_COUNT), .MAX_TAPS(DW_MAX_TAPS), .POOL_MAX_TAPS(POOL_MAX_TAPS)) u_engine (
            .clk, .rst_n(core_rst_n),
            .start(vector_start_fire),
            .cfg(cfg_vector), .ready(vector_engine_ready), .done_valid(vector_engine_done),
            .done_ready(engine_i_done_ready), .error(vector_engine_error),
            .o_weight_read_en(engine_o_weight_read_en), .o_weight_read_addr(engine_o_weight_read_addr),
            .i_weight_read_valid(engine_i_weight_read_valid), .i_weight_read_data(engine_i_weight_read_data),
            .o_weight_write_en(engine_o_weight_write_en), .o_weight_write_addr(engine_o_weight_write_addr),
            .o_weight_write_data(engine_o_weight_write_data), .o_weight_write_mask(engine_o_weight_write_mask),
            .o_ps_read_en(engine_o_ps_read_en), .o_ps_read_addr(engine_o_ps_read_addr),
            .i_ps_read_valid(engine_i_ps_read_valid), .i_ps_read_data(engine_i_ps_read_data),
            .o_ps_write_en(engine_o_ps_write_en), .o_ps_write_addr(engine_o_ps_write_addr),
            .o_ps_write_data(engine_o_ps_write_data), .i_storage_error(engine_i_storage_error),
            .dma_cfg_valid(vector_dma_cfg_valid), .dma_cfg_ready(conv_cfg_ready && run_vector),
            .dma_conv_enable(vector_dma_conv_enable), .dma_range_enable(vector_dma_range_enable),
            .dma_conv_cfg(vector_dma_conv_cfg), .dma_range_base(vector_dma_range_base),
            .dma_range_end(vector_dma_range_end),
            .win_req_valid,.win_req_ready,.win_req_p0,.win_req_q0,.win_req_cols,.win_req_tag,
            .win_rsp_valid,.win_rsp_ready,.win_rsp_tag,.win_rsp_col,.win_rsp_data,.win_rsp_mask,
            .win_rsp_last,.win_rsp_error,.win_busy,
            .quant_req_valid(dw_quant_req_valid), .quant_req_ready(dw_quant_req_ready),
            .quant_req_tag(dw_quant_req_tag), .quant_req_accumulator(dw_quant_accumulator),
            .quant_req_multiplier(dw_quant_multiplier), .quant_req_right(dw_quant_right),
            .quant_req_mask(dw_quant_mask), .quant_req_offset(dw_quant_offset),
            .quant_req_minimum(dw_quant_minimum), .quant_req_maximum(dw_quant_maximum),
            .quant_rsp_valid(dw_quant_rsp_valid), .quant_rsp_tag(dw_quant_rsp_tag),
            .quant_rsp_data(requant_out),
            .rd_req(dw_rd_req), .rd_start(dw_rd_start), .rd_granted(dw_rd_granted),
            .rd_im2col(dw_rd_im2col), .rd_p0(dw_rd_p0), .rd_q0(dw_rd_q0),
            .rd_base_addr(dw_rd_base_addr), .rd_row_stride(dw_rd_row_stride),
            .rd_rows_to_read(dw_rd_rows_to_read), .rd_valid_cols(dw_rd_valid_cols),
            .rd_burst_len_m1(dw_rd_burst_len_m1), .rd_use_16bits(dw_rd_use_16bits),
            .rd_busy(dw_rd_busy), .rd_done(dw_rd_done), .rd_error(dw_rd_error),
            .rd_data(dw_rd_data), .rd_valid(dw_rd_valid), .rd_col_base(dw_rd_col_base),
            .rd_raw_data(dw_rd_raw_data), .rd_raw_valid(dw_rd_raw_valid),
            .wr_req(dw_wr_req), .wr_start(dw_wr_start), .wr_granted(dw_wr_granted),
            .wr_base_addr(dw_wr_base_addr), .wr_row_stride(dw_wr_row_stride),
            .wr_rows_to_write(dw_wr_rows_to_write), .wr_burst_len_m1(dw_wr_burst_len_m1),
            .src_wdata(dw_src_wdata), .src_wmask(dw_src_wmask), .src_wvalid(dw_src_wvalid),
            .src_wready(dw_src_wready), .wr_busy(dw_wr_busy), .wr_done(dw_wr_done),
            .wr_error(dw_wr_error)
        );
    end else begin : g_no_vector_engine
        assign engine_o_weight_read_en = 1'b0;
        assign engine_o_weight_read_addr = '0;
        assign engine_o_weight_write_en = 1'b0;
        assign engine_o_weight_write_addr = '0;
        assign engine_o_weight_write_data = '0;
        assign engine_o_weight_write_mask = '0;
        assign engine_o_ps_read_en = 1'b0;
        assign engine_o_ps_read_addr = '0;
        assign engine_o_ps_write_en = 1'b0;
        assign engine_o_ps_write_addr = '0;
        assign engine_o_ps_write_data = '0;
        assign vector_engine_ready = 1'b1;
        assign vector_engine_done = 1'b0;
        assign vector_engine_error = 2'b01;
        assign vector_dma_cfg_valid = 1'b0; assign vector_dma_conv_enable = 1'b0;
        assign vector_dma_range_enable = 1'b0; assign vector_dma_conv_cfg = '0;
        for (genvar r = 0; r < 4; r++) begin : g_ranges
            assign vector_dma_range_base[r] = '0; assign vector_dma_range_end[r] = '0;
        end
        assign win_req_valid=1'b0;assign win_req_p0='0;assign win_req_q0='0;assign win_req_cols='0;
        assign win_req_tag='0;assign win_rsp_ready=1'b1;
        assign dw_rd_req = 1'b0; assign dw_rd_start = 1'b0; assign dw_rd_im2col = 1'b0;
        assign dw_rd_use_16bits = 1'b0; assign dw_rd_p0 = '0; assign dw_rd_q0 = '0;
        assign dw_rd_base_addr = '0; assign dw_rd_row_stride = '0;
        assign dw_rd_rows_to_read = '0; assign dw_rd_valid_cols = '0;
        assign dw_rd_burst_len_m1 = '0;
        assign dw_wr_req = 1'b0; assign dw_wr_start = 1'b0;
        assign dw_wr_base_addr = '0; assign dw_wr_row_stride = '0;
        assign dw_wr_rows_to_write = '0; assign dw_wr_burst_len_m1 = '0;
        assign dw_src_wdata = '0; assign dw_src_wmask = '0; assign dw_src_wvalid = 1'b0;
        assign dw_quant_req_valid = 1'b0;
        assign dw_quant_req_tag = 1'b0;
        assign dw_quant_mask = '0;
        assign dw_quant_offset = '0;
        assign dw_quant_minimum = '0;
        assign dw_quant_maximum = '0;
        for (genvar lane = 0; lane < SIZE; lane++) begin : g_quant_zero
            assign dw_quant_accumulator[lane] = '0;
            assign dw_quant_multiplier[lane] = '0;
            assign dw_quant_right[lane] = '0;
        end
    end endgenerate

    logic ps_capacity_fault;
    logic block_dma_arbiter_i_abort;

    // 各运算来源并行汇总故障，中止状态持续保持至当前任务结束。
    assign task_fault = ps_capacity_fault || shared_ram_capacity_fault || vector_shared_store_o_error || dma_bus_error ||
                        (frame_mode_q && inner_done_valid && (inner_err_code != 2'b00)) ||
                        ((run_conv || run_vector) && conv_error);
    // 全局中止由已保存的任务状态驱动；总线错误仍由 DMA 本地同周期阻止接收。
    assign block_dma_arbiter_i_abort = abort_pending;
    logic controller_done_valid;
    logic [1:0] controller_err_code;
    logic operand_completion_seen;

    // 控制器保持完成状态直到接收，公开接口为每个普通任务报告一次完成。
    // 状态清除覆盖接收后的寄存尾拍，也适用于后台预取排空及外部背压。
    always_ff @(posedge clk or negedge core_rst_n) begin
        if (!core_rst_n) operand_completion_seen<=1'b0;
        else if (!controller_done_valid) operand_completion_seen<=1'b0;
        else if (abort_state==AB_IDLE && done_valid && done_ready)
            operand_completion_seen<=1'b1;
    end
`ifdef GEMMORA_INT8_PROFILE
    wire profile_input_invalid=cfg_16bits_ia || cfg_16x8 || lhs_zp!=0 || rhs_zp!=0;
    logic profile_error;
    always_ff @(posedge clk or negedge core_rst_n) begin
        if(!core_rst_n)profile_error<=1'b0;
        else if(calc_start && !cfg_vector_enable && profile_input_invalid)profile_error<=1'b1;
    end
`else
    logic profile_input_invalid;

    assign profile_input_invalid = 1'b0;

    logic profile_error;

    assign profile_error = 1'b0;

`endif
    assign normal_done_valid = operand_cache_idle && frame_prefetch_idle && conv_task_idle &&
        ((controller_done_valid && !operand_completion_seen) || profile_error);
    assign normal_err_code = profile_error ? 2'b01 : controller_err_code;

    // 控制器向各执行模块发送的单周期配置事件。

  // 16位数据指示信号
  // 分块计数信号

    logic ctrl_sa_ready;

        assign task_accept_conditions = !run_vector && !vector_rejected && vector_engine_ready &&
            ctrl_sa_ready && frame_scheduler_ready && !cfg_valid_q[0] && !cfg_valid_q[1] &&
            !cfg_valid_q[2] && (abort_state == AB_IDLE) && !task_fault && operand_cache_idle &&
            frame_prefetch_idle && conv_task_idle;

    logic run_compact;
    logic block_dma_arbiter_i_ia_wide_im2col;
    logic [REG_WIDTH-1:0] ia_reuse_num_eff;
    logic is_mode;
    logic exec_dma_job_init;

    // Raw rows use adjacent words in separate banks; each bank selects its own write data.
    assign block_dma_arbiter_i_ia_wide_im2col = run_compact ||
        (SHARED_RAM_ENABLED && SHARED_MAX_IA_BANKS >= 4 && shared_ia_banks_q >= 32'd2);

        axi_block_dma_arbiter #(
            .DMA_MAX_BYTES(DMA_MAX_BYTES),
            .DATA_WIDTH  (IA_DATA_WIDTH),
            .KERNEL_WIDTH(KERNEL_DATA_WIDTH),
            .SIZE        (SIZE),
            .DMA_SIZE    (SHARED_DMA_SIZE),
            .BUS_WIDTH   (BUS_WIDTH),
            .REG_WIDTH   (REG_WIDTH),
            .CACHE_BLOCKS(IA_SLOT_BLOCKS),
            .ENABLE_QUANT_CLIENT(ENABLE_PER_CHANNEL),
            .READ_OUTSTANDING(AXI_READ_OUTSTANDING),
            .WRITE_OUTSTANDING(AXI_WRITE_OUTSTANDING),
            .WINDOW_LANES(WINDOW_LANES),
            .DATA_LANES(MATRIX_INPUT_LANES),
            .CONV_CACHE_SETS(CONV_CACHE_SETS),
            .CONV_CACHE_WAYS(CONV_CACHE_WAYS),
            .CONV_LINE_BYTES(CONV_LINE_BYTES),
            .CONV_CACHE_POLICY(CONV_CACHE_POLICY),
            .p_register_bus_error(1'b1)
        ) u_block_dma_arbiter (
            .clk                     (clk),
            .rst_n                   (core_rst_n),
            .abort                   (block_dma_arbiter_i_abort),
            // 每个任务均更新 DMA 配置，矩阵与卷积使用各自的地址范围和缓存策略。
            .conv_cfg_valid          (run_vector ? vector_dma_cfg_valid : exec_dma_job_init),
            .conv_cfg_ready          (conv_cfg_ready),
            .conv_enable             (run_vector ? vector_dma_conv_enable : run_conv),
            .dma_range_enable       (run_vector && vector_dma_range_enable),
            .conv_cfg                (run_vector ? vector_dma_conv_cfg : conv_cfg_q),
            .conv_sched_r            (run_vector ? 32'd0 : 32'(ia_reuse_num_eff)),
            .conv_sched_groups       ((run_vector || is_mode || frame_mode_q) ? 32'd0 : 32'(cfg_col_groups)),
            .conv_range_base         (selected_range_base),
            .conv_range_end          (selected_range_end),
            .conv_error              (conv_error),
            .conv_busy               (conv_busy),
            .win_req_valid,.win_req_ready,.win_req_p0,.win_req_q0,.win_req_cols,.win_req_tag,
            .win_rsp_valid,.win_rsp_ready,.win_rsp_tag,.win_rsp_col,.win_rsp_data,.win_rsp_mask,
            .win_rsp_last,.win_rsp_error,.win_busy,
            .dw_req(dw_rd_req && !abort_pending), .dw_granted(dw_rd_granted), .dw_start(dw_rd_start),
            .dw_im2col(dw_rd_im2col), .dw_p0(dw_rd_p0), .dw_q0(dw_rd_q0),
            .dw_group(32'd0), .dw_linear_read_mode(1'b0), .dw_lhs_zp('0),
            .dw_base_addr(dw_rd_base_addr), .dw_row_stride(dw_rd_row_stride),
            .dw_rows_to_read(dw_rd_rows_to_read), .dw_valid_cols(dw_rd_valid_cols),
            .dw_burst_len_m1(dw_rd_burst_len_m1), .dw_use_16bits(dw_rd_use_16bits),
            .dw_busy(dw_rd_busy), .dw_done(dw_rd_done), .dw_error(dw_rd_error),
            .dw_data(vector_dma_data), .dw_valid(dw_rd_valid), .dw_row(), .dw_col_base(dw_rd_col_base),
            .dw_raw_data(dw_rd_raw_data), .dw_raw_valid(dw_rd_raw_valid),
            .dw_wr_req(dw_wr_req && !abort_pending), .dw_wr_granted(dw_wr_granted), .dw_wr_start(dw_wr_start),
            .dw_wr_base_addr(dw_wr_base_addr), .dw_wr_row_stride(dw_wr_row_stride),
            .dw_wr_rows_to_write(dw_wr_rows_to_write), .dw_wr_burst_len_m1(dw_wr_burst_len_m1),
            .dw_src_wdata(dw_src_wdata), .dw_src_wmask(dw_src_wmask),
            .dw_src_wvalid(dw_src_wvalid), .dw_src_wready(dw_src_wready),
            .dw_wr_busy(dw_wr_busy), .dw_wr_done(dw_wr_done), .dw_wr_error(dw_wr_error),
            .ia_req                  (load_ia_req && !abort_pending),
            .ia_granted              (arbiter_ia_granted),
            .ia_start                (ia_dma_start),
            .ia_linear_read_mode     (ia_dma_linear_read_mode),
            .ia_im2col               (ia_dma_im2col),
            .ia_p0                   (ia_dma_p0),
            .ia_q0                   (ia_dma_q0),
            .ia_group                (ia_dma_group),
            .ia_base_addr            (ia_dma_base_addr),
            .ia_row_stride           (ia_dma_row_stride),
            .ia_rows_to_read         (ia_dma_rows_to_read),
            .ia_burst_len_m1         (ia_dma_burst_len_m1),
            .ia_slot_id              (ia_dma_slot_id),
            .ia_use_16bits           (ia_dma_use_16bits),
            .ia_lhs_zp               (ia_dma_lhs_zp),
            .ia_busy                 (ia_dma_busy),
            .ia_done                 (ia_dma_done),
            .ia_wr_slot              (ia_dma_wr_slot),
            .ia_wr_row               (ia_dma_wr_row),
            .ia_wr_col_base          (ia_dma_wr_col_base),
            .ia_wr_data              (ia_dma_wr_data),
            .ia_wr_valid             (ia_dma_wr_valid),
            .ia_wr_use_16bits        (ia_dma_wr_use_16bits),
            .ia_wide_im2col          (block_dma_arbiter_i_ia_wide_im2col),
                .kernel_req(load_weight_req && !abort_pending),
                .kernel_granted          (load_weight_granted),
            .o_kernel_eligible       (block_dma_arbiter_o_kernel_eligible),
                .kernel_start            (kernel_dma_start),
                .kernel_linear_read_mode (kernel_dma_linear_read_mode),
            .kernel_im2col           (kernel_dma_im2col),
            .kernel_p0               (kernel_dma_p0),
            .kernel_q0               (kernel_dma_q0),
            .kernel_group            (kernel_dma_group),
            .kernel_base_addr        (kernel_dma_base_addr),
            .kernel_row_stride       (kernel_dma_row_stride),
            .kernel_rows_to_read     (kernel_dma_rows_to_read),
            .kernel_burst_len_m1     (kernel_dma_burst_len_m1),
            .kernel_slot_id          (kernel_dma_slot_id),
            .kernel_use_16bits       (kernel_dma_use_16bits),
            .kernel_lhs_zp           (kernel_dma_lhs_zp),
            .kernel_busy             (kernel_dma_busy),
            .kernel_done             (kernel_dma_done),
            .kernel_wr_slot          (kernel_dma_wr_slot),
            .kernel_wr_row           (kernel_dma_wr_row),
            .kernel_wr_col_base      (kernel_dma_wr_col_base),
            .kernel_wr_data          (kernel_dma_wr_data),
            .kernel_wr_valid         (kernel_dma_wr_valid),
                .bias_req(load_bias_req && !abort_pending),
                .bias_granted            (load_bias_granted),
                .bias_start              (bias_dma_start),
                .bias_linear_read_mode   (bias_dma_linear_read_mode),
            .bias_base_addr          (bias_dma_base_addr),
            .bias_row_stride         (bias_dma_row_stride),
            .bias_rows_to_read       (bias_dma_rows_to_read),
            .bias_burst_len_m1       (bias_dma_burst_len_m1),
            .bias_slot_id            (bias_dma_slot_id),
            .bias_use_16bits         (bias_dma_use_16bits),
            .bias_lhs_zp             (bias_dma_lhs_zp),
            .bias_busy               (bias_dma_busy),
            .bias_done               (bias_dma_done),
            .bias_wr_slot            (bias_dma_wr_slot),
            .bias_wr_row             (bias_dma_wr_row),
            .bias_wr_col_base        (bias_dma_wr_col_base),
            .bias_wr_data            (bias_dma_wr_data),
            .bias_wr_valid           (bias_dma_wr_valid),
            .bias_wr_use_16bits      (bias_dma_wr_use_16bits),
                .quant_req(load_quant_req && !abort_pending),
                .quant_granted           (load_quant_granted),
                .quant_start             (quant_dma_start),
                .quant_linear_read_mode  (quant_dma_linear_read_mode),
            .quant_base_addr         (quant_dma_base_addr),
            .quant_row_stride        (quant_dma_row_stride),
            .quant_rows_to_read      (quant_dma_rows_to_read),
            .quant_burst_len_m1      (quant_dma_burst_len_m1),
            .quant_slot_id           (quant_dma_slot_id),
            .quant_use_16bits        (quant_dma_use_16bits),
            .quant_lhs_zp            (quant_dma_lhs_zp),
            .quant_busy              (quant_dma_busy),
            .quant_done              (quant_dma_done),
            .quant_raw_data          (quant_dma_raw_data),
            .quant_raw_valid         (quant_dma_raw_valid),
                .oa_req(write_oa_req && !abort_pending),
                .oa_granted              (write_oa_granted),
                .oa_start                (oa_dma_start),
                .oa_base_addr            (oa_dma_base_addr),
                .oa_row_stride           (oa_dma_row_stride),
                .oa_rows_to_read         (oa_dma_rows_to_read),
                .oa_burst_len_m1         (oa_dma_burst_len_m1),
                // 排空期间完成已接收的写事务，并用字节掩码保护其余输出。
                .oa_src_wdata            (abort_pending ? '0 : oa_dma_src_wdata),
            .oa_src_wmask            (abort_pending ? '0 : oa_dma_src_wmask),
            .oa_src_wvalid           (abort_pending || oa_dma_src_wvalid),
            .oa_src_wready           (oa_dma_src_wready),
            .oa_busy                 (oa_dma_busy),
            .oa_done                 (oa_dma_done),
            .m_axi_arvalid           (cache_axi_arvalid),
            .m_axi_arready           (cache_axi_arready),
            .m_axi_araddr            (cache_axi_araddr),
            .m_axi_arlen             (cache_axi_arlen),
            .m_axi_arsize            (cache_axi_arsize),
            .m_axi_arburst           (cache_axi_arburst),
            .m_axi_rvalid            (cache_axi_rvalid),
            .m_axi_rready            (cache_axi_rready),
            .m_axi_rdata             (cache_axi_rdata),
            .m_axi_rresp             (cache_axi_rresp),
            .m_axi_rlast             (cache_axi_rlast),
            .m_axi_awvalid           (m_axi_awvalid),
            .m_axi_awready           (m_axi_awready),
            .m_axi_awaddr            (m_axi_awaddr),
            .m_axi_awlen             (m_axi_awlen),
            .m_axi_awsize            (m_axi_awsize),
            .m_axi_awburst           (m_axi_awburst),
            .m_axi_wvalid            (m_axi_wvalid),
            .m_axi_wready            (m_axi_wready),
            .m_axi_wdata             (m_axi_wdata),
            .m_axi_wstrb             (m_axi_wstrb),
            .m_axi_wlast             (m_axi_wlast),
            .m_axi_bvalid            (m_axi_bvalid),
            .m_axi_bready            (m_axi_bready),
            .m_axi_bresp             (m_axi_bresp),
            .idle(dma_idle), .bus_error(dma_bus_error)
        );

`ifdef NPU_SIM_ASSERT
        initial forever @(posedge clk) if (core_rst_n && exec_dma_job_init) begin
            assert(conv_cfg_ready);
            assert(!ia_dma_start && !kernel_dma_start);
        end
`endif

        //========================================
    // 模块实例化
    //========================================

        // NPU 控制器

    generate if (SHARED_RAM_ENABLED) begin : g_shared_ia_ps
        logic ram_i_cfg_valid, ram_config_request, ram_access_en, ram_request_enable;
        logic [SHARED_PHYSICAL_BANKS_WIDTH-1:0] ram_i_cfg_ia_banks;
        logic ram_o_capacity_fault;
        logic [1:0] ram_i_ia_read_en, ram_i_ia_write_en;
        logic [SHARED_IA_ADDR_WIDTH-1:0] ram_i_ia_read_addr [2], ram_i_ia_write_addr [2];
        logic [127:0] ram_o_ia_read_data [2], ram_i_ia_write_data [2];
        logic [127:0] ram_i_ia_shared_write_data;
        logic [15:0] ram_i_ia_write_mask [2];
        logic [3:0] ram_i_ps_read_en, ram_i_ps_write_en;
        logic [SHARED_PS_ADDR_WIDTH-1:0] ram_i_ps_read_addr [4], ram_i_ps_write_addr [4];
        logic [127:0] ram_o_ps_read_data [4], ram_i_ps_write_data [4];
        logic vector_shared_store_i_cfg_valid, vector_shared_store_i_enable, vector_shared_store_i_flush;
        logic [SHARED_PHYSICAL_BANKS_WIDTH-1:0] vector_shared_store_i_cfg_ia_banks;
        logic vector_shared_store_i_weight_read_en, vector_shared_store_i_weight_write_en;
        logic [SHARED_IA_ADDR_WIDTH-1:0] vector_shared_store_i_weight_read_addr, vector_shared_store_i_weight_write_addr;
        logic [127:0] vector_shared_store_i_weight_write_data, vector_shared_store_o_weight_read_data;
        logic [15:0] vector_shared_store_i_weight_write_mask;
        logic vector_shared_store_o_weight_read_valid;
        logic vector_shared_store_i_ps_read_en, vector_shared_store_i_ps_write_en;
        logic [SHARED_IA_ADDR_WIDTH-1:0] vector_shared_store_i_ps_read_addr, vector_shared_store_i_ps_write_addr;
        logic [511:0] vector_shared_store_i_ps_write_data, vector_shared_store_o_ps_read_data;
        logic vector_shared_store_o_ps_read_valid;
        logic [1:0] vector_shared_store_o_ia_read_en, vector_shared_store_o_ia_write_en;
        logic [SHARED_IA_ADDR_WIDTH-1:0] vector_shared_store_o_ia_read_addr [2], vector_shared_store_o_ia_write_addr [2];
        logic [127:0] vector_shared_store_i_ia_read_data [2], vector_shared_store_o_ia_write_data [2];
        logic [127:0] vector_shared_store_o_ia_shared_write_data;
        logic [15:0] vector_shared_store_o_ia_write_mask [2];
        logic [3:0] vector_shared_store_o_ps_read_en, vector_shared_store_o_ps_write_en;
        logic [SHARED_IA_ADDR_WIDTH-1:0] vector_shared_store_o_ps_read_addr [4], vector_shared_store_o_ps_write_addr [4];
        logic [127:0] vector_shared_store_i_ps_read_data [4], vector_shared_store_o_ps_write_data [4];

        // 保存任务分配后配置共享存储，接收拍和配置拍均禁止物理访问。
        assign ram_config_request = core_rst_n &&
            (vector_start_fire || (cfg_stage2_fire && !shared_allocation_invalid));
        always_ff @(posedge clk or negedge core_rst_n) begin
            if (!core_rst_n) begin
                ram_i_cfg_valid <= 1'b0;
                ram_i_cfg_ia_banks <= SHARED_PHYSICAL_BANKS_WIDTH'(1);
            end else begin
                ram_i_cfg_valid <= ram_config_request;
                if (ram_config_request) begin
                    ram_i_cfg_ia_banks <= vector_start_fire ?
                        SHARED_PHYSICAL_BANKS_WIDTH'(VECTOR_SHARED_IA_BANKS) :
                        SHARED_PHYSICAL_BANKS_WIDTH'(shared_ia_banks_q);
                end
            end
        end
        assign ram_access_en = core_rst_n && !ram_config_request && !ram_i_cfg_valid &&
            !abort_pending;
        // 固定通道在存储器内部最后合并访问资格，通用布局保持端口输入屏蔽。
        assign ram_request_enable = p_fixed_ps_channels || ram_access_en;
        assign shared_ram_capacity_fault = ram_o_capacity_fault;

        assign vector_shared_store_i_cfg_valid = ram_i_cfg_valid;
        assign vector_shared_store_i_cfg_ia_banks = ram_i_cfg_ia_banks;
        assign vector_shared_store_i_enable = run_vector;
        assign vector_shared_store_i_flush = abort_pending;
        assign vector_shared_store_i_weight_read_en = engine_o_weight_read_en;
        assign vector_shared_store_i_weight_read_addr = engine_o_weight_read_addr;
        assign vector_shared_store_i_weight_write_en = engine_o_weight_write_en;
        assign vector_shared_store_i_weight_write_addr = engine_o_weight_write_addr;
        assign vector_shared_store_i_weight_write_data = engine_o_weight_write_data;
        assign vector_shared_store_i_weight_write_mask = engine_o_weight_write_mask;
        assign engine_i_weight_read_valid = vector_shared_store_o_weight_read_valid;
        assign engine_i_weight_read_data = vector_shared_store_o_weight_read_data;
        assign vector_shared_store_i_ps_read_en = engine_o_ps_read_en;
        assign vector_shared_store_i_ps_read_addr = engine_o_ps_read_addr;
        assign vector_shared_store_i_ps_write_en = engine_o_ps_write_en;
        assign vector_shared_store_i_ps_write_addr = engine_o_ps_write_addr;
        assign vector_shared_store_i_ps_write_data = engine_o_ps_write_data;
        assign engine_i_ps_read_valid = vector_shared_store_o_ps_read_valid;
        assign engine_i_ps_read_data = vector_shared_store_o_ps_read_data;
        assign vector_shared_store_i_ia_read_data = ram_o_ia_read_data;
        assign vector_shared_store_i_ps_read_data = ram_o_ps_read_data;

        // 矩阵与向量任务互斥，整个任务持有端口；任务结束前等待所有同步读取返回。
        assign ram_i_ia_read_en = !ram_request_enable ? 2'b00 :
            run_vector ? vector_shared_store_o_ia_read_en : ia_ram_read_en;
        assign ram_i_ia_write_en = !ram_request_enable ? 2'b00 :
            run_vector ? vector_shared_store_o_ia_write_en : ia_ram_write_en;
        assign ram_i_ia_read_addr = run_vector ? vector_shared_store_o_ia_read_addr : ia_ram_read_addr;
        assign ram_i_ia_write_addr = run_vector ? vector_shared_store_o_ia_write_addr : ia_ram_write_addr;
        assign ram_i_ia_write_data = run_vector ? vector_shared_store_o_ia_write_data : ia_ram_write_data;
        assign ram_i_ia_write_mask = run_vector ? vector_shared_store_o_ia_write_mask : ia_ram_write_mask;
        assign ram_i_ia_shared_write_data = run_vector ?
            vector_shared_store_o_ia_shared_write_data : ia_ram_shared_write_data;
        assign ram_i_ps_read_en = !ram_request_enable ? 4'b0000 :
            run_vector ? vector_shared_store_o_ps_read_en : ps_ram_read_en;
        assign ram_i_ps_write_en = !ram_request_enable ? 4'b0000 :
            run_vector ? vector_shared_store_o_ps_write_en : ps_ram_write_en;
        assign ram_i_ps_read_addr = run_vector ? vector_shared_store_o_ps_read_addr : ps_ram_read_addr;
        assign ram_i_ps_write_addr = run_vector ? vector_shared_store_o_ps_write_addr : ps_ram_write_addr;
        assign ram_i_ps_write_data = run_vector ? vector_shared_store_o_ps_write_data : ps_ram_write_data;
        assign ia_ram_read_data = ram_o_ia_read_data;
        assign ps_ram_read_data = ram_o_ps_read_data;

        vector_shared_store #(
            .p_bank_bytes(SHARED_BANK_BYTES), .p_total_bytes(SHARED_TOTAL_BYTES),
            .p_addr_width(SHARED_IA_ADDR_WIDTH), .p_bank_count_width(SHARED_PHYSICAL_BANKS_WIDTH),
            .p_fixed_ps_channels(p_fixed_ps_channels)
        ) u_vector_shared_store (
            .clk(clk), .rst_n(core_rst_n),
            .i_cfg_valid(vector_shared_store_i_cfg_valid), .i_cfg_ia_banks(vector_shared_store_i_cfg_ia_banks),
            .i_enable(vector_shared_store_i_enable), .i_flush(vector_shared_store_i_flush),
            .o_idle(vector_shared_store_o_idle), .o_error(vector_shared_store_o_error),
            .i_weight_read_en(vector_shared_store_i_weight_read_en),
            .i_weight_read_addr(vector_shared_store_i_weight_read_addr),
            .o_weight_read_valid(vector_shared_store_o_weight_read_valid),
            .o_weight_read_data(vector_shared_store_o_weight_read_data),
            .i_weight_write_en(vector_shared_store_i_weight_write_en),
            .i_weight_write_addr(vector_shared_store_i_weight_write_addr),
            .i_weight_write_data(vector_shared_store_i_weight_write_data),
            .i_weight_write_mask(vector_shared_store_i_weight_write_mask),
            .i_ps_read_en(vector_shared_store_i_ps_read_en), .i_ps_read_addr(vector_shared_store_i_ps_read_addr),
            .o_ps_read_valid(vector_shared_store_o_ps_read_valid), .o_ps_read_data(vector_shared_store_o_ps_read_data),
            .i_ps_write_en(vector_shared_store_i_ps_write_en), .i_ps_write_addr(vector_shared_store_i_ps_write_addr),
            .i_ps_write_data(vector_shared_store_i_ps_write_data),
            .o_ia_read_en(vector_shared_store_o_ia_read_en), .o_ia_read_addr(vector_shared_store_o_ia_read_addr),
            .i_ia_read_data(vector_shared_store_i_ia_read_data),
            .o_ia_write_en(vector_shared_store_o_ia_write_en), .o_ia_write_addr(vector_shared_store_o_ia_write_addr),
            .o_ia_write_data(vector_shared_store_o_ia_write_data), .o_ia_write_mask(vector_shared_store_o_ia_write_mask),
            .o_ia_shared_write_data(vector_shared_store_o_ia_shared_write_data),
            .o_ps_read_en(vector_shared_store_o_ps_read_en), .o_ps_read_addr(vector_shared_store_o_ps_read_addr),
            .i_ps_read_data(vector_shared_store_i_ps_read_data),
            .o_ps_write_en(vector_shared_store_o_ps_write_en), .o_ps_write_addr(vector_shared_store_o_ps_write_addr),
            .o_ps_write_data(vector_shared_store_o_ps_write_data)
        );

        if (p_fixed_ps_channels) begin : g_channels
            ia_ps_channel_ram #(
                .p_bank_bytes(SHARED_BANK_BYTES), .p_total_bytes(SHARED_TOTAL_BYTES),
                .p_addr_width(SHARED_IA_ADDR_WIDTH), .p_bank_count_width(SHARED_PHYSICAL_BANKS_WIDTH),
                .p_shared_write_stage(1'b1),
                .p_ia_nonempty_writes(1'b1)
            ) u_ram (
                .clk(clk), .rst_n(core_rst_n),
                .i_access_enable(ram_access_en),
                .i_cfg_valid(ram_i_cfg_valid), .i_cfg_ia_banks(ram_i_cfg_ia_banks),
                .o_capacity_fault(ram_o_capacity_fault),
                .i_ia_read_en(ram_i_ia_read_en), .i_ia_read_addr(ram_i_ia_read_addr), .o_ia_read_data(ram_o_ia_read_data),
                .i_ia_write_en(ram_i_ia_write_en), .i_ia_write_addr(ram_i_ia_write_addr),
                .i_ia_write_data(ram_i_ia_write_data), .i_ia_write_mask(ram_i_ia_write_mask),
                .i_ia_shared_write_data(ram_i_ia_shared_write_data),
                .i_ps_read_en(ram_i_ps_read_en), .i_ps_read_addr(ram_i_ps_read_addr), .o_ps_read_data(ram_o_ps_read_data),
                .i_ps_write_en(ram_i_ps_write_en), .i_ps_write_addr(ram_i_ps_write_addr), .i_ps_write_data(ram_i_ps_write_data)
            );
        end else begin : g_rotating
            ia_ps_shared_ram #(
                .BANK_BYTES(SHARED_BANK_BYTES), .TOTAL_BYTES(SHARED_TOTAL_BYTES),
                .IA_ADDR_BITS(SHARED_IA_ADDR_WIDTH), .PS_ADDR_BITS(SHARED_PS_ADDR_WIDTH)
            ) u_ram (
                .clk(clk), .rst_n(core_rst_n),
                .cfg_valid(ram_i_cfg_valid), .cfg_ia_banks(ram_i_cfg_ia_banks),
                .capacity_fault(ram_o_capacity_fault),
                .ia_read_en(ram_i_ia_read_en), .ia_read_addr(ram_i_ia_read_addr), .ia_read_data(ram_o_ia_read_data),
                .ia_write_en(ram_i_ia_write_en), .ia_write_addr(ram_i_ia_write_addr),
                .ia_write_data(ram_i_ia_write_data), .ia_write_mask(ram_i_ia_write_mask),
                .ps_read_en(ram_i_ps_read_en), .ps_read_addr(ram_i_ps_read_addr), .ps_read_data(ram_o_ps_read_data),
                .ps_write_en(ram_i_ps_write_en), .ps_write_addr(ram_i_ps_write_addr), .ps_write_data(ram_i_ps_write_data)
            );
        end
    end else begin : g_fixed_ia_ps
        assign shared_ram_capacity_fault = 1'b0;
        assign ia_ram_read_data = '{default:'0};
        assign ps_ram_read_data = '{default:'0};
        assign engine_i_weight_read_valid = 1'b0;
        assign engine_i_weight_read_data = '0;
        assign engine_i_ps_read_valid = 1'b0;
        assign engine_i_ps_read_data = '0;
        assign vector_shared_store_o_idle = 1'b1;
        assign vector_shared_store_o_error = 1'b0;
    end endgenerate

    npu_matrix_engine #(
        .p_addr_width(ADDR_WIDTH),
        .p_bias_dma_size(BIAS_DMA_SIZE),
        .p_bus_width(BUS_WIDTH),
        .p_data_width(DATA_WIDTH),
        .p_dw_shared_quant_enable(DW_SHARED_QUANT_ENABLE),
        .p_enable_is_mode(ENABLE_IS_MODE),
        .p_enable_per_channel(ENABLE_PER_CHANNEL),
        .p_frame_exec_enabled(FRAME_EXEC_ENABLED),
        .p_frame_prefetch_enable(FRAME_PREFETCH_ENABLE),
        .p_ia_cache_blocks(IA_CACHE_BLOCKS),
        .p_ia_cache_slot_w(IA_CACHE_SLOT_W),
        .p_ia_compact_enable(IA_COMPACT_ENABLE),
        .p_ia_data_width(IA_DATA_WIDTH),
        .p_ia_max_cache_blocks(IA_MAX_CACHE_BLOCKS),
        .p_ia_slot_blocks(IA_SLOT_BLOCKS),
        .p_kernel_data_width(KERNEL_DATA_WIDTH),
        .p_matrix_input_lanes(MATRIX_INPUT_LANES),
        .p_oa_fifo_banks_max(OA_FIFO_BANKS_MAX),
        .p_oa_s16_fifo_banks_max(OA_S16_FIFO_BANKS_MAX),
        .p_ps_frame_count(PS_FRAME_COUNT),
        .p_ps_frame_id_w(PS_FRAME_ID_W),
        .p_ps_storage_rows(PS_STORAGE_ROWS),
        .p_reg_width(REG_WIDTH),
        .p_shared_requant_lanes(REQUANT_COMPUTE_LANES),
        .p_shared_bank_bytes(SHARED_BANK_BYTES),
        .p_shared_ia_addr_width(SHARED_IA_ADDR_WIDTH),
        .p_shared_physical_banks(SHARED_PHYSICAL_BANKS),
        .p_shared_physical_banks_width(SHARED_PHYSICAL_BANKS_WIDTH),
        .p_shared_ps_addr_width(SHARED_PS_ADDR_WIDTH),
        .p_shared_ps_directory_rows(SHARED_PS_DIRECTORY_ROWS),
        .p_shared_ram_enabled(SHARED_RAM_ENABLED),
        .p_shared_total_bytes(SHARED_TOTAL_BYTES),
        .p_size(SIZE),
        .p_size_shift(SIZE_SHIFT),
        .p_vector_shared_ia_banks(VECTOR_SHARED_IA_BANKS),
        .p_fixed_ps_channels(p_fixed_ps_channels)
    ) u_matrix_engine (
        .i_abort_pending(abort_pending),
        .i_act_max(act_max),
        .i_act_min(act_min),
        .i_bias_base(bias_base),
        .i_bias_dma_busy(bias_dma_busy),
        .i_bias_dma_done(bias_dma_done),
        .i_bias_dma_wr_col_base(bias_dma_wr_col_base),
        .i_bias_dma_wr_data(bias_dma_wr_data),
        .i_bias_dma_wr_row(bias_dma_wr_row),
        .i_bias_dma_wr_slot(bias_dma_wr_slot),
        .i_bias_dma_wr_use_16bits(bias_dma_wr_use_16bits),
        .i_bias_dma_wr_valid(bias_dma_wr_valid),
        .i_calc_start(calc_start),
        .i_cfg_16bits_ia(cfg_16bits_ia),
        .i_cfg_16x8(cfg_16x8),
        .i_cfg_col_groups(cfg_col_groups),
        .i_cfg_col_tail_tiles(cfg_col_tail_tiles),
        .i_cfg_conv(cfg_conv),
        .i_cfg_conv_enable(cfg_conv_enable),
        .i_cfg_dataflow_mode(cfg_dataflow_mode),
        .i_cfg_dataflow_mode_eff(cfg_dataflow_mode_eff),
        .i_cfg_ia_reuse_num(cfg_ia_reuse_num),
        .i_cfg_rhs_tile_packed(cfg_rhs_tile_packed),
        .i_cfg_row_groups(cfg_row_groups),
        .i_cfg_row_tail_tiles(cfg_row_tail_tiles),
        .i_cfg_shared_ia_banks(cfg_shared_ia_banks),
        .i_cfg_vector_enable(cfg_vector_enable),
        .i_cfg_w_reuse_num(cfg_w_reuse_num),
        .clk(clk),
        .i_conv_cfg_q(conv_cfg_q),
        .rst_n(core_rst_n),
        .i_dst_base(dst_base),
        .i_dst_row_stride_b(dst_row_stride_b),
        .i_dst_zp(dst_zp),
        .i_dw_quant_accumulator(dw_quant_accumulator),
        .i_dw_quant_mask(dw_quant_mask),
        .i_dw_quant_maximum(dw_quant_maximum),
        .i_dw_quant_minimum(dw_quant_minimum),
        .i_dw_quant_multiplier(dw_quant_multiplier),
        .i_dw_quant_offset(dw_quant_offset),
        .i_dw_quant_req_tag(dw_quant_req_tag),
        .i_dw_quant_req_valid(dw_quant_req_valid),
        .i_dw_quant_right(dw_quant_right),
        .i_ia_dma_busy(ia_dma_busy),
        .i_ia_dma_done(ia_dma_done),
        .i_ia_dma_wr_col_base(ia_dma_wr_col_base),
        .i_ia_dma_wr_data(ia_dma_wr_data),
        .i_ia_dma_wr_row(ia_dma_wr_row),
        .i_ia_dma_wr_slot(ia_dma_wr_slot),
        .i_ia_dma_wr_use_16bits(ia_dma_wr_use_16bits),
        .i_ia_dma_wr_valid(ia_dma_wr_valid),
        .i_ia_ram_read_data(ia_ram_read_data),
        .i_k(k),
        .i_kernel_dma_busy(kernel_dma_busy),
        .i_kernel_dma_done(kernel_dma_done),
        .i_kernel_dma_wr_col_base(kernel_dma_wr_col_base),
        .i_kernel_dma_wr_data(kernel_dma_wr_data),
        .i_kernel_dma_wr_row(kernel_dma_wr_row),
        .i_kernel_dma_wr_slot(kernel_dma_wr_slot),
        .i_kernel_dma_wr_valid(kernel_dma_wr_valid),
        .i_lhs_base(lhs_base),
        .i_lhs_row_stride_b(lhs_row_stride_b),
        .i_lhs_zp(lhs_zp),
        .i_load_bias_granted(load_bias_granted),
        .i_load_ia_granted(load_ia_granted),
        .i_load_quant_granted(load_quant_granted),
        .i_load_weight_granted(load_weight_granted),
        .i_m(m),
        .i_n(n),
        .i_oa_dma_busy(oa_dma_busy),
        .i_oa_dma_done(oa_dma_done),
        .i_oa_dma_src_wready(oa_dma_src_wready),
        .i_operand_loader_flush_q(operand_loader_flush_q),
        .i_ps_control_q(ps_control_q),
        .i_ps_ram_read_data(ps_ram_read_data),
        .i_q_mult_pt(q_mult_pt),
        .i_q_shift_pt(q_shift_pt),
        .i_quant_dma_raw_data(quant_dma_raw_data),
        .i_quant_dma_raw_valid(quant_dma_raw_valid),
        .i_rhs_base(rhs_base),
        .i_rhs_col_stride_b(rhs_col_stride_b),
        .i_rhs_zp(rhs_zp),
        .i_run_conv(run_conv),
        .i_run_lhs_tile_packed(run_lhs_tile_packed),
        .i_run_rhs_tile_packed(run_rhs_tile_packed),
        .i_run_vector(run_vector),
        .i_sa_ready(sa_ready),
        .i_task_completion_accept(task_completion_accept),
        .i_use_per_channel(use_per_channel),
        .i_vector_start_fire(vector_start_fire),
        .i_write_oa_granted(write_oa_granted),
        .o_bias_dma_base_addr(bias_dma_base_addr),
        .o_bias_dma_burst_len_m1(bias_dma_burst_len_m1),
        .o_bias_dma_lhs_zp(bias_dma_lhs_zp),
        .o_bias_dma_linear_read_mode(bias_dma_linear_read_mode),
        .o_bias_dma_row_stride(bias_dma_row_stride),
        .o_bias_dma_rows_to_read(bias_dma_rows_to_read),
        .o_bias_dma_slot_id(bias_dma_slot_id),
        .o_bias_dma_start(bias_dma_start),
        .o_bias_dma_use_16bits(bias_dma_use_16bits),
        .o_cfg_16x8_q(cfg_16x8_q),
        .o_cfg_ia_reuse_q(cfg_ia_reuse_q),
        .o_cfg_stage2_fire(cfg_stage2_fire),
        .o_cfg_stream_k_q(cfg_stream_k_q),
        .o_cfg_stream_m_q(cfg_stream_m_q),
        .o_cfg_use16_q(cfg_use16_q),
        .o_cfg_valid_q(cfg_valid_q),
        .o_cfg_w_reuse_q(cfg_w_reuse_q),
        .o_controller_done_valid(controller_done_valid),
        .o_controller_err_code(controller_err_code),
        .o_conv_range_base(conv_range_base),
        .o_conv_range_end(conv_range_end),
        .o_ctrl_sa_ready(ctrl_sa_ready),
        .o_dw_quant_req_ready(dw_quant_req_ready),
        .o_dw_quant_rsp_tag(dw_quant_rsp_tag),
        .o_dw_quant_rsp_valid(dw_quant_rsp_valid),
        .o_exec_dma_job_init(exec_dma_job_init),
        .o_frame_mode_q(frame_mode_q),
        .o_frame_scheduler_ready(frame_scheduler_ready),
        .o_ia_dma_base_addr(ia_dma_base_addr),
        .o_ia_dma_burst_len_m1(ia_dma_burst_len_m1),
        .o_ia_dma_group(ia_dma_group),
        .o_ia_dma_im2col(ia_dma_im2col),
        .o_ia_dma_lhs_zp(ia_dma_lhs_zp),
        .o_ia_dma_linear_read_mode(ia_dma_linear_read_mode),
        .o_ia_dma_p0(ia_dma_p0),
        .o_ia_dma_q0(ia_dma_q0),
        .o_ia_dma_row_stride(ia_dma_row_stride),
        .o_ia_dma_rows_to_read(ia_dma_rows_to_read),
        .o_ia_dma_slot_id(ia_dma_slot_id),
        .o_ia_dma_start(ia_dma_start),
        .o_ia_dma_use_16bits(ia_dma_use_16bits),
        .o_ia_prefetch_idle(ia_prefetch_idle),
        .o_ia_ram_read_addr(ia_ram_read_addr),
        .o_ia_ram_read_en(ia_ram_read_en),
        .o_ia_ram_shared_write_data(ia_ram_shared_write_data),
        .o_ia_ram_write_addr(ia_ram_write_addr),
        .o_ia_ram_write_data(ia_ram_write_data),
        .o_ia_ram_write_en(ia_ram_write_en),
        .o_ia_ram_write_mask(ia_ram_write_mask),
        .o_ia_reuse_num_eff(ia_reuse_num_eff),
        .o_inner_done_valid(inner_done_valid),
        .o_inner_err_code(inner_err_code),
        .o_is_mode(is_mode),
        .o_kernel_dma_base_addr(kernel_dma_base_addr),
        .o_kernel_dma_burst_len_m1(kernel_dma_burst_len_m1),
        .o_kernel_dma_group(kernel_dma_group),
        .o_kernel_dma_im2col(kernel_dma_im2col),
        .o_kernel_dma_lhs_zp(kernel_dma_lhs_zp),
        .o_kernel_dma_linear_read_mode(kernel_dma_linear_read_mode),
        .o_kernel_dma_p0(kernel_dma_p0),
        .o_kernel_dma_q0(kernel_dma_q0),
        .o_kernel_dma_row_stride(kernel_dma_row_stride),
        .o_kernel_dma_rows_to_read(kernel_dma_rows_to_read),
        .o_kernel_dma_slot_id(kernel_dma_slot_id),
        .o_kernel_dma_start(kernel_dma_start),
        .o_kernel_dma_use_16bits(kernel_dma_use_16bits),
        .o_kernel_prefetch_idle(kernel_prefetch_idle),
        .o_load_bias_req(load_bias_req),
        .o_load_ia_req(load_ia_req),
        .o_load_quant_req(load_quant_req),
        .o_load_weight_req(load_weight_req),
        .o_oa_dma_base_addr(oa_dma_base_addr),
        .o_oa_dma_burst_len_m1(oa_dma_burst_len_m1),
        .o_oa_dma_row_stride(oa_dma_row_stride),
        .o_oa_dma_rows_to_read(oa_dma_rows_to_read),
        .o_oa_dma_src_wdata(oa_dma_src_wdata),
        .o_oa_dma_src_wmask(oa_dma_src_wmask),
        .o_oa_dma_src_wvalid(oa_dma_src_wvalid),
        .o_oa_dma_start(oa_dma_start),
        .o_ps_capacity_fault(ps_capacity_fault),
        .o_ps_ram_read_addr(ps_ram_read_addr),
        .o_ps_ram_read_en(ps_ram_read_en),
        .o_ps_ram_write_addr(ps_ram_write_addr),
        .o_ps_ram_write_data(ps_ram_write_data),
        .o_ps_ram_write_en(ps_ram_write_en),
        .o_quant_dma_base_addr(quant_dma_base_addr),
        .o_quant_dma_burst_len_m1(quant_dma_burst_len_m1),
        .o_quant_dma_lhs_zp(quant_dma_lhs_zp),
        .o_quant_dma_linear_read_mode(quant_dma_linear_read_mode),
        .o_quant_dma_row_stride(quant_dma_row_stride),
        .o_quant_dma_rows_to_read(quant_dma_rows_to_read),
        .o_quant_dma_slot_id(quant_dma_slot_id),
        .o_quant_dma_start(quant_dma_start),
        .o_quant_dma_use_16bits(quant_dma_use_16bits),
        .o_requant_out(requant_out),
        .o_run_compact(run_compact),
        .o_shared_allocation_invalid(shared_allocation_invalid),
        .o_shared_ia_banks_q(shared_ia_banks_q),
        .o_write_oa_req(write_oa_req)
    );

    npu_operand_cache_bridge #(
        .p_bus_width(BUS_WIDTH),
        .p_operand_cache_enable(OPERAND_CACHE_ENABLE),
        .p_operand_stream_bytes(OPERAND_STREAM_BYTES),
        .p_reg_width(REG_WIDTH),
        .p_size_shift(SIZE_SHIFT)
    ) u_operand_cache_bridge (
        .i_cache_axi_araddr(cache_axi_araddr),
        .i_cache_axi_arburst(cache_axi_arburst),
        .i_cache_axi_arlen(cache_axi_arlen),
        .i_cache_axi_arsize(cache_axi_arsize),
        .i_cache_axi_arvalid(cache_axi_arvalid),
        .i_cache_axi_rready(cache_axi_rready),
        .i_calc_start(calc_start),
        .i_cfg_16x8_q(cfg_16x8_q),
        .i_cfg_conv_enable(cfg_conv_enable),
        .i_cfg_dataflow_mode_eff(cfg_dataflow_mode_eff),
        .i_cfg_ia_reuse_q(cfg_ia_reuse_q),
        .i_cfg_lhs_tile_packed(cfg_lhs_tile_packed),
        .i_cfg_operand_fetch64(cfg_operand_fetch64),
        .i_cfg_rhs_tile_packed(cfg_rhs_tile_packed),
        .i_cfg_stage2_fire(cfg_stage2_fire),
        .i_cfg_stream_k_q(cfg_stream_k_q),
        .i_cfg_stream_m_q(cfg_stream_m_q),
        .i_cfg_use16_q(cfg_use16_q),
        .i_cfg_vector_enable(cfg_vector_enable),
        .i_cfg_w_reuse_q(cfg_w_reuse_q),
        .clk(clk),
        .rst_n(core_rst_n),
        .i_k(k),
        .i_legacy_axi_arready(legacy_axi_arready),
        .i_legacy_axi_rdata(legacy_axi_rdata),
        .i_legacy_axi_rlast(legacy_axi_rlast),
        .i_legacy_axi_rresp(legacy_axi_rresp),
        .i_legacy_axi_rvalid(legacy_axi_rvalid),
        .i_lhs_base(lhs_base),
        .i_lhs_row_stride_b(lhs_row_stride_b),
        .i_m(m),
        .i_rhs_base(rhs_base),
        .i_rhs_col_stride_b(rhs_col_stride_b),
        .i_run_conv(run_conv),
        .i_run_lhs_tile_packed(run_lhs_tile_packed),
        .i_run_rhs_tile_packed(run_rhs_tile_packed),
        .i_sa_ready(sa_ready),
        .o_cache_axi_arready(cache_axi_arready),
        .o_cache_axi_rdata(cache_axi_rdata),
        .o_cache_axi_rlast(cache_axi_rlast),
        .o_cache_axi_rresp(cache_axi_rresp),
        .o_cache_axi_rvalid(cache_axi_rvalid),
        .o_legacy_axi_araddr(legacy_axi_araddr),
        .o_legacy_axi_arburst(legacy_axi_arburst),
        .o_legacy_axi_arlen(legacy_axi_arlen),
        .o_legacy_axi_arsize(legacy_axi_arsize),
        .o_legacy_axi_arvalid(legacy_axi_arvalid),
        .o_legacy_axi_rready(legacy_axi_rready),
        .o_operand_cache_idle(operand_cache_idle)
    );
endmodule

`default_nettype wire
