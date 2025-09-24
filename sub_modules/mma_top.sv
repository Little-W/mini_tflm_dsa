`include "../define.svh"

// 矩阵乘累加(MMA)顶层模块
module mma_top #(
    parameter int unsigned WEIGHT_WIDTH  = 8,   // 权重数据宽度
    parameter int unsigned DATA_WIDTH    = 16,  // IA数据宽度
    parameter int unsigned SIZE          = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH     = 32,   // 总线宽度
    parameter int unsigned REG_WIDTH     = 32   // 寄存器宽度
) (
    //==== 时钟与复位 ====
    input wire clk,   // 系统时钟
    input wire rst_n, // 异步复位，低有效

    //==== 外部控制接口 ====
    input  wire calc_start,  // 计算开始信号
    output wire sa_ready,    // 系统就绪信号

    // --- base pointers
    input  logic [REG_WIDTH-1:0] lhs_base,            // A base         (MULT_LHS_PTR)
    input  logic [REG_WIDTH-1:0] rhs_base,            // B base (s8)    (MULT_RHS_PTR, N x K row-major)
    input  logic [REG_WIDTH-1:0] dst_base,            // C base (s8)    (MULT_DST_PTR)
    input  logic [REG_WIDTH-1:0] bias_base,           // bias s32 (0=none)   (MULT_BIAS_PTR)
    input  logic [REG_WIDTH-1:0] ksum_base,           // kernel-sum (0=unused)(MULT_KSUM_PTR)

    // --- quantization & zero-points ---
    input  logic signed [REG_WIDTH-1:0] lhs_zp,              // A zero-point (s32)  (MULT_LHS_OFFSET)
    input  logic signed [REG_WIDTH-1:0] dst_zp,              // C zero-point (s32)  (MULT_DST_OFFSET)
    input  logic signed [REG_WIDTH-1:0] q_mult_pt,           // per-tensor mult     (MULT_DST_MULT)
    input  logic signed [REG_WIDTH-1:0] q_shift_pt,          // per-tensor rshift   (MULT_DST_SHIFT, +N => >>N)
    input  logic [REG_WIDTH-1:0] q_mult_pc_base,      // per-channel mult[]  (MULT_DST_MULT_PTR)
    input  logic [REG_WIDTH-1:0] q_shift_pc_base,     // per-channel rsh[]   (MULT_DST_SHIFT_PTR)
    input  logic                         use_per_channel,     // 1: per-channel; 0: per-tensor

    // --- dimensions ---
    input  logic [REG_WIDTH-1:0] k,                   // (MULT_RHS_COLS)
    input  logic [REG_WIDTH-1:0] n,                   // (MULT_RHS_ROWS)
    input  logic [REG_WIDTH-1:0] m,                   // (MULT_LHS_ROWS)

    // --- row strides (all in BYTES) ---
    input  logic [REG_WIDTH-1:0] lhs_row_stride_b,    // A row stride       (MULT_LHS_COLS_OFFSET)
    input  logic [REG_WIDTH-1:0] dst_row_stride_b,    // C row stride       (MULT_ROW_ADDR_OFFSET)
    input  logic [REG_WIDTH-1:0] rhs_row_stride_b,    // B row stride       (MULT_RHS_ROW_STRIDE)

    // --- activation clamp ---
    input  logic signed [REG_WIDTH-1:0] act_min,             // (MULT_ACT_MIN)
    input  logic signed [REG_WIDTH-1:0] act_max,             // (MULT_ACT_MAX)

    //==== 外部数据接口 ====
    input wire [BUS_WIDTH-1:0] weight_data_bus,  // 权重数据总线
    input wire [BUS_WIDTH-1:0] bias_data_bus,    // 偏置数据总线
    input wire [BUS_WIDTH-1:0] ia_data_bus,      // 输入激活数据总线

    //==== Memory LSU 接口 ====
    output wire                       sa_icb_cmd_valid,  // ICB命令有效
    input  wire                       sa_icb_cmd_ready,  // ICB命令就绪
    output wire [`E203_ADDR_SIZE-1:0] sa_icb_cmd_addr,   // ICB命令地址
    output wire                       sa_icb_cmd_read,   // ICB读命令
    output wire [     `E203_XLEN-1:0] sa_icb_cmd_wdata,  // ICB写数据
    output wire [  `E203_XLEN_MW-1:0] sa_icb_cmd_wmask,  // ICB写掩码
    output wire [                1:0] sa_icb_cmd_size,   // ICB命令数据宽度
    input  wire                       sa_icb_rsp_valid,  // ICB响应有效
    output wire                       sa_icb_rsp_ready,  // ICB响应就绪
    input  wire [     `E203_XLEN-1:0] sa_icb_rsp_rdata,  // ICB响应数据
    input  wire                       sa_icb_rsp_err     // ICB响应错误
);

    //========================================
    // 内部信号定义
    //========================================

    // Weight Loader 内部信号
    wire                                load_weight_trigger;
    wire        [     $clog2(SIZE)-1:0] valid_row_num;
    wire        [     $clog2(SIZE)-1:0] valid_col_num;
    wire        [$clog2(SIZE*SIZE)-1:0] weight_wr_addr;
    wire                                weight_wr_en;
    wire        [     $clog2(SIZE)-1:0] bias_wr_addr;
    wire                                bias_wr_en;
    wire                                weight_loading_done;
    wire                                store_weight_req;
    wire signed [     WEIGHT_WIDTH-1:0] weight_out              [SIZE];
    wire signed [     WEIGHT_WIDTH-1:0] bias_out                [SIZE];

    // IA Loader 内部信号
    wire                                load_ia_trigger;
    wire        [     $clog2(SIZE)-1:0] ia_valid_row_num;
    wire        [$clog2(SIZE*SIZE)-1:0] ia_wr_addr;
    wire                                ia_wr_en;
    wire        [        BUS_WIDTH-1:0] ia_data_in;
    wire                                ia_use_offset;
    wire                                use_16bits;
    wire                                is_last_tile;
    wire                                ia_loading_done;
    wire                                ia_row_valid;
    wire                                ia_calc_done;
    wire signed [       DATA_WIDTH-1:0] ia_out                  [SIZE];

    // Data Setup 内部信号
    wire signed [       DATA_WIDTH-1:0] data_setup_out          [SIZE];
    wire                                data_setup_input_valid;   // data_setup输出的延迟input_valid
    wire                                data_setup_calc_done;    // data_setup输出的延迟calc_done

    // Accumulator Array 内部信号
    wire        [     $clog2(SIZE)-1:0] acc_valid_depth;
    wire                                acc_is_init_data;
    wire        [     $clog2(SIZE)-1:0] acc_valid_depth_out;      // 累加器输出信号，直连到其他模块
    wire                                acc_is_init_data_out;     // 累加器输出信号，直连到其他模块
    wire                                acc_calc_done;            // 累加器输出信号，直连到其他模块
    wire        [                 31:0] acc_data_out            [SIZE];

    // Systolic Array 内部信号
    wire signed [                 31:0] sa_sum_out              [SIZE];
    wire signed [                 31:0] sa_sum_in               [SIZE];

    // Requantization 内部信号
    wire                                requant_cfg_load_common;
    wire                                requant_cfg_per_channel;
    wire                                requant_in_valid;
    wire                                requant_out_valid;
    wire                                requant_done;
    wire signed [                  7:0] requant_out             [SIZE];
    wire                                cfg_init_quant;
    wire                                data_valid;
    wire        [                 31:0] data_in_s32            [SIZE];

    // FIFO 内部信号
    wire                                fifo_in_valid;
    wire                                fifo_output_req;
    wire                                fifo_req_ack;
    wire        [     $clog2(SIZE)-1:0] fifo_vec_valid_num_col;
    wire                                fifo_output_valid;
    wire                                fifo_output_ready;
    wire        [           3:0] fifo_output_mask;
    wire        [          31:0] fifo_output_data;
    wire                                fifo_full_flag;

    //========================================
    // 模块实例化
    //========================================

    // MMA 控制器
    mma_controller #(
        .DATA_WIDTH   (WEIGHT_WIDTH),   // 控制器使用权重位宽
        .SIZE         (SIZE)
    ) u_mma_controller (
        .clk       (clk),
        .rst_n     (rst_n),
        .calc_start(calc_start),
        .sa_ready  (sa_ready),
        // --- base pointers ---
        .lhs_base(lhs_base),
        .rhs_base(rhs_base),
        .dst_base(dst_base),
        .bias_base(bias_base),
        .ksum_base(ksum_base),
        // --- quantization & zero-points ---
        .lhs_zp(lhs_zp),
        .dst_zp(dst_zp),
        .q_mult_pt(q_mult_pt),
        .q_shift_pt(q_shift_pt),
        .q_mult_pc_base(q_mult_pc_base),
        .q_shift_pc_base(q_shift_pc_base),
        .use_per_channel(use_per_channel),
        // --- dimensions ---
        .k(k),
        .n(n),
        .m(m),
        // --- row strides ---
        .lhs_row_stride_b(lhs_row_stride_b),
        .dst_row_stride_b(dst_row_stride_b),
        .rhs_row_stride_b(rhs_row_stride_b),
        // --- activation clamp ---
        .act_min(act_min),
        .act_max(act_max),
        // Weight Loader Interface
        .load_weight_trigger(load_weight_trigger),
        .weight_data_in     (weight_data_bus),      // 直接连接外部总线
        .bias_data_in       (bias_data_bus),        // 直接连接外部总线
        .valid_row_num      (valid_row_num),
        .valid_col_num      (valid_col_num),
        .weight_wr_addr     (weight_wr_addr),
        .weight_wr_en       (weight_wr_en),
        .bias_wr_addr       (bias_wr_addr),
        .bias_wr_en         (bias_wr_en),
        .weight_loading_done(weight_loading_done),
        // IA Loader Interface
        .load_ia_trigger (load_ia_trigger),
        .ia_valid_row_num(ia_valid_row_num),
        .ia_wr_addr      (ia_wr_addr),
        .ia_wr_en        (ia_wr_en),
        .ia_data_in      (ia_data_in),
        .ia_use_offset   (ia_use_offset),
        .use_16bits      (use_16bits),
        .is_last_tile    (is_last_tile),
        .ia_loading_done (ia_loading_done),
        .ia_row_valid    (ia_row_valid),
        .ia_calc_done    (ia_calc_done),
        // Accumulator Interface
        .acc_valid_depth     (acc_valid_depth),
        .acc_is_init_data    (acc_is_init_data),
        // Requantization Interface
        .requant_cfg_load_common(requant_cfg_load_common),
        .requant_cfg_per_channel(requant_cfg_per_channel),
        .cfg_init_quant         (cfg_init_quant),
        .data_valid            (data_valid),
        .data_in_s32           (data_in_s32),
        .requant_in_valid      (requant_in_valid),
        .requant_out_valid     (requant_out_valid),
        .requant_done          (requant_done),
        // FIFO Interface
        .fifo_in_valid         (fifo_in_valid),
        .fifo_output_req       (fifo_output_req),
        .fifo_req_ack          (fifo_req_ack),
        .fifo_vec_valid_num_col(fifo_vec_valid_num_col),
        .fifo_output_valid     (fifo_output_valid),
        .fifo_output_ready     (fifo_output_ready),
        .fifo_output_mask      (fifo_output_mask),
        .fifo_output_data      (fifo_output_data),
        .fifo_full_flag        (fifo_full_flag),
        // Memory LSU Interface
        .sa_icb_cmd_valid(sa_icb_cmd_valid),
        .sa_icb_cmd_ready(sa_icb_cmd_ready),
        .sa_icb_cmd_addr (sa_icb_cmd_addr),
        .sa_icb_cmd_read (sa_icb_cmd_read),
        .sa_icb_cmd_wdata(sa_icb_cmd_wdata),
        .sa_icb_cmd_wmask(sa_icb_cmd_wmask),
        .sa_icb_cmd_size (sa_icb_cmd_size),
        .sa_icb_rsp_valid(sa_icb_rsp_valid),
        .sa_icb_rsp_ready(sa_icb_rsp_ready),
        .sa_icb_rsp_rdata(sa_icb_rsp_rdata),
        .sa_icb_rsp_err  (sa_icb_rsp_err)
    );

    // Weight Loader
    weight_loader #(
        .DATA_WIDTH(WEIGHT_WIDTH),  // 使用权重位宽
        .SIZE      (SIZE),
        .BUS_WIDTH (BUS_WIDTH)
    ) u_weight_loader (
        .clk                (clk),
        .rst_n              (rst_n),
        .load_weight_trigger(load_weight_trigger),
        .weight_data_in     (weight_data_bus),      // 连接到外部总线
        .bias_data_in       (bias_data_bus),        // 连接到外部总线
        .valid_row_num      (valid_row_num),
        .valid_col_num      (valid_col_num),
        .weight_wr_addr     (weight_wr_addr),
        .weight_wr_en       (weight_wr_en),
        .bias_wr_addr       (bias_wr_addr),
        .bias_wr_en         (bias_wr_en),
        .weight_loading_done(weight_loading_done),
        .store_weight_req   (store_weight_req),     // 直接连到脉动阵列
        .weight_out         (weight_out),           // 直接连到脉动阵列
        .bias_out           (bias_out)              // 直接连到累加器
    );

    // IA Loader
    ia_loader #(
        .DATA_WIDTH(DATA_WIDTH),  // 使用IA数据位宽（16位）
        .SIZE      (SIZE),
        .BUS_WIDTH (BUS_WIDTH)
    ) u_ia_loader (
        .clk            (clk),
        .rst_n          (rst_n),
        .load_ia_trigger(load_ia_trigger),
        .valid_row_num  (ia_valid_row_num),
        .is_last_tile   (is_last_tile),
        .ia_wr_addr     (ia_wr_addr),
        .ia_wr_en       (ia_wr_en),
        .ia_data_in     (ia_data_bus),       // 连接到外部总线
        .lhs_offset     (lhs_zp),            // 直接连接顶层lhs_zp
        .ia_use_offset  (ia_use_offset),
        .use_16bits     (use_16bits),
        .ia_loading_done(ia_loading_done),
        .ia_row_valid   (ia_row_valid),
        .ia_calc_done   (ia_calc_done),
        .ia_out         (ia_out)             // 直接连到data_setup
    );

    // Data Setup (数据对齐)
    data_setup #(
        .DATA_WIDTH(DATA_WIDTH),
        .DATA_NUM  (SIZE)
    ) u_data_setup (
        .clk          (clk),
        .data_in      (ia_out),                    // 来自IA Loader
        .data_out     (data_setup_out),            // 输出到脉动阵列
        .input_valid_i(ia_row_valid),              // 来自IA Loader
        .calc_done_i  (ia_calc_done),              // 来自IA Loader
        .input_valid_o(data_setup_input_valid),    // 延迟后的输入有效信号
        .calc_done_o  (data_setup_calc_done)       // 延迟后的计算完成信号
    );

    // Systolic Array
    ws_systolic_array #(
        .SIZE(SIZE)
    ) u_systolic_array (
        .clk             (clk),
        .store_weight_req(store_weight_req),  // 来自weight_loader
        .weight_in       (weight_out),        // 直接连接来自weight_loader
        .data_in         (data_setup_out),    // 直接连接来自data_setup（16位）
        .sum_in          (sa_sum_in),         // 来自accumulator反馈
        .sum_out         (sa_sum_out)         // 输出到accumulator
    );

    // Accumulator Array
    accumulator_array #(
        .SIZE      (SIZE),
        .DATA_WIDTH(32)
    ) u_accumulator_array (
        .clk           (clk),
        .data_in       (sa_sum_out),              // 来自脉动阵列
        .bias_in       (bias_out),                // 来自weight_loader的偏置
        .calc_done_i   (data_setup_calc_done),    // 来自data_setup延迟后的信号
        .input_valid_i (data_setup_input_valid),  // 来自data_setup延迟后的信号
        .data_out      (acc_data_out),            // 输出到requantization
        .calc_done_o   (acc_calc_done),
        .valid_depth_i (acc_valid_depth),
        .is_init_data_i(acc_is_init_data),
        .valid_depth_o (acc_valid_depth_out),
        .is_init_data_o(acc_is_init_data_out)
    );

    // 连接累加器输出到脉动阵列输入
    assign sa_sum_in = acc_data_out;    // Requantization
    vec_requant #(
        .VLEN(SIZE)
    ) u_vec_requant (
        .clk              (clk),
        .rstn             (rst_n),
        .cfg_load_common  (requant_cfg_load_common),
        .cfg_per_channel  (requant_cfg_per_channel),
        .activation_min_in(act_min),
        .activation_max_in(act_max),
        .dst_offset_in    (dst_zp),
        .pt_multiplier_in (q_mult_pt),
        .pt_shift_in      (q_shift_pt),
        .cfg_init_quant   (cfg_init_quant),
        .data_valid       (data_valid),
        .data_in_s32      (data_in_s32),
        .in_valid         (requant_in_valid),
        .in_vec_s32       (acc_data_out),             // 来自accumulator
        .out_valid        (requant_out_valid),
        .out_vec_s8       (requant_out)               // 输出到FIFO
    );

    // FIFO
    vec_s8_to_fifo #(
        .VLEN(SIZE)
    ) u_vec_s8_to_fifo (
        .clk              (clk),
        .rstn             (rst_n),
        .in_valid         (fifo_in_valid),
        .in_vec_s8        (requant_out),             // 来自requantization
        .output_req       (fifo_output_req),
        .req_ack          (fifo_req_ack),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .output_valid     (fifo_output_valid),
        .output_ready     (fifo_output_ready),
        .output_mask      (fifo_output_mask),
        .output_data      (fifo_output_data),
        .fifo_full_flag   (fifo_full_flag)
    );

endmodule
