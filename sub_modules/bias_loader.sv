/*
 * bias_loader / bias_adder 偏置加载与加法控制器设计说明（自主访存版本）
 * ---------------------------------------------------------------------
 * 设计目标：
 *  - 本模块负责为分块矩阵计算（Tile化）自主读取偏置数据，并在需要时将偏置与输入数据做逐元素相加。
 *  - 支持模块内部计算每个 bias Tile 的访存地址并发起 ICB 读请求，读取完成后将偏置缓存并通知上层（bias_valid）。
 *  - 提供自动重触发逻辑：在每次 Tile 计算完成后按约定节拍申请下一批偏置的读取，以保持计算流水的连续性。
 *
 * 主要信号与语义：
 *  - init_cfg（单拍）：锁存配置参数，包括 need_bias、output_channels、bias_base 等。
 *  - bias_valid：指示当前偏置 Tile 已完成读取并可用于加法；在 tile_calc_start 触发时会被清零以准备下一次加载。
 *  - load_bias_req / load_bias_granted：模块在需要读取下一批偏置时提出请求，外部调度器通过 load_bias_granted 授权。
 *  - ia_loader_calc_done：来自 IA 加载/发送模块的 calc_done 信号，表示当前 IA Tile 在计算流中已达到某个阶段（用于触发偏置重载节拍）。
 *  - tile_calc_start：在上层开始对当前 Tile 的计算时，模块应清零 bias_valid（或在约定的时序点进行清理），以避免旧参数被误用。
 *
 * 地址生成与访存策略：
 *  - 模块在 init_cfg 时锁存偏置基地址 cfg_bias_base、输出通道数 cfg_output_channels 以及其它必要参数。
 *  - 对于每个 bias Tile，模块计算 tile_base = cfg_bias_base + tile_idx * tile_stride（具体 stride 与上层地址映射约定一致）。
 *  - 模块按行或按块发起 ICB 读请求，读取 tile 内有效的 bias 元素数（通常为 SIZE 或 output_channels 的子集）。
 *  - 读取完成后，偏置写入内部 bias_buffer[]，并置 bias_valid = 1。
 *
 * 自动重触发逻辑：
 *  - 本模块使用 ia_loader_calc_done 的下降沿作为重触发起点：当检测到 ia_loader_calc_done 从1到0的下降沿时，认为当前计算阶段进入了一个可统计的结束点。
 *  - 在该下降沿到来时模块开始计数一个固定的周期数（SIZE-1 个时钟周期），计数完毕后模块驱动 load_bias_req = 1 请求下一次偏置访存授权。
 *    * 该延迟计数用于给上层阵列和其它模块留下时间完成当前的写回/同步操作，避免直接在下降沿立即发起访存导致资源冲突。
 *  - 在收到 load_bias_granted 授权后，模块计算下一批偏置的基地址并进入 LOAD 状态发起 ICB 读事务。
 *  - 每次读取完成后置 bias_valid = 1，表示新偏置可用；若 need_bias=0，则模块可以跳过访存并将 bias_valid 保持为0或置为已准备好（视上层约定）。
 *
 * tile_calc_start 与 bias_valid 的关系：
 *  - tile_calc_start 表示上层开始对当前 Tile 的计算，模块应在该信号断言时清零 bias_valid（或在一个安全时序点清零），以确保随后的加法使用的是新加载的偏置。
 *  - 典型时序：bias_valid 在 LOAD 完成后置1；上层在检测 bias_valid=1 后开始计算；在 tile_calc_start（下一个Tile开始）时，bias_valid 被清零以准备下一轮加载。
 *
 * 边界与补零策略：
 *  - 对于最后一个 Tile 中通道数不足 SIZE 的情形，模块应在内部对多余位置填充0或其它约定填充值，以保证输出数据宽度一致并避免越界读取。
 *  - 对于完全超出范围的行/列，可在地址计算阶段跳过实际访存以节省带宽；跳过后仍需在输出阶段用填充值替代相应位置。
 *
 * ICB 与错误处理：
 *  - 模块作为 ICB Master 发起读命令，驱动 icb_cmd_m；从端通过 icb_cmd_s.ready/ icb_rsp_s 提供握手与数据。
 *  - 模块需检测响应中的错误标志，若发生错误应进入错误处理路径并上报或重试（视系统约定）。
 *
 * 推荐实现要点：
 *  - 在模块内部维护 ia_calc_done_d 延迟寄存以检测下降沿，基于该下降沿启动 delay_counter；delay_counter 到达预定值后置 load_bias_req。
 *  - 维护 tile_idx、cur_bias_addr 与 load_count，用于逐块计算与发起 ICB 事务。
 *  - 确保 bias_valid 在时钟域内同步，并由 tile_calc_start 在安全时刻清零，避免竞态。
 *
 * 行为总结：
 *  1) init_cfg：锁存配置；若 need_bias=1，模块准备首次访存。
 *  2) WAIT_FOR_IA_DONE：监测 ia_loader_calc_done 的下降沿并开始 delay 计数。
 *  3) REQUEST_LOAD：delay 计数完成后驱动 load_bias_req，等待 load_bias_granted。
 *  4) LOAD：授权到位后发起 ICB 读事务并缓存偏置，读完置 bias_valid=1。
 *  5) USE_AND_CLEAR：上层在使用偏置后在 tile_calc_start 时清零 bias_valid，模块准备下一轮。
 */

`include "../inc/define.svh"
`include "../inc/icb_types.svh"

module bias_loader #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned REG_WIDTH = 32     // 配置寄存器宽度
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
    input wire need_bias,  // 是否需要偏置加法
    input wire [REG_WIDTH-1:0] bias_base,  // 偏置数据基地址（第一个分块）

    input wire [REG_WIDTH-1:0] k,  // 输入激活矩阵列数（RHS_COLS）
    input wire [REG_WIDTH-1:0] m,  // 输出矩阵列数（LHS_COLS）

    // ICB 主接口（模块作为 Master）
    output icb_cmd_m_t icb_cmd_m,  // Master -> Slave: 命令有效载荷
    input  icb_cmd_s_t icb_cmd_s,  // Slave -> Master: 命令就绪
    input  icb_rsp_s_t icb_rsp_s,  // Slave -> Master: 响应有效载荷
    output icb_rsp_m_t icb_rsp_m,  // Master -> Slave: 响应就绪

    input wire ia_loader_calc_done,  // 来自 ia_loader 的 calc_done 信号
    input wire tile_calc_start,  // 触发当前tile的计算开始
    output reg bias_valid,  // 偏置数据已准备好信号
    // 输出信号
    output reg  [DATA_WIDTH-1:0]       data_out[SIZE]    // 输出数据向量
);
    parameter DELAY_CYCLES = SIZE-1; // 延迟周期数

    // 状态定义
    typedef enum logic [2:0] {
        IDLE = 3'b000,                // 空闲状态
        WAIT_FOR_IA_DONE = 3'b001,    // 等待 IA 计算完成（检测下降沿）
        REQUEST_LOAD = 3'b010,        // 启动延迟计数并请求加载
        WAIT_FOR_LOAD_GRANT = 3'b011, // 等待外部访存授权
        LOAD = 3'b100                 // 读取偏置数据状态
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

    // 偏置缓冲区（单缓冲区存储）
    reg     [    DATA_WIDTH-1:0] bias_buffer         [SIZE];
    integer                      i;

    // 锁存的配置信号
    reg                          cfg_need_bias;
    reg     [     REG_WIDTH-1:0] cfg_bias_base;
    // 额外锁存的矩阵尺寸与延迟周期
    reg     [     REG_WIDTH-1:0] cfg_k;
    reg     [     REG_WIDTH-1:0] cfg_m;
    reg     [$clog2(SIZE+1)-1:0] cfg_delay_cycles;

    // 计数器与状态寄存器
    reg     [$clog2(SIZE+1)-1:0] load_count;
    reg     [     REG_WIDTH-1:0] cur_addr;
    reg     [$clog2(SIZE+1)-1:0] delay_counter; // 延迟计数器

    // 配置参数锁存
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_need_bias       <= 0;
            cfg_bias_base       <= '0;
            cfg_k               <= '0;
            cfg_m               <= '0;
            // 默认延迟周期为 SIZE-1（若 SIZE==0 则为0）
            cfg_delay_cycles    <= (SIZE > 0) ? (SIZE-1) : '0;
        end else if (init_cfg) begin
            cfg_need_bias       <= need_bias;
            cfg_bias_base       <= bias_base;
            // 锁存矩阵维度与衍生延迟周期
            cfg_k               <= k;
            cfg_m               <= m;
            cfg_delay_cycles    <= (SIZE > 0) ? (SIZE-1) : '0;
        end
    end

    // 偏置加载与计算状态机
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state           <= IDLE;
            load_bias_req   <= 0;
            bias_valid      <= 0;
            cur_addr        <= '0;
            load_count      <= '0;
        end else begin
            case (state)
                IDLE: begin
                    // 等待配置与 IA 计算完成信号
                    if (init_cfg && cfg_need_bias) begin
                        // 锁存配置后，计算首个偏置块的地址
                        cur_addr <= cfg_bias_base;
                        // 进入等待 IA 计算完成的状态
                        state <= WAIT_FOR_IA_DONE;
                    end
                end

                WAIT_FOR_IA_DONE: begin
                    // 监测 ia_loader_calc_done 的下降沿
                    if (ia_loader_calc_done_d1 && !ia_loader_calc_done) begin
                        // 下降沿到来，开始计数延迟周期
                        delay_counter <= 0;
                        state <= REQUEST_LOAD;
                    end
                end

                REQUEST_LOAD: begin
                    // 延迟计数完成后，驱动 load_bias_req 请求访存授权
                    if (delay_counter == DELAY_CYCLES-1) begin
                        load_bias_req <= 1;
                        state <= WAIT_FOR_LOAD_GRANT;
                    end else begin
                        delay_counter <= delay_counter + 1;
                    end
                end

                WAIT_FOR_LOAD_GRANT: begin
                    // 等待外部授权信号 load_bias_granted
                    if (load_bias_granted) begin
                        // 授权到位，发起 ICB 读事务
                        state <= LOAD;
                    end
                end

                LOAD: begin
                    // ICB 读事务进行中
                    if (icb_rsp_s.rsp_valid && icb_rsp_m.rsp_ready) begin
                        // 读取完成，缓存偏置数据
                        // 使用锁存的 cfg_m 作为输出通道数，且不超过内部缓冲区 SIZE
                        for (i = 0; i < cfg_m && i < SIZE; i = i + 1) begin
                            bias_buffer[i] <= icb_rsp_s.rsp_rdata[i];
                        end
                        bias_valid <= 1;
                        state <= IDLE;
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

    // 生成 ia_loader_calc_done 的延迟信号，用于检测下降沿
    reg ia_loader_calc_done_d1;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ia_loader_calc_done_d1 <= 0;
        end else begin
            ia_loader_calc_done_d1 <= ia_loader_calc_done;
        end
    end

endmodule
