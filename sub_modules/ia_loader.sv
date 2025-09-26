/*
 * ia_loader 输入激活加载控制器设计说明（自主访存版本）
 * ------------------------------------------------------------
 * 功能概述:
 *  本模块负责面向分块矩阵运算，从外部存储器自主读取输入激活（lhs），并将数据按行输出到脉动阵列。
 *  模块采用自主驱动模式：init_cfg 后自动开始第一次分块访存，每次完成后申请下一次访存授权。
 *  模块通过 ICB 总线作为主设备主动发起读请求并接收响应数据，采用单缓冲区结构。
 *
 * 工作流程:
 *  1) 配置阶段（通过 init_cfg 触发）
 *     - 当 init_cfg 有效时，模块锁存配置：k、n、lhs_base、lhs_row_stride_b、lhs_zp、ia_use_offset、use_16bits、tile_count。
 *     - k: 输入激活矩阵列数（对应 RHS_COLS，即权重列数）
 *     - n: 输入激活矩阵行数（对应 RHS_ROWS，即权重行数）
 *     - lhs_base: 读取基地址（第一个分块）
 *     - lhs_row_stride_b: 每行之间的地址间距
 *     - lhs_zp: 输入激活零点偏移
 *     - ia_use_offset: 是否使用零点偏移
 *     - use_16bits: 输入数据类型指示
 *     - tile_count: 总分块数量
 *     - 配置完成后，模块自动开始第一次分块数据读取。
 *
 *  2) 自主Load阶段
 *     - 模块自动通过 ICB 主接口从当前分块基地址开始连续读取数据。
 *     - 总共读取 n 行数据，每行包含 k 个元素，行间地址偏移为 lhs_row_stride_b。
 *     - 读取到的数据依序缓存到模块内部行缓冲区（单缓冲），读取完毕置 ia_data_valid=1。
 *
 *  3) Send阶段（通过 send_ia_trigger 触发）
 *     - send_ia_trigger 为单周期触发信号。触发时模块锁存 is_last_tile 并进入 SEND 状态。
 *     - 在 SEND 状态，模块每个周期输出一行数据到 ia_out 总线，同时置 ia_row_valid=1。
 *     - ia_calc_done 与锁存的 is_last_tile 保持一致（如果为最后一个 tile，则该行的 ia_calc_done=1）。
 *     - SEND 持续 n 个周期，发送完成后置 ia_sending_done=1。
 *
 *  4) 自动重触发阶段
 *     - 每次完成一个分块的处理后，模块驱动 load_ia_req=1 申请下一次访存授权。
 *     - 外部控制器通过 load_ia_granted 握手信号确认授权，模块开始下一个分块的访存。
 *     - 模块内部维护分块地址指针，每次访存时自动计算下一个分块的基地址。
 *     - 当所有分块处理完成时，停止申请重触发。
 *
 *  ICB 握手：
 *   - ICB 命令通道：模块作为 Master，驱动 icb_cmd_m，从端驱动 icb_cmd_s.ready。
 *   - ICB 响应通道：从端驱动 icb_rsp_s，模块驱动 icb_rsp_m.rsp_ready。
 *   - 模块应正确处理 ICB 响应的握手及错误处理。
 */

`include "icb_types.sv"

// 输入激活加载控制器，双缓冲区交替向脉动阵列加载输入数据
module ia_loader #(
    parameter int unsigned DATA_WIDTH = 16,   // 单个输入数据宽度
    parameter int unsigned SIZE = 16,         // 输入阵列大小（每行元素数）
    parameter int unsigned BUS_WIDTH = 32,    // 总线位宽（用于 ICB 数据宽度）
    parameter int unsigned REG_WIDTH = 32     // 配置寄存器宽度（地址/偏移/零点）
) (
    // 时钟与复位
    input  wire                        clk,               // 时钟信号
    input  wire                        rst_n,             // 异步复位，低有效

    // 配置控制接口
    input  wire                        init_cfg,          // 触发配置参数锁存

    // Load/Send 控制接口
    output reg                         load_ia_req,       // 申请下一次访存授权（输出到外部控制器）
    input  wire                        load_ia_granted,   // 外部控制器授权下一次访存（握手信号）
    input  wire                        send_ia_trigger,   // 触发发送输入激活到脉动阵列（单拍触发，锁存 is_last_tile）

    // 矩阵尺寸配置（在 init_cfg 时被锁存）
    input  wire [REG_WIDTH-1:0]        k,                 // 输入激活矩阵列数（RHS_COLS）
    input  wire [REG_WIDTH-1:0]        n,                 // 输入激活矩阵行数（RHS_ROWS）
    input  wire [REG_WIDTH-1:0]        tile_count,        // 总分块数量

    // 行数与 tile 信息（在 send_ia_trigger 时被锁存）
    input  wire                        is_last_tile,      // 当前输入的行已经是最后一个 tile

    // 配置寄存器（在 init_cfg 时锁存）
    input  wire signed [REG_WIDTH-1:0] lhs_zp,            // 输入激活零点（s32）
    input  wire [REG_WIDTH-1:0]        lhs_row_stride_b,  // 每行之间的地址间距（以调用方约定的单位）
    input  wire [REG_WIDTH-1:0]        lhs_base,          // 读取基地址（第一个分块）
    input  wire                        ia_use_offset,     // 是否使用零点偏移
    input  wire                        use_16bits,        // 输入数据类型指示，1为s16，0为s8

    // ICB 主接口（模块作为 Master）
    output icb_cmd_m_t                  icb_cmd_m,         // Master -> Slave: 命令有效载荷（模块驱动）
    input  icb_cmd_s_t                  icb_cmd_s,         // Slave -> Master: 命令就绪（从设备驱动）
    input  icb_rsp_s_t                  icb_rsp_s,         // Slave -> Master: 响应有效载荷（从设备驱动）
    output icb_rsp_m_t                  icb_rsp_m,         // Master -> Slave: 响应就绪（模块驱动）

    // 输出信号到脉动阵列
    output reg                         ia_sending_done,   // trigger后，一整个tile已经输出完毕
    output reg                         ia_row_valid,      // 当前行数据有效
    output reg                         ia_calc_done,      // 当前输入的行已经是最后一个tile，部分和将累加得到最终结果
    output reg signed [DATA_WIDTH-1:0] ia_out [SIZE],      // 输出到脉动阵列的输入数据

    // 新增输出：当完成所有行读取时指示数据已准备好
    output reg                         ia_data_valid      // 所有行数据已读取完毕并可用于发送
);

    // 状态定义
    typedef enum logic [1:0] {
        IDLE = 2'b00,     // 空闲状态
        LOAD = 2'b01,    // 读取数据状态
        SEND = 2'b10     // 发送数据状态
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
    // 固定 size 字段为 2'b10，其余字段从寄存器取值（按 struct 定义顺序）
    assign icb_cmd_m_wire = '{ icb_cmd_m_reg.valid,
                               icb_cmd_m_reg.addr,
                               icb_cmd_m_reg.read,
                               icb_cmd_m_reg.wdata,
                               icb_cmd_m_reg.wmask,
                               2'b10 };

    // 行数据缓存（单缓冲区：保存最近读取的一行）
    reg signed [DATA_WIDTH-1:0] line_buffer [SIZE];
    integer i;

    // 锁存的配置信号
    reg [REG_WIDTH-1:0] cfg_k;
    reg [REG_WIDTH-1:0] cfg_n;
    reg signed [REG_WIDTH-1:0] cfg_lhs_zp;
    reg [REG_WIDTH-1:0] cfg_lhs_row_stride_b;
    reg [REG_WIDTH-1:0] cfg_lhs_base;
    reg cfg_ia_use_offset;
    reg cfg_use_16bits;
    reg cfg_is_last_tile;

    // 计数器与状态寄存器
    reg [REG_WIDTH-1:0] load_count;
    reg [REG_WIDTH-1:0] send_count;
    reg [REG_WIDTH-1:0] cur_addr;

    // 配置参数锁存
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_k <= '0;
            cfg_n <= '0;
            cfg_lhs_zp <= '0;
            cfg_lhs_row_stride_b <= '0;
            cfg_lhs_base <= '0;
            cfg_ia_use_offset <= 0;
            cfg_use_16bits <= 0;
        end else if (init_cfg) begin
            cfg_k <= k;
            cfg_n <= n;
            cfg_lhs_zp <= lhs_zp;
            cfg_lhs_row_stride_b <= lhs_row_stride_b;
            cfg_lhs_base <= lhs_base;
            cfg_ia_use_offset <= ia_use_offset;
            cfg_use_16bits <= use_16bits;
        end
    end

endmodule