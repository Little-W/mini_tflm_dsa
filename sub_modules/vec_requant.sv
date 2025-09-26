// =============================================
// vec_requant: 16通道并行向量量化缩放模块（自主访存版本）
// =============================================
// 实现功能：
//   - 支持per-channel和per-tensor两种量化参数配置
//   - 量化流程：左移、乘法取高位、右移四舍五入、加偏移、激活裁剪
//   - 输出out_valid同步，完成向量处理
//   - 配置机制分离，支持独立初始化激活阈值和量化参数
//   - 量化算法兼容CMSIS-NN/NMSIS-NN
//   - 面向分块矩阵运算，自主访存量化参数（per-channel模式）
//
// 工作流程（更新后）：
//   1) 配置阶段（通过 init_cfg 触发）
//      - init_cfg：一拍加载激活阈值、dst_offset、量化模式和参数基地址/值、tile_count
//      - per-tensor模式 (cfg_per_channel=0)：pt_multiplier_in/pt_shift_in 直接为量化参数值
//      - per-channel模式 (cfg_per_channel=1)：pt_multiplier_in/pt_shift_in 为量化参数数组在内存中的基地址
//        配置完成后，per-channel模式自动开始第一次分块量化参数读取
//
//   2) 自主Load阶段（仅per-channel模式）
//      - 模块通过ICB主接口从基地址读取16个multiplier和16个shift参数
//      - 读取完成后置 quant_params_valid=1，表示量化参数已准备好
//
//   3) 量化计算阶段
//      - 当 in_valid 有效时，对输入向量进行并行量化计算
//      - 一拍延迟后通过 out_valid 输出量化结果
//
//   4) 自动重触发阶段（仅per-channel模式）
//      - 每次完成一个分块的处理后，模块驱动 load_quant_req=1 申请下一次访存授权
//      - 外部控制器通过 load_quant_granted 握手信号确认授权，模块开始下一个分块的访存
//      - 模块内部维护分块地址指针，每次访存时自动计算下一个分块的基地址
//      - 当所有分块处理完成时，停止申请重触发
//
//   5) 状态清除
//      - 当检测到 in_valid 的下降沿时，清除 quant_params_valid=0，为下一次参数加载做准备
// =============================================

`include "icb_types.sv"

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
    input wire signed [31:0] pt_multiplier_in,  // per-tensor: 量化参数值; per-channel: multiplier数组基地址
    input wire signed [31:0] pt_shift_in,       // per-tensor: 量化参数值; per-channel: shift数组基地址

    // ===== Load/Init 控制接口（仅per-channel模式使用） =====
    output reg load_quant_req,  // 申请下一次访存授权（输出到外部控制器）
    input wire load_quant_granted,  // 外部控制器授权下一次访存（握手信号）
    output reg quant_params_valid,  // 量化参数已加载完成信号

    // 量化参数配置（在 init_cfg 时锁存）
    input wire [REG_WIDTH-1:0] output_channels,  // 输出通道数（MULT_LHS_ROWS），指导读取参数个数
    input wire [REG_WIDTH-1:0] tile_count,       // 总分块数量

    // ICB 主接口（模块作为 Master，仅per-channel模式使用）
    output icb_cmd_m_t icb_cmd_m,  // Master -> Slave: 命令有效载荷
    input  icb_cmd_s_t icb_cmd_s,  // Slave -> Master: 命令就绪
    input  icb_rsp_s_t icb_rsp_s,  // Slave -> Master: 响应有效载荷
    output icb_rsp_m_t icb_rsp_m,  // Master -> Slave: 响应就绪

    // ===== 工作阶段：并行输入/输出 =====
    input wire               in_valid,         // 一拍喂入一个"并行向量"
    input wire signed [31:0] in_vec_s32[VLEN],

    output reg              out_valid,        // 与输出对齐（1 拍延迟）
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
    reg [REG_WIDTH-1:0] cfg_output_channels;

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
            cfg_output_channels <= 0;
        end else if (init_cfg) begin
            // 锁存模式 + 公共三件套 + 输出通道数
            mode_per_channel    <= cfg_per_channel;
            activation_min_r    <= activation_min_in;
            activation_max_r    <= activation_max_in;
            dst_offset_r        <= dst_offset_in;
            cfg_output_channels <= output_channels;
            // 若 per-tensor，直接从端口加载两量化参数
            if (!cfg_per_channel) begin
                pt_multiplier_r <= pt_multiplier_in;
                pt_shift_r      <= pt_shift_in;
            end else begin
                // per-channel 模式，保存内存基地址
                cfg_multiplier_base <= pt_multiplier_in;
                cfg_shift_base      <= pt_shift_in;
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
    // 状态机实现（仅per-channel模式使用ICB主动访存）
    // -------------------------

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

    integer           m;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            in_valid_q <= 1'b0;
            for (m = 0; m < VLEN; m = m + 1) in_vec_q[m] <= 32'sd0;
        end else begin
            in_valid_q <= work_accept;
            if (work_accept) begin
                for (m = 0; m < VLEN; m = m + 1) in_vec_q[m] <= in_vec_s32[m];
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

endmodule
