/*
 * bias_loader 偏置加载模块设计说明（自主访存版本，基于 partial_sum_calc_over / tile_calc_over）
 * ---------------------------------------------------------------------
 * 设计目标：
 *  - 模块为每个 OA Tile 的“第一次部分和”提供偏置数据；同一 OA Tile 的后续部分和偏置恒为0。
 *  - 不实现总线访存细节，仅实现控制、状态与 data_out 选择逻辑。
 * 关键时序与信号（已修正）：
 *  - partial_sum_calc_over：一次部分和结束后触发；在该脉冲到来后，应将偏置输出置0（本 OA Tile 内后续 IA/W tile 不输出偏置），直到当前 OA Tile 结束。
 *  - tile_calc_over：当前 OA Tile 计算结束；随后到来的 tile_calc_start 所对应的那次部分和被视为“某个 OA Tile 的第一个 IA/W tile”，该次可以输出偏置（如果偏置已准备好）。
 *  - tile_calc_start：计算开始；在其后一个时钟周期，将 data_out 连接为：
 *      • 若本次开始的是“第一个 IA/W tile 且偏置已准备好”，则输出 bias_buffer；
 *      • 否则输出全0。
 *  - bias_valid：表示 bias_buffer 已经就绪（一次预取完成后置1；在消耗于“第一次部分和”开始时清0，等待下一次预取）。
 *
 * 补充说明（与原有时序一致，作为明确约定）：
 *  - 仅在某个 OA Tile 流程中的“第一个 IA tile 与第一个 W tile”上输出偏置，其余 IA/W tile 输出应为 0。
 *  - 当 partial_sum_calc_over 上升沿到来时，表示下一次启动的部分和属于某个 OA Tile 的第一个 IA/W tile（模块可据此准备/预取偏置）。
 *  - 当 tile_calc_over 上升沿到来时，表示当前 OA Tile 流程结束；随后到来的 tile_calc_start 不应再输出此前 OA Tile 的偏置，直到再次由 partial_sum_calc_over 标记新的第一个 IA/W。
 *  - tile_calc_start 作为实际输出时刻：若该次被判定为“第一个 IA/W 并且偏置已准备好”，则在下一拍将 bias_buffer 放到 data_out；否则放 0。
 *
 * 预取策略（无总线实现占位）：
 *  - 在 partial_sum_calc_over 上升沿，若 need_bias 且当前没有就绪的偏置（bias_valid=0），则提出 load_bias_req。
 *  - 收到 load_bias_granted 后撤销请求；总线细节未实现，这里直接置 bias_valid=1 作为占位。
 * 地址生成与访存策略：
 *  - 偏置数据地址由 bias_base 加上 tile 索引偏移自动生成。
 *  - 访存请求由 partial_sum_calc_over 上升沿自动触发，授权后 bias_valid 置位。
 *  - 访存细节未实现，实际数据填充由 bias_buffer 占位。
 *
 * 自动重触发逻辑：
 *  - 每次 partial_sum_calc_over 触发后，若需要偏置且未就绪，则自动提出 load_bias_req。
 *  - tile_calc_over 结束后，下一次 tile_calc_start 视为新 OA Tile 的第一次部分和。
 *
 * 边界与补零策略：
 *  - 对于最后一个 Tile 中通道数不足 SIZE 的情形，模块应在内部对多余位置填充0或其它约定填充值，以保证输出数据宽度一致并避免越界读取。
 *  - 对于完全超出范围的行/列，可在地址计算阶段跳过实际访存以节省带宽；跳过后仍需在输出阶段用填充值替代相应位置。
 *
 * 行为总结：
 *  1) init_cfg：锁存配置；若 need_bias=1，模块准备首次访存。
 *  2) partial_sum_calc_over：部分和计算结束，自动触发下一轮偏置预取。
 *  3) tile_calc_over：OA Tile 计算结束，下一次 tile_calc_start 进入新 Tile。
 *  4) tile_calc_start：计算开始，下一拍 data_out 输出偏置或0，取决于是否为第一次部分和。
 *  5) bias_valid：表示偏置已准备好，消耗后清零，等待下一次预取。
 */

`include "../inc/define.svh"
`include "../inc/icb_types.svh"

module bias_loader #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned REG_WIDTH = 32
) (
    // 时钟与复位
    input wire clk,   // 时钟信号
    input wire rst_n, // 异步复位，低有效

    // 配置控制接口
    input wire init_cfg,  // 触发配置参数锁存

    // Load 控制接口
    output reg  load_bias_req,     // 申请下一次访存授权（输出到外部控制器）
    input  wire load_bias_granted, // 外部控制器授权下一次访存（握手信号）

    // 偏置配置参数（在 init_cfg 时锁存）
    input wire                 need_bias,  // 是否需要偏置加法
    input wire [REG_WIDTH-1:0] bias_base,  // 偏置数据基地址（第一个分块）

    input wire [REG_WIDTH-1:0] k,  // 输入激活矩阵列数（RHS_COLS）
    input wire [REG_WIDTH-1:0] m,  // 输出矩阵列数（LHS_COLS）

    // ICB 主接口（模块作为 Master, 扩展三通道）
    output icb_ext_cmd_m_t icb_cmd_m,  // Master -> Slave: 命令有效载荷
    output icb_ext_wr_m_t icb_wr_m, // Master -> Slave: 写数据有效载荷（本模块读取为主，通常不使用）
    input icb_ext_cmd_s_t icb_cmd_s,  // Slave -> Master: 命令就绪
    input icb_ext_wr_s_t icb_wr_s,  // Slave -> Master: 写数据就绪
    input icb_ext_rsp_s_t icb_rsp_s,  // Slave -> Master: 响应有效载荷
    output icb_ext_rsp_m_t icb_rsp_m,  // Master -> Slave: 响应就绪

    input wire partial_sum_calc_over,  // 来自compute_core的当前部分和计算结束指示
    input wire tile_calc_over,  // 来自compute_core的当前OA Tile计算结束指示
    input wire tile_calc_start,  // 触发当前tile的计算开始
    output reg bias_valid,  // 偏置数据已准备好信号
    // 输出信号
    output wire [DATA_WIDTH-1:0] data_out[SIZE]  // 输出数据向量
);
    // 状态定义
    // ICB 命令与响应内部信号与连接（保留旧打包并映射到新接口）
    icb_cmd_m_t icb_cmd_m_reg;  // 驱动可变字段的寄存器
    icb_cmd_m_t icb_cmd_m_wire;  // 由寄存器与常量 size 组合成的输出线网
    // 固定 size 字段为 2'b10，其余字段从寄存器取值
    assign icb_cmd_m_wire = '{
            icb_cmd_m_reg.valid,
            icb_cmd_m_reg.addr,
            icb_cmd_m_reg.read,
            icb_cmd_m_reg.wdata,
            icb_cmd_m_reg.wmask,
            2'b10
        };

    // 新端口映射
    assign icb_cmd_m.valid = icb_cmd_m_wire.valid;
    assign icb_cmd_m.addr = icb_cmd_m_wire.addr;
    assign icb_cmd_m.read = icb_cmd_m_wire.read;
    assign icb_cmd_m.len = 3'd0;  // 默认单拍

    assign icb_wr_m.w_valid = 1'b0;  // 本模块通常只读
    assign icb_wr_m.wdata = '0;
    assign icb_wr_m.wmask = '0;

    // 直接使用 icb_ext rsp 接口，表明 Master 可以接收响应（占位为可用）
    assign icb_rsp_m = '{ rsp_ready: 1'b1 };

    // 偏置缓冲区（单缓冲区存储）
    reg [DATA_WIDTH-1:0] bias_buffer[SIZE];
    integer i;

    // 锁存的配置信号
    reg cfg_need_bias;
    reg [REG_WIDTH-1:0] cfg_bias_base;
    reg [REG_WIDTH-1:0] cfg_k;
    reg [REG_WIDTH-1:0] cfg_m;

    // 输出保持寄存器
    reg [DATA_WIDTH-1:0] data_out_reg[SIZE];

    // 计算阶段标志
    reg is_first_ps;  // 是否为当前 OA Tile 的第一次部分和
    reg tile_calc_start_d;
    reg tile_calc_over_d;
    reg partial_sum_calc_over_d;

    // 新增：标志表示“下一次是 OA Tile 流程中的第一个 IA/W tile”
    reg first_ia_w_flag;

    wire tile_start_pulse = tile_calc_start & ~tile_calc_start_d;
    wire tile_over_pulse = tile_calc_over & ~tile_calc_over_d;
    wire ps_over_pulse = partial_sum_calc_over & ~partial_sum_calc_over_d;

    // 在 tile_calc_start 捕获当次是否需要使用偏置，并由 first_ia_w_flag 限制
    reg use_bias_this_run;
    reg arm_output_update;  // 在 tile_calc_start 后一拍拉高1拍，用于更新输出寄存器

    // 配置参数锁存与复位初始化
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_need_bias           <= 1'b0;
            cfg_bias_base           <= '0;
            cfg_k                   <= '0;
            cfg_m                   <= '0;
            bias_valid              <= 1'b0;

            is_first_ps             <= 1'b1;
            tile_calc_start_d       <= 1'b0;
            tile_calc_over_d        <= 1'b0;
            partial_sum_calc_over_d <= 1'b0;
            use_bias_this_run       <= 1'b0;
            arm_output_update       <= 1'b0;

            load_bias_req           <= 1'b0;

            for (i = 0; i < SIZE; i = i + 1) begin
                bias_buffer[i]  <= '0;
                data_out_reg[i] <= '0;
            end
        end else begin
            tile_calc_start_d       <= tile_calc_start;
            tile_calc_over_d        <= tile_calc_over;
            partial_sum_calc_over_d <= partial_sum_calc_over;

            if (init_cfg) begin
                cfg_need_bias <= need_bias;
                cfg_bias_base <= bias_base;
                cfg_k         <= k;
                cfg_m         <= m;
                bias_valid    <= 1'b0;
                // 初始化 first_ia_w_flag（配置变动时清除）
                first_ia_w_flag <= 1'b0;
            end

            // 每个 OA Tile 的第一次部分和标记
            if (tile_over_pulse || init_cfg) begin
                is_first_ps <= 1'b1;
            end else if (tile_start_pulse) begin
                is_first_ps <= 1'b0;  // 开始后，其余部分和不再使用偏置
            end

            // 管理 first_ia_w_flag（修正：tile_calc_over 表示 OA Tile 结束，下一次为第一个 IA/W；partial_sum_calc_over 表示部分和结束，随后禁止偏置输出）
            if (tile_over_pulse) begin
                // OA Tile 结束：下次启动属于新的 OA Tile 的第一个 IA/W tile
                first_ia_w_flag <= 1'b1;
            end
            if (ps_over_pulse) begin
                // 部分和完成：在当前 OA Tile 内后续 IA/W 不再输出偏置
                first_ia_w_flag <= 1'b0;
            end

            // 在 tile_calc_start 捕获是否需要使用偏置（仅当配置需要、是 OA Tile 的第一次部分和，且 first_ia_w_flag 有效）
            if (tile_start_pulse) begin
                use_bias_this_run <= (cfg_need_bias && is_first_ps && first_ia_w_flag);
            end

            // tile_calc_start 后一拍更新 data_out
            arm_output_update <= tile_start_pulse;
            if (arm_output_update) begin
                if (use_bias_this_run) begin
                    for (i = 0; i < SIZE; i = i + 1) begin
                        data_out_reg[i] <= bias_buffer[i];
                    end
                end else begin
                    for (i = 0; i < SIZE; i = i + 1) begin
                        data_out_reg[i] <= '0;
                    end
                end
            end

            // 预取请求：OA Tile 结束时为下一 OA Tile 准备偏置
            if (tile_over_pulse && cfg_need_bias && !bias_valid) begin
                load_bias_req <= 1'b1;
            end

            // 授权后撤销请求；总线未实现，这里直接置 bias_valid=1 作为占位
            if (load_bias_req && load_bias_granted) begin
                load_bias_req <= 1'b0;
                bias_valid    <= 1'b1;  // TODO: 实际应在读回完成后置位
                // TODO: 通过总线将读取到的数据写入 bias_buffer[i]
            end

            // 在“第一次部分和”开始时消费当前偏置并清除 valid，等待下一轮预取
            if (tile_start_pulse && use_bias_this_run) begin
                bias_valid <= 1'b0;
                // 偏置已被消费，清除 first_ia_w_flag，确保同一 OA Tile 不重复输出偏置
                first_ia_w_flag <= 1'b0;
            end
        end
    end

    // data_out 连接
    genvar gi;
    generate
        for (gi = 0; gi < SIZE; gi = gi + 1) begin : g_out
            assign data_out[gi] = data_out_reg[gi];
        end
    endgenerate

endmodule
