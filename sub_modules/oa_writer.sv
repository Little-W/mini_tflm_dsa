/*
 * oa_writer 输出激活写回控制器设计说明（自主访存版本）
 * ------------------------------------------------------------
 * 功能概述:
 *  本模块负责面向分块矩阵运算，将脉动阵列的输出激活数据通过 ICB 总线主动写回到外部存储器。
 *  模块采用自主驱动模式：init_cfg 后自动准备写回流程，每次完成后申请下一次写回授权。
 *  模块通过 ICB 总线作为主设备主动发起写请求，支持按行写回和地址stride控制。
 *
 * 工作流程:
 *  1) 配置阶段（通过 init_cfg 触发）
 *     - 当 init_cfg 有效时，模块锁存配置：dst_base、dst_row_stride_b、k、m、tile_count。
 *     - dst_base: 输出矩阵在内存中的基地址（第一个分块）
 *     - dst_row_stride_b: 每行之间的地址间距（字节）
 *     - k: 输出矩阵列数（对应 RHS_COLS）
 *     - m: 输出矩阵行数（对应 LHS_ROWS）
 *     - tile_count: 总分块数量
 *     - 配置完成后，模块准备接收数据写回。
 *
 *  2) 写回阶段（通过 write_oa_trigger 触发）
 *     - write_oa_trigger 为单周期触发信号，开始输出激活写回流程。
 *     - 模块通过 output_ready 握手接收来自脉动阵列的输出数据。
 *     - 当 output_valid 有效时，根据 output_mask 和 switch_row 控制数据写回：
 *       * output_mask: 4位掩码，指示32位数据中哪些字节有效
 *       * switch_row: 指示是否切换到下一行
 *     - 通过 ICB 主接口将数据写入到计算得到的目标地址。
 *     - 写回完成后，模块置 write_done=1。
 *
 *  3) 自动重触发阶段
 *     - 每次完成一个分块的写回后，模块驱动 write_oa_req=1 申请下一次写回授权。
 *     - 外部控制器通过 write_oa_granted 握手信号确认授权，模块开始下一个分块的写回准备。
 *     - 模块内部维护分块地址指针，每次写回时自动计算下一个分块的基地址。
 *     - 当所有分块处理完成时，停止申请重触发。
 *
 *  4) 地址计算
 *     - 当前写入地址 = dst_base + row_index * dst_row_stride_b + col_index * element_size
 *     - switch_row 信号用于控制行索引的递增
 *
 *  ICB 握手：
 *   - ICB 命令通道：模块作为 Master，驱动 icb_cmd_m，从端驱动 icb_cmd_s.ready。
 *   - ICB 响应通道：从端驱动 icb_rsp_s，模块驱动 icb_rsp_m.rsp_ready。
 */

`include "icb_types.sv"

module oa_writer #(
    parameter int unsigned DATA_WIDTH = 8,       // 输出数据元素宽度
    parameter int unsigned REG_WIDTH = 32        // 配置寄存器宽度
) (
    // 时钟与复位
    input  wire                        clk,               // 时钟信号
    input  wire                        rst_n,             // 异步复位，低有效

    // 配置控制接口
    input  wire                        init_cfg,          // 触发配置参数锁存
    input  wire                        write_oa_trigger,  // 触发开始输出激活写回

    // 自动重触发控制接口
    output reg                         write_oa_req,      // 申请下一次写回授权（输出到外部控制器）
    input  wire                        write_oa_granted,  // 外部控制器授权下一次写回（握手信号）

    // 配置寄存器（在 init_cfg 时锁存）
    input  wire [REG_WIDTH-1:0]        dst_base,          // 输出矩阵基地址（第一个分块）
    input  wire [REG_WIDTH-1:0]        dst_row_stride_b,  // 行间地址间距（字节）
    input  wire [REG_WIDTH-1:0]        k,                 // 输出矩阵列数
    input  wire [REG_WIDTH-1:0]        m,                 // 输出矩阵行数
    input  wire [REG_WIDTH-1:0]        tile_count,        // 总分块数量

    // 数据输入接口（来自脉动阵列）
    input  wire                        output_valid,      // 输出数据有效信号
    input  wire                        switch_row,        // 切换到下一行信号
    output reg                         output_ready,      // 输出数据就绪信号
    input  wire [3:0]                  output_mask,       // 4位字节掩码
    input  wire [31:0]                 output_data,       // 32位输出数据

    // ICB 主接口（模块作为 Master）
    output icb_cmd_m_t                  icb_cmd_m,         // Master -> Slave: 命令有效载荷
    input  icb_cmd_s_t                  icb_cmd_s,         // Slave -> Master: 命令就绪
    input  icb_rsp_s_t                  icb_rsp_s,         // Slave -> Master: 响应有效载荷
    output icb_rsp_m_t                  icb_rsp_m,         // Master -> Slave: 响应就绪

    // 状态输出
    output reg                         write_done         // 写回完成信号
);

    // 状态定义
    typedef enum logic [1:0] {
        IDLE  = 2'b00,    // 空闲状态
        WRITE = 2'b01     // 写回数据状态
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

    // 锁存的配置信号
    reg [REG_WIDTH-1:0] cfg_dst_base;
    reg [REG_WIDTH-1:0] cfg_dst_row_stride_b;
    reg [REG_WIDTH-1:0] cfg_k;
    reg [REG_WIDTH-1:0] cfg_m;

    // 地址计算与计数器
    reg [REG_WIDTH-1:0] cur_row_index;
    reg [REG_WIDTH-1:0] cur_col_index;
    reg [REG_WIDTH-1:0] cur_addr;
    reg [REG_WIDTH-1:0] total_elements;
    reg [REG_WIDTH-1:0] element_count;

    // 配置参数锁存
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_dst_base <= '0;
            cfg_dst_row_stride_b <= '0;
            cfg_k <= '0;
            cfg_m <= '0;
        end else if (init_cfg) begin
            cfg_dst_base <= dst_base;
            cfg_dst_row_stride_b <= dst_row_stride_b;
            cfg_k <= k;
            cfg_m <= m;
        end
    end

    // 状态机实现

endmodule