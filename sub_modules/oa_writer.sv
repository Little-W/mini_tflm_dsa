/*
 * oa_writer 输出激活写回控制器设计说明（自主访存版本）
 * ------------------------------------------------------------
 * 功能概述:
 *  本模块负责面向分块矩阵运算，将脉动阵列的输出激活数据通过 ICB 总线主动写回到外部存储器。
 *  模块采用自主驱动模式：init_cfg 后自动准备写回流程，每次完成后申请下一次写回授权。
 *  模块通过 ICB 总线作为主设备主动发起写请求，支持按行写回和地址 stride 控制。
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
 *  2) 写回阶段（由 oa_fifo_req 与握手驱动）
 *     - 上游 FIFO 在需要写回某个 OA Tile 的数据时提示 oa_fifo_req。
 *     - 约定时序：当模块检测到 oa_fifo_req 被断言时，说明上游 FIFO 已取走当前 vec_valid_num_col 值并将开始传输数据；
 *       模块在“下一周期”执行两件事：
 *         a) 更新 vec_valid_num_col 为下一个 Tile 的有效列数（供上游 FIFO 在准备下一次传输时使用）；
 *         b) 驱动 write_oa_req=1 向外部控制器申请写回授权（write_oa_req 在下一周期提出）。
 *     - 在收到 write_oa_granted 之前，模块应保持 output_ready=0，表示尚不可接受脉动阵列的数据传输。
 *     - 若在后续周期内收到 write_oa_granted 授权，则模块进入写回传输阶段，此时可将 output_ready 置1 并开始接受 output_valid/output_data
 *       （在每个周期当 output_valid=1 且 output_ready=1 时，模块采样并通过 ICB 发起写请求）。
 *     - 写回完成后，模块置 write_done=1，并按需驱动 write_oa_req 寻求下一次写回授权。
 *
 *  3) 自动重触发阶段
 *     - 每次完成一个分块的写回后，模块可驱动 write_oa_req=1 申请下一次写回授权，外部控制器通过 write_oa_granted 授权。
 *     - 模块内部维护分块地址指针，每次写回时自动计算下一个分块的基地址；所有分块写回完成后停止申请。
 *
 *  4) 地址计算
 *     - 当前写入地址 = dst_base + row_index * dst_row_stride_b + col_index * element_size。
 *     - switch_row 信号用于控制行索引的递增。
 *
 * ICB 握手：
 *   - ICB 命令通道：模块作为 Master，驱动 icb_cmd_m，从端驱动 icb_cmd_s.ready。
 *   - ICB 响应通道：从端驱动 icb_rsp_s，模块驱动 icb_rsp_m.rsp_ready。
 *
 * 信号时序要点总结：
 *  - oa_fifo_req 被断言的周期说明上游正在请求写回；模块将在下一周期更新 vec_valid_num_col 并提出 write_oa_req。
 *  - 在外部授权（write_oa_granted）到来之前，output_ready 必须为0；授权到达后模块可以置 output_ready=1 并开始采样 output_valid/output_data。
 *  - 该时序保证上游 FIFO 能安全读取 vec_valid_num_col 并避免在未授权时向总线发送数据，从而避免总线冲突或丢失数据。
 */

`include "../inc/define.svh"
`include "../inc/icb_types.svh"

module oa_writer #(
    parameter int unsigned DATA_WIDTH = 8,  // 输出数据元素宽度
    parameter int unsigned VLEN = 16,       // 向量长度（阵列宽度）
    parameter int unsigned REG_WIDTH  = 32  // 配置寄存器宽度
) (
    // 时钟与复位
    input wire clk,   // 时钟信号
    input wire rst_n, // 异步复位，低有效

    // 配置控制接口
    input  wire                    init_cfg,          // 触发配置参数锁存
    input  wire                    oa_fifo_req,       // OA FIFO 请求写回
    output wire [$clog2(VLEN)-1:0] vec_valid_num_col, // 当前有效列数，发送给 oa_fifo 用于控制读出

    // 自动触发控制接口
    output wire write_oa_req,     // 申请写回授权（输出到外部控制器）
    input  wire write_oa_granted, // 外部控制器授权下一次写回（握手信号）

    // 配置寄存器（在 init_cfg 时锁存）
    input wire [REG_WIDTH-1:0] dst_base,          // 输出矩阵基地址（第一个分块）
    input wire [REG_WIDTH-1:0] dst_row_stride_b,  // 行间地址间距（字节）
    input wire [REG_WIDTH-1:0] k,                 // 输出矩阵列数
    input wire [REG_WIDTH-1:0] m,                 // 输出矩阵行数
    input wire [REG_WIDTH-1:0] tile_count,        // 总分块数量

    // 数据输入接口（来自脉动阵列）
    input  wire        output_valid,  // 输出数据有效信号
    input  wire        switch_row,    // 切换到下一行信号
    output wire        output_ready,  // 输出数据就绪信号
    input  wire [ 3:0] output_mask,   // 4位字节掩码
    input  wire [31:0] output_data,   // 32位输出数据

    // ICB 主接口（模块作为 Master）
    output icb_cmd_m_t icb_cmd_m,  // Master -> Slave: 命令有效载荷
    input  icb_cmd_s_t icb_cmd_s,  // Slave -> Master: 命令就绪
    input  icb_rsp_s_t icb_rsp_s,  // Slave -> Master: 响应有效载荷
    output icb_rsp_m_t icb_rsp_m,  // Master -> Slave: 响应就绪

    // 状态输出
    output wire write_done,   // 写回完成信号
    output wire oa_calc_over  // 所有分块写回完成信号
);

    // 状态定义
    typedef enum logic [1:0] {
        IDLE  = 2'b00,  // 空闲状态
        WRITE = 2'b01   // 写回数据状态
    } state_t;

    state_t     state;

    // ICB 命令与响应内部信号与连接
    // 使用寄存器存储可变字段，通过连续赋值将 size 字段固定为 2'b10
    icb_cmd_m_t icb_cmd_m_reg;  // 驱动可变字段的寄存器
    icb_cmd_m_t icb_cmd_m_wire;  // 由寄存器与常量 size 组合成的输出线网
    icb_rsp_m_t icb_rsp_m_wire;
    // 将 wire 输出到模块端口
    assign icb_cmd_m = icb_cmd_m_wire;
    assign icb_rsp_m = icb_rsp_m_wire;
    // 固定 size 字段为 2'b10，其余字段从寄存器取值
    assign icb_cmd_m_wire = '{
            icb_cmd_m_reg.valid,
            icb_cmd_m_reg.addr,
            icb_cmd_m_reg.read,
            icb_cmd_m_reg.wdata,
            icb_cmd_m_reg.wmask,
            2'b10
        };

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
            cfg_dst_base         <= '0;
            cfg_dst_row_stride_b <= '0;
            cfg_k                <= '0;
            cfg_m                <= '0;
        end else if (init_cfg) begin
            cfg_dst_base         <= dst_base;
            cfg_dst_row_stride_b <= dst_row_stride_b;
            cfg_k                <= k;
            cfg_m                <= m;
        end
    end

    // 状态机实现

endmodule
