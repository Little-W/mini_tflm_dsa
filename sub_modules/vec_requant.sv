// =============================================
// vec_requant: 16通道并行向量量化缩放模块
// =============================================
// 实现功能：
//   - 支持16路s32输入向量，下一拍输出16路s8量化结果
//   - 量化流程：左移、乘法取高位、右移四舍五入、加偏移、激活裁剪
//   - 支持per-channel和per-tensor两种量化参数配置
//   - 输出out_valid同步，done指示一次向量处理完成
//   - 配置机制分离，支持独立初始化激活阈值和量化参数
//   - 量化算法兼容CMSIS-NN/NMSIS-NN
//
// 配置说明：
//   - cfg_load_common：一拍加载激活阈值和dst_offset，per-tensor时加载量化参数
//   - cfg_init_q：per-channel时连续写入16个multiplier和16个shift，per-tensor时写入1组参数
//   - 初始化阶段下降沿清零计数器并锁存配置
// =============================================

module vec_requant #(
    parameter integer VLEN = 16
) (
    input wire clk,
    input wire rstn,

    // ===== 模式 & 公共配置一拍加载 =====
    input  wire                 cfg_load_common,       // 高电平一拍：加载三件套；若 per-tensor 也加载两量化参，并锁存模式
    input  wire                 cfg_per_channel,       // 1=per-channel, 0=per-tensor（在 cfg_load_common 一拍锁存）
    input wire signed [31:0] activation_min_in,
    input wire signed [31:0] activation_max_in,
    input wire signed [31:0] dst_offset_in,
    // 若 per-tensor，还需同时经端口加载这两个量化参数
    input wire signed [31:0] pt_multiplier_in,
    input wire signed [31:0] pt_shift_in,

    // ===== 初始化：仅在 per-channel=1 时有效 =====
    input wire               cfg_init_quant,  // 高电平期间按顺序写入：16×mult -> 16×shift
    input wire               data_valid,
    input wire signed [31:0] data_in_s32,

    // ===== 工作阶段：并行输入/输出 =====
    input wire               in_valid,             // 一拍喂入一个“并行向量”
    input wire signed [31:0] in_vec_s32[0:VLEN-1],

    output reg              out_valid,            // 与输出对齐（1 拍延迟）
    output reg signed [7:0] out_vec_s8[0:VLEN-1]
);

    // -------------------------
    // 模式与公共参数寄存（cfg_load_common 一拍装载）
    // -------------------------
    reg mode_per_channel;
    reg signed [31:0] activation_min_r, activation_max_r, dst_offset_r;
    reg signed [31:0] pt_multiplier_r, pt_shift_r;

    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            mode_per_channel <= 1'b0;
            activation_min_r <= -128;
            activation_max_r <= 127;
            dst_offset_r     <= 0;
            pt_multiplier_r  <= 0;
            pt_shift_r       <= 0;
        end else if (cfg_load_common) begin
            // 锁存模式 + 公共三件套
            mode_per_channel <= cfg_per_channel;
            activation_min_r <= activation_min_in;
            activation_max_r <= activation_max_in;
            dst_offset_r     <= dst_offset_in;
            // 若 per-tensor，直接从端口加载两量化参数
            if (!cfg_per_channel) begin
                pt_multiplier_r <= pt_multiplier_in;
                pt_shift_r      <= pt_shift_in;
            end
        end
    end

    // -------------------------
    // per-channel 量化参数：只有在 mode_per_channel=1 & cfg_init_quant=1 时接收
    // 顺序：16×multiplier[0..15] 接着 16×shift[0..15]
    // -------------------------
    reg signed [31:0] ch_multiplier_r[0:VLEN-1];
    reg signed [31:0] ch_shift_r     [0:VLEN-1];

    reg               initq_q;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) initq_q <= 1'b0;
        else initq_q <= cfg_init_quant;
    end
    // 复位串行写计数器：在 cfg_init_quant 下降沿 或 模式切换/加载时都可归零
    wire          reset_body_cnt = (initq_q && !cfg_init_quant) | cfg_load_common;

    reg     [5:0] body_cnt;  // 0..32
    integer       ii;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            body_cnt <= 6'd0;
            for (ii = 0; ii < VLEN; ii = ii + 1) begin
                ch_multiplier_r[ii] <= 0;
                ch_shift_r[ii]      <= 0;
            end
        end else if (reset_body_cnt) begin
            body_cnt <= 6'd0;
        end else if (cfg_init_quant && mode_per_channel) begin
            if (data_valid) begin
                if (body_cnt < VLEN) begin
                    ch_multiplier_r[body_cnt] <= data_in_s32;
                end else if (body_cnt < 2 * VLEN) begin
                    ch_shift_r[body_cnt-VLEN] <= data_in_s32;
                end
                body_cnt <= body_cnt + 6'd1;
            end
        end
    end

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
    wire              work_mode = ~(cfg_init_quant | cfg_load_common);
    wire              work_accept = in_valid & work_mode;

    reg               in_valid_q;
    reg signed [31:0] in_vec_q                                    [0:VLEN-1];

    integer           k;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            in_valid_q <= 1'b0;
            for (k = 0; k < VLEN; k = k + 1) in_vec_q[k] <= 32'sd0;
        end else begin
            in_valid_q <= work_accept;
            if (work_accept) begin
                for (k = 0; k < VLEN; k = k + 1) in_vec_q[k] <= in_vec_s32[k];
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
