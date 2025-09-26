/*
 * 权重加载控制器设计说明（自主访存版本）
 * ------------------------------------------------------------
 * 功能概述:
 *  本模块负责面向分块矩阵运算，从外部存储器自主读取权重数据（rhs），并将权重数据输出到脉动阵列。
 *  模块采用自主驱动模式：init_cfg 后自动开始第一次分块访存，每次完成后申请下一次访存授权。
 *  模块通过 ICB 总线作为主设备主动发起读请求并接收响应数据，采用单缓冲区结构。
 *
 * 存储与输出格式:
 *  - 权重在外部存储器按行主序存储（N x M），即 {w00, w01, ..., w0(M-1), w10, w11, ..., w1(M-1), ...}
 *  - 模块内部按列主序重新排列并缓存，即 {w00, w10, ..., w(N-1)0, w01, w11, ..., w(N-1)1, ...}
 *  - 输出时按行输出到脉动阵列：weight_out[i] 为第 i 行的权重向量
 *
 * 工作流程:
 *  1) 配置阶段（通过 init_cfg 触发）
 *     - 当 init_cfg 有效时，模块锁存配置：n、m、rhs_zp、rhs_base、rhs_row_stride_b、tile_count。
 *     - n: 权重矩阵行数（对应 RHS_ROWS）
 *     - m: 权重矩阵列数（对应 LHS_ROWS，即输出行数）
 *     - rhs_zp: 权重零点偏移
 *     - rhs_base: 权重数据基地址（第一个分块）
 *     - rhs_row_stride_b: 权重行间地址间距
 *     - tile_count: 总分块数量
 *     - 配置完成后，模块自动开始第一次分块权重读取。
 *
 *  2) 自主Load阶段
 *     - 模块自动通过 ICB 主接口从当前分块基地址开始按行读取权重数据。
 *     - 总共读取 n 行，每行 m 个元素，行间地址偏移为 rhs_row_stride_b。
 *     - 读取到的数据按列主序重新排列存储到内部缓冲区，当分块权重读取完毕，模块置 weight_data_valid=1。
 *
 *  3) Send阶段（通过 send_weight_trigger 触发）
 *     - send_weight_trigger 为单周期触发信号。触发时模块进入 SEND 状态。
 *     - 在 SEND 状态，模块将内部缓存的权重按行输出到 weight_out 总线，同时置 store_weight_req=1 指示脉动阵列加载权重。
 *     - 输出规则：根据锁存的 n 和 m，只输出有效的行和列；无效部分填零。
 *     - SEND 完成后，模块置 weight_sending_done=1。
 *
 *  4) 自动重触发阶段
 *     - 每次完成一个分块的处理后，模块驱动 load_weight_req=1 申请下一次访存授权。
 *     - 外部控制器通过 load_weight_granted 握手信号确认授权，模块开始下一个分块的访存。
 *     - 模块内部维护分块地址指针，每次访存时自动计算下一个分块的基地址。
 *     - 当所有分块处理完成时，停止申请重触发。
 *
 *  ICB 握手：
 *   - ICB 命令通道：模块作为 Master，驱动 icb_cmd_m，从端驱动 icb_cmd_s.ready。
 *   - ICB 响应通道：从端驱动 icb_rsp_s，模块驱动 icb_rsp_m.rsp_ready。
 *   - 模块应正确处理 ICB 握手协议及错误处理。
 */

`include "icb_types.sv"

module kernel_loader #(
    parameter int unsigned DATA_WIDTH = 8,      // 权重数据宽度
    parameter int unsigned SIZE = 16,           // 阵列大小
    parameter int unsigned BUS_WIDTH = 32,      // 总线宽度
    parameter int unsigned REG_WIDTH = 32       // 配置寄存器宽度
) (
    // 时钟与复位
    input  wire                        clk,               // 时钟信号
    input  wire                        rst_n,             // 异步复位，低有效

    // 配置控制接口
    input  wire                        init_cfg,          // 触发配置参数锁存

    // 自动重触发控制接口
    output reg                         load_weight_req,     // 申请下一次访存授权（输出到外部控制器）
    input  wire                        load_weight_granted, // 外部控制器授权下一次访存（握手信号）
    input  wire                        send_weight_trigger, // 触发发送权重到脉动阵列（单拍触发）

    // 矩阵尺寸与分块配置（在 init_cfg 时被锁存）
    input  wire [REG_WIDTH-1:0]        n,                 // 权重矩阵行数（RHS_ROWS）
    input  wire [REG_WIDTH-1:0]        m,                 // 权重矩阵列数（LHS_ROWS）
    input  wire [REG_WIDTH-1:0]        tile_count,        // 总分块数量

    // 配置寄存器（在 init_cfg 时锁存）
    input  wire signed [REG_WIDTH-1:0] rhs_zp,            // 权重零点（s32）
    input  wire [REG_WIDTH-1:0]        rhs_base,          // 权重数据基地址（第一个分块）
    input  wire [REG_WIDTH-1:0]        rhs_row_stride_b,  // 权重行间地址间距

    // ICB 主接口（模块作为 Master）
    output icb_cmd_m_t                  icb_cmd_m,         // Master -> Slave: 命令有效载荷
    input  icb_cmd_s_t                  icb_cmd_s,         // Slave -> Master: 命令就绪
    input  icb_rsp_s_t                  icb_rsp_s,         // Slave -> Master: 响应有效载荷
    output icb_rsp_m_t                  icb_rsp_m,         // Master -> Slave: 响应就绪

    // 输出信号到脉动阵列
    output reg                         weight_sending_done, // 权重发送完成
    output reg                         store_weight_req,    // 控制脉动阵列权重加载
    output reg signed [DATA_WIDTH-1:0] weight_out[SIZE],   // 输出到脉动阵列的权重（按行输出）

    // 新增输出：当完成所有权重读取时指示数据已准备好
    output reg                         weight_data_valid   // 所有权重数据已读取完毕并可用于发送
);

    // 状态定义
    typedef enum logic [1:0] {
        IDLE = 2'b00,     // 空闲状态
        LOAD = 2'b01,     // 读取权重数据状态
        SEND = 2'b10      // 发送权重数据状态
    } state_t;

    state_t state;

    // ICB 命令与响应内部信号与连接
    // 使用寄存器存储可变字段，通过连续赋值将 size 字段固定为 2'b10
    icb_cmd_m_t icb_cmd_m_reg; // 驱动可变字段的寄存器
    icb_cmd_m_t icb_cmd_m_wire; // 由寄存器与常量 size 组合成的输出线网
    icb_rsp_m_t icb_rsp_m_wire;
    // 将 wire 输出到模块端口
    assign icb_cmd_m = icb_cmd_m_wire;
    assign icb_rsp_m = icb_rsp_m_wire;
    // 固定 size 字段为 2'b10，其余字段从寄存器取值
    assign icb_cmd_m_wire = '{ icb_cmd_m_reg.valid,
                               icb_cmd_m_reg.addr,
                               icb_cmd_m_reg.read,
                               icb_cmd_m_reg.wdata,
                               icb_cmd_m_reg.wmask,
                               2'b10 };

    // 权重缓冲区（按列主序存储）
    reg signed [DATA_WIDTH-1:0] weight_buffer [SIZE*SIZE];
    integer i, j;

    // 锁存的配置信号
    reg [REG_WIDTH-1:0] cfg_n;
    reg [REG_WIDTH-1:0] cfg_m;
    reg signed [REG_WIDTH-1:0] cfg_rhs_zp;
    reg [REG_WIDTH-1:0] cfg_rhs_base;
    reg [REG_WIDTH-1:0] cfg_rhs_row_stride_b;

    // 计数器与状态寄存器
    reg [REG_WIDTH-1:0] load_row_count;
    reg [REG_WIDTH-1:0] load_col_count;
    reg [REG_WIDTH-1:0] cur_addr;

    // 配置参数锁存
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_n <= '0;
            cfg_m <= '0;
            cfg_rhs_zp <= '0;
            cfg_rhs_base <= '0;
            cfg_rhs_row_stride_b <= '0;
        end else if (init_cfg) begin
            cfg_n <= n;
            cfg_m <= m;
            cfg_rhs_zp <= rhs_zp;
            cfg_rhs_base <= rhs_base;
            cfg_rhs_row_stride_b <= rhs_row_stride_b;
        end
    end

    // 状态机实现

endmodule