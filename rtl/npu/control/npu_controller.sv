// 协调分块矩阵乘加的输入、驻留操作数、偏置、输出及任务完成握手。
//
// ==== 参数配置规则 ====
// 1. 基地址指针 (base pointers):
//    - lhs_base:  A 矩阵基地址，不允许为 0
//    - rhs_base:  B 矩阵基地址，不允许为 0
//    - dst_base:  C 矩阵基地址，不允许为 0
//    - bias_base: 偏置基地址，允许为 0（表示无偏置）
//
// 2. 矩阵维度 (dimensions):
//    - k: 输出矩阵与左操作数的行数，不允许为 0
//    - n: 矩阵乘法的归约长度，不允许为 0
//    - m: B 矩阵列数 / C 矩阵列数，不允许为 0
//
// 3. 行步长 (row strides):
//    - lhs_row_stride_b: A 矩阵行步长（字节），不允许为 0
//    - rhs_col_stride_b: B 矩阵行步长（字节），不允许为 0
//    - dst_row_stride_b: C 矩阵行步长（字节），不允许为 0
//
// 4. 量化参数 (quantization):
//    - 当 use_per_channel = 1 时，q_mult_pt 和 q_shift_pt 不允许为 0
//    - 当 use_per_channel = 0 时，无此限制（per-tensor 模式下可为 0）
//
// 5. 错误码 (err_code):
//    - 2'b00: 正常完成
//    - 2'b01: 无效/不支持的配置（非法参数组合）
//    - 2'b10: 必需资源缺失或指针为 0
//
module npu_controller #(
    parameter int unsigned WEIGHT_WIDTH = 16,  // 权重数据宽度
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
    input wire cfg_tiling_error /* 派生的矩阵分块配置不合法 */,
    input  wire cfg_dataflow_mode /* 数据流选择，零为权重驻留，一为输入驻留 */,  // 0: WS, 1: IS
    output wire sa_ready,       // 控制器就绪

    //==== Configuration Parameters ====
    // Base pointers
    input logic [REG_WIDTH-1:0] lhs_base /* 左操作数矩阵的首字节地址 */,  // A base         (MULT_LHS_PTR)
    input logic [REG_WIDTH-1:0] rhs_base /* 右操作数矩阵的首字节地址 */,  // B base (s8)    (MULT_RHS_PTR)
    input logic [REG_WIDTH-1:0] dst_base /* 输出矩阵的首字节地址 */,  // C base (s8)    (MULT_DST_PTR)
    input logic [REG_WIDTH-1:0] bias_base /* 偏置数组的首字节地址，零表示不使用偏置 */, // bias s32 (0=none)   (MULT_BIAS_PTR)

    // Quantization & zero-points
    input logic signed [REG_WIDTH-1:0] q_mult_pt /* 逐张量量化乘数或逐通道乘数表首地址 */,  // per-tensor mult     (MULT_DST_MULT)
    input logic signed [REG_WIDTH-1:0] q_shift_pt /* 逐张量量化移位量或逐通道移位表首地址 */,      // 量化移位配置寄存器 MULT_DST_SHIFT
    input logic use_per_channel /* 为每个输出通道读取独立量化参数 */,  // 1: per-channel; 0: per-tensor

    // Dimensions
    input logic [REG_WIDTH-1:0] k /* 输出矩阵行数 */,  // (MULT_LHS_ROWS)
    input logic [REG_WIDTH-1:0] n /* 矩阵乘法的归约长度 */,  // (MULT_RHS_ROWS)
    input logic [REG_WIDTH-1:0] m /* 输出矩阵列数 */,  // (MULT_RHS_COLS)

    // Row strides (all in BYTES)
    input logic [REG_WIDTH-1:0] lhs_row_stride_b /* 左操作数相邻行的字节步长 */,  // A row stride       (MULT_LHS_COLS_OFFSET)
    input logic [REG_WIDTH-1:0] dst_row_stride_b /* 输出矩阵相邻行的字节步长 */,  // C row stride       (MULT_ROW_ADDR_OFFSET)
    input logic [REG_WIDTH-1:0] rhs_col_stride_b /* 右操作数相邻存储行的字节步长 */,  // B row stride       (MULT_RHS_ROW_STRIDE)

    //==== Control Signals ====
    output reg                 init_cfg_ia,       // IA Loader 配置初始化（单拍）
    output reg                 init_cfg_weight,   // Kernel Loader 配置初始化（单拍）
    output reg                 init_cfg_bias,     // Bias Loader 配置初始化（单拍）
    output reg                 init_cfg_requant,  // Vec Requant 配置初始化（单拍）
    output reg                 init_cfg_oa,       // OA Writer 配置初始化（单拍）
    output reg                 use_16bits,        // 16位数据指示信号

    //==== Compute Core Interface ====
    input wire partial_sum_calc_over,  // legacy: 部分和计算结束
    input wire partial_sum_advance_ready = 1'b0 /* 部分和通路允许推进下一输入分组 */,
    input wire tile_calc_over,         // 新版 ps_buffer 最终 tile 输出结束

    //==== IA Loader Interface ====
    output reg  send_ia_trigger,  // IA发送触发
    input  wire ia_sending_done,  // IA发送完成
    input  wire ia_data_valid,    // IA数据有效
    input  wire ps_frame_ready = 1'b1 /* 部分和存储已准备接收当前帧 */,

    //==== Weight Loader Interface ====
    output reg  weight_commit /* 提交当前驻留操作数块用于阵列计算 */,
    output reg  send_weight_trigger,  // 权重发送触发
    input  wire weight_sending_done,  // 权重发送完成
    input  wire weight_data_valid,    // 权重数据有效
    input  wire weight_resident = 1'b0 /* 所需驻留操作数已保存于阵列 */,

    //==== Bias Loader Interface ====
    input  wire bias_valid,         // 偏置数据有效
    input  wire bias_sleep,         // 1: 当前 IA 组使用 ps_buffer 回灌，不需要 bias 阻塞

    // Requantization Interface
    input  wire quant_params_valid,  // 量化参数有效

    //==== FIFO Interface ====
    input wire fifo_full_flag,  // FIFO满信号

    //==== OA Writer Interface ====
    input  wire oa_calc_over,      // OA计算完成

    //==== Task Completion Handshake Interface ====
    output reg        done_valid,  // 任务完成有效信号
    input  wire       done_ready,  // 任务完成接收就绪信号
    output reg  [1:0] err_code   // 完成状态码: 00=正常, 01=配置错误, 10=资源缺失
);

    // 状态机定义
    typedef enum logic [3:0] {
        IDLE = 4'b0000,
        INIT = 4'b0001,
        WEIGHT_START = 4'b0010,
        IA_START = 4'b0011,
        WEIGHT_WAIT = 4'b0101,  // 在发送权重触发后等待发送完成
        IA_WAIT = 4'b0110,      // 在发送IA触发后等待发送完成（保证单拍脉冲）
        WAIT_DONE = 4'b0111,      // 等待完成握手
        ERROR = 4'b1000         // 参数配置错误状态
    } state_t;

    state_t current_state, next_state;
	    reg       cfg_16bits_ia_reg;  // 锁存的16位IA配置
	    reg       config_error;  // 参数配置错误标志
	    reg [1:0] error_type;  // 错误类型: 01=配置错误, 10=资源缺失
	    wire      bias_ready_for_compute;
	    logic [1:0] compute_tail_count;
	    wire      compute_tail_pending = compute_tail_count != 0;
	    wire      compute_tail_done;
	    wire      input_tail_ready;
	    wire      issue_ia_now;

    logic issue_data_ready, issue_aux_ready, issue_state_ready;
    logic issue_operand_ready, issue_bias_optional;
    (* keep = 1 *) logic issue_tail_quant_ready;
    // 零偏置地址表示不需要等待偏置数据，其他输入资源分别形成接收资格。
    assign bias_ready_for_compute = (bias_base == '0) || bias_sleep || bias_valid;
    assign issue_bias_optional = bias_base == '0;
    assign compute_tail_done = compute_tail_pending && partial_sum_calc_over;
    assign input_tail_ready = !compute_tail_pending ||
                              (compute_tail_count == 1 && compute_tail_done) ||
                              partial_sum_advance_ready;
    assign issue_data_ready = !oa_calc_over && ia_data_valid && !fifo_full_flag && !ia_sending_done;
    assign issue_operand_ready = !oa_calc_over && ia_data_valid && !ia_sending_done;
    // 计算尾部和量化参数先形成资格，偏置条件在末级参与计算发送。
    assign issue_tail_quant_ready = input_tail_ready && quant_params_valid;
    assign issue_aux_ready = issue_tail_quant_ready && bias_ready_for_compute;
    // 部分和、输出容量和偏置直接参与最终发送，其余条件提前形成。
    npu_ia_issue_select u_issue_requests (
        .i_ps_ready(ps_frame_ready), .i_data_ready(issue_operand_ready),
        .i_aux_ready(issue_tail_quant_ready), .i_state_ready(issue_state_ready),
        .i_output_full(fifo_full_flag),
        .i_bias_valid(bias_valid), .i_bias_optional(issue_bias_optional),
        .i_bias_reused(bias_sleep),
        .o_trigger(send_ia_trigger)
    );
    assign issue_ia_now = ps_frame_ready && issue_data_ready && issue_aux_ready;

    // 参数校验函数
    function automatic logic check_config_valid();
        logic ptr_error;
        logic dim_error;
        logic stride_error;
        logic quant_error;
        logic mode_error;

        // 检查必需指针（bias_base 允许为 0）
        ptr_error = (lhs_base == '0) || (rhs_base == '0) || (dst_base == '0);

        // 检查矩阵维度
        dim_error = cfg_tiling_error || (k == '0) || (n == '0) || (m == '0);

        // 检查行步长
        stride_error = (lhs_row_stride_b == '0) || (rhs_col_stride_b == '0) || (dst_row_stride_b == '0);

        // 检查量化参数（仅当 use_per_channel = 1 时）
        quant_error = use_per_channel && (q_mult_pt == '0) && (q_shift_pt == '0);

        mode_error = 1'b0;

        return ptr_error || dim_error || stride_error || quant_error || mode_error;
    endfunction

    // 确定错误类型
    function automatic logic [1:0] get_error_type();
        logic ptr_error;
        logic config_err;
        logic mode_error;

        // 必需资源缺失（指针错误）
        ptr_error = (lhs_base == '0) || (rhs_base == '0) || (dst_base == '0);

        // 配置错误（维度、步长、量化参数）
        config_err = cfg_tiling_error || (k == '0) || (n == '0) || (m == '0) ||
                     (lhs_row_stride_b == '0) || (rhs_col_stride_b == '0) || (dst_row_stride_b == '0) ||
                     (use_per_channel && ((q_mult_pt == '0) || (q_shift_pt == '0)));
        mode_error = 1'b0;

        if (ptr_error) return 2'b10;  // 资源缺失
        else if (config_err || mode_error) return 2'b01;  // 配置错误
        else return 2'b00;  // 无错误
    endfunction

    // 状态寄存器
	    always_ff @(posedge clk or negedge rst_n) begin
	        if (!rst_n) begin
	            current_state     <= IDLE;
	            cfg_16bits_ia_reg <= 1'b0;
	            config_error      <= 1'b0;
	            error_type        <= 2'b00;
	            compute_tail_count <= '0;
	        end else begin
	            current_state <= next_state;

		            if (current_state == IDLE && calc_start) begin
		                cfg_16bits_ia_reg <= cfg_16bits_ia;
	                // 在收到 calc_start 时检查参数配置
	                config_error      <= check_config_valid();
	                error_type        <= get_error_type();

		            end

	            if (current_state == INIT) begin
	                compute_tail_count <= '0;
	            end else begin
		                case ({send_ia_trigger, compute_tail_done})
                        2'b10: compute_tail_count <= compute_tail_count + 1'b1;
                        2'b01: compute_tail_count <= compute_tail_count - 1'b1;
                        default: ;
                    endcase

	            end
	        end
	    end

    // Loading fills the inactive bank. Selection follows physical input rows,
    // while activation admission retains PS, parameter, and output capacity checks.
    logic shadow_inflight, shadow_ready, resident_used;
    wire reuse_stationary_now = current_state==WEIGHT_START && weight_resident && !resident_used &&
                                 !oa_calc_over;
    wire commit_now = current_state==WEIGHT_START && shadow_ready &&
                      !oa_calc_over;
    wire prefetch_now = !weight_resident && (current_state==WEIGHT_START || current_state==IA_WAIT) &&
                        !shadow_inflight && !shadow_ready &&
                        weight_data_valid && !weight_sending_done && !oa_calc_over;
    always_comb begin
        next_state=current_state;
        case(current_state)
            IDLE: if(calc_start) next_state=check_config_valid()?ERROR:INIT;
            INIT: next_state=WEIGHT_START;
            WEIGHT_START: begin
                if(oa_calc_over) next_state=done_ready?IDLE:WAIT_DONE;
                else if(commit_now || reuse_stationary_now)
                    next_state=issue_ia_now ? IA_WAIT : IA_START;
            end
            IA_START: if(issue_ia_now) next_state=IA_WAIT;
            IA_WAIT: if(ia_sending_done) next_state=WEIGHT_START;
            WAIT_DONE, ERROR: if(done_ready) next_state=IDLE;
            default: next_state=IDLE;
        endcase
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            init_cfg_ia<=0; init_cfg_weight<=0; init_cfg_bias<=0;
            init_cfg_requant<=0; init_cfg_oa<=0; use_16bits<=0;
            send_weight_trigger<=0; weight_commit<=0;
            shadow_inflight<=0; shadow_ready<=0; resident_used<=0; err_code<=0;
        end else begin
            init_cfg_ia<=0; init_cfg_weight<=0; init_cfg_bias<=0;
            init_cfg_requant<=0; init_cfg_oa<=0;
            send_weight_trigger<=prefetch_now;
            weight_commit<=commit_now;
            if(prefetch_now) shadow_inflight<=1;
            if(shadow_inflight && weight_sending_done) begin
                shadow_inflight<=0; shadow_ready<=1;
            end
            if(commit_now) shadow_ready<=0;
            if(reuse_stationary_now) resident_used<=1;
            if(current_state==IDLE) err_code<=0;
            if(current_state==ERROR) err_code<=error_type;
            if(current_state==INIT) begin
                init_cfg_ia<=1; init_cfg_weight<=1; init_cfg_bias<=1;
                init_cfg_requant<=1; init_cfg_oa<=1;
                use_16bits<=cfg_16bits_ia_reg;
                shadow_inflight<=0; shadow_ready<=0; resident_used<=0;
            end
        end
    end
    assign issue_state_ready = current_state==IA_START || commit_now || reuse_stationary_now;
    assign sa_ready=current_state==IDLE;
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) done_valid<=0;
        else done_valid<=oa_calc_over || current_state==WAIT_DONE || current_state==ERROR;
    end
endmodule
