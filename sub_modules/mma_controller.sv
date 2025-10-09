`include "../inc/define.svh"
`include "../inc/icb_types.svh"

// MMA(Matrix Multiply Accumulate) Controller
module mma_controller #(
    parameter int unsigned WEIGHT_WIDTH = 8,   // 权重数据宽度
    parameter int unsigned DATA_WIDTH   = 16,  // IA数据宽度
    parameter int unsigned SIZE         = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH    = 32,  // 总线宽度
    parameter int unsigned REG_WIDTH    = 32   // 寄存器宽度
) (
    //==== Clock & Control Signals ====
    input  wire clk,         // 时钟
    input  wire rst_n,       // 异步复位，低有效
    input  wire calc_start,  // 计算开始
    input  wire cfg_16bits_ia, // 使用16位IA数据
    output wire sa_ready,    // 控制器就绪

    //==== Control Signals ====
    input  wire                 tile_calc_over,    // 来自accumulator的tile计算结束指示
    input wire                  partial_sum_calc_over, // 来自accumulator的部分和计算结束指示
    output reg  [          2:0] icb_sel,           // ICB多路复用器选择信号
    output reg                  init_cfg_ia,       // IA Loader 配置初始化（单拍）
    output reg                  init_cfg_weight,   // Kernel Loader 配置初始化（单拍）
    output reg                  init_cfg_bias,     // Bias Loader 配置初始化（单拍）
    output reg                  init_cfg_requant,  // Vec Requant 配置初始化（单拍）
    output reg                  init_cfg_oa,       // OA Writer 配置初始化（单拍）
    output reg                  need_bias,         // 是否需要偏置信号
    output reg                  use_16bits,        // 16位数据指示信号
    output reg  [REG_WIDTH-1:0] tile_count,        // 分块计数信号

    //==== IA Loader Interface ====
    input  wire load_ia_req,      // IA加载请求
    output reg  load_ia_granted,  // IA加载授权
    output reg  send_ia_trigger,  // IA发送触发
    input  wire ia_sending_done,  // IA发送完成
    input  wire ia_row_valid,     // IA行数据有效
    input  wire ia_is_init_data,  // IA初始化数据标志
    input  wire ia_calc_done,     // IA计算完成
    input  wire ia_data_valid,    // IA数据有效

    //==== Weight Loader Interface ====
    input  wire load_weight_req,      // 权重加载请求
    output reg  load_weight_granted,  // 权重加载授权
    output reg  send_weight_trigger,  // 权重发送触发
    input  wire weight_sending_done,  // 权重发送完成
    input  wire weight_data_valid,    // 权重数据有效

    //==== Bias Loader Interface ====
    input  wire load_bias_req,      // 偏置加载请求
    output reg  load_bias_granted,  // 偏置加载授权
    input  wire bias_valid,         // 偏置数据有效

    // Requantization Interface
    input  wire load_quant_req,      // 申请下一次量化参数访存
    output wire load_quant_granted,  // 量化参数访存授权
    input  wire quant_params_valid,  // 量化参数有效

    //==== FIFO Interface ====
    input  wire                    fifo_full_flag,          // FIFO满信号

    //==== OA Writer Interface ====
    input  wire write_oa_req,      // OA写回请求
    output reg  write_oa_granted,  // OA写回授权
    input  wire write_done,        // 写回完成
    input  wire oa_calc_over       // OA计算完成
);

endmodule
