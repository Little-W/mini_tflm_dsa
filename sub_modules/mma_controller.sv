`include "../define.svh"

// MMA(Matrix Multiply Accumulate) Controller
module mma_controller #(
    parameter int unsigned WEIGHT_WIDTH  = 8,   // 权重数据宽度
    parameter int unsigned DATA_WIDTH    = 16,  // IA数据宽度
    parameter int unsigned SIZE          = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH     = 32,  // 总线宽度
    parameter int unsigned REG_WIDTH     = 32   // 寄存器宽度
) (
    //==== Clock & Control Signals ====
    input  wire clk,                // 时钟
    input  wire rst_n,              // 异步复位，低有效
    input  wire calc_start,         // 计算开始
    output wire sa_ready,           // 控制器就绪

    //==== Parameter Inputs ====
    // --- base pointers (byte addresses) ---
    input  logic [REG_WIDTH-1:0] lhs_base,            // A base (MULT_LHS_PTR)
    input  logic [REG_WIDTH-1:0] rhs_base,            // B base (s8) (MULT_RHS_PTR)
    input  logic [REG_WIDTH-1:0] dst_base,            // C base (s8) (MULT_DST_PTR)
    input  logic [REG_WIDTH-1:0] bias_base,           // bias s32 (0=none) (MULT_BIAS_PTR)
    input  logic [REG_WIDTH-1:0] ksum_base,           // kernel-sum (0=unused)(MULT_KSUM_PTR)

    // --- quantization & zero-points ---
    input  logic signed [REG_WIDTH-1:0] lhs_zp,              // A zero-point (s32)
    input  logic signed [REG_WIDTH-1:0] dst_zp,              // C zero-point (s32)
    input  logic signed [REG_WIDTH-1:0] q_mult_pt,           // per-tensor mult
    input  logic signed [REG_WIDTH-1:0] q_shift_pt,          // per-tensor rshift (+N => >>N)
    input  logic [REG_WIDTH-1:0] q_mult_pc_base,      // per-channel mult[]
    input  logic [REG_WIDTH-1:0] q_shift_pc_base,     // per-channel rsh[]
    input  logic                         use_per_channel,     // 1: per-channel; 0: per-tensor

    // --- dimensions ---
    input  logic [REG_WIDTH-1:0] k,                   // (MULT_RHS_COLS)
    input  logic [REG_WIDTH-1:0] n,                   // (MULT_RHS_ROWS)
    input  logic [REG_WIDTH-1:0] m,                   // (MULT_LHS_ROWS)

    // --- row strides (all in BYTES) ---
    input  logic [REG_WIDTH-1:0] lhs_row_stride_b,    // A row stride
    input  logic [REG_WIDTH-1:0] dst_row_stride_b,    // C row stride
    input  logic [REG_WIDTH-1:0] rhs_row_stride_b,    // B row stride

    // --- activation clamp ---
    input  logic signed [REG_WIDTH-1:0] act_min,             // (MULT_ACT_MIN)
    input  logic signed [REG_WIDTH-1:0] act_max,             // (MULT_ACT_MAX)

    //==== Systolic Array Control ====
    output reg last_tile_done,                      // 最后分块完成指示

    //==== Weight Loader Interface ====
    output reg                         load_weight_trigger,    // 触发权重加载
    output wire [BUS_WIDTH-1:0]        weight_data_bus,        // 权重数据总线输出
    output reg [$clog2(SIZE)-1:0]      valid_row_num,          // 当前有效权重行数
    output reg [$clog2(SIZE)-1:0]      valid_col_num,          // 当前有效权重列数
    output reg [$clog2(SIZE*SIZE)-1:0] weight_wr_addr,         // 权重写入地址
    output reg                         weight_wr_en,           // 权重写使能
    input  wire                        weight_loading_done,    // 权重加载完成

    //==== Bias Adder Interface ====
    output reg                         init_bias_cfg,          // 触发加载偏置的相关参数
    output wire [BUS_WIDTH-1:0]        bias_data_bus,          // 偏置数据总线输出
    output reg [$clog2(SIZE)-1:0]      bias_valid_row_num,     // 当前有效偏置行数
    output reg                         need_bias,              // 是否需要偏置
    output reg [$clog2(SIZE)-1:0]      bias_wr_addr,           // 偏置写入地址
    output reg                         bias_wr_en,             // 偏置写使能
    input  wire                        bias_loading_done,      // 偏置加载完成

    //==== Input Activation Loader Interface ====
    output reg                         load_ia_trigger,         // 触发输入激活加载
    output reg [$clog2(SIZE)-1:0]      ia_valid_row_num,        // 当前有效输入行数
    output reg [$clog2(SIZE*SIZE)-1:0] ia_wr_addr,              // 输入激活写入地址
    output reg                         ia_wr_en,                // 输入激活写使能
    output wire [BUS_WIDTH-1:0]        ia_data_bus,             // 输入激活数据总线输出
    output reg signed [31:0]           lhs_offset,              // 输入激活零点偏移
    output reg                         ia_use_offset,           // 输入激活零点偏移使能
    output reg                         use_16bits,              // 输入数据类型指示，1为s16，0为s8
    output reg                         is_last_tile,            // 当前输入的行已经是最后一个tile
    input  wire                        ia_loading_done,         // 输入激活加载完成
    input  wire                        ia_row_valid,            // 当前行数据有效
    input  wire                        ia_calc_done,            // 当前输入行为最后一个tile

    //==== Accumulator Array Interface ====
    output reg [$clog2(SIZE)-1:0]      acc_valid_depth,         // 累加器有效深度
    output reg                         acc_is_init_data,        // 累加器初始化数据指示

    //==== Requantization Interface ====
    output reg                requant_cfg_load_common,       // 量化配置加载
    output reg                requant_cfg_per_channel,       // per-channel模式
    output reg                cfg_init_quant,                // per-channel初始化
    output reg                data_valid,                    // per-channel数据有效
    output reg signed [31:0]  data_in_s32,                   // per-channel数据输入
    output reg                requant_in_valid,              // requant输入有效
    input  wire               requant_out_valid,             // requant输出有效
    input  wire               requant_done,                  // requant完成

    //==== FIFO Interface ====
    output reg                fifo_in_valid,                 // FIFO输入有效
    input  wire               fifo_output_req,               // FIFO输出请求
    output reg                fifo_req_ack,                  // FIFO请求确认
    output reg [$clog2(SIZE)-1:0] fifo_vec_valid_num_col,    // FIFO有效列数
    input  wire               fifo_output_valid,             // FIFO输出有效
    output reg                fifo_output_ready,             // FIFO输出就绪
    input  wire [3:0]         fifo_output_mask,              // FIFO输出mask
    input  wire [31:0]        fifo_output_data,              // FIFO输出数据
    input  wire               fifo_full_flag,                // FIFO满信号

    //==== Data Setup Interface ====
    // (data_setup模块主要用于数据对齐，通常不需要额外控制信号)

    //==== Memory LSU Request Interface ====
    output                       sa_icb_cmd_valid,          // ICB命令有效
    input                        sa_icb_cmd_ready,          // ICB命令就绪
    output [`E203_ADDR_SIZE-1:0] sa_icb_cmd_addr,           // ICB命令地址
    output                       sa_icb_cmd_read,           // ICB读命令
    output [`E203_XLEN-1:0]      sa_icb_cmd_wdata,          // ICB写数据
    output [`E203_XLEN_MW-1:0]   sa_icb_cmd_wmask,          // ICB写掩码
    output [1:0]                 sa_icb_cmd_size,           // ICB命令数据宽度

    //==== Memory LSU Response Interface ====
    input                        sa_icb_rsp_valid,          // ICB响应有效
    output                       sa_icb_rsp_ready,          // ICB响应就绪
    input  [`E203_XLEN-1:0]      sa_icb_rsp_rdata,          // ICB响应数据
    input                        sa_icb_rsp_err             // ICB响应错误
);

endmodule
