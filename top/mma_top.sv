`include "../inc/define.svh"
`include "../inc/icb_types.svh"

// 矩阵乘累加(MMA)顶层模块
module mma_top #(
    parameter int unsigned WEIGHT_WIDTH = 8,   // 权重数据宽度
    parameter int unsigned DATA_WIDTH   = 16,  // IA数据宽度
    parameter int unsigned SIZE         = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH    = 32,  // 总线宽度
    parameter int unsigned REG_WIDTH    = 32   // 寄存器宽度
) (
    //==== 时钟与复位 ====
    input wire clk,   // 系统时钟
    input wire rst_n, // 异步复位，低有效

    //==== 外部控制接口 ====
    input  wire calc_start,  // 计算开始信号
    output wire sa_ready,    // 系统就绪信号

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
    input logic [REG_WIDTH-1:0] k,  // (MULT_RHS_COLS)
    input logic [REG_WIDTH-1:0] n,  // (MULT_RHS_ROWS)
    input logic [REG_WIDTH-1:0] m,  // (MULT_LHS_ROWS)

    // --- row strides (all in BYTES) ---
    input logic [REG_WIDTH-1:0] lhs_row_stride_b,  // A row stride       (MULT_LHS_COLS_OFFSET)
    input logic [REG_WIDTH-1:0] dst_row_stride_b,  // C row stride       (MULT_ROW_ADDR_OFFSET)
    input logic [REG_WIDTH-1:0] rhs_row_stride_b,  // B row stride       (MULT_RHS_ROW_STRIDE)

    // --- activation clamp ---
    input logic signed [REG_WIDTH-1:0] act_min,  // (MULT_ACT_MIN)
    input logic signed [REG_WIDTH-1:0] act_max,  // (MULT_ACT_MAX)

    //==== Memory LSU 接口（改为 icb_ext 三通道） ====
    // master -> slave: command payload
    output icb_ext_cmd_m_t   sa_icb_cmd,
    // master -> slave: write-data payload
    output icb_ext_wr_m_t sa_icb_wr,
    // slave -> master: command ready
    input  icb_ext_cmd_s_t   sa_icb_cmd_ready,
    // slave -> master: write-data ready
    input  icb_ext_wr_s_t sa_icb_w_ready,
    // slave -> master: response payload
    input  icb_ext_rsp_s_t   sa_icb_rsp,
    // master -> slave: response ready
    output icb_ext_rsp_m_t   sa_icb_rsp_ready
);

    //========================================
    // 内部信号定义
    //========================================

    // ICB 多路复用器信号（扩展）
    icb_ext_cmd_m_t   mux_m_cmd;
    icb_ext_wr_m_t mux_m_wr;
    icb_ext_cmd_s_t   mux_m_cmd_rsp;
    icb_ext_wr_s_t mux_m_wr_rsp;
    icb_ext_rsp_s_t   mux_m_rsp;
    icb_ext_rsp_m_t   mux_m_rsp_ready;

    // 各子模块的 ICB 接口信号（扩展）
    icb_ext_cmd_m_t   ia_loader_cmd,   kernel_loader_cmd,   bias_loader_cmd,   vec_requant_cmd,   oa_writer_cmd;
    icb_ext_wr_m_t ia_loader_wr, kernel_loader_wr, bias_loader_wr, vec_requant_wr, oa_writer_wr;

    icb_ext_cmd_s_t   ia_loader_cmd_ready,   kernel_loader_cmd_ready,   bias_loader_cmd_ready,   vec_requant_cmd_ready,   oa_writer_cmd_ready;
    icb_ext_wr_s_t ia_loader_w_ready,     kernel_loader_w_ready,     bias_loader_w_ready,     vec_requant_w_ready,     oa_writer_w_ready;

    icb_ext_rsp_s_t   ia_loader_rsp, kernel_loader_rsp, bias_loader_rsp, vec_requant_rsp, oa_writer_rsp;
    icb_ext_rsp_m_t   ia_loader_rsp_ready, kernel_loader_rsp_ready, bias_loader_rsp_ready, vec_requant_rsp_ready, oa_writer_rsp_ready;

    // ICB 选择信号
    reg         [             2:0] icb_sel;

    // IA Loader 内部信号
    wire                           load_ia_req;
    wire                           load_ia_granted;
    wire                           send_ia_trigger;
    wire                           ia_sending_done;
    wire                           ia_row_valid;
    wire                           ia_is_init_data;
    wire                           ia_calc_done;
    wire signed [  DATA_WIDTH-1:0] ia_out                                    [SIZE];
    wire                           ia_data_valid;

    // Kernel Loader 内部信号
    wire                           load_weight_req;
    wire                           load_weight_granted;
    wire                           send_weight_trigger;
    wire                           weight_sending_done;
    wire                           store_weight_req;
    wire signed [WEIGHT_WIDTH-1:0] weight_out                                [SIZE];
    wire                           weight_data_valid;

    // Bias Loader 内部信号
    wire                           load_bias_req;
    wire                           load_bias_granted;
    wire                           bias_valid;
    wire        [            31:0] bias_data_out                             [SIZE];

    // Accumulator Array 输出（来自封装模块）
    wire                           acc_data_valid;
    wire                           tile_calc_over;
    wire                           partial_sum_calc_over;
    wire        [            31:0] acc_data_out                              [SIZE];

    // Requantization 内部信号
    wire                           load_quant_req;
    wire                           load_quant_granted;
    wire                           quant_params_valid;
    wire                           requant_out_valid;
    wire signed [             7:0] requant_out                               [SIZE];

    // FIFO 内部信号
    wire                           fifo_output_req;
    wire        [$clog2(SIZE)-1:0] fifo_vec_valid_num_col;
    wire                           fifo_output_valid;
    wire                           fifo_output_switch_row;
    wire                           fifo_output_ready;
    wire        [             3:0] fifo_output_mask;
    wire        [            31:0] fifo_output_data;
    wire                           fifo_full_flag;

    // OA Writer 内部信号
    wire                           write_oa_req;
    wire                           write_oa_granted;
    wire                           write_done;
    wire                           oa_calc_over;

    // 添加缺少的内部信号
    // per-submodule init_cfg signals (由mma_controller产生的单拍脉冲)
    wire                           init_cfg_ia;
    wire                           init_cfg_weight;
    wire                           init_cfg_bias;
    wire                           init_cfg_requant;
    wire                           init_cfg_oa;
    wire                           need_bias;  // 是否需要偏置信号
    wire                           ia_use_offset;  // IA偏移量使能信号
    wire                           use_16bits;  // 16位数据指示信号
    wire        [   REG_WIDTH-1:0] tile_count;  // 分块计数信号

    //========================================
    // 模块实例化
    //========================================

    // ICB 5选1多路复用器（扩展）
    icb_mux_5to1 u_icb_mux (
        .m_cmd        (mux_m_cmd),
        .m_wr      (mux_m_wr),
        .m_cmd_rsp    (mux_m_cmd_rsp),
        .m_wr_rsp  (mux_m_wr_rsp),
        .m_rsp        (mux_m_rsp),
        .m_rsp_ready  (mux_m_rsp_ready),
        .s0_cmd       (ia_loader_cmd),
        .s0_wr     (ia_loader_wr),
        .s0_cmd_ready (ia_loader_cmd_ready),
        .s0_wr_ready(ia_loader_w_ready),
        .s0_rsp       (ia_loader_rsp),
        .s0_rsp_ready (ia_loader_rsp_ready),
        .s1_cmd       (kernel_loader_cmd),
        .s1_wr     (kernel_loader_wr),
        .s1_cmd_ready (kernel_loader_cmd_ready),
        .s1_wr_ready(kernel_loader_w_ready),
        .s1_rsp       (kernel_loader_rsp),
        .s1_rsp_ready (kernel_loader_rsp_ready),
        .s2_cmd       (bias_loader_cmd),
        .s2_wr     (bias_loader_wr),
        .s2_cmd_ready (bias_loader_cmd_ready),
        .s2_wr_ready(bias_loader_w_ready),
        .s2_rsp       (bias_loader_rsp),
        .s2_rsp_ready (bias_loader_rsp_ready),
        .s3_cmd       (vec_requant_cmd),
        .s3_wr     (vec_requant_wr),
        .s3_cmd_ready (vec_requant_cmd_ready),
        .s3_wr_ready(vec_requant_w_ready),
        .s3_rsp       (vec_requant_rsp),
        .s3_rsp_ready (vec_requant_rsp_ready),
        .s4_cmd       (oa_writer_cmd),
        .s4_wr     (oa_writer_wr),
        .s4_cmd_ready (oa_writer_cmd_ready),
        .s4_wr_ready(oa_writer_w_ready),
        .s4_rsp       (oa_writer_rsp),
        .s4_rsp_ready (oa_writer_rsp_ready),
        .sel          (icb_sel)
    );

    // 将多路复用器连接到外部ICB接口
    assign sa_icb_cmd        = mux_m_cmd;
    assign sa_icb_wr      = mux_m_wr;
    assign mux_m_cmd_rsp     = sa_icb_cmd_ready;
    assign mux_m_wr_rsp   = sa_icb_w_ready;
    assign mux_m_rsp         = sa_icb_rsp;
    assign sa_icb_rsp_ready  = mux_m_rsp_ready;

    // MMA 控制器
    mma_controller #(
        .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .DATA_WIDTH  (DATA_WIDTH),
        .SIZE        (SIZE),
        .BUS_WIDTH   (BUS_WIDTH),
        .REG_WIDTH   (REG_WIDTH)
    ) u_mma_controller (
        .clk       (clk),
        .rst_n     (rst_n),
        .calc_start(calc_start),
        .sa_ready  (sa_ready),

        .tile_calc_over       (tile_calc_over),
        .partial_sum_calc_over(partial_sum_calc_over),
        .icb_sel              (icb_sel),
        .init_cfg_ia          (init_cfg_ia),
        .init_cfg_weight      (init_cfg_weight),
        .init_cfg_bias        (init_cfg_bias),
        .init_cfg_requant     (init_cfg_requant),
        .init_cfg_oa          (init_cfg_oa),
        .need_bias            (need_bias),
        .ia_use_offset        (ia_use_offset),
        .use_16bits           (use_16bits),
        .tile_count           (tile_count),
        // IA Loader Interface
        .load_ia_req          (load_ia_req),
        .load_ia_granted      (load_ia_granted),
        .send_ia_trigger      (send_ia_trigger),
        .ia_sending_done      (ia_sending_done),
        .ia_row_valid         (ia_row_valid),
        .ia_is_init_data      (ia_is_init_data),
        .ia_calc_done         (ia_calc_done),
        .ia_data_valid        (ia_data_valid),
        // Weight Loader Interface
        .load_weight_req      (load_weight_req),
        .load_weight_granted  (load_weight_granted),
        .send_weight_trigger  (send_weight_trigger),
        .weight_sending_done  (weight_sending_done),
        .weight_data_valid    (weight_data_valid),
        // Bias Loader Interface
        .load_bias_req        (load_bias_req),
        .load_bias_granted    (load_bias_granted),
        .bias_valid           (bias_valid),
        // Requantization Interface
        .load_quant_req       (load_quant_req),
        .load_quant_granted   (load_quant_granted),
        .quant_params_valid   (quant_params_valid),
        // FIFO Interface
        .fifo_full_flag       (fifo_full_flag),
        // OA Writer Interface
        .write_oa_req         (write_oa_req),
        .write_oa_granted     (write_oa_granted),
        .write_done           (write_done),
        .oa_calc_over         (oa_calc_over)
    );

    // IA Loader
    ia_loader #(
        .DATA_WIDTH(DATA_WIDTH),
        .SIZE      (SIZE),
        .BUS_WIDTH (BUS_WIDTH),
        .REG_WIDTH (REG_WIDTH)
    ) u_ia_loader (
        .clk             (clk),
        .rst_n           (rst_n),
        .init_cfg        (init_cfg_ia),
        .load_ia_req     (load_ia_req),
        .load_ia_granted (load_ia_granted),
        .send_ia_trigger (send_ia_trigger),
        .k               (k),
        .n               (n),
        .m               (m),
        .lhs_zp          (lhs_zp),
        .lhs_row_stride_b(lhs_row_stride_b),
        .lhs_base        (lhs_base),
        .ia_use_offset   (ia_use_offset),
        .use_16bits      (use_16bits),
        .icb_cmd_m       (ia_loader_cmd),
        .icb_cmd_s       (ia_loader_cmd_ready),
        .icb_rsp_s       (ia_loader_rsp),
        .icb_rsp_m       (ia_loader_rsp_ready),
        .ia_sending_done (ia_sending_done),
        .ia_row_valid    (ia_row_valid),
        .ia_is_init_data (ia_is_init_data),
        .ia_calc_done    (ia_calc_done),
        .ia_out          (ia_out),
        .ia_data_valid   (ia_data_valid)
    );

    // Kernel Loader
    kernel_loader #(
        .DATA_WIDTH(WEIGHT_WIDTH),
        .SIZE      (SIZE),
        .BUS_WIDTH (BUS_WIDTH),
        .REG_WIDTH (REG_WIDTH)
    ) u_kernel_loader (
        .clk                (clk),
        .rst_n              (rst_n),
        .init_cfg           (init_cfg_weight),
        .load_weight_req    (load_weight_req),
        .load_weight_granted(load_weight_granted),
        .send_weight_trigger(send_weight_trigger),
        .k                  (k),
        .n                  (n),
        .m                  (m),
        .rhs_zp             (rhs_zp),
        .rhs_base           (rhs_base),
        .rhs_row_stride_b   (rhs_row_stride_b),
        .icb_cmd_m          (kernel_loader_cmd),
        .icb_cmd_s          (kernel_loader_cmd_ready),
        .icb_rsp_s          (kernel_loader_rsp),
        .icb_rsp_m          (kernel_loader_rsp_ready),
        .weight_sending_done(weight_sending_done),
        .store_weight_req   (store_weight_req),
        .weight_out         (weight_out),
        .weight_data_valid  (weight_data_valid)
    );

    // Bias Loader
    bias_loader #(
        .SIZE      (SIZE),
        .DATA_WIDTH(32),
        .REG_WIDTH (REG_WIDTH)
    ) u_bias_loader (
        .clk              (clk),
        .rst_n            (rst_n),
        .init_cfg         (init_cfg_bias),
        .load_bias_req    (load_bias_req),
        .load_bias_granted(load_bias_granted),
        .need_bias        (need_bias),
        .bias_base        (bias_base),
        .k                (k),
        .m                (m),
        .icb_cmd_m        (bias_loader_cmd),
        .icb_cmd_s        (bias_loader_cmd_ready),
        .icb_rsp_s        (bias_loader_rsp),
        .icb_rsp_m        (bias_loader_rsp_ready),
        .tile_calc_over   (tile_calc_over),
        .tile_calc_start  (send_ia_trigger),
        .bias_valid       (bias_valid),
        .data_out         (bias_data_out)
    );

    // 脉动阵列计算核心
    compute_core #(
        .SIZE      (SIZE),
        .DATA_WIDTH(DATA_WIDTH)
    ) u_compute_core (
        .clk                  (clk),
        .store_weight_req     (store_weight_req),
        .weight_in            (weight_out),
        .ia_vec_in            (ia_out),
        .ia_row_valid         (ia_row_valid),
        .ia_calc_done         (ia_calc_done),
        .ia_is_init_data      (ia_is_init_data),
        .bias_in              (bias_data_out),
        .acc_data_out         (acc_data_out),
        .acc_data_valid       (acc_data_valid),
        .tile_calc_over       (tile_calc_over),
        .partial_sum_calc_over(partial_sum_calc_over)
    );

    // Vec Requant
    vec_requant #(
        .VLEN     (SIZE),
        .REG_WIDTH(REG_WIDTH)
    ) u_vec_requant (
        .clk               (clk),
        .rstn              (rst_n),
        .init_cfg          (init_cfg_requant),
        .cfg_per_channel   (use_per_channel),
        .activation_min_in (act_min),
        .activation_max_in (act_max),
        .dst_offset_in     (dst_zp),
        .multiplier_in     (q_mult_pt),
        .shift_in          (q_shift_pt),
        .load_quant_req    (load_quant_req),
        .load_quant_granted(load_quant_granted),
        .quant_params_valid(quant_params_valid),
        .k                 (k),
        .m                 (m),
        .icb_cmd_m         (vec_requant_cmd),
        .icb_cmd_s         (vec_requant_cmd_ready),
        .icb_rsp_s         (vec_requant_rsp),
        .icb_rsp_m         (vec_requant_rsp_ready),
        .in_valid          (acc_data_valid),
        .in_vec_s32        (acc_data_out),
        .out_valid         (requant_out_valid),
        .out_vec_s8        (requant_out)
    );

    // FIFO
    vec_s8_to_fifo #(
        .VLEN(SIZE)
    ) u_vec_s8_to_fifo (
        .clk              (clk),
        .rstn             (rst_n),
        .in_valid         (requant_out_valid),
        .in_vec_s8        (requant_out),
        .output_req       (fifo_output_req),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .output_valid     (fifo_output_valid),
        .output_switch_row(fifo_output_switch_row),
        .output_ready     (fifo_output_ready),
        .output_mask      (fifo_output_mask),
        .output_data      (fifo_output_data),
        .fifo_full_flag   (fifo_full_flag)
    );

    // OA Writer
    oa_writer #(
        .DATA_WIDTH(8),
        .REG_WIDTH (REG_WIDTH)
    ) u_oa_writer (
        .clk              (clk),
        .rst_n            (rst_n),
        .init_cfg         (init_cfg_oa),
        .oa_fifo_req      (fifo_output_req),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .write_oa_req     (write_oa_req),
        .write_oa_granted (write_oa_granted),
        .dst_base         (dst_base),
        .dst_row_stride_b (dst_row_stride_b),
        .k                (k),
        .m                (m),
        .tile_count       (tile_count),
        .output_valid     (fifo_output_valid),
        .switch_row       (fifo_output_switch_row),
        .output_ready     (fifo_output_ready),
        .output_mask      (fifo_output_mask),
        .output_data      (fifo_output_data),
        .icb_cmd_m        (oa_writer_cmd),
        .icb_cmd_s        (oa_writer_cmd_ready),
        .icb_rsp_s        (oa_writer_rsp),
        .icb_rsp_m        (oa_writer_rsp_ready),
        .write_done       (write_done),
        .oa_calc_over     (oa_calc_over)
    );

endmodule
