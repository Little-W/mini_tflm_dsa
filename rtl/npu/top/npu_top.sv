`ifndef GEMMORA_PS_POOL_BYTES
`define GEMMORA_PS_POOL_BYTES 179200
`endif
// NPU 顶层模块：矩阵/卷积算子的分块计算、量化和写回数据通路
module npu_top #(
    parameter int unsigned WEIGHT_WIDTH = 16,  // 权重数据宽度；WS 下 s8 符号扩展，IS+s16 下使用 16bit LHS
    parameter int unsigned DATA_WIDTH = 16,  // IA数据宽度
    parameter int unsigned SIZE = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH = 32,  // 总线宽度
    parameter int unsigned REG_WIDTH = 32,  // 寄存器宽度
    parameter int unsigned ADDR_WIDTH = 19,  // AXI 地址宽度
    parameter int unsigned IA_CACHE_BLOCKS = 4,  // IA loader cache slots；默认 IA reuse = IA_CACHE_BLOCKS/2
    parameter int unsigned OPERAND_CACHE_ENABLE = 0,
    parameter int unsigned CONV_CACHE_SETS = 32,
    parameter int unsigned CONV_CACHE_WAYS = 2,
    parameter int unsigned CONV_LINE_BYTES = 16,
    parameter int unsigned CONV_CACHE_POLICY = 2,
    parameter int unsigned ENABLE_DW_POOL = 1,
    parameter int unsigned DW_PE_COUNT = (SIZE < 8) ? SIZE : 8,
    parameter int unsigned DW_MAX_TAPS = 49,
    parameter int unsigned PS_FRAME_COUNT = SIZE,  // PS buffer 可保留的输出列 tile 数
    parameter int unsigned OPERAND_STREAM_BYTES = (PS_FRAME_COUNT >= 16) ? 65536 : 262144,
    parameter int unsigned AXI_READ_OUTSTANDING = 4,  // AXI 读通道最多提前排队的 burst 数
    parameter int unsigned AXI_WRITE_OUTSTANDING = AXI_READ_OUTSTANDING,  // AXI 写通道最多提前排队的 burst 数
    parameter int unsigned ENABLE_IS_MODE = 1,  // 置 0 时综合裁剪 IS 转置/分组 bias 支持
    parameter int unsigned ENABLE_PER_CHANNEL = 1,  // 置 0 时综合裁剪 per-channel 量化装载路径
    parameter int unsigned OA_FIFO_BANKS_MAX =
        ((ENABLE_IS_MODE == 0) && (ENABLE_PER_CHANNEL == 0)) ? 16 :
        32  // common 8 KiB output FIFO in this experiment; 写回 FIFO 最大 tile bank 数；裁剪版用更浅线性 FIFO 压低面积
) (
    //==== 时钟与复位 ====
    input wire clk,   // 系统时钟
    input wire rst_n, // 异步复位，低有效

    //==== 外部控制接口 ====
    input wire cfg_operand_fetch64, // 0: 16-byte sectors; 1: 64-byte read allocation
    input wire cfg_conv_enable = 1'b0,
    input conv_im2col_pkg::conv_cfg_t cfg_conv = '0,
    input wire cfg_dw_enable = 1'b0,
    input dw_pool_pkg::dw_pool_cfg_t cfg_dw = '0,
    output logic [31:0] dw_stat_cycles, dw_stat_compute, dw_stat_dma_wait,
    output logic [31:0] conv_stat_hits, conv_stat_misses, conv_stat_read_bytes, conv_stat_cycles,
    input wire calc_start,  // 计算开始信号
    input wire cfg_16bits_ia,  // 使用16位IA数据
    input wire cfg_16x8,  // TFLM s16 activation x s8 weight, s32 bias, s16 output
    input wire cfg_dataflow_mode,  // 0: WS, 1: IS
    input  logic [REG_WIDTH-1:0] cfg_ia_reuse_num,  // IA L1 组复用深度，ABI 2: 外部写入最终生效值，0 非法
    input  logic [REG_WIDTH-1:0] cfg_w_reuse_num,   // W 侧复用窗口，ABI 2: 外部写入最终生效值，0 非法
    input logic [REG_WIDTH-1:0] cfg_row_groups,
    input logic [REG_WIDTH-1:0] cfg_row_tail_tiles,
    input logic [REG_WIDTH-1:0] cfg_col_groups,
    input logic [REG_WIDTH-1:0] cfg_col_tail_tiles,
    output wire sa_ready,  // 系统就绪信号

    //==== 完成握手接口 ====
    output wire       done_valid,  // 任务完成有效信号
    input  wire       done_ready,  // 任务完成接收就绪信号
    output wire [1:0] err_code,  // 完成状态码

    // --- base pointers
    input logic [REG_WIDTH-1:0] lhs_base,  // A base         (MULT_LHS_PTR)
    input logic [REG_WIDTH-1:0] rhs_base,  // B base (s8)    (MULT_RHS_PTR, N x K row-major)
    input logic [REG_WIDTH-1:0] dst_base,  // C base (s8)    (MULT_DST_PTR)
    input logic [REG_WIDTH-1:0] bias_base, // bias s32 (0=none)   (MULT_BIAS_PTR)

    // --- quantization & zero-points ---
    input logic signed [REG_WIDTH-1:0] lhs_zp,          // A zero-point (s32)  (MULT_LHS_OFFSET)
    input logic signed [REG_WIDTH-1:0] rhs_zp,          // B zero-point (s32)  (MULT_RHS_OFFSET)
    input logic signed [REG_WIDTH-1:0] dst_zp,          // C zero-point (s32)  (MULT_DST_OFFSET)
    input logic signed [REG_WIDTH-1:0] q_mult_pt,       // per-tensor mult     (MULT_DST_MULT)
    input logic signed [REG_WIDTH-1:0] q_shift_pt,      // per-tensor rshift
    // (MULT_DST_SHIFT, +N => >>N)
    input logic                        use_per_channel, // 1: per-channel; 0: per-tensor

    // --- dimensions ---
    input logic [REG_WIDTH-1:0] k,  // IA矩阵行数
    input logic [REG_WIDTH-1:0] n,  // IA矩阵列数 = W矩阵行数
    input logic [REG_WIDTH-1:0] m,  // W矩阵列数

    // --- row strides (all in BYTES) ---
    input logic [REG_WIDTH-1:0] lhs_row_stride_b,  // A row stride       (MULT_LHS_COLS_OFFSET)
    input logic [REG_WIDTH-1:0] dst_row_stride_b,  // C row stride       (MULT_ROW_ADDR_OFFSET)
    input logic [REG_WIDTH-1:0] rhs_col_stride_b,  // B row stride       (MULT_RHS_ROW_STRIDE) （转置后的右矩阵是列展平的，所以这个步长本质上是列步长）

    // --- activation clamp ---
    input logic signed [REG_WIDTH-1:0] act_min,  // (MULT_ACT_MIN)
    input logic signed [REG_WIDTH-1:0] act_max,  // (MULT_ACT_MAX)

    //==== AXI4 master 接口 ====
    output logic                   m_axi_arvalid,
    input  logic                   m_axi_arready,
    output logic [  REG_WIDTH-1:0] m_axi_araddr,
    output logic [            7:0] m_axi_arlen,
    output logic [            2:0] m_axi_arsize,
    output logic [            1:0] m_axi_arburst,
    input  logic                   m_axi_rvalid,
    output logic                   m_axi_rready,
    input  logic [  BUS_WIDTH-1:0] m_axi_rdata,
    input  logic [            1:0] m_axi_rresp,
    input  logic                   m_axi_rlast,

    output logic                   m_axi_awvalid,
    input  logic                   m_axi_awready,
    output logic [  REG_WIDTH-1:0] m_axi_awaddr,
    output logic [            7:0] m_axi_awlen,
    output logic [            2:0] m_axi_awsize,
    output logic [            1:0] m_axi_awburst,
    output logic                   m_axi_wvalid,
    input  logic                   m_axi_wready,
    output logic [  BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic                   m_axi_wlast,
    input  logic                   m_axi_bvalid,
    output logic                   m_axi_bready,
    input  logic [            1:0] m_axi_bresp
);


`ifdef GEMPACT_PANEL_ENGINE
    wire alt_ready, alt_done;
    wire [1:0] alt_error;
    logic unsupported_conv_done;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) unsupported_conv_done <= 1'b0;
        else if (calc_start && sa_ready && (cfg_conv_enable || cfg_dw_enable)) unsupported_conv_done <= 1'b1;
        else if (unsupported_conv_done && done_ready) unsupported_conv_done <= 1'b0;
    end
    assign sa_ready = alt_ready && !unsupported_conv_done;
    assign done_valid = alt_done || unsupported_conv_done;
    assign err_code = unsupported_conv_done ? 2'b01 : alt_error;
    assign conv_stat_hits = '0;
    assign conv_stat_misses = '0;
    assign conv_stat_read_bytes = '0;
    assign conv_stat_cycles = '0;
    assign dw_stat_cycles = '0;
    assign dw_stat_compute = '0;
    assign dw_stat_dma_wait = '0;
    gempact_panel_engine #(.POOL_BYTES(`GEMMORA_PS_POOL_BYTES), .SIZE(SIZE), .BUS_WIDTH(BUS_WIDTH), .REG_WIDTH(REG_WIDTH), .ADDR_WIDTH(ADDR_WIDTH), .IA_CACHE_BLOCKS(IA_CACHE_BLOCKS), .PS_FRAME_COUNT(PS_FRAME_COUNT)) u_panel(
        .calc_start(calc_start && !cfg_conv_enable && !cfg_dw_enable), .sa_ready(alt_ready),
        .done_valid(alt_done), .err_code(alt_error), .*);
`elsif GEMPACT_RESIDENT_ENGINE
    wire alt_ready, alt_done;
    wire [1:0] alt_error;
    logic unsupported_conv_done;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) unsupported_conv_done <= 1'b0;
        else if (calc_start && sa_ready && (cfg_conv_enable || cfg_dw_enable)) unsupported_conv_done <= 1'b1;
        else if (unsupported_conv_done && done_ready) unsupported_conv_done <= 1'b0;
    end
    assign sa_ready = alt_ready && !unsupported_conv_done;
    assign done_valid = alt_done || unsupported_conv_done;
    assign err_code = unsupported_conv_done ? 2'b01 : alt_error;
    assign conv_stat_hits = '0;
    assign conv_stat_misses = '0;
    assign conv_stat_read_bytes = '0;
    assign conv_stat_cycles = '0;
    assign dw_stat_cycles = '0;
    assign dw_stat_compute = '0;
    assign dw_stat_dma_wait = '0;
    gempact_resident_engine #(.POOL_BYTES(`GEMMORA_PS_POOL_BYTES), .SIZE(SIZE), .BUS_WIDTH(BUS_WIDTH), .REG_WIDTH(REG_WIDTH), .ADDR_WIDTH(ADDR_WIDTH), .IA_CACHE_BLOCKS(IA_CACHE_BLOCKS), .PS_FRAME_COUNT(PS_FRAME_COUNT)) u_resident(
        .calc_start(calc_start && !cfg_conv_enable && !cfg_dw_enable), .sa_ready(alt_ready),
        .done_valid(alt_done), .err_code(alt_error), .*);
`else

    // A Conv task is immutable after acceptance. The legacy software keeps
    // the other task fields stable; the AXI-Lite interface locks writes while busy.
    logic run_conv, run_dw, dw_rejected;
    logic dw_engine_ready, dw_engine_done;
    logic [1:0] dw_engine_error;
    logic normal_done_valid;
    logic [1:0] normal_err_code;
    logic dw_dma_cfg_valid, dw_dma_conv_enable, dw_dma_range_enable;
    conv_im2col_pkg::conv_cfg_t dw_dma_conv_cfg;
    logic [31:0] dw_dma_range_base [4], selected_range_base [4];
    logic [32:0] dw_dma_range_end [4], selected_range_end [4];
`ifdef GEMMORA_INT8_PROFILE
    localparam bit DW_POOL_CAPABLE = 1'b0;
`else
    localparam bit DW_POOL_CAPABLE = ENABLE_DW_POOL != 0 && BUS_WIDTH == 32 && REG_WIDTH == 32 &&
        SIZE >= 2 && SIZE <= 64 && ((SIZE & (SIZE-1)) == 0) &&
        DW_MAX_TAPS >= 1 && DW_MAX_TAPS <= 255 && DW_PE_COUNT >= 1 &&
        DW_PE_COUNT <= SIZE && ((DW_PE_COUNT & (DW_PE_COUNT-1)) == 0);
`endif
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            run_dw <= 1'b0;
            dw_rejected <= 1'b0;
        end else begin
            if (calc_start && sa_ready) begin
                run_dw <= cfg_dw_enable;
                dw_rejected <= cfg_dw_enable && (!DW_POOL_CAPABLE || cfg_conv_enable);
            end else if (run_dw && done_valid && done_ready) begin
                run_dw <= 1'b0;
                dw_rejected <= 1'b0;
            end
        end
    end
    assign done_valid = run_dw ? (dw_rejected || dw_engine_done) : normal_done_valid;
    assign err_code = run_dw ? (dw_rejected ? 2'b01 : dw_engine_error) : normal_err_code;
    for (genvar r = 0; r < 4; r++) begin : g_dma_ranges
        assign selected_range_base[r] = run_dw ? dw_dma_range_base[r] : conv_range_base[r];
        assign selected_range_end[r] = run_dw ? dw_dma_range_end[r] : conv_range_end[r];
    end
    conv_im2col_pkg::conv_cfg_t conv_cfg_q;
    logic conv_error, conv_busy, dma_bus_error, dma_idle;
    logic conv_cfg_ready;
    wire operand_cache_idle;
    logic arbiter_ia_granted;
    logic [31:0] conv_hits_raw, conv_misses_raw, conv_read_bytes_raw;
    logic legacy_axi_arvalid, legacy_axi_arready, legacy_axi_rvalid, legacy_axi_rready, legacy_axi_rlast;
    logic [REG_WIDTH-1:0] legacy_axi_araddr;
    logic [BUS_WIDTH-1:0] legacy_axi_rdata;
    logic [7:0] legacy_axi_arlen;
    logic [2:0] legacy_axi_arsize;
    logic [1:0] legacy_axi_arburst, legacy_axi_rresp;
    logic [31:0] conv_range_base[4];
    logic [32:0] conv_range_end[4];
    assign conv_range_base[0] = 32'(rhs_base);
    assign conv_range_base[1] = 32'(bias_base);
    assign conv_range_base[2] = use_per_channel ? 32'(q_mult_pt) : 32'd0;
    assign conv_range_base[3] = use_per_channel ? 32'(q_shift_pt) : 32'd0;
    assign conv_range_end[0] = 33'(rhs_base) + 33'(64'(n)*64'(m));
    assign conv_range_end[1] = 33'(bias_base) + (33'(m)<<2);
    assign conv_range_end[2] = 33'($unsigned(q_mult_pt)) + (33'(m)<<2);
    assign conv_range_end[3] = 33'($unsigned(q_shift_pt)) + (33'(m)<<2);
    typedef enum logic [1:0] {AB_IDLE, AB_DRAIN, AB_RESET, AB_DONE} abort_t;
    abort_t abort_state;
    wire abort_pending = abort_state != AB_IDLE;
    wire core_rst_n = rst_n && (abort_state != AB_RESET);
    logic conv_count_active, conv_stats_started;
`ifdef GEMMORA_INT8_PROFILE
    localparam bit CONV_CORE_SUPPORTED = 1'b0;
`else
    localparam bit CONV_CORE_SUPPORTED = DATA_WIDTH >= 16 && BUS_WIDTH == 32 && REG_WIDTH == 32 && ENABLE_PER_CHANNEL != 0;
`endif
    wire [63:0] conv_input_bytes = 64'(conv_cfg_q.input_h) * 64'(conv_cfg_q.input_w) * 64'(conv_cfg_q.input_c);
    wire conv_config_invalid = run_conv &&
        (!CONV_CORE_SUPPORTED ||
         (cfg_dataflow_mode && (ENABLE_IS_MODE == 0 || KERNEL_DATA_WIDTH < 16)) ||
         !cfg_16bits_ia || cfg_16x8 || conv_cfg_q.input_s16 ||
         (lhs_zp != 0) || (rhs_zp != 0) ||
         conv_cfg_q.input_h == 0 || conv_cfg_q.input_w == 0 || conv_cfg_q.input_c == 0 ||
         conv_cfg_q.kernel_h == 0 || conv_cfg_q.kernel_w == 0 || conv_cfg_q.group_c == 0 ||
         conv_cfg_q.output_h == 0 || conv_cfg_q.output_w == 0 ||
         conv_cfg_q.stride_h == 0 || conv_cfg_q.stride_w == 0 ||
         conv_cfg_q.dilation_h == 0 || conv_cfg_q.dilation_w == 0 ||
         (32'(conv_cfg_q.group_offset)+32'(conv_cfg_q.group_c) > 32'(conv_cfg_q.input_c)) ||
         $signed(conv_cfg_q.input_offset) < -127 || $signed(conv_cfg_q.input_offset) > 128 ||
         (64'(conv_cfg_q.input_base) + conv_input_bytes >= 64'h1_0000_0000) ||
         (64'(rhs_base) + 64'(n)*64'(m) >= 64'h1_0000_0000) ||
         (64'(bias_base) + (64'(m)<<2) >= 64'h1_0000_0000) ||
         (use_per_channel && (64'($unsigned(q_mult_pt))+(64'(m)<<2) >= 64'h1_0000_0000 ||
                              64'($unsigned(q_shift_pt))+(64'(m)<<2) >= 64'h1_0000_0000)) ||
         (64'(conv_cfg_q.output_h) * 64'(conv_cfg_q.output_w) != 64'(k)) ||
         (64'(conv_cfg_q.kernel_h) * 64'(conv_cfg_q.kernel_w) * 64'(conv_cfg_q.group_c) != 64'(n)));
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            run_conv <= 1'b0; conv_cfg_q <= '0; abort_state <= AB_IDLE;
            conv_stat_hits <= '0; conv_stat_misses <= '0; conv_stat_read_bytes <= '0;
            conv_stat_cycles <= '0; conv_count_active <= 1'b0; conv_stats_started <= 1'b0;
        end else begin
            if (calc_start && sa_ready) begin
                run_conv <= cfg_conv_enable && !cfg_dw_enable;
                conv_cfg_q <= cfg_conv;
                conv_stats_started <= 1'b0;
                if (cfg_conv_enable && !cfg_dw_enable) begin
                    conv_stat_hits <= '0; conv_stat_misses <= '0;
                    conv_stat_read_bytes <= '0; conv_stat_cycles <= '0;
                    conv_count_active <= 1'b1;
                end
            end
            if (conv_count_active) begin
                conv_stat_cycles <= conv_stat_cycles + 32'd1;
                if (conv_stats_started && abort_state != AB_RESET && abort_state != AB_DONE) begin
                    conv_stat_hits <= conv_hits_raw;
                    conv_stat_misses <= conv_misses_raw;
                    conv_stat_read_bytes <= conv_read_bytes_raw;
                end
            end
            if (init_cfg_ia && run_conv) conv_stats_started <= 1'b1;
            if (done_valid) conv_count_active <= 1'b0;
            case (abort_state)
                AB_IDLE: if (run_conv && (conv_error || dma_bus_error)) abort_state <= AB_DRAIN;
                AB_DRAIN: if (dma_idle && !conv_busy && operand_cache_idle) abort_state <= AB_RESET;
                AB_RESET: abort_state <= AB_DONE;
                AB_DONE: if (done_ready) begin abort_state <= AB_IDLE; run_conv <= 1'b0; end
                default: abort_state <= AB_IDLE;
            endcase
        end
    end
    // Both operand loaders always use the shared matrix-block DMA. Its read
    // engine owns im2col, the raw-input cache and the ordinary-read guard/mux.
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

    localparam int unsigned SIZE_SHIFT = $clog2(SIZE);
    wire cfg_dataflow_mode_eff = (ENABLE_IS_MODE != 0) ? cfg_dataflow_mode : 1'b0;
    logic cfg_use16_s2, cfg_16x8_s2;
    logic [REG_WIDTH-1:0] cfg_stream_k_s2, cfg_stream_m_s2;
    logic [REG_WIDTH-1:0] cfg_ia_reuse_eff_s2, cfg_w_reuse_eff_s2;
    wire cfg_stage2_fire;
    logic cache_axi_arvalid, cache_axi_arready, cache_axi_rvalid, cache_axi_rready, cache_axi_rlast;
    logic [REG_WIDTH-1:0] cache_axi_araddr;
    logic [7:0] cache_axi_arlen;
    logic [2:0] cache_axi_arsize;
    logic [1:0] cache_axi_arburst, cache_axi_rresp;
    logic [BUS_WIDTH-1:0] cache_axi_rdata;
    generate if (OPERAND_CACHE_ENABLE != 0) begin : g_operand_cache
        // Snapshot the task and pipeline range arithmetic. The original SoC
        // keeps configuration in AXI-Lite registers, so an unpipelined 32x32
        // extent product plus base addition is a real clocked timing path.
        localparam int HALF = (REG_WIDTH + 1) / 2;
        logic [3:0] range_stage;
        logic range_ready, fetch64_q;
        logic [REG_WIDTH-1:0] a_base_cfg, b_base_cfg;
        logic [REG_WIDTH-1:0] ax, ay, bx, by;
        (* use_dsp="yes" *) logic [REG_WIDTH-1:0] a_ll, a_lh, a_hl, b_ll, b_lh, b_hl;
        logic [REG_WIDTH-1:0] a_bytes_cfg, b_bytes_cfg;
        logic cache_request_ready;
        logic single_group_bypass;
        wire retained_arvalid, retained_rvalid, retained_rready, retained_rlast;
        wire [REG_WIDTH-1:0] retained_araddr;
        wire [7:0] retained_arlen;
        wire [2:0] retained_arsize;
        wire [1:0] retained_arburst, retained_rresp;
        wire [BUS_WIDTH-1:0] retained_rdata;
        wire accept_cache_task = calc_start && sa_ready;
        // A complete output workgroup already retains every required A/B K
        // tile in the native IA/PS schedule. It has no cross-group cache hits.
        // Select the direct path once per task, before any DMA request starts.
        // Conv always bypasses this optional matrix-operand cache: the shared
        // DMA owns raw-image reuse, and a virtual im2col stride is not an
        // external allocation. GEMM retains the original task-dependent path.
        always_ff @(posedge clk) begin
            if (!core_rst_n) single_group_bypass <= 1'b0;
            else begin
                if (accept_cache_task) single_group_bypass <= cfg_conv_enable || cfg_dw_enable;
                if (cfg_stage2_fire)
                    single_group_bypass <= run_conv || (!fetch64_q && !cfg_use16_s2 && !cfg_16x8_s2 &&
                        cfg_stream_k_s2 != 0 && cfg_stream_m_s2 != 0 &&
                        cfg_stream_k_s2 <= (cfg_ia_reuse_eff_s2 << SIZE_SHIFT) &&
                        cfg_stream_m_s2 <= (cfg_w_reuse_eff_s2 << SIZE_SHIFT));
            end
        end
        always_ff @(posedge clk) begin
            if (!core_rst_n) begin
                range_stage <= 0; range_ready <= 0; fetch64_q <= 0;
                a_base_cfg <= 0; b_base_cfg <= 0;
                ax <= 0; ay <= 0; bx <= 0; by <= 0;
                a_ll <= 0; a_lh <= 0; a_hl <= 0;
                b_ll <= 0; b_lh <= 0; b_hl <= 0;
                a_bytes_cfg <= 0; b_bytes_cfg <= 0;
            end else begin
                range_stage <= {range_stage[2:0],accept_cache_task};
                if (accept_cache_task) begin
                    range_ready <= 0;
                    fetch64_q <= cfg_operand_fetch64;
                    a_base_cfg <= cfg_dataflow_mode_eff ? rhs_base : lhs_base;
                    b_base_cfg <= cfg_dataflow_mode_eff ? lhs_base : rhs_base;
                    ax <= cfg_dataflow_mode_eff ? m : k;
                    ay <= cfg_dataflow_mode_eff ? rhs_col_stride_b : lhs_row_stride_b;
                    bx <= cfg_dataflow_mode_eff ? k : m;
                    by <= cfg_dataflow_mode_eff ? lhs_row_stride_b : rhs_col_stride_b;
                end
                if (range_stage[0]) begin
                    a_ll <= ax[HALF-1:0] * ay[HALF-1:0];
                    a_lh <= ax[HALF-1:0] * ay[REG_WIDTH-1:HALF];
                    a_hl <= ax[REG_WIDTH-1:HALF] * ay[HALF-1:0];
                    b_ll <= bx[HALF-1:0] * by[HALF-1:0];
                    b_lh <= bx[HALF-1:0] * by[REG_WIDTH-1:HALF];
                    b_hl <= bx[REG_WIDTH-1:HALF] * by[HALF-1:0];
                end
                if (range_stage[1]) begin
                    a_bytes_cfg <= a_ll + ((a_lh + a_hl) << HALF);
                    b_bytes_cfg <= b_ll + ((b_lh + b_hl) << HALF);
                end
                if (range_stage[3]) range_ready <= 1;
            end
        end
        assign cache_axi_arready = (single_group_bypass ? legacy_axi_arready : cache_request_ready) && range_ready;
        assign legacy_axi_arvalid = single_group_bypass ? (cache_axi_arvalid && range_ready) : retained_arvalid;
        assign legacy_axi_araddr = single_group_bypass ? cache_axi_araddr : retained_araddr;
        assign legacy_axi_arlen = single_group_bypass ? cache_axi_arlen : retained_arlen;
        assign legacy_axi_arsize = single_group_bypass ? cache_axi_arsize : retained_arsize;
        assign legacy_axi_arburst = single_group_bypass ? cache_axi_arburst : retained_arburst;
        assign cache_axi_rvalid = single_group_bypass ? legacy_axi_rvalid : retained_rvalid;
        assign cache_axi_rdata = single_group_bypass ? legacy_axi_rdata : retained_rdata;
        assign cache_axi_rresp = single_group_bypass ? legacy_axi_rresp : retained_rresp;
        assign cache_axi_rlast = single_group_bypass ? legacy_axi_rlast : retained_rlast;
        assign legacy_axi_rready = single_group_bypass ? cache_axi_rready : retained_rready;
        operand_read_cache #(.AW(REG_WIDTH), .DW(BUS_WIDTH), .A_BYTES(OPERAND_STREAM_BYTES)) u_cache (
            .clk(clk), .rst_n(core_rst_n), .flush(range_stage[2]),
            .idle(operand_cache_idle),
            .prefetch_enable(fetch64_q),
            // The large retention bank follows the streamed IA operand.
            // WS retains A; IS retains physical B (the internal C^T problem).
            .a_base(a_base_cfg), .a_bytes(a_bytes_cfg),
            .b_base(b_base_cfg), .b_bytes(b_bytes_cfg),
            .s_arvalid(cache_axi_arvalid && range_ready && !single_group_bypass), .m_arvalid(retained_arvalid),
            .s_arready(cache_request_ready), .m_arready(legacy_axi_arready),
            .s_araddr(cache_axi_araddr), .m_araddr(retained_araddr),
            .s_arlen(cache_axi_arlen), .m_arlen(retained_arlen),
            .s_arsize(cache_axi_arsize), .m_arsize(retained_arsize),
            .s_arburst(cache_axi_arburst), .m_arburst(retained_arburst),
            .s_rvalid(retained_rvalid), .m_rvalid(legacy_axi_rvalid && !single_group_bypass),
            .s_rready(cache_axi_rready && !single_group_bypass), .m_rready(retained_rready),
            .s_rdata(retained_rdata), .m_rdata(legacy_axi_rdata),
            .s_rresp(retained_rresp), .m_rresp(legacy_axi_rresp),
            .s_rlast(retained_rlast), .m_rlast(legacy_axi_rlast)
        );
    end else begin : g_no_operand_cache
        assign operand_cache_idle=1'b1;
        assign legacy_axi_arvalid=cache_axi_arvalid;
        assign cache_axi_arready=legacy_axi_arready;
        assign legacy_axi_araddr=cache_axi_araddr;
        assign legacy_axi_arlen=cache_axi_arlen;
        assign legacy_axi_arsize=cache_axi_arsize;
        assign legacy_axi_arburst=cache_axi_arburst;
        assign cache_axi_rvalid=legacy_axi_rvalid;
        assign legacy_axi_rready=cache_axi_rready;
        assign cache_axi_rdata=legacy_axi_rdata;
        assign cache_axi_rresp=legacy_axi_rresp;
        assign cache_axi_rlast=legacy_axi_rlast;
    end endgenerate

    //========================================
    // 内部信号定义
    //========================================
    localparam int unsigned BIAS_DMA_SIZE = SIZE * 4;
    localparam int unsigned SHARED_DMA_SIZE =
        (BIAS_DMA_SIZE > SIZE) ? BIAS_DMA_SIZE : SIZE;
    // int8 activations plus zero-point need more than 8 signed bits.
`ifdef GEMMORA_INT8_PROFILE
    // This profile requires INT8 operands with zero offsets; validate at launch.
    localparam int unsigned IA_DATA_WIDTH = DATA_WIDTH;
    localparam int unsigned KERNEL_DATA_WIDTH = WEIGHT_WIDTH;
`else
    localparam int unsigned IA_DATA_WIDTH =
        (DATA_WIDTH < 16) ? 16 : DATA_WIDTH;
    localparam int unsigned KERNEL_DATA_WIDTH =
        (WEIGHT_WIDTH < 16) ? 16 : WEIGHT_WIDTH;
`endif

    // IA Loader 内部信号
    wire load_ia_req;
    wire load_ia_granted;
    wire send_ia_trigger;
    wire ia_sending_done;
    wire ia_row_valid;
    wire ia_tile_start;
    wire ia_is_init_data;
    wire ia_calc_done;
    wire partial_sum_calc_over;
    wire signed [IA_DATA_WIDTH-1:0] ia_out[SIZE];
    wire ia_data_valid;
    wire ia_l1_switch;
    wire bias_sleep;
    wire bias_switch;
    wire bias_last_loop;

    // Kernel Loader 内部信号
    wire load_weight_req;
    wire load_weight_granted;
    wire send_weight_trigger;
    wire weight_sending_done;
    wire load_weight_done;
    wire store_weight_req;
    wire weight_commit;
    wire signed [KERNEL_DATA_WIDTH-1:0] weight_out[SIZE];
    wire weight_data_valid;

    // Bias Loader 内部信号
    wire load_bias_req;
    wire load_bias_granted;
    wire bias_valid;
    wire bias_group_valid;
    wire load_bias_done;
    wire signed [31:0] bias_data_out[SIZE];

    // Accumulator Array 输出（来自封装模块）
    wire acc_data_valid;
    wire tile_calc_over;
    wire signed [31:0] acc_data_out[SIZE];

    // Requantization 内部信号
    wire load_quant_req;
    wire load_quant_granted;
    wire quant_params_valid;
    wire load_quant_req_s8;
    wire quant_params_valid_s8;
    wire requant_out_valid;
    wire requant_out_tile_done;
    wire requant_s8_valid;
    wire requant_s8_tile_done;
    wire requant_s16_valid;
    wire requant_s16_tile_done;
    wire signed [7:0] requant_out[SIZE];
    wire signed [15:0] requant_out_s16[SIZE];
    wire signed [31:0] requant_multiplier_lane[SIZE];
    wire signed [31:0] requant_shift_lane[SIZE];

    // FIFO 内部信号
    wire fifo_output_req;
    wire [$clog2(SIZE)-1:0] fifo_vec_valid_num_col;
    wire [$clog2(SIZE)-1:0] fifo_vec_valid_num_row;
    wire fifo_output_valid;
    wire fifo_output_switch_row;
    wire fifo_output_ready;
    wire [3:0] fifo_output_mask;
    wire [31:0] fifo_output_data;
    wire fifo_full_flag;
    wire ia_output_pending;
    wire fifo_s8_output_req;
    wire fifo_s8_output_valid;
    wire fifo_s8_output_switch_row;
    wire [3:0] fifo_s8_output_mask;
    wire [31:0] fifo_s8_output_data;
    wire fifo_s8_full_flag;
    wire fifo_s16_output_req;
    wire fifo_s16_output_valid;
    wire fifo_s16_output_switch_row;
    wire [3:0] fifo_s16_output_mask;
    wire [31:0] fifo_s16_output_data;
    wire fifo_s16_full_flag;

    // OA Writer 内部信号
    wire write_oa_req;
    wire write_oa_granted;
    wire write_done;
    wire oa_calc_over;

    // Shared block_dma client signals
    logic ia_dma_start, ia_dma_linear_read_mode;
    logic ia_dma_im2col;
    logic [REG_WIDTH-1:0] ia_dma_p0, ia_dma_q0, ia_dma_group;
    logic [REG_WIDTH-1:0] ia_dma_base_addr, ia_dma_row_stride, ia_dma_rows_to_read;
    logic [7:0] ia_dma_burst_len_m1;
    localparam int unsigned IA_CACHE_SLOT_W = (IA_CACHE_BLOCKS <= 1) ? 1 : $clog2(IA_CACHE_BLOCKS);
    logic [IA_CACHE_SLOT_W-1:0] ia_dma_slot_id;
    logic ia_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] ia_dma_lhs_zp;
    logic ia_dma_busy, ia_dma_done;
    logic [IA_CACHE_SLOT_W-1:0] ia_dma_wr_slot;
    logic [$clog2(SIZE)-1:0] ia_dma_wr_row, ia_dma_wr_col_base;
    logic signed [IA_DATA_WIDTH-1:0] ia_dma_wr_data[BUS_WIDTH/8];
    logic ia_dma_wr_valid[BUS_WIDTH/8];
    logic ia_dma_wr_use_16bits;

    logic kernel_dma_start, kernel_dma_linear_read_mode;
    logic kernel_dma_im2col;
    logic [REG_WIDTH-1:0] kernel_dma_p0, kernel_dma_q0, kernel_dma_group;
    logic [REG_WIDTH-1:0] kernel_dma_base_addr, kernel_dma_row_stride, kernel_dma_rows_to_read;
    logic [7:0] kernel_dma_burst_len_m1;
    logic kernel_dma_slot_id, kernel_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] kernel_dma_lhs_zp;
    logic kernel_dma_busy, kernel_dma_done;
    logic [$clog2(SIZE)-1:0] kernel_dma_wr_row, kernel_dma_wr_col_base;
    logic signed [KERNEL_DATA_WIDTH-1:0] kernel_dma_wr_data[BUS_WIDTH/8];
    logic kernel_dma_wr_valid[BUS_WIDTH/8];

    logic bias_dma_start, bias_dma_linear_read_mode;
    logic [REG_WIDTH-1:0] bias_dma_base_addr, bias_dma_row_stride, bias_dma_rows_to_read;
    logic [7:0] bias_dma_burst_len_m1;
    logic bias_dma_slot_id, bias_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] bias_dma_lhs_zp;
    logic bias_dma_busy, bias_dma_done, bias_dma_wr_slot, bias_dma_wr_use_16bits;
    logic [$clog2(BIAS_DMA_SIZE)-1:0] bias_dma_wr_row, bias_dma_wr_col_base;
    logic signed [7:0] bias_dma_wr_data[BUS_WIDTH/8];
    logic bias_dma_wr_valid[BUS_WIDTH/8];

    logic quant_dma_start, quant_dma_linear_read_mode;
    logic [REG_WIDTH-1:0] quant_dma_base_addr, quant_dma_row_stride, quant_dma_rows_to_read;
    logic [7:0] quant_dma_burst_len_m1;
    logic quant_dma_slot_id, quant_dma_use_16bits;
    logic signed [REG_WIDTH-1:0] quant_dma_lhs_zp;
    logic quant_dma_busy, quant_dma_done;
    logic [BUS_WIDTH-1:0] quant_dma_raw_data;
    logic quant_dma_raw_valid;

    logic oa_dma_start;
    logic [REG_WIDTH-1:0] oa_dma_base_addr, oa_dma_row_stride, oa_dma_rows_to_read;
    logic [7:0] oa_dma_burst_len_m1;
    logic [BUS_WIDTH-1:0] oa_dma_src_wdata;
    logic [BUS_WIDTH/8-1:0] oa_dma_src_wmask;
    logic oa_dma_src_wvalid, oa_dma_src_wready, oa_dma_busy, oa_dma_done;

    logic dw_rd_req, dw_rd_granted, dw_rd_start, dw_rd_im2col, dw_rd_use_16bits;
    logic [31:0] dw_rd_p0, dw_rd_q0, dw_rd_base_addr, dw_rd_row_stride;
    logic [31:0] dw_rd_rows_to_read, dw_rd_valid_cols;
    logic [7:0] dw_rd_burst_len_m1;
    logic dw_rd_busy, dw_rd_done, dw_rd_error;
    logic signed [IA_DATA_WIDTH-1:0] dw_dma_data [BUS_WIDTH/8];
    logic signed [15:0] dw_rd_data [4];
    logic dw_rd_valid [BUS_WIDTH/8];
    logic [$clog2(SHARED_DMA_SIZE)-1:0] dw_rd_col_base;
    logic [BUS_WIDTH-1:0] dw_rd_raw_data;
    logic dw_rd_raw_valid;
    logic dw_wr_req, dw_wr_granted, dw_wr_start;
    logic [31:0] dw_wr_base_addr, dw_wr_row_stride, dw_wr_rows_to_write;
    logic [7:0] dw_wr_burst_len_m1;
    logic [BUS_WIDTH-1:0] dw_src_wdata;
    logic [BUS_WIDTH/8-1:0] dw_src_wmask;
    logic dw_src_wvalid, dw_src_wready, dw_wr_busy, dw_wr_done, dw_wr_error;
    generate if (DW_POOL_CAPABLE) begin : g_dw_pool
        for (genvar lane = 0; lane < 4; lane++) begin : g_data
            assign dw_rd_data[lane] = 16'($signed(dw_dma_data[lane]));
        end
        dw_pool_engine #(.TILE(SIZE), .DMA_SIZE(SHARED_DMA_SIZE),
            .PE_COUNT(DW_PE_COUNT), .MAX_TAPS(DW_MAX_TAPS)) u_engine (
            .clk, .rst_n(core_rst_n),
            .start(calc_start && sa_ready && cfg_dw_enable && !cfg_conv_enable),
            .cfg(cfg_dw), .ready(dw_engine_ready), .done_valid(dw_engine_done),
            .done_ready(done_ready && run_dw), .error(dw_engine_error),
            .stat_cycles(dw_stat_cycles), .stat_compute(dw_stat_compute),
            .stat_dma_wait(dw_stat_dma_wait),
            .dma_cfg_valid(dw_dma_cfg_valid), .dma_cfg_ready(conv_cfg_ready && run_dw),
            .dma_conv_enable(dw_dma_conv_enable), .dma_range_enable(dw_dma_range_enable),
            .dma_conv_cfg(dw_dma_conv_cfg), .dma_range_base(dw_dma_range_base),
            .dma_range_end(dw_dma_range_end),
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
    end else begin : g_no_dw_pool
        assign dw_engine_ready = 1'b1;
        assign dw_engine_done = 1'b0;
        assign dw_engine_error = 2'b01;
        assign dw_stat_cycles = '0; assign dw_stat_compute = '0; assign dw_stat_dma_wait = '0;
        assign dw_dma_cfg_valid = 1'b0; assign dw_dma_conv_enable = 1'b0;
        assign dw_dma_range_enable = 1'b0; assign dw_dma_conv_cfg = '0;
        for (genvar r = 0; r < 4; r++) begin : g_ranges
            assign dw_dma_range_base[r] = '0; assign dw_dma_range_end[r] = '0;
        end
        assign dw_rd_req = 1'b0; assign dw_rd_start = 1'b0; assign dw_rd_im2col = 1'b0;
        assign dw_rd_use_16bits = 1'b0; assign dw_rd_p0 = '0; assign dw_rd_q0 = '0;
        assign dw_rd_base_addr = '0; assign dw_rd_row_stride = '0;
        assign dw_rd_rows_to_read = '0; assign dw_rd_valid_cols = '0;
        assign dw_rd_burst_len_m1 = '0;
        assign dw_wr_req = 1'b0; assign dw_wr_start = 1'b0;
        assign dw_wr_base_addr = '0; assign dw_wr_row_stride = '0;
        assign dw_wr_rows_to_write = '0; assign dw_wr_burst_len_m1 = '0;
        assign dw_src_wdata = '0; assign dw_src_wmask = '0; assign dw_src_wvalid = 1'b0;
    end endgenerate

    wire ps_capacity_fault;
    wire controller_done_valid;
    wire [1:0] controller_err_code;
    wire operand_completion_seen;
    generate if (OPERAND_CACHE_ENABLE != 0) begin : g_operand_retirement
        logic completion_seen;
        assign operand_completion_seen=completion_seen;
        // WAIT_DONE holds the controller until the physical cache tail drains.
        // Its registered valid has one trailing cycle after the handshake;
        // expose exactly one completion, including after a prolonged wait.
        always_ff @(posedge clk or negedge core_rst_n) begin
            if (!core_rst_n) completion_seen<=1'b0;
            else if (!controller_done_valid) completion_seen<=1'b0;
            else if (abort_state==AB_IDLE && done_valid && done_ready)
                completion_seen<=1'b1;
        end
    end else begin : g_no_operand_retirement
        assign operand_completion_seen=1'b0;
    end endgenerate
`ifdef GEMMORA_INT8_PROFILE
    wire profile_input_invalid=cfg_16bits_ia || cfg_16x8 || lhs_zp!=0 || rhs_zp!=0;
    logic profile_error;
    always_ff @(posedge clk or negedge core_rst_n) begin
        if(!core_rst_n)profile_error<=1'b0;
        else if(calc_start && !cfg_dw_enable && profile_input_invalid)profile_error<=1'b1;
    end
`else
    wire profile_input_invalid=1'b0;
    wire profile_error=1'b0;
`endif
    assign normal_done_valid=(abort_state == AB_DONE) ||
        ((abort_state == AB_IDLE) && !(run_conv && (conv_error || dma_bus_error)) &&
         operand_cache_idle &&
         ((controller_done_valid && !operand_completion_seen) || ps_capacity_fault || profile_error));
    assign normal_err_code=(abort_state == AB_DONE) ? 2'b11 : ps_capacity_fault ? 2'b11 : profile_error ? 2'b01 : controller_err_code;

    // 添加缺少的内部信号
    // per-submodule init_cfg signals (由npu_controller产生的单拍脉冲)
    wire init_cfg_ia;
    wire init_cfg_weight;
    wire init_cfg_bias;
    wire init_cfg_requant;
    wire init_cfg_oa;
    wire use_16bits;  // 16位数据指示信号
    wire [REG_WIDTH-1:0] tile_count;  // 分块计数信号
        localparam int unsigned IA_REUSE_NUM_MAX =
            (IA_CACHE_BLOCKS < 2) ? 1 : (IA_CACHE_BLOCKS / 2);
        localparam int unsigned DIM_COUNT_WIDTH =
            (ADDR_WIDTH <= SIZE_SHIFT) ? 1 :
            (((ADDR_WIDTH - SIZE_SHIFT + 1) > REG_WIDTH) ? REG_WIDTH :
                (ADDR_WIDTH - SIZE_SHIFT + 1));
        localparam int unsigned W_REUSE_NUM_MAX =
            (PS_FRAME_COUNT < 1) ? 1 : PS_FRAME_COUNT;
        localparam int unsigned IA_REUSE_W =
            (IA_REUSE_NUM_MAX <= 1) ? 1 : ($clog2(IA_REUSE_NUM_MAX) + 1);
        localparam int unsigned W_REUSE_W =
            (W_REUSE_NUM_MAX <= 1) ? 1 : ($clog2(W_REUSE_NUM_MAX) + 1);
        localparam int unsigned OA_FIFO_BANKS_RAW = PS_FRAME_COUNT * IA_REUSE_NUM_MAX;
        localparam int unsigned OA_FIFO_BANKS =
            (OA_FIFO_BANKS_RAW <= OA_FIFO_BANKS_MAX) ? OA_FIFO_BANKS_RAW : OA_FIFO_BANKS_MAX;
        localparam int unsigned BIAS_GROUP_BLOCKS_MAX =
            (ENABLE_IS_MODE != 0) ? IA_REUSE_NUM_MAX : 1;
        localparam int unsigned REQUANT_MAX_IA_REUSE =
            ((ENABLE_IS_MODE != 0) && (ENABLE_PER_CHANNEL != 0)) ? IA_REUSE_NUM_MAX : 1;
        localparam int unsigned IS_BIAS_ROWS = BIAS_GROUP_BLOCKS_MAX * SIZE;
        localparam int unsigned IS_BIAS_ROW_W = (IS_BIAS_ROWS <= 1) ? 1 : $clog2(IS_BIAS_ROWS);
        localparam int unsigned IS_BIAS_VALID_W =
            (IS_BIAS_ROWS <= 1) ? 1 : ($clog2(IS_BIAS_ROWS) + 1);
        logic [IS_BIAS_ROW_W-1:0] is_bias_row_idx;
        wire signed [31:0] bias_group_scalar;
        wire use_per_channel_eff = (ENABLE_PER_CHANNEL != 0)
                                 ? use_per_channel : 1'b0;
        wire cfg_16bits_ia_eff = (IA_DATA_WIDTH > 8) ? cfg_16bits_ia : 1'b0;

        wire ctrl_sa_ready;
        logic cfg_stage0_valid;
        logic cfg_stage1_valid;
        logic cfg_stage2_valid;
        logic cfg_mode_s0;
        logic cfg_use16_s0;
        logic cfg_16x8_s0;
        logic [REG_WIDTH-1:0] cfg_k_s0;
        logic [REG_WIDTH-1:0] cfg_m_s0;
        logic [REG_WIDTH-1:0] cfg_n_s0;
        logic [REG_WIDTH-1:0] cfg_stream_k_s0;
        logic [REG_WIDTH-1:0] cfg_stream_m_s0;
        logic [REG_WIDTH-1:0] cfg_ia_req_s0;
        logic [REG_WIDTH-1:0] cfg_w_req_s0;
        logic cfg_mode_s1;
        logic cfg_use16_s1;
        logic cfg_16x8_s1;
        logic [REG_WIDTH-1:0] cfg_k_s1;
        logic [REG_WIDTH-1:0] cfg_m_s1;
        logic [REG_WIDTH-1:0] cfg_n_s1;
        logic [REG_WIDTH-1:0] cfg_stream_k_s1;
        logic [REG_WIDTH-1:0] cfg_stream_m_s1;
        logic [REG_WIDTH-1:0] cfg_ia_req_s1;
        logic [REG_WIDTH-1:0] cfg_w_req_s1;
        logic cfg_mode_s2;
        logic [REG_WIDTH-1:0] cfg_k_s2;
        logic [REG_WIDTH-1:0] cfg_m_s2;
        logic [REG_WIDTH-1:0] cfg_n_s2;
        logic [IS_BIAS_VALID_W-1:0] cfg_bias_rows_target_s2;

        wire cfg_start_event = calc_start && sa_ready && !cfg_dw_enable;
        assign cfg_stage2_fire = cfg_stage2_valid && ctrl_sa_ready;
        wire ctrl_calc_start = cfg_stage2_fire;
        assign sa_ready = !run_dw && !dw_rejected && dw_engine_ready && ctrl_sa_ready && !cfg_stage0_valid && !cfg_stage1_valid && !cfg_stage2_valid &&
                          (abort_state == AB_IDLE) && operand_cache_idle;

        // ABI 2: external software provides effective, legal R/W values.
        // There is no automatic rounding or resizing after the host computes groups.
        wire [REG_WIDTH-1:0] ia_reuse_num_eff_s1 = cfg_ia_req_s1;
        wire [REG_WIDTH-1:0] w_reuse_num_eff_s1 = cfg_w_req_s1;
        wire [IA_REUSE_W-1:0] ext_r_small = cfg_ia_reuse_eff_s2[IA_REUSE_W-1:0];
        wire [W_REUSE_W-1:0] ext_w_small = cfg_w_reuse_eff_s2[W_REUSE_W-1:0];
        wire ext_r_legal = (cfg_ia_reuse_eff_s2 >> IA_REUSE_W)==0 && ext_r_small!=0 &&
            ext_r_small<=IA_REUSE_W'(IA_REUSE_NUM_MAX) &&
            (((ext_r_small & (ext_r_small-IA_REUSE_W'(1)))==0) || ext_r_small==25);
        wire ext_w_legal = (cfg_w_reuse_eff_s2 >> W_REUSE_W)==0 && ext_w_small!=0 &&
            ext_w_small<=W_REUSE_W'(W_REUSE_NUM_MAX) &&
            (((ext_w_small & (ext_w_small-W_REUSE_W'(1)))==0) || ext_w_small==25);

        always_ff @(posedge clk or negedge core_rst_n) begin
            if (!core_rst_n) begin
                    cfg_stage0_valid <= 1'b0;
                    cfg_stage1_valid <= 1'b0;
                    cfg_stage2_valid <= 1'b0;
                    cfg_mode_s0 <= 1'b0;
                    cfg_use16_s0 <= 1'b0;
                    cfg_16x8_s0 <= 1'b0;
                    cfg_k_s0 <= '0;
                    cfg_m_s0 <= '0;
                    cfg_n_s0 <= '0;
                    cfg_stream_k_s0 <= '0;
                    cfg_stream_m_s0 <= '0;
                    cfg_ia_req_s0 <= '0;
                    cfg_w_req_s0 <= '0;
                    cfg_mode_s1 <= 1'b0;
                    cfg_use16_s1 <= 1'b0;
                    cfg_16x8_s1 <= 1'b0;
                    cfg_k_s1 <= '0;
                    cfg_m_s1 <= '0;
                    cfg_n_s1 <= '0;
                    cfg_stream_k_s1 <= '0;
                    cfg_stream_m_s1 <= '0;
                    cfg_ia_req_s1 <= '0;
                    cfg_w_req_s1 <= '0;
                    cfg_mode_s2 <= 1'b0;
                    cfg_use16_s2 <= 1'b0;
                    cfg_16x8_s2 <= 1'b0;
                    cfg_k_s2 <= '0;
                    cfg_m_s2 <= '0;
                    cfg_n_s2 <= '0;
                    cfg_stream_k_s2 <= '0;
                    cfg_stream_m_s2 <= '0;
                    cfg_ia_reuse_eff_s2 <= REG_WIDTH'(1);
                    cfg_w_reuse_eff_s2 <= REG_WIDTH'(1);
                    cfg_bias_rows_target_s2 <= IS_BIAS_VALID_W'(SIZE);
                end else begin
                    if (cfg_stage2_fire) begin
                        cfg_stage2_valid <= 1'b0;
                    end

                    if (cfg_stage1_valid && !cfg_stage2_valid) begin
                        cfg_stage2_valid <= 1'b1;
                        cfg_stage1_valid <= 1'b0;
                        cfg_mode_s2 <= cfg_mode_s1;
                        cfg_use16_s2 <= cfg_use16_s1;
                        cfg_16x8_s2 <= cfg_16x8_s1;
                        cfg_k_s2 <= cfg_k_s1;
                        cfg_m_s2 <= cfg_m_s1;
                        cfg_n_s2 <= cfg_n_s1;
                        cfg_stream_k_s2 <= cfg_stream_k_s1;
                        cfg_stream_m_s2 <= cfg_stream_m_s1;
                        cfg_ia_reuse_eff_s2 <= ia_reuse_num_eff_s1;
                        cfg_w_reuse_eff_s2 <= w_reuse_num_eff_s1;
                        cfg_bias_rows_target_s2 <= IS_BIAS_VALID_W'(ia_reuse_num_eff_s1 << SIZE_SHIFT);
                    end

                    if (cfg_stage0_valid && !cfg_stage1_valid) begin
                        cfg_stage1_valid <= 1'b1;
                        cfg_stage0_valid <= 1'b0;
                    cfg_mode_s1 <= cfg_mode_s0;
                    cfg_use16_s1 <= cfg_use16_s0;
                    cfg_16x8_s1 <= cfg_16x8_s0;
                    cfg_k_s1 <= cfg_k_s0;
                    cfg_m_s1 <= cfg_m_s0;
                        cfg_n_s1 <= cfg_n_s0;
                        cfg_stream_k_s1 <= cfg_stream_k_s0;
                        cfg_stream_m_s1 <= cfg_stream_m_s0;
                        cfg_ia_req_s1 <= cfg_ia_req_s0;
                        cfg_w_req_s1 <= cfg_w_req_s0;
                    end

                    if (cfg_start_event) begin
                        cfg_stage0_valid <= 1'b1;
                        cfg_mode_s0 <= cfg_16x8 ? 1'b0 : cfg_dataflow_mode_eff;
                        cfg_use16_s0 <= cfg_16bits_ia_eff | cfg_16x8;
                        cfg_16x8_s0 <= cfg_16x8;
                    cfg_k_s0 <= k;
                    cfg_m_s0 <= m;
                        cfg_n_s0 <= n;
                        cfg_stream_k_s0 <= cfg_dataflow_mode_eff ? m : k;
                        cfg_stream_m_s0 <= cfg_dataflow_mode_eff ? k : m;
                        cfg_ia_req_s0 <= cfg_ia_reuse_num;
                        cfg_w_req_s0 <= cfg_w_reuse_num;
                    end
                end
            end

        logic run_is_mode;
        logic run_use_16bits;
        logic run_16x8;
        logic [REG_WIDTH-1:0] run_k;
        logic [REG_WIDTH-1:0] run_m;
        logic [REG_WIDTH-1:0] run_n;
        logic [REG_WIDTH-1:0] stream_k;
        logic [REG_WIDTH-1:0] stream_m;
        logic [REG_WIDTH-1:0] ia_reuse_num_eff;
        logic [REG_WIDTH-1:0] w_reuse_num_eff;
        logic [IS_BIAS_VALID_W-1:0] is_bias_group_rows_target;

        always_ff @(posedge clk or negedge core_rst_n) begin
            if (!core_rst_n) begin
                run_is_mode <= 1'b0;
                run_use_16bits <= 1'b0;
                run_16x8 <= 1'b0;
                run_k <= '0;
                run_m <= '0;
                run_n <= '0;
                stream_k <= '0;
                stream_m <= '0;
                ia_reuse_num_eff <= REG_WIDTH'(1);
                w_reuse_num_eff <= REG_WIDTH'(1);
                is_bias_group_rows_target <= IS_BIAS_VALID_W'(SIZE);
            end else if (cfg_stage2_fire) begin
                run_is_mode <= cfg_mode_s2;
                run_use_16bits <= cfg_use16_s2;
                run_16x8 <= cfg_16x8_s2;
                run_k <= cfg_k_s2;
                run_m <= cfg_m_s2;
                run_n <= cfg_n_s2;
                stream_k <= cfg_stream_k_s2;
                stream_m <= cfg_stream_m_s2;
                ia_reuse_num_eff <= cfg_ia_reuse_eff_s2;
                w_reuse_num_eff <= cfg_w_reuse_eff_s2;
                is_bias_group_rows_target <= cfg_bias_rows_target_s2;
            end
        end

        wire is_mode = (ENABLE_IS_MODE != 0) ? run_is_mode : 1'b0;
        wire [REG_WIDTH-1:0] ia_base_eff = is_mode ? rhs_base : lhs_base;
        wire [REG_WIDTH-1:0] ia_stride_eff = is_mode ? rhs_col_stride_b : lhs_row_stride_b;
        wire signed [REG_WIDTH-1:0] ia_zp_eff = is_mode ? rhs_zp : lhs_zp;
        wire ia_use_16bits_eff = ((IA_DATA_WIDTH > 8) && !is_mode) ? run_use_16bits : 1'b0;
        wire [REG_WIDTH-1:0] weight_base_eff = is_mode ? lhs_base : rhs_base;
        wire [REG_WIDTH-1:0] weight_stride_eff = is_mode ? lhs_row_stride_b : rhs_col_stride_b;
        wire signed [REG_WIDTH-1:0] weight_zp_eff = is_mode ? lhs_zp : rhs_zp;
        wire weight_use_16bits_eff = ((KERNEL_DATA_WIDTH > 8) && is_mode) ? run_use_16bits : 1'b0;
        wire compute_bias_sleep = bias_sleep;

        axi_block_dma_arbiter #(
            .DATA_WIDTH  (IA_DATA_WIDTH),
            .KERNEL_WIDTH(KERNEL_DATA_WIDTH),
            .SIZE        (SIZE),
            .DMA_SIZE    (SHARED_DMA_SIZE),
            .BUS_WIDTH   (BUS_WIDTH),
            .REG_WIDTH   (REG_WIDTH),
            .CACHE_BLOCKS(IA_CACHE_BLOCKS),
            .ENABLE_QUANT_CLIENT(ENABLE_PER_CHANNEL),
            .READ_OUTSTANDING(AXI_READ_OUTSTANDING),
            .WRITE_OUTSTANDING(AXI_WRITE_OUTSTANDING),
            .CONV_CACHE_SETS(CONV_CACHE_SETS),
            .CONV_CACHE_WAYS(CONV_CACHE_WAYS),
            .CONV_LINE_BYTES(CONV_LINE_BYTES),
            .CONV_CACHE_POLICY(CONV_CACHE_POLICY)
        ) u_block_dma_arbiter (
            .clk                     (clk),
            .rst_n                   (core_rst_n),
            // Reconfigure even for GEMM so a previous Conv task cannot leave
            // image bounds or cache policy active on ordinary matrix reads.
            .conv_cfg_valid          (run_dw ? dw_dma_cfg_valid : init_cfg_ia),
            .conv_cfg_ready          (conv_cfg_ready),
            .conv_enable             (run_dw ? dw_dma_conv_enable : run_conv),
            .dma_range_enable       (run_dw && dw_dma_range_enable),
            .conv_cfg                (run_dw ? dw_dma_conv_cfg : conv_cfg_q),
            .conv_sched_r            (run_dw ? 32'd0 : 32'(ia_reuse_num_eff)),
            // The geometry predictor's rank follows the WS loop order. IS
            // retains raw-input caching but uses its generic fallback policy.
            .conv_sched_groups       ((run_dw || is_mode) ? 32'd0 : 32'(cfg_col_groups)),
            .conv_range_base         (selected_range_base),
            .conv_range_end          (selected_range_end),
            .conv_error              (conv_error),
            .conv_busy               (conv_busy),
            .conv_stat_hits          (conv_hits_raw),
            .conv_stat_misses        (conv_misses_raw),
            .conv_stat_read_bytes    (conv_read_bytes_raw),
            .dw_req(dw_rd_req), .dw_granted(dw_rd_granted), .dw_start(dw_rd_start),
            .dw_im2col(dw_rd_im2col), .dw_p0(dw_rd_p0), .dw_q0(dw_rd_q0),
            .dw_group(32'd0), .dw_linear_read_mode(1'b0), .dw_lhs_zp('0),
            .dw_base_addr(dw_rd_base_addr), .dw_row_stride(dw_rd_row_stride),
            .dw_rows_to_read(dw_rd_rows_to_read), .dw_valid_cols(dw_rd_valid_cols),
            .dw_burst_len_m1(dw_rd_burst_len_m1), .dw_use_16bits(dw_rd_use_16bits),
            .dw_busy(dw_rd_busy), .dw_done(dw_rd_done), .dw_error(dw_rd_error),
            .dw_data(dw_dma_data), .dw_valid(dw_rd_valid), .dw_row(), .dw_col_base(dw_rd_col_base),
            .dw_raw_data(dw_rd_raw_data), .dw_raw_valid(dw_rd_raw_valid),
            .dw_wr_req(dw_wr_req), .dw_wr_granted(dw_wr_granted), .dw_wr_start(dw_wr_start),
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
                .kernel_req(load_weight_req && !abort_pending),
                .kernel_granted          (load_weight_granted),
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
                .oa_src_wdata            (oa_dma_src_wdata),
            .oa_src_wmask            (oa_dma_src_wmask),
            .oa_src_wvalid           (oa_dma_src_wvalid),
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

`ifndef SYNTHESIS
        always_ff @(posedge clk) if (core_rst_n && init_cfg_ia) begin
            assert(conv_cfg_ready);
            assert(!ia_dma_start && !kernel_dma_start);
        end
`endif

        //========================================
    // 模块实例化
    //========================================

        // NPU 控制器
    npu_controller #(
        .WEIGHT_WIDTH(KERNEL_DATA_WIDTH),
        .DATA_WIDTH  (IA_DATA_WIDTH),
        .SIZE        (SIZE),
        .BUS_WIDTH   (BUS_WIDTH),
        .REG_WIDTH   (REG_WIDTH)
    ) u_npu_controller (
        .clk              (clk),
        .rst_n            (core_rst_n),
        .calc_start       (ctrl_calc_start),
        .cfg_16bits_ia    (cfg_16bits_ia_eff | cfg_16x8),
        .cfg_dataflow_mode(cfg_dataflow_mode_eff),
        .cfg_tiling_error (conv_config_invalid || (!ext_r_legal) || (!ext_w_legal) || (cfg_row_groups == 0) || (cfg_col_groups == 0) ||
            (cfg_row_tail_tiles == 0) || (cfg_col_tail_tiles == 0) ||
            (cfg_row_tail_tiles > cfg_ia_reuse_eff_s2) || (cfg_col_tail_tiles > cfg_w_reuse_eff_s2) ||
            ((cfg_row_groups >> DIM_COUNT_WIDTH) != 0) || ((cfg_col_groups >> DIM_COUNT_WIDTH) != 0)),
        .sa_ready         (ctrl_sa_ready),

        .partial_sum_calc_over(partial_sum_calc_over),
        .tile_calc_over       (tile_calc_over),
            .init_cfg_ia          (init_cfg_ia),
        .init_cfg_weight      (init_cfg_weight),
        .init_cfg_bias        (init_cfg_bias),
        .init_cfg_requant     (init_cfg_requant),
        .init_cfg_oa          (init_cfg_oa),
        .use_16bits           (use_16bits),
        // 新增配置参数连接
        .lhs_base             (lhs_base),
        .rhs_base             (rhs_base),
        .dst_base             (dst_base),
        .bias_base            (bias_base),
        .q_mult_pt            (q_mult_pt),
        .q_shift_pt           (q_shift_pt),
        .use_per_channel      (use_per_channel_eff),
        .k                    (k),
        .n                    (n),
        .m                    (m),
        .lhs_row_stride_b     (lhs_row_stride_b),
        .dst_row_stride_b     (dst_row_stride_b),
        .rhs_col_stride_b     (rhs_col_stride_b),
            // IA Loader Interface
            .send_ia_trigger      (send_ia_trigger),
            .ia_sending_done      (ia_sending_done),
            .ia_data_valid        (ia_data_valid),
                // Weight Loader Interface
            .send_weight_trigger  (send_weight_trigger),
            .weight_commit(weight_commit),
        .weight_sending_done  (weight_sending_done),
        .weight_data_valid    (weight_data_valid),
            // Bias Loader Interface
            .bias_valid           (bias_group_valid),
            .bias_sleep           (bias_sleep),
            // Requantization Interface
            .quant_params_valid   (quant_params_valid),
        // FIFO Interface
        .fifo_full_flag       (fifo_full_flag && ia_output_pending),
            // OA Writer Interface
            .oa_calc_over         (oa_calc_over),
        // Task Completion Handshake Interface
        .done_valid             (controller_done_valid),
        .done_ready             (done_ready && operand_cache_idle),
        .err_code             (controller_err_code)
    );
        // IA Loader
            ia_loader #(
                .DATA_WIDTH  (IA_DATA_WIDTH),
                .SIZE        (SIZE),
                .BUS_WIDTH   (BUS_WIDTH),
                .REG_WIDTH   (REG_WIDTH),
                .COUNT_WIDTH (DIM_COUNT_WIDTH),
                .CACHE_BLOCKS(IA_CACHE_BLOCKS),
                .PS_FRAME_COUNT(PS_FRAME_COUNT)
            ) u_ia_loader (
        .clk             (clk),
        .rst_n           (core_rst_n),
        .init_cfg        (init_cfg_ia),
        .cfg_im2col(run_conv && !is_mode),
        .load_ia_req     (load_ia_req),
        .load_ia_granted (load_ia_granted),
            .send_ia_trigger (send_ia_trigger),
            .k               (stream_k),
            .n               (run_n),
            .m               (stream_m),
        .lhs_zp          (ia_zp_eff),
        .lhs_row_stride_b(ia_stride_eff),
        .lhs_base        (ia_base_eff),
        .use_16bits      (ia_use_16bits_eff),
        .bias_by_row_mode(is_mode),
        .ia_reuse_num    (ia_reuse_num_eff),
            .w_reuse_num     (w_reuse_num_eff),
        .row_groups (cfg_row_groups),
        .row_tail_tiles (cfg_row_tail_tiles),
        .col_groups (cfg_col_groups),
        .col_tail_tiles (cfg_col_tail_tiles),
            .ext_dma_start(ia_dma_start),
            .ext_dma_is_write(),
            .ext_dma_linear_read_mode(ia_dma_linear_read_mode),
            .ext_dma_im2col(ia_dma_im2col),
            .ext_dma_p0(ia_dma_p0),
            .ext_dma_q0(ia_dma_q0),
            .ext_dma_group(ia_dma_group),
            .ext_dma_base_addr(ia_dma_base_addr),
            .ext_dma_row_stride(ia_dma_row_stride),
            .ext_dma_rows_to_read(ia_dma_rows_to_read),
            .ext_dma_burst_len_m1(ia_dma_burst_len_m1),
            .ext_dma_slot_id(ia_dma_slot_id),
            .ext_dma_use_16bits(ia_dma_use_16bits),
            .ext_dma_lhs_zp(ia_dma_lhs_zp),
            .ext_dma_busy(ia_dma_busy),
            .ext_dma_done(ia_dma_done),
            .ext_dma_wr_slot(ia_dma_wr_slot),
            .ext_dma_wr_row(ia_dma_wr_row),
            .ext_dma_wr_col_base(ia_dma_wr_col_base),
            .ext_dma_wr_data(ia_dma_wr_data),
            .ext_dma_wr_valid(ia_dma_wr_valid),
            .ext_dma_wr_use_16bits(ia_dma_wr_use_16bits),


        .ia_sending_done(ia_sending_done),
        .ia_row_valid   (ia_row_valid),
        .ia_tile_start  (ia_tile_start),
        .ia_is_init_data(ia_is_init_data),
            .ia_calc_done   (ia_calc_done),
            .ia_out         (ia_out),
            .ia_data_valid  (ia_data_valid),
            .ia_output_pending(ia_output_pending),
            .bias_sleep     (bias_sleep),
        .bias_switch    (bias_switch),
        .bias_last_loop (bias_last_loop),
        .ia_l1_switch   (ia_l1_switch)
    );
        // Kernel Loader
            kernel_loader #(
                .DATA_WIDTH(KERNEL_DATA_WIDTH),
                .SIZE      (SIZE),
                .BUS_WIDTH (BUS_WIDTH),
                .REG_WIDTH (REG_WIDTH),
                .COUNT_WIDTH(DIM_COUNT_WIDTH)
            ) u_kernel_loader (
        .clk                (clk),
        .rst_n              (core_rst_n),
        .init_cfg           (init_cfg_weight),
        .cfg_im2col          (run_conv && is_mode),
        .load_weight_req    (load_weight_req),
        .load_weight_granted(load_weight_granted),
            .send_weight_trigger(send_weight_trigger),
            .k                  (stream_k),
            .n                  (run_n),
            .m                  (stream_m),
        .rhs_zp             (weight_zp_eff),
        .rhs_base           (weight_base_eff),
        .rhs_row_stride_b   (weight_stride_eff),
        .ia_reuse_num       (ia_reuse_num_eff),
        .w_reuse_num        (w_reuse_num_eff),
        .row_groups (cfg_row_groups),
        .row_tail_tiles (cfg_row_tail_tiles),
        .col_groups (cfg_col_groups),
        .col_tail_tiles (cfg_col_tail_tiles),
            .use_16bits         (weight_use_16bits_eff),
            .ext_dma_start(kernel_dma_start),
            .ext_dma_is_write(),
            .ext_dma_linear_read_mode(kernel_dma_linear_read_mode),
            .ext_dma_im2col(kernel_dma_im2col),
            .ext_dma_p0(kernel_dma_p0),
            .ext_dma_q0(kernel_dma_q0),
            .ext_dma_group(kernel_dma_group),
            .ext_dma_base_addr(kernel_dma_base_addr),
            .ext_dma_row_stride(kernel_dma_row_stride),
            .ext_dma_rows_to_read(kernel_dma_rows_to_read),
            .ext_dma_burst_len_m1(kernel_dma_burst_len_m1),
            .ext_dma_slot_id(kernel_dma_slot_id),
            .ext_dma_use_16bits(kernel_dma_use_16bits),
            .ext_dma_lhs_zp(kernel_dma_lhs_zp),
            .ext_dma_busy(kernel_dma_busy),
            .ext_dma_done(kernel_dma_done),
            .ext_dma_wr_row(kernel_dma_wr_row),
            .ext_dma_wr_col_base(kernel_dma_wr_col_base),
            .ext_dma_wr_data(kernel_dma_wr_data),
            .ext_dma_wr_valid(kernel_dma_wr_valid),


        .weight_sending_done(weight_sending_done),
        .load_weight_done   (load_weight_done),
        .store_weight_req   (store_weight_req),
        .weight_out         (weight_out),
        .weight_data_valid  (weight_data_valid)
    );

        // Bias Loader
        bias_loader #(
            .SIZE      (SIZE),
            .DATA_WIDTH(32),
                .BUS_WIDTH (BUS_WIDTH),
                .REG_WIDTH (REG_WIDTH),
                .COUNT_WIDTH(DIM_COUNT_WIDTH),
                .GROUP_BLOCKS_MAX(BIAS_GROUP_BLOCKS_MAX)
            ) u_bias_loader (
        .clk              (clk),
        .rst_n            (core_rst_n),
        .init_cfg         (init_cfg_bias),
        .load_bias_req    (load_bias_req),
            .load_bias_granted(load_bias_granted),
            .bias_base        (bias_base),
            .k                (run_k),
            .m                (run_m),
            .bias_step_blocks (is_mode ? ia_reuse_num_eff : REG_WIDTH'(1)),
        .bias_switch      (bias_switch),
        .bias_sleep       (bias_sleep),
        .bias_last_loop   (bias_last_loop),
            .bias_valid       (bias_valid),
            .bias_group_valid (bias_group_valid),
            .load_bias_done   (load_bias_done),
            .group_read_idx   (is_bias_row_idx),
            .data_out         (bias_data_out),
            .group_data_scalar(bias_group_scalar),
                .ext_dma_start    (bias_dma_start),
                .ext_dma_is_write (),
            .ext_dma_linear_read_mode(bias_dma_linear_read_mode),
            .ext_dma_base_addr(bias_dma_base_addr),
            .ext_dma_row_stride(bias_dma_row_stride),
            .ext_dma_rows_to_read(bias_dma_rows_to_read),
            .ext_dma_burst_len_m1(bias_dma_burst_len_m1),
            .ext_dma_slot_id  (bias_dma_slot_id),
            .ext_dma_use_16bits(bias_dma_use_16bits),
            .ext_dma_lhs_zp   (bias_dma_lhs_zp),
            .ext_dma_busy     (bias_dma_busy),
            .ext_dma_done     (bias_dma_done),
            .ext_dma_wr_slot  (bias_dma_wr_slot),
            .ext_dma_wr_row   (bias_dma_wr_row),
            .ext_dma_wr_col_base(bias_dma_wr_col_base),
            .ext_dma_wr_data  (bias_dma_wr_data),
            .ext_dma_wr_valid (bias_dma_wr_valid),
            .ext_dma_wr_use_16bits(bias_dma_wr_use_16bits)
        );

  // 脉动阵列计算核心
  wire signed [31:0] compute_bias_in[SIZE];
  logic signed [31:0] bias_data_hold[SIZE];
  logic signed [31:0] compute_bias_latched[SIZE];
  wire capture_compute_bias = !is_mode && (bias_base != '0) &&
                              ia_tile_start && !bias_sleep;

  always_ff @(posedge clk or negedge core_rst_n) begin
    if (!core_rst_n) begin
      for (int bi = 0; bi < SIZE; bi = bi + 1) begin
        bias_data_hold[bi] <= '0;
        compute_bias_latched[bi] <= '0;
      end
    end else if (init_cfg_bias) begin
      for (int bi = 0; bi < SIZE; bi = bi + 1) begin
        bias_data_hold[bi] <= '0;
        compute_bias_latched[bi] <= '0;
      end
    end else begin
      if (bias_group_valid) begin
        for (int bi = 0; bi < SIZE; bi = bi + 1) begin
          bias_data_hold[bi] <= bias_data_out[bi];
        end
      end

      if (capture_compute_bias) begin
        for (int bi = 0; bi < SIZE; bi = bi + 1) begin
          compute_bias_latched[bi] <= bias_group_valid ? bias_data_out[bi] : bias_data_hold[bi];
        end
      end
    end
  end

  genvar cb_i;
  generate
    for (cb_i = 0; cb_i < SIZE; cb_i = cb_i + 1) begin : gen_compute_bias_in
      assign compute_bias_in[cb_i] =
        (is_mode || (bias_base == '0)) ? 32'sd0 : compute_bias_latched[cb_i];
    end
  endgenerate

    compute_core #(
        .SIZE          (SIZE),
        .DATA_WIDTH    (IA_DATA_WIDTH),
        .WEIGHT_WIDTH  (KERNEL_DATA_WIDTH),
        .PS_FRAME_COUNT(PS_FRAME_COUNT),
        .MAX_IA_REUSE  (IA_REUSE_NUM_MAX)
    ) u_compute_core (
        .ps_capacity_fault(ps_capacity_fault),
        .clk             (clk),
        .rst_n           (core_rst_n),
        .store_weight_req(store_weight_req),
        .weight_commit(weight_commit),
        .weight_in       (weight_out),
        .ia_vec_in       (ia_out),
        .ia_row_valid    (ia_row_valid),
        .ia_tile_start   (ia_tile_start),
        .ia_calc_done    (ia_calc_done),
        .ia_is_init_data (ia_is_init_data),
        .ia_l1_switch    (ia_l1_switch),
        .ia_sending_done (ia_sending_done),
        .send_ia_trigger (send_ia_trigger),
        .bias_sleep      (compute_bias_sleep),
        .bias_in         (compute_bias_in),
        .acc_data_out    (acc_data_out),
        .acc_data_valid  (acc_data_valid),
        .partial_sum_calc_over(partial_sum_calc_over),
        .tile_calc_over  (tile_calc_over)
    );

    // Vec Requant
        logic [REG_WIDTH-1:0] is_bias_group_base;
        logic [REG_WIDTH-1:0] is_bias_last_group_base;
        logic [IS_BIAS_VALID_W-1:0] is_bias_last_rows;
        logic [IS_BIAS_VALID_W-1:0] is_bias_rows_valid;
        logic [IS_BIAS_VALID_W-1:0] is_bias_rows_valid_pending;
        wire [REG_WIDTH-1:0] is_bias_group_rows_target_ext =
          REG_WIDTH'(is_bias_group_rows_target);
        wire [REG_WIDTH-1:0] is_bias_target_mask_ext =
          is_bias_group_rows_target_ext - REG_WIDTH'(1);
        wire [REG_WIDTH-1:0] is_bias_tail_rows_raw =
          run_m & is_bias_target_mask_ext;
        wire [IS_BIAS_VALID_W-1:0] is_bias_tail_rows_calc =
          (is_bias_tail_rows_raw == '0)
              ? is_bias_group_rows_target
              : is_bias_tail_rows_raw[IS_BIAS_VALID_W-1:0];
        wire [REG_WIDTH-1:0] is_bias_tail_rows_ext =
          REG_WIDTH'(is_bias_tail_rows_calc);
        wire [REG_WIDTH-1:0] is_bias_last_group_base_calc =
          (run_m <= is_bias_group_rows_target_ext)
              ? REG_WIDTH'(0)
              : (run_m - is_bias_tail_rows_ext);
        wire [IS_BIAS_VALID_W-1:0] is_bias_first_rows_valid =
          (run_m == '0) ? IS_BIAS_VALID_W'(1) :
          (run_m > is_bias_group_rows_target_ext)
              ? is_bias_group_rows_target
              : run_m[IS_BIAS_VALID_W-1:0];
        wire [REG_WIDTH-1:0] is_bias_group_base_plus =
          is_bias_group_base + REG_WIDTH'(is_bias_rows_valid);
        wire is_bias_group_wrap_step =
          (is_bias_group_base >= is_bias_last_group_base);
        wire [REG_WIDTH-1:0] is_bias_group_base_step =
          is_bias_group_wrap_step ? REG_WIDTH'(0) : is_bias_group_base_plus;
        wire is_bias_group_step_is_last =
          (is_bias_group_base_step >= is_bias_last_group_base);
        wire [IS_BIAS_VALID_W-1:0] is_bias_rows_valid_step =
          is_bias_group_step_is_last ? is_bias_last_rows : is_bias_group_rows_target;
    wire signed [31:0] is_bias_scalar =
      (is_mode && (bias_base != '0)) ? bias_group_scalar : 32'sd0;
    wire signed [31:0] requant_in_vec[SIZE];
    wire signed [63:0] requant_in_vec_s64[SIZE];

        always_ff @(posedge clk or negedge core_rst_n) begin
            if (!core_rst_n) begin
                is_bias_row_idx <= '0;
                is_bias_group_base <= '0;
                is_bias_last_group_base <= '0;
                is_bias_last_rows <= IS_BIAS_VALID_W'(1);
                is_bias_rows_valid <= IS_BIAS_VALID_W'(1);
                is_bias_rows_valid_pending <= IS_BIAS_VALID_W'(1);
            end else begin
                if (init_cfg_ia) begin
                    is_bias_row_idx <= '0;
                    is_bias_group_base <= '0;
                    is_bias_last_group_base <= is_bias_last_group_base_calc;
                    is_bias_last_rows <= is_bias_tail_rows_calc;
                    is_bias_rows_valid <= IS_BIAS_VALID_W'(1);
                    is_bias_rows_valid_pending <= is_bias_first_rows_valid;
                end else begin
                    if (is_mode && acc_data_valid) begin
                        if (is_bias_rows_valid <= IS_BIAS_VALID_W'(1)) begin
                            is_bias_row_idx <= '0;
                        end else if ((IS_BIAS_VALID_W'(is_bias_row_idx) +
                                      IS_BIAS_VALID_W'(1)) >= is_bias_rows_valid) begin
                            is_bias_row_idx <= '0;
                        end else begin
                            is_bias_row_idx <= is_bias_row_idx + 1'b1;
                        end
                    end

                    if (is_mode && bias_switch) begin
                        is_bias_group_base <= is_bias_group_base_step;
                        is_bias_rows_valid_pending <= is_bias_rows_valid_step;
                    end

                    if (is_mode && send_ia_trigger && !bias_sleep) begin
                        is_bias_row_idx <= '0;
                        is_bias_rows_valid <= is_bias_rows_valid_pending;
                    end
                end
            end
        end

    genvar rq_i;
    generate
        for (rq_i = 0; rq_i < SIZE; rq_i = rq_i + 1) begin : gen_requant_in_vec
            assign requant_in_vec[rq_i] =
          is_mode ? (acc_data_out[rq_i] + is_bias_scalar) : acc_data_out[rq_i];
            assign requant_in_vec_s64[rq_i] =
          {{32{acc_data_out[rq_i][31]}}, acc_data_out[rq_i]};
        end
    endgenerate

    assign load_quant_req = load_quant_req_s8;
    assign quant_params_valid = quant_params_valid_s8;

        vec_requant #(
            .VLEN        (SIZE),
            .REG_WIDTH   (REG_WIDTH),
            .MAX_IA_REUSE(REQUANT_MAX_IA_REUSE),
            .ENABLE_PER_CHANNEL(ENABLE_PER_CHANNEL),
            .ENABLE_IS_MODE(ENABLE_IS_MODE)
    ) u_vec_requant (
        .clk               (clk),
        .rst_n             (core_rst_n),
        .init_cfg          (init_cfg_requant),
        .cfg_per_channel   (use_per_channel_eff),
        .cfg_dataflow_mode (cfg_dataflow_mode_eff),
        .activation_min_in (act_min),
        .activation_max_in (act_max),
        .dst_offset_in     (dst_zp),
        .multiplier_in     (q_mult_pt),
        .shift_in          (q_shift_pt),
        .load_quant_req    (load_quant_req_s8),
        .load_quant_granted(load_quant_granted),
        .quant_params_valid(quant_params_valid_s8),
            .k                 (stream_k),
            .m                 (stream_m),
            .ia_reuse_num_in   (ia_reuse_num_eff),
            .dma_start         (quant_dma_start),
            .dma_is_write      (),
            .dma_linear_read_mode(quant_dma_linear_read_mode),
            .dma_base_addr     (quant_dma_base_addr),
            .dma_row_stride    (quant_dma_row_stride),
            .dma_rows_to_read  (quant_dma_rows_to_read),
            .dma_burst_len_m1  (quant_dma_burst_len_m1),
            .dma_slot_id       (quant_dma_slot_id),
            .dma_use_16bits    (quant_dma_use_16bits),
            .dma_lhs_zp        (quant_dma_lhs_zp),
            .dma_raw_data      (quant_dma_raw_data),
            .dma_raw_valid     (quant_dma_raw_valid),
            .in_valid          (acc_data_valid && !ps_capacity_fault),
            .in_tile_done      (tile_calc_over),
            .in_vec_s32        (requant_in_vec),
        .out_valid         (requant_s8_valid),
        .out_tile_done     (requant_s8_tile_done),
            .out_vec_s8        (requant_out),
            .quant_multiplier_lane(requant_multiplier_lane),
            .quant_shift_lane(requant_shift_lane)
        );

`ifdef GEMMORA_INT8_PROFILE
    assign requant_s16_valid=1'b0;
    assign requant_s16_tile_done=1'b0;
    assign requant_out_s16='{default:'0};
`else
    vec_requant_s64 #(
        .VLEN(SIZE)
    ) u_vec_requant_s64 (
        .clk               (clk),
        .rst_n             (core_rst_n),
        .init_cfg          (init_cfg_requant),
        .activation_min_in (act_min),
        .activation_max_in (act_max),
        .multiplier_in     (requant_multiplier_lane),
        .shift_in          (requant_shift_lane),
        .in_valid          (acc_data_valid && run_16x8),
        .in_tile_done      (tile_calc_over),
        .in_vec_s64        (requant_in_vec_s64),
        .out_valid         (requant_s16_valid),
        .out_tile_done     (requant_s16_tile_done),
        .out_vec_s16       (requant_out_s16)
    );

`endif

    assign requant_out_valid = run_16x8 ? requant_s16_valid : requant_s8_valid;
    assign requant_out_tile_done = run_16x8 ? requant_s16_tile_done : requant_s8_tile_done;

    wire [SIZE*8-1:0] in_vec_s8;
    wire [SIZE*16-1:0] in_vec_s16;
    genvar i;
    generate
        for (i = 0; i < SIZE; i = i + 1) begin : gen_unpack_in_vec
            assign in_vec_s8[i*8+:8] = requant_out[i];
            assign in_vec_s16[i*16+:16] = requant_out_s16[i];
        end
    endgenerate

    assign fifo_output_req = run_16x8 ? fifo_s16_output_req : fifo_s8_output_req;
    assign fifo_output_valid = run_16x8 ? fifo_s16_output_valid : fifo_s8_output_valid;
    assign fifo_output_switch_row = run_16x8 ? fifo_s16_output_switch_row
                                             : fifo_s8_output_switch_row;
    assign fifo_output_mask = run_16x8 ? fifo_s16_output_mask : fifo_s8_output_mask;
    assign fifo_output_data = run_16x8 ? fifo_s16_output_data : fifo_s8_output_data;
    assign fifo_full_flag = run_16x8 ? fifo_s16_full_flag : fifo_s8_full_flag;

    // Reorder bounded column segments in the existing output FIFO. The segment
    // holds at most 128 tiles; wider matrices drain several strided segments.
    logic [4:0] oa_chunk_cols_pre;
    always_comb begin
        if (w_reuse_num_eff >= 16 && run_m >= 256 && dst_base[7:0] == 0 &&
            (int'(ia_reuse_num_eff) * 16 <= OA_FIFO_BANKS)) oa_chunk_cols_pre = 16;
        else if (w_reuse_num_eff >= 8 && run_m >= 128 && dst_base[6:0] == 0 &&
            (int'(ia_reuse_num_eff) * 8 <= OA_FIFO_BANKS)) oa_chunk_cols_pre = 8;
        else if (w_reuse_num_eff >= 4 && run_m >= 64 && dst_base[5:0] == 0 &&
            (int'(ia_reuse_num_eff) * 4 <= OA_FIFO_BANKS)) oa_chunk_cols_pre = 4;
        else if (w_reuse_num_eff >= 2 && run_m >= 32 && dst_base[4:0] == 0 &&
            (int'(ia_reuse_num_eff) * 2 <= OA_FIFO_BANKS)) oa_chunk_cols_pre = 2;
        else oa_chunk_cols_pre = 1;
    end
    wire oa_row_coalesce_pre = (SIZE == 16) && (ENABLE_IS_MODE != 0) &&
        !is_mode && !run_16x8 && run_k != 0 &&
        ia_reuse_num_eff <= 16 && oa_chunk_cols_pre >= 2 &&
        (run_k & ((ia_reuse_num_eff << 4) - 1'b1)) == 0 &&
        (run_m & ((REG_WIDTH'(oa_chunk_cols_pre) << 4) - 1'b1)) == 0 &&
        dst_row_stride_b == run_m;
    logic oa_row_coalesce;
    logic [4:0] oa_coalesce_rows, oa_coalesce_cols;
    always_ff @(posedge clk) begin
        if (!core_rst_n) begin
            oa_row_coalesce <= 0;
            oa_coalesce_rows <= 0;
            oa_coalesce_cols <= 0;
        end else if (init_cfg_oa) begin
            oa_row_coalesce <= oa_row_coalesce_pre;
            oa_coalesce_rows <= ia_reuse_num_eff[4:0];
            oa_coalesce_cols <= oa_chunk_cols_pre;
        end
    end

    // FIFO
    vec_s8_to_fifo #(
        .VLEN (SIZE),
        .BANKS(OA_FIFO_BANKS),
        .ENABLE_TRANSPOSE(ENABLE_IS_MODE)
    ) u_vec_s8_to_fifo (
        .clk              (clk),
        .rst_n            (core_rst_n),
        .in_valid         (requant_s8_valid),
        .in_tile_done     (requant_s8_tile_done),
        .in_vec_s8        (in_vec_s8),
        .oa_fifo_req      (fifo_s8_output_req),
        .transpose_mode   (is_mode),
        .coalesce_enable  (oa_row_coalesce),
        .coalesce_rows    (REG_WIDTH'(oa_coalesce_rows)),
        .coalesce_cols    (REG_WIDTH'(oa_coalesce_cols)),
        .reserve_banks    (ia_reuse_num_eff),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .vec_valid_num_row(fifo_vec_valid_num_row),
        .output_valid     (fifo_s8_output_valid),
        .output_row_switch(fifo_s8_output_switch_row),
        .output_ready     (fifo_output_ready),
        .output_mask      (fifo_s8_output_mask),
        .output_data      (fifo_s8_output_data),
        .fifo_full_flag   (fifo_s8_full_flag)
    );

`ifdef GEMMORA_INT8_PROFILE
    assign fifo_s16_output_req=1'b0;
    assign fifo_s16_output_valid=1'b0;
    assign fifo_s16_output_switch_row=1'b0;
    assign fifo_s16_output_mask='0;
    assign fifo_s16_output_data='0;
    assign fifo_s16_full_flag=1'b0;
`else
    vec_s16_to_fifo #(
        .VLEN (SIZE),
        .BANKS(OA_FIFO_BANKS)
    ) u_vec_s16_to_fifo (
        .clk              (clk),
        .rst_n            (core_rst_n),
        .in_valid         (requant_s16_valid),
        .in_tile_done     (requant_s16_tile_done),
        .in_vec_s16       (in_vec_s16),
        .oa_fifo_req      (fifo_s16_output_req),
        .reserve_banks    (ia_reuse_num_eff),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .output_valid     (fifo_s16_output_valid),
        .output_ready     (fifo_output_ready),
        .output_row_switch(fifo_s16_output_switch_row),
        .output_mask      (fifo_s16_output_mask),
        .output_data      (fifo_s16_output_data),
        .fifo_full_flag   (fifo_s16_full_flag)
    );

`endif

    // OA Writer
        oa_writer #(
            .VLEN      (SIZE),
            .DATA_WIDTH(8),
            .REG_WIDTH (REG_WIDTH),
            .BUS_WIDTH (BUS_WIDTH),
            .COUNT_WIDTH(DIM_COUNT_WIDTH),
            .ENABLE_IS_MODE(ENABLE_IS_MODE)
        ) u_oa_writer (
        .clk              (clk),
        .rst_n            (core_rst_n),
        .init_cfg         (init_cfg_oa),
        .oa_fifo_req      (fifo_output_req),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .vec_valid_num_row(fifo_vec_valid_num_row),
        //.write_oa_trigger(),
        .write_oa_req     (write_oa_req),
        .write_oa_granted (write_oa_granted),
            .dst_base         (dst_base),
            .dst_row_stride_b (dst_row_stride_b),
            .k                (run_k),
            .m                (run_m),
        .ia_reuse_num     (ia_reuse_num_eff),
        .is_mode          (is_mode),
        .output_16bits    (run_16x8),
        .coalesce_enable  (oa_row_coalesce_pre),
        .coalesce_cols    (oa_chunk_cols_pre),
        .output_valid     (fifo_output_valid),
        .switch_row       (fifo_output_switch_row),
            .output_ready     (fifo_output_ready),
            .output_mask      (fifo_output_mask),
            .output_data      (fifo_output_data),
            .dma_start        (oa_dma_start),
            .dma_is_write     (),
            .dma_linear_read_mode(),
            .dma_base_addr    (oa_dma_base_addr),
            .dma_row_stride   (oa_dma_row_stride),
            .dma_rows_to_read (oa_dma_rows_to_read),
            .dma_burst_len_m1 (oa_dma_burst_len_m1),
            .dma_slot_id      (),
            .dma_use_16bits   (),
            .dma_lhs_zp       (),
            .dma_src_wdata    (oa_dma_src_wdata),
            .dma_src_wmask    (oa_dma_src_wmask),
            .dma_src_wvalid   (oa_dma_src_wvalid),
            .dma_src_wready   (oa_dma_src_wready),
            .dma_busy         (oa_dma_busy),
            .dma_done         (oa_dma_done),
            .write_done       (write_done),
            .oa_calc_over     (oa_calc_over)
        );

`ifndef SYNTHESIS
    function automatic longint unsigned util_bp(
        input longint unsigned numerator,
        input longint unsigned denominator
    );
        begin
            util_bp = (denominator == 0) ? 0 : ((numerator * 10000) / denominator);
        end
    endfunction

    bit top_util_trace_en;
    logic top_util_active;
    longint unsigned top_util_op_id;
    longint unsigned top_util_active_cycles;
    longint unsigned top_util_ia_row_cycles;
    longint unsigned top_util_acc_valid_cycles;
    longint unsigned top_util_requant_valid_cycles;
    longint unsigned top_util_fifo_valid_cycles;
    longint unsigned top_util_fifo_full_cycles;
    longint unsigned top_util_store_weight_cycles;
    longint unsigned top_util_send_weight_count;
    longint unsigned top_util_send_ia_count;
    longint unsigned top_util_tile_start_count;
    longint unsigned top_util_tile_over_count;
    longint unsigned top_util_partial_over_count;
    longint unsigned top_util_ia_l1_switch_count;
    longint unsigned top_util_ia_dma_busy_cycles;
    longint unsigned top_util_kernel_dma_busy_cycles;
    longint unsigned top_util_bias_dma_busy_cycles;
    longint unsigned top_util_quant_dma_busy_cycles;
    longint unsigned top_util_oa_dma_busy_cycles;
    longint unsigned top_util_axi_ar_cycles;
    longint unsigned top_util_axi_r_cycles;
    longint unsigned top_util_axi_aw_cycles;
    longint unsigned top_util_axi_w_cycles;
    longint unsigned top_util_axi_b_cycles;

    initial begin
        top_util_trace_en = 1'b0;
        if ($test$plusargs("NPU_UTIL_TRACE")) top_util_trace_en = 1'b1;
    end

    wire top_util_start_event = calc_start && sa_ready;
    wire top_util_finish_event = top_util_active && done_valid && done_ready;

    always_ff @(posedge clk or negedge core_rst_n) begin
        if (!core_rst_n) begin
            top_util_active                 <= 1'b0;
            top_util_op_id                  <= '0;
            top_util_active_cycles          <= '0;
            top_util_ia_row_cycles          <= '0;
            top_util_acc_valid_cycles       <= '0;
            top_util_requant_valid_cycles   <= '0;
            top_util_fifo_valid_cycles      <= '0;
            top_util_fifo_full_cycles       <= '0;
            top_util_store_weight_cycles    <= '0;
            top_util_send_weight_count      <= '0;
            top_util_send_ia_count          <= '0;
            top_util_tile_start_count       <= '0;
            top_util_tile_over_count        <= '0;
            top_util_partial_over_count     <= '0;
            top_util_ia_l1_switch_count     <= '0;
            top_util_ia_dma_busy_cycles     <= '0;
            top_util_kernel_dma_busy_cycles <= '0;
            top_util_bias_dma_busy_cycles   <= '0;
            top_util_quant_dma_busy_cycles  <= '0;
            top_util_oa_dma_busy_cycles     <= '0;
            top_util_axi_ar_cycles          <= '0;
            top_util_axi_r_cycles           <= '0;
            top_util_axi_aw_cycles          <= '0;
            top_util_axi_w_cycles           <= '0;
            top_util_axi_b_cycles           <= '0;
        end else begin
            if (top_util_start_event) begin
                top_util_active                 <= 1'b1;
                top_util_op_id                  <= top_util_op_id + 1'b1;
                top_util_active_cycles          <= '0;
                top_util_ia_row_cycles          <= '0;
                top_util_acc_valid_cycles       <= '0;
                top_util_requant_valid_cycles   <= '0;
                top_util_fifo_valid_cycles      <= '0;
                top_util_fifo_full_cycles       <= '0;
                top_util_store_weight_cycles    <= '0;
                top_util_send_weight_count      <= '0;
                top_util_send_ia_count          <= '0;
                top_util_tile_start_count       <= '0;
                top_util_tile_over_count        <= '0;
                top_util_partial_over_count     <= '0;
                top_util_ia_l1_switch_count     <= '0;
                top_util_ia_dma_busy_cycles     <= '0;
                top_util_kernel_dma_busy_cycles <= '0;
                top_util_bias_dma_busy_cycles   <= '0;
                top_util_quant_dma_busy_cycles  <= '0;
                top_util_oa_dma_busy_cycles     <= '0;
                top_util_axi_ar_cycles          <= '0;
                top_util_axi_r_cycles           <= '0;
                top_util_axi_aw_cycles          <= '0;
                top_util_axi_w_cycles           <= '0;
                top_util_axi_b_cycles           <= '0;
            end else if (top_util_active) begin
                top_util_active_cycles <= top_util_active_cycles + 1'b1;

                if (ia_row_valid) begin
                    top_util_ia_row_cycles <= top_util_ia_row_cycles + 1'b1;
                end
                if (acc_data_valid) begin
                    top_util_acc_valid_cycles <= top_util_acc_valid_cycles + 1'b1;
                end
                if (requant_out_valid) begin
                    top_util_requant_valid_cycles <= top_util_requant_valid_cycles + 1'b1;
                end
                if (fifo_output_valid) begin
                    top_util_fifo_valid_cycles <= top_util_fifo_valid_cycles + 1'b1;
                end
                if (fifo_full_flag) begin
                    top_util_fifo_full_cycles <= top_util_fifo_full_cycles + 1'b1;
                end
                if (store_weight_req) begin
                    top_util_store_weight_cycles <= top_util_store_weight_cycles + 1'b1;
                end
                if (send_weight_trigger) begin
                    top_util_send_weight_count <= top_util_send_weight_count + 1'b1;
                end
                if (send_ia_trigger) begin
                    top_util_send_ia_count <= top_util_send_ia_count + 1'b1;
                end
                if (ia_tile_start) begin
                    top_util_tile_start_count <= top_util_tile_start_count + 1'b1;
                end
                if (tile_calc_over) begin
                    top_util_tile_over_count <= top_util_tile_over_count + 1'b1;
                end
                if (partial_sum_calc_over) begin
                    top_util_partial_over_count <= top_util_partial_over_count + 1'b1;
                end
                if (ia_l1_switch) begin
                    top_util_ia_l1_switch_count <= top_util_ia_l1_switch_count + 1'b1;
                end
                if (ia_dma_busy) begin
                    top_util_ia_dma_busy_cycles <= top_util_ia_dma_busy_cycles + 1'b1;
                end
                if (kernel_dma_busy) begin
                    top_util_kernel_dma_busy_cycles <= top_util_kernel_dma_busy_cycles + 1'b1;
                end
                if (bias_dma_busy) begin
                    top_util_bias_dma_busy_cycles <= top_util_bias_dma_busy_cycles + 1'b1;
                end
                if (quant_dma_busy) begin
                    top_util_quant_dma_busy_cycles <= top_util_quant_dma_busy_cycles + 1'b1;
                end
                if (oa_dma_busy) begin
                    top_util_oa_dma_busy_cycles <= top_util_oa_dma_busy_cycles + 1'b1;
                end
                if (m_axi_arvalid && m_axi_arready) begin
                    top_util_axi_ar_cycles <= top_util_axi_ar_cycles + 1'b1;
                end
                if (m_axi_rvalid && m_axi_rready) begin
                    top_util_axi_r_cycles <= top_util_axi_r_cycles + 1'b1;
                end
                if (m_axi_awvalid && m_axi_awready) begin
                    top_util_axi_aw_cycles <= top_util_axi_aw_cycles + 1'b1;
                end
                if (m_axi_wvalid && m_axi_wready) begin
                    top_util_axi_w_cycles <= top_util_axi_w_cycles + 1'b1;
                end
                if (m_axi_bvalid && m_axi_bready) begin
                    top_util_axi_b_cycles <= top_util_axi_b_cycles + 1'b1;
                end
            end

            if (top_util_finish_event) begin
                if (top_util_trace_en) begin
                    $display("[NPU_UTIL] op=%0d active=%0d ia_row=%0d ia_row_util_bp=%0d acc_valid=%0d acc_util_bp=%0d requant_valid=%0d fifo_valid=%0d fifo_full=%0d store_weight=%0d send_weight=%0d send_ia=%0d tile_start=%0d tile_over=%0d partial_over=%0d l1_switch=%0d dma_busy_ia=%0d dma_busy_kernel=%0d dma_busy_bias=%0d dma_busy_quant=%0d dma_busy_oa=%0d axi_ar=%0d axi_r=%0d axi_aw=%0d axi_w=%0d axi_b=%0d",
                             top_util_op_id,
                             top_util_active_cycles,
                             top_util_ia_row_cycles,
                             util_bp(top_util_ia_row_cycles, top_util_active_cycles),
                             top_util_acc_valid_cycles,
                             util_bp(top_util_acc_valid_cycles, top_util_active_cycles),
                             top_util_requant_valid_cycles,
                             top_util_fifo_valid_cycles,
                             top_util_fifo_full_cycles,
                             top_util_store_weight_cycles,
                             top_util_send_weight_count,
                             top_util_send_ia_count,
                             top_util_tile_start_count,
                             top_util_tile_over_count,
                             top_util_partial_over_count,
                             top_util_ia_l1_switch_count,
                             top_util_ia_dma_busy_cycles,
                             top_util_kernel_dma_busy_cycles,
                             top_util_bias_dma_busy_cycles,
                             top_util_quant_dma_busy_cycles,
                             top_util_oa_dma_busy_cycles,
                             top_util_axi_ar_cycles,
                             top_util_axi_r_cycles,
                             top_util_axi_aw_cycles,
                             top_util_axi_w_cycles,
                             top_util_axi_b_cycles);
                end
                top_util_active <= 1'b0;
            end
        end
    end
`endif

    //assign calc_done = oa_calc_over;
`endif
endmodule
