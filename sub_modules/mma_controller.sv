`include "define.svh"
`include "icb_types.svh"

// MMA(Matrix Multiply Accumulate) Controller
module mma_controller #(
    parameter int unsigned WEIGHT_WIDTH = 8,   // 权重数据宽度
    parameter int unsigned DATA_WIDTH   = 16,  // IA数据宽度
    parameter int unsigned SIZE         = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH    = 32,  // 总线宽度
    parameter int unsigned REG_WIDTH    = 32   // 寄存器宽度
) (
    //==== Clock & Control Signals ====
    input  wire clk,            // 时钟
    input  wire rst_n,          // 异步复位，低有效
    input  wire calc_start,     // 计算开始
    input  wire cfg_16bits_ia,  // 使用16位IA数据
    output wire sa_ready,       // 控制器就绪

    //==== Control Signals ====
    output reg [          2:0] icb_sel,           // ICB多路复用器选择信号
    output reg                 init_cfg_ia,       // IA Loader 配置初始化（单拍）
    output reg                 init_cfg_weight,   // Kernel Loader 配置初始化（单拍）
    output reg                 init_cfg_bias,     // Bias Loader 配置初始化（单拍）
    output reg                 init_cfg_requant,  // Vec Requant 配置初始化（单拍）
    output reg                 init_cfg_oa,       // OA Writer 配置初始化（单拍）
    output reg                 use_16bits,        // 16位数据指示信号
    output reg [REG_WIDTH-1:0] tile_count,        // 分块计数信号

    //==== Compute Core Interface ====
    input wire partial_sum_calc_over,  // 部分和计算结束

    //==== IA Loader Interface ====
    input  wire load_ia_req,      // IA加载请求
    output reg  load_ia_granted,  // IA加载授权
    output reg  send_ia_trigger,  // IA发送触发
    input  wire ia_sending_done,  // IA发送完成
    input  wire ia_data_valid,    // IA数据有效

    //==== Weight Loader Interface ====
    input  wire load_weight_req,      // 权重加载请求
    output reg  load_weight_granted,  // 权重加载授权
    output reg  send_weight_trigger,  // 权重发送触发
    input  wire weight_sending_done,  // 权重发送完成
    input  wire weight_data_valid,    // 权重数据有效

    //==== Bias Loader Interface ====
    input  wire load_bias_req,      // 偏置加载请求
    output reg  load_bias_granted,  // 偏置加载授权
    input  wire bias_valid,         // 偏置数据有效

    // Requantization Interface
    input  wire load_quant_req,      // 申请下一次量化参数访存
    output wire load_quant_granted,  // 量化参数访存授权
    input  wire quant_params_valid,  // 量化参数有效

    //==== FIFO Interface ====
    input wire fifo_full_flag,  // FIFO满信号

    //==== OA Writer Interface ====
    input  wire write_oa_req,      // OA写回请求
    output reg  write_oa_granted,  // OA写回授权
    input  wire write_done,        // 写回完成
    input  wire oa_calc_over       // OA计算完成
);

    // 状态机定义
    typedef enum logic [2:0] {
        IDLE = 3'b000,
        INIT = 3'b001,
        WEIGHT_START = 3'b010,
        IA_START = 3'b011,
        WAIT_PARTIAL_SUM = 3'b100,
        WEIGHT_WAIT = 3'b101,  // 新增：在发送权重触发后等待发送完成
        IA_WAIT = 3'b110  // 新增：在发送IA触发后等待发送完成（保证单拍脉冲）
    } state_t;

    state_t current_state, next_state;
    reg cfg_16bits_ia_reg;  // 锁存的16位IA配置

    // 状态寄存器
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            current_state     <= IDLE;
            cfg_16bits_ia_reg <= 1'b0;
        end else begin
            current_state <= next_state;
            if (current_state == IDLE && calc_start) begin
                cfg_16bits_ia_reg <= cfg_16bits_ia;
            end
        end
    end

    // 状态转换逻辑
    always_comb begin
        next_state = current_state;
        case (current_state)
            IDLE: begin
                if (calc_start) begin
                    next_state = INIT;
                end
            end

            INIT: begin
                next_state = WEIGHT_START;
            end

            WEIGHT_START: begin
                if (oa_calc_over) begin
                    next_state = IDLE;
                end else if (weight_data_valid && !weight_sending_done) begin
                    // 当有权重数据且尚未发送完成，发出触发并进入等待状态（保证触发为单拍）
                    next_state = WEIGHT_WAIT;
                end
            end

            // 新增等待状态：在发出触发后等待 weight_sending_done 完成
            WEIGHT_WAIT: begin
                if (oa_calc_over) begin
                    next_state = IDLE;
                end else if (weight_sending_done) begin
                    next_state = IA_START;
                end
            end

            IA_START: begin
                // 如果满足发送条件，发出一次触发并进入 IA_WAIT（保证触发为单拍）
                if (ia_data_valid && bias_valid && quant_params_valid && 
                         !fifo_full_flag && !ia_sending_done) begin
                    next_state = IA_WAIT;
                end
            end

            // 新增 IA_WAIT：在发出 IA 触发后等待 ia_sending_done 完成
            IA_WAIT: begin
                if (ia_sending_done) begin
                    next_state = WAIT_PARTIAL_SUM;
                end
            end

            WAIT_PARTIAL_SUM: begin
                if (partial_sum_calc_over) begin
                    next_state = WEIGHT_START;
                end
            end

            default: begin
                next_state = IDLE;
            end
        endcase
    end

    // 输出逻辑
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            init_cfg_ia         <= 1'b0;
            init_cfg_weight     <= 1'b0;
            init_cfg_bias       <= 1'b0;
            init_cfg_requant    <= 1'b0;
            init_cfg_oa         <= 1'b0;
            use_16bits          <= 1'b0;
            send_weight_trigger <= 1'b0;
            send_ia_trigger     <= 1'b0;
        end else begin
            // 默认值
            init_cfg_ia         <= 1'b0;
            init_cfg_weight     <= 1'b0;
            init_cfg_bias       <= 1'b0;
            init_cfg_requant    <= 1'b0;
            init_cfg_oa         <= 1'b0;
            send_weight_trigger <= 1'b0;  // 默认清零，保证脉冲行为
            send_ia_trigger     <= 1'b0;  // 默认清零，保证脉冲行为

            case (current_state)
                INIT: begin
                    // 初始化所有模块（单拍脉冲）
                    init_cfg_ia      <= 1'b1;
                    init_cfg_weight  <= 1'b1;
                    init_cfg_bias    <= 1'b1;
                    init_cfg_requant <= 1'b1;
                    init_cfg_oa      <= 1'b1;
                    use_16bits       <= cfg_16bits_ia_reg;
                end

                WEIGHT_START: begin
                    // 仅在 WEIGHT_START 一拍内发出发送触发，之后转到 WEIGHT_WAIT 等待完成 -> 保证单拍脉冲
                    if (weight_data_valid && !weight_sending_done) begin
                        send_weight_trigger <= 1'b1;
                    end
                end

                WEIGHT_WAIT: begin
                    // 等待 weight_sending_done 完成，不重复发出触发
                end

                IA_START: begin
                    // 仅在 IA_START 一拍内发出发送触发，之后转到 IA_WAIT 等待完成 -> 保证单拍脉冲
                    if (ia_data_valid && bias_valid && quant_params_valid && 
                        !fifo_full_flag && !ia_sending_done) begin
                        send_ia_trigger <= 1'b1;
                    end
                end

                IA_WAIT: begin
                    // 等待 ia_sending_done 完成，不重复发出触发
                end

                default: begin
                end
            endcase
        end
    end

    // sa_ready信号
    assign sa_ready = (current_state == IDLE);

    // 实例化ICB仲裁器
    icb_arbiter u_icb_arbiter (
        .clk       (clk),
        .rst_n     (rst_n),
        // IA Loader
        .s0_req    (load_ia_req),
        .s0_granted(load_ia_granted),
        .s0_done   (ia_data_valid),
        // Kernel Loader
        .s1_req    (load_weight_req),
        .s1_granted(load_weight_granted),
        .s1_done   (weight_data_valid),
        // Bias Loader
        .s2_req    (load_bias_req),
        .s2_granted(load_bias_granted),
        .s2_done   (bias_valid),
        // Vec Requant
        .s3_req    (load_quant_req),
        .s3_granted(load_quant_granted),
        .s3_done   (quant_params_valid),
        // OA Writer
        .s4_req    (write_oa_req),
        .s4_granted(write_oa_granted),
        .s4_done   (write_done),
        // ICB选择
        .icb_sel   (icb_sel)
    );

endmodule
