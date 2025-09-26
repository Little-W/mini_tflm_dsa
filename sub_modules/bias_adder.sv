/*
 * bias_adder 偏置加法控制器设计说明（自主访存版本）
 * ------------------------------------------------------------
 * 功能概述:
 *  本模块负责面向分块矩阵运算，从外部存储器自主读取偏置数据，并在收到 calc_done_i 信号时对输入数据进行偏置加法。
 *  模块采用自主驱动模式：init_cfg 后自动开始第一次分块访存，每次完成后申请下一次访存授权。
 *  模块通过 ICB 总线作为主设备主动发起读请求并接收响应数据，采用单缓冲区结构。
 *
 * 工作流程:
 *  1) 配置阶段（通过 init_cfg 触发）
 *     - 当 init_cfg 有效时，模块锁存配置：need_bias、output_channels、bias_base、tile_count。
 *     - output_channels: 输出通道数，指导读取偏置数据的个数
 *     - bias_base: 偏置数据基地址（第一个分块）
 *     - need_bias: 是否需要偏置加法
 *     - tile_count: 总分块数量
 *     - 配置完成后，模块自动开始第一次分块偏置数据读取。
 *
 *  2) 自主Load阶段
 *     - 模块自动通过 ICB 主接口从当前分块基地址开始连续读取偏置数据。
 *     - 总共读取 output_channels 个偏置数据。
 *     - 读取完成后，模块置 bias_valid=1，表示偏置数据已准备好。
 *
 *  3) 偏置加法（被动触发）
 *     - 模块持续监听 calc_done_i 信号。当 calc_done_i 有效且 bias_valid=1 且 cfg_need_bias=1 时，执行偏置加法。
 *     - 偏置加法：data_out[i] = data_in[i] + bias_buffer[i]，同时驱动 output_valid_o=1。
 *     - 如果 cfg_need_bias=0，则直接透传：data_out[i] = data_in[i]。
 *
 *  4) 自动重触发阶段
 *     - 每次完成一个分块的处理后，模块驱动 load_bias_req=1 申请下一次访存授权。
 *     - 外部控制器通过 load_bias_granted 握手信号确认授权，模块开始下一个分块的访存。
 *     - 模块内部维护分块地址指针，每次访存时自动计算下一个分块的基地址。
 *     - 当所有分块处理完成时，停止申请重触发。
 *
 *  5) 状态清除
 *     - 当检测到 calc_done_i 的下降沿时，清除 bias_valid=0，为下一次偏置加载做准备。
 *
 *  ICB 握手：
 *   - ICB 命令通道：模块作为 Master，驱动 icb_cmd_m，从端驱动 icb_cmd_s.ready。
 *   - ICB 响应通道：从端驱动 icb_rsp_s，模块驱动 icb_rsp_m.rsp_ready。
 */

`include "icb_types.sv"

module bias_adder #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned BUS_WIDTH = 32,    // 总线宽度
    parameter int unsigned REG_WIDTH = 32     // 配置寄存器宽度
) (
    // 时钟与复位
    input  wire                        clk,               // 时钟信号
    input  wire                        rst_n,             // 异步复位，低有效

    // 配置控制接口
    input  wire                        init_cfg,          // 触发配置参数锁存

    // Load 控制接口
    output reg                         load_bias_req,     // 申请下一次访存授权（输出到外部控制器）
    input  wire                        load_bias_granted, // 外部控制器授权下一次访存（握手信号）

    // 偏置配置参数（在 init_cfg 时锁存）
    input  wire                        need_bias,         // 是否需要偏置加法
    input  wire [REG_WIDTH-1:0]        output_channels,   // 输出通道数（MULT_LHS_ROWS），指导读取偏置个数
    input  wire [REG_WIDTH-1:0]        bias_base,         // 偏置数据基地址（第一个分块）
    input  wire [REG_WIDTH-1:0]        tile_count,        // 总分块数量

    // ICB 主接口（模块作为 Master）
    output icb_cmd_m_t                  icb_cmd_m,         // Master -> Slave: 命令有效载荷
    input  icb_cmd_s_t                  icb_cmd_s,         // Slave -> Master: 命令就绪
    input  icb_rsp_s_t                  icb_rsp_s,         // Slave -> Master: 响应有效载荷
    output icb_rsp_m_t                  icb_rsp_m,         // Master -> Slave: 响应就绪

    // 输入数据
    input  wire [DATA_WIDTH-1:0]       data_in[SIZE],     // 输入数据向量
    input  wire                        calc_done_i,       // 计算完成信号，下降沿触发 bias_valid 清除

    // 输出信号
    output reg  [DATA_WIDTH-1:0]       data_out[SIZE],    // 输出数据向量（偏置加法后或直接透传）
    output reg                         output_valid_o,    // 输出数据有效信号
    output reg                         bias_valid         // 偏置数据已准备好信号
);

    // 状态定义
    typedef enum logic [1:0] {
        IDLE = 2'b00,     // 空闲状态
        LOAD = 2'b01      // 读取偏置数据状态
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

    // 偏置缓冲区（单缓冲区存储）
    reg [DATA_WIDTH-1:0] bias_buffer [SIZE];
    integer i;

    // 锁存的配置信号
    reg cfg_need_bias;
    reg [REG_WIDTH-1:0] cfg_output_channels;
    reg [REG_WIDTH-1:0] cfg_bias_base;

    // 计数器与状态寄存器
    reg [$clog2(SIZE+1)-1:0] load_count;
    reg [REG_WIDTH-1:0] cur_addr;

    // calc_done_i 边沿检测
    reg calc_done_i_d1;
    wire calc_done_i_falling_edge;
    assign calc_done_i_falling_edge = calc_done_i_d1 & ~calc_done_i;

    // 偏置加法组合逻辑
    always_comb begin
        for (i = 0; i < SIZE; i = i + 1) begin
            if (calc_done_i && bias_valid && cfg_need_bias) begin
                data_out[i] = data_in[i] + bias_buffer[i];
            end else if (calc_done_i) begin
                data_out[i] = data_in[i];
            end else begin
                data_out[i] = '0;
            end
        end
        output_valid_o = calc_done_i && bias_valid;
    end

    // 配置参数锁存
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_need_bias <= 0;
            cfg_output_channels <= '0;
            cfg_bias_base <= '0;
        end else if (init_cfg) begin
            cfg_need_bias <= need_bias;
            cfg_output_channels <= output_channels;
            cfg_bias_base <= bias_base;
        end
    end

    // 状态机实现
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            load_bias_ready <= 1;
            bias_valid <= 0;
            calc_done_i_d1 <= 0;
            // 清空 ICB 输出结构
            icb_cmd_m_reg <= '{default: '0};
            icb_rsp_m_wire <= '{default: '0};
            load_count <= 0;
            cur_addr <= '0;
            
            // 清空偏置缓冲区
            for (i = 0; i < SIZE; i = i + 1) begin
                bias_buffer[i] <= '0;
            end
        end else begin
            // 更新 calc_done_i 延迟信号用于边沿检测
            calc_done_i_d1 <= calc_done_i;

            // 默认保持某些信号
            icb_cmd_m_reg <= '{default: '0};
            icb_rsp_m_wire <= '{default: '0};

            // 检测 calc_done_i 下降沿，清除 bias_valid
            if (calc_done_i_falling_edge) begin
                bias_valid <= 0;
            end

            case (state)
                IDLE: begin
                    load_bias_ready <= 1;

                    if (load_bias_req && load_bias_ready) begin
                        // 初始化读取指针与计数
                        cur_addr <= cfg_bias_base;
                        load_count <= 0;
                        load_bias_ready <= 0;
                        state <= LOAD;
                    end
                end

                LOAD: begin
                    // 在 LOAD 状态，作为 ICB Master 发起读命令，并接收响应
                    // 填充寄存器字段（size 由连续赋值固定）
                    icb_cmd_m_reg.valid <= 1;
                    icb_cmd_m_reg.addr  <= cur_addr;
                    icb_cmd_m_reg.read  <= 1;
                    icb_cmd_m_reg.wdata <= '0;
                    icb_cmd_m_reg.wmask <= '0;

                    // 如果命令被从端接受，推进地址
                    if (icb_cmd_s.ready && icb_cmd_m_reg.valid) begin
                        cur_addr <= cur_addr + (DATA_WIDTH / 8); // 假设按字节寻址
                    end

                    // 表明主设备愿意接收响应
                    icb_rsp_m_wire.rsp_ready <= 1;

                    if (icb_rsp_s.rsp_valid && icb_rsp_m_wire.rsp_ready) begin
                        // 将读取的数据存储到偏置缓冲区
                        bias_buffer[load_count] <= icb_rsp_s.rsp_rdata[DATA_WIDTH-1:0];
                        load_count <= load_count + 1;

                        // 使用 cfg_output_channels 控制读取的偏置个数
                        if (load_count + 1 == cfg_output_channels) begin
                            // 读取完成，返回 IDLE 并指示偏置数据已准备好
                            state <= IDLE;
                            bias_valid <= 1;
                            load_bias_ready <= 1;
                        end
                    end
                end

                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end

endmodule