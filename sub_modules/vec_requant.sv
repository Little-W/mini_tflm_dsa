/*
 * vec_requant: 并行向量量化缩放模块（支持 per-tensor 与 per-channel，带自主访存能力）
 * ============================================================================
 * 设计目标：
 *  - 对向量数据并行执行量化缩放（左移、乘法高位取整、右移四舍五入、加偏移、激活裁剪），兼容 CMSIS-NN/NMSIS-NN 算法。
 *  - 支持 per-tensor 模式（全通道共享 multiplier/shift）与 per-channel 模式（每通道独立 multiplier/shift）。
 *  - 在 per-channel 模式下模块可作为 ICB Master 自主发起访存，按分块读取每组通道的量化参数并在读取完成后通知可用。
 *  - 模块能够根据 OA Tile 的尺寸（由上层矩阵维度 k,m 等推断）自动计算每次需要读取的 multiplier/shift 的内存基地址与访问次数。
 *  - 支持自动重触发：当上一个 OA Tile 的计算完成时（由 in_valid 的下降沿或上层信号指示），模块自动申请并读取下一批量化参数，保证计算流水连续。
 *
 * 主要信号与语义：
 *  - init_cfg (一拍)：锁存配置，包括量化模式(per-tensor/per-channel)、activation_min/max、dst_offset、multiplier/shift（或其基地址）、输出通道数等。
 *  - cfg_per_channel (1=per-channel,0=per-tensor)：决定参数来源。
 *  - per-tensor 模式：multiplier_in/shift_in 直接作为量化参数值，用于整个向量处理。
 *  - per-channel 模式：multiplier_in/shift_in 被视为内存基地址，模块将按块读取一组通道的 multiplier/shift。
 *
 * 访存/地址推断策略（per-channel）：
 *  - 模块在 init_cfg 时已知输出通道数（即 OA Tile 的列宽或其它上层提供的尺寸），据此自动计算每次需要读取的通道数（通常为 VLEN）和地址偏移。
 *  - 例如：每次读取 VLEN 个 multiplier/shift；下一组的地址 = 当前基地址 + VLEN * sizeof(param)
 *  - 模块维护内部指针（current_param_addr、load_count 等）并在每次授权后发起连续 ICB 读事务以加载所需参数。
 *  - 读取完成后，模块将参数写入内部 ch_multiplier_r[]/ch_shift_r[] 并置 quant_params_valid = 1。
 *
 * 自动重触发与完成检测：
 *  - OA Tile 完成检测：模块通过捕捉 in_valid 的下降沿判断一次 OA Tile 的向量计算已完成（上层不再输入该Tile的数据），此时视为该Tile的计算周期结束。
 *  - 在检测到 OA Tile 完成后，若处于 per-channel 模式且还有剩余参数未加载，模块自动驱动 load_quant_req = 1 申请下一次访存授权。
 *  - 外部控制器通过 load_quant_granted 授权后，模块开始下一个分块参数的读取。
 *  - 每次参数加载完成后，模块将 quant_params_valid 置为 1，指示量化参数可用于后续计算。
 *  - quant_params_valid 的有效期：由模块在参数加载完成后保持为 1，直到收到 tile_calc_start（上层信号，或其它约定的计算开始/清除信号）使其被清零，为下一次参数加载做准备。
 *    * 注：当前实现也可在 in_valid 的下降沿配合使用来清除或触发状态机，具体时序应以上层控制流程为准。
 *
 * 时序与握手要点：
 *  - load_quant_req / load_quant_granted：模块在需要新一组参数时提出请求，外部通过 load_quant_granted 授权以避免总线冲突或仲裁。
 *  - ICB 读事务应正确处理响应握手（icb_cmd_s.ready、icb_rsp_s）和错误标志；出现错误时应进入错误处理或回退流程。
 *  - quant_params_valid 与 out_valid/计算流程需要清晰定义的握手关系：在 quant_params_valid=1 且参数被使用后，上层可通过 tile_calc_start 将 quant_params_valid 清零并开始下一轮的参数加载节拍。
 *
 * 行为总结（按阶段）：
 *  1) init_cfg：锁存配置；若为 per-channel 模式，模块自动准备并可立即申请第一次参数加载。
 *  2) LOAD（仅 per-channel）：模块根据内部指针与OA尺寸推断出读地址与长度，发起 ICB 读事务；读完置 quant_params_valid=1。
 *  3) COMPUTE：若 in_valid 上升沿喂入数据并且 quant_params_valid=1，模块按并行通道执行量化；out_valid 与输出对齐。
 *  4) TILE_COMPLETE：当检测到 in_valid 的下降沿（或上层通过 tile_calc_start 明确指示）表示此 OA Tile 的计算已结束；模块据此自动驱动 load_quant_req 以准备下一组参数。
 *
 * 实现注意事项：
 *  - 为避免竞态，quant_params_valid 在加载完成的同一个时钟域内置1，并由 tile_calc_start 在确定安全的时刻清零。
 *  - 对于通道数不足 VLEN 的最后一组参数，应在内部用合理的默认值或复制策略填充，或在使用时对超出范围的通道进行保护。
 *  - 建议在仿真/验证中分别验证 per-tensor 与 per-channel 的时序、以及 load_quant_req/granted 的交互。
 */

`include "../inc/define.svh"
`include "../inc/icb_types.svh"

module vec_requant #(
    parameter integer VLEN = 16,
    parameter integer REG_WIDTH = 32
) (
    input wire clk,
    input wire rstn,

    // ===== 模式 & 公共配置一拍加载 =====
    input wire init_cfg,  // 高电平一拍：加载激活阈值和dst_offset
    input wire cfg_per_channel,  // 1=per-channel, 0=per-tensor
    input wire signed [31:0] activation_min_in,
    input wire signed [31:0] activation_max_in,
    input wire signed [31:0] dst_offset_in,

    // 复用信号：per-tensor时为参数值，per-channel时为内存基地址
    input wire signed [31:0] multiplier_in,  // per-tensor: 量化参数值; per-channel: multiplier数组基地址
    input wire signed [31:0] shift_in,       // per-tensor: 量化参数值; per-channel: shift数组基地址

    // ===== Load/Init 控制接口（仅per-channel模式使用） =====
    output reg  load_quant_req,      // 申请下一次访存授权（输出到外部控制器）
    input  wire load_quant_granted,  // 外部控制器授权下一次访存（握手信号）
    output reg  quant_params_valid,  // 量化参数已加载完成信号，multiplier等读完后拉高，in_valid上升沿后拉低

    // 矩阵尺寸与分块配置（在 init_cfg 时被锁存）
    input wire [REG_WIDTH-1:0] k,  // 输入激活矩阵列数（RHS_COLS）
    input wire [REG_WIDTH-1:0] m,  // 输出矩阵列数（LHS_COLS）

    // ICB 主接口（模块作为 Master，仅per-channel模式使用）
    output icb_ext_cmd_m_t icb_cmd_m,  // Master -> Slave: 命令有效载荷
    output icb_ext_wr_m_t icb_wr_m, // Master -> Slave: 写数据有效载荷（本模块读取为主，通常不使用）
    input icb_ext_cmd_s_t icb_cmd_s,  // Slave -> Master: 命令就绪
    input icb_ext_wr_s_t icb_wr_s,  // Slave -> Master: 写数据就绪
    input icb_ext_rsp_s_t icb_rsp_s,  // Slave -> Master: 响应有效载荷
    output icb_ext_rsp_m_t icb_rsp_m,  // Master -> Slave: 响应就绪

    // ===== 工作阶段：并行输入/输出 =====
    input wire               in_valid,         // 一拍喂入一个"并行向量"
    input wire signed [31:0] in_vec_s32[VLEN],

    output reg              out_valid,        // 与输出对齐
    output reg signed [7:0] out_vec_s8[VLEN]
);

    // -------------------------
    // 状态定义
    // -------------------------
    typedef enum logic [1:0] {
        IDLE = 2'b00,  // 空闲状态
        LOAD = 2'b01   // 读取量化参数状态
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

    // -------------------------
    // 模式与公共参数寄存（init_cfg 一拍装载）
    // -------------------------
    reg mode_per_channel;
    reg signed [31:0] activation_min_r, activation_max_r, dst_offset_r;
    reg signed [31:0] pt_multiplier_r, pt_shift_r;
    reg signed [31:0] cfg_multiplier_base, cfg_shift_base;

    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            mode_per_channel    <= 1'b0;
            activation_min_r    <= -128;
            activation_max_r    <= 127;
            dst_offset_r        <= 0;
            pt_multiplier_r     <= 0;
            pt_shift_r          <= 0;
            cfg_multiplier_base <= 0;
            cfg_shift_base      <= 0;
        end else if (init_cfg) begin
            // 锁存模式 + 公共三件套 + 输出通道数
            mode_per_channel    <= cfg_per_channel;
            activation_min_r    <= activation_min_in;
            activation_max_r    <= activation_max_in;
            dst_offset_r        <= dst_offset_in;
            // 若 per-tensor，直接从端口加载两量化参数
            if (!cfg_per_channel) begin
                pt_multiplier_r <= multiplier_in;
                pt_shift_r      <= shift_in;
            end else begin
                // per-channel 模式，保存内存基地址
                cfg_multiplier_base <= multiplier_in;
                cfg_shift_base      <= shift_in;
            end
        end
    end

    // -------------------------
    // per-channel 量化参数存储
    // -------------------------
    reg signed [31:0] ch_multiplier_r[VLEN];
    reg signed [31:0] ch_shift_r[VLEN];

    // 计数器与状态寄存器
    reg [$clog2(VLEN*2+1)-1:0] load_count;
    reg [REG_WIDTH-1:0] cur_addr;
    reg loading_multipliers;  // 1: 正在加载multipliers; 0: 正在加载shifts

    // in_valid 边沿检测用于清除 quant_params_valid
    reg in_valid_d1;
    wire in_valid_falling_edge;
    assign in_valid_falling_edge = in_valid_d1 & ~in_valid;

    // -------------------------
    // NMSIS/CMSIS-NN 等价函数
    // -------------------------
    function automatic signed [31:0] left_shift_apply;
        input signed [31:0] val, shift_s;
        reg [5:0] lsh;
        begin
            lsh              = (shift_s > 0) ? shift_s[5:0] : 6'd0;
            left_shift_apply = (lsh == 0) ? val : (val <<< lsh);
        end
    endfunction

    function automatic signed [31:0] doubling_high_mult_round;
        input signed [31:0] a, m;
        reg signed [63:0] prod, prod2, adj;
        begin
            prod                     = $signed(a) * $signed(m);
            prod2                    = prod <<< 1;  // 2*a*m
            adj                      = prod2 + 64'sh0000_0000_4000_0000;  // +2^30
            doubling_high_mult_round = adj >>> 31;  // round((a*m)/2^31)
        end
    endfunction

    function automatic signed [31:0] divide_by_power_of_two_round;
        input signed [31:0] val;
        input [5:0] rsh;
        reg signed [31:0] add;
        begin
            if (rsh == 0) divide_by_power_of_two_round = val;
            else begin
                add = (val >= 0) ? (32'sd1 <<< (rsh - 1)) : ((32'sd1 <<< (rsh - 1)) - 32'sd1);
                divide_by_power_of_two_round = (val + add) >>> rsh;
            end
        end
    endfunction

    // -------------------------
    // 并行计算：一拍输入 -> 一拍后并行输出
    // -------------------------
    wire              work_mode = (state == IDLE) && (!load_quant_req);
    wire              work_accept = in_valid & work_mode;

    reg               in_valid_q;
    reg signed [31:0] in_vec_q                                         [VLEN];

    integer           mm;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            in_valid_q <= 1'b0;
            for (mm = 0; mm < VLEN; mm = mm + 1) in_vec_q[mm] <= 32'sd0;
        end else begin
            in_valid_q <= work_accept;
            if (work_accept) begin
                for (mm = 0; mm < VLEN; mm = mm + 1) in_vec_q[mm] <= in_vec_s32[mm];
            end
        end
    end

    integer j;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            out_valid <= 1'b0;
            for (j = 0; j < VLEN; j = j + 1) out_vec_s8[j] <= 8'sd0;
        end else begin
            out_valid <= in_valid_q;
            if (in_valid_q) begin
                for (j = 0; j < VLEN; j = j + 1) begin : LANE
                    reg signed [31:0] cur_m, cur_s, a_shifted, high_mul, rq;
                    reg [ 5:0] right_s;
                    reg [31:0] cur_s_neg;

                    // 选参：per-channel or per-tensor
                    cur_m     = mode_per_channel ? ch_multiplier_r[j] : pt_multiplier_r;
                    cur_s     = mode_per_channel ? ch_shift_r[j] : pt_shift_r;
                    cur_s_neg = ~cur_s + 1'b1;
                    right_s   = (cur_s < 0) ? cur_s_neg[5:0] : 6'd0;

                    // 量化流程
                    a_shifted = left_shift_apply(in_vec_q[j], cur_s);
                    high_mul  = doubling_high_mult_round(a_shifted, cur_m);
                    rq        = divide_by_power_of_two_round(high_mul, right_s);

                    rq        = rq + dst_offset_r;
                    if (rq < activation_min_r) rq = activation_min_r;
                    if (rq > activation_max_r) rq = activation_max_r;

                    if (rq > 32'sd127) out_vec_s8[j] <= 8'sd127;
                    else if (rq < -32'sd128) out_vec_s8[j] <= -8'sd128;
                    else out_vec_s8[j] <= rq[7:0];
                end
            end
        end
    end

    // -------------------------
    // 状态机实现（仅per-channel模式使用ICB主动访存）
    // -------------------------

endmodule
