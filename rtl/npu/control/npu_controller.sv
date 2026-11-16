// NPU task controller for tiled matrix multiply/accumulate execution.
//
// ==== 参数配置规则 ====
// 1. 基地址指针 (base pointers):
//    - lhs_base:  A 矩阵基地址，不允许为 0
//    - rhs_base:  B 矩阵基地址，不允许为 0
//    - dst_base:  C 矩阵基地址，不允许为 0
//    - bias_base: 偏置基地址，允许为 0（表示无偏置）
//
// 2. 矩阵维度 (dimensions):
//    - k: A 矩阵行数 / B 矩阵列数，不允许为 0
//    - n: B 矩阵行数 / C 矩阵行数，不允许为 0
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
    input wire cfg_tiling_error,
    input  wire cfg_dataflow_mode,  // 0: WS, 1: IS
    output wire sa_ready,       // 控制器就绪

    //==== Configuration Parameters ====
    // Base pointers
    input logic [REG_WIDTH-1:0] lhs_base,  // A base         (MULT_LHS_PTR)
    input logic [REG_WIDTH-1:0] rhs_base,  // B base (s8)    (MULT_RHS_PTR, N x K row-major)
    input logic [REG_WIDTH-1:0] dst_base,  // C base (s8)    (MULT_DST_PTR)
    input logic [REG_WIDTH-1:0] bias_base, // bias s32 (0=none)   (MULT_BIAS_PTR)

    // Quantization & zero-points
    input logic signed [REG_WIDTH-1:0] q_mult_pt,  // per-tensor mult     (MULT_DST_MULT)
    input logic signed [REG_WIDTH-1:0] q_shift_pt,      // per-tensor rshift   (MULT_DST_SHIFT, +N => >>N)
    input logic use_per_channel,  // 1: per-channel; 0: per-tensor

    // Dimensions
    input logic [REG_WIDTH-1:0] k,  // (MULT_LHS_ROWS)
    input logic [REG_WIDTH-1:0] n,  // (MULT_RHS_ROWS)
    input logic [REG_WIDTH-1:0] m,  // (MULT_RHS_COLS)

    // Row strides (all in BYTES)
    input logic [REG_WIDTH-1:0] lhs_row_stride_b,  // A row stride       (MULT_LHS_COLS_OFFSET)
    input logic [REG_WIDTH-1:0] dst_row_stride_b,  // C row stride       (MULT_ROW_ADDR_OFFSET)
    input logic [REG_WIDTH-1:0] rhs_col_stride_b,  // B row stride       (MULT_RHS_ROW_STRIDE)

    //==== Control Signals ====
    output reg                 init_cfg_ia,       // IA Loader 配置初始化（单拍）
    output reg                 init_cfg_weight,   // Kernel Loader 配置初始化（单拍）
    output reg                 init_cfg_bias,     // Bias Loader 配置初始化（单拍）
    output reg                 init_cfg_requant,  // Vec Requant 配置初始化（单拍）
    output reg                 init_cfg_oa,       // OA Writer 配置初始化（单拍）
    output reg                 use_16bits,        // 16位数据指示信号

    //==== Compute Core Interface ====
    input wire partial_sum_calc_over,  // legacy: 部分和计算结束
    input wire partial_sum_advance_ready = 1'b0,
    input wire tile_calc_over,         // 新版 ps_buffer 最终 tile 输出结束

    //==== IA Loader Interface ====
    output reg  send_ia_trigger,  // IA发送触发
    input  wire ia_sending_done,  // IA发送完成
    input  wire ia_data_valid,    // IA数据有效

    //==== Weight Loader Interface ====
    output reg  weight_commit,
    output reg  send_weight_trigger,  // 权重发送触发
    input  wire weight_sending_done,  // 权重发送完成
    input  wire weight_data_valid,    // 权重数据有效

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
	    logic     compute_tail_pending;
	    wire      compute_tail_done;
	    wire      weight_safe_to_send;
	    wire      issue_weight_now;
	    wire      issue_ia_now;
`ifndef SYNTHESIS
    bit       ctrl_trace_en;
    bit       util_trace_en;
    bit       util_summary_en;
    logic     util_active;
    longint unsigned util_op_id;
    longint unsigned util_active_cycles;
    longint unsigned util_weight_start_cycles;
    longint unsigned util_weight_wait_cycles;
    longint unsigned util_ia_start_cycles;
    longint unsigned util_ia_wait_cycles;
    longint unsigned util_wait_done_cycles;
    longint unsigned util_stall_weight_tail_cycles;
    longint unsigned util_stall_weight_data_cycles;
    longint unsigned util_stall_weight_done_cycles;
    longint unsigned util_stall_ia_data_cycles;
    longint unsigned util_stall_bias_cycles;
    longint unsigned util_stall_quant_cycles;
    longint unsigned util_stall_fifo_cycles;
    longint unsigned util_stall_ia_done_cycles;
    longint unsigned util_tail_pending_cycles;
    longint unsigned util_tail_done_count;
    longint unsigned util_weight_trigger_count;
    longint unsigned util_ia_trigger_count;
    longint unsigned util_sum_active_cycles;
    longint unsigned util_sum_weight_start_cycles;
    longint unsigned util_sum_weight_wait_cycles;
    longint unsigned util_sum_ia_start_cycles;
    longint unsigned util_sum_ia_wait_cycles;
    longint unsigned util_sum_wait_done_cycles;
    longint unsigned util_sum_stall_weight_tail_cycles;
    longint unsigned util_sum_stall_weight_data_cycles;
    longint unsigned util_sum_stall_weight_done_cycles;
    longint unsigned util_sum_stall_ia_data_cycles;
    longint unsigned util_sum_stall_bias_cycles;
    longint unsigned util_sum_stall_quant_cycles;
    longint unsigned util_sum_stall_fifo_cycles;
    longint unsigned util_sum_stall_ia_done_cycles;
    longint unsigned util_sum_tail_pending_cycles;
    longint unsigned util_sum_tail_done_count;
    longint unsigned util_sum_weight_trigger_count;
    longint unsigned util_sum_ia_trigger_count;

    initial begin
        ctrl_trace_en = 1'b0;
        util_trace_en = 1'b0;
        util_summary_en = 1'b0;
        if ($test$plusargs("NPU_CTRL_TRACE")) ctrl_trace_en = 1'b1;
        if ($test$plusargs("NPU_UTIL_TRACE")) util_trace_en = 1'b1;
        if ($test$plusargs("NPU_UTIL_SUMMARY")) util_summary_en = 1'b1;
    end
`endif

    // A zero bias address is the architectural encoding for "no bias".
    // In that case there is no DMA payload to wait for.
    assign bias_ready_for_compute = (bias_base == '0) || bias_sleep || bias_valid;
	    assign compute_tail_done = compute_tail_pending && partial_sum_calc_over;
	    assign weight_safe_to_send = !compute_tail_pending || compute_tail_done;
	    assign issue_weight_now = !oa_calc_over &&
	                              weight_safe_to_send &&
	                              weight_data_valid &&
	                              !weight_sending_done;
	    assign issue_ia_now = !oa_calc_over &&
	                          ia_data_valid &&
	                          bias_ready_for_compute &&
	                          quant_params_valid &&
	                          !fifo_full_flag &&
	                          !ia_sending_done;

`ifndef SYNTHESIS
    wire util_start_event = (current_state == IDLE) && calc_start;
    wire util_finish_event = util_active && (current_state != IDLE) && (next_state == IDLE);
`endif

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
	            compute_tail_pending <= 1'b0;
	        end else begin
	            current_state <= next_state;
`ifndef SYNTHESIS
            if (ctrl_trace_en && (current_state != next_state)) begin
		                $display("[%0t] CTRL state %0d -> %0d wt_valid=%0d wt_done=%0d ia_valid=%0d ia_done=%0d bias_ok=%0d q_valid=%0d fifo_full=%0d tail=%0d tail_done=%0d oa_over=%0d",
		                         $time, current_state, next_state,
		                         weight_data_valid, weight_sending_done,
		                         ia_data_valid, ia_sending_done,
		                         bias_ready_for_compute, quant_params_valid,
		                         fifo_full_flag, compute_tail_pending,
		                         compute_tail_done, oa_calc_over);
		            end
`endif
		            if (current_state == IDLE && calc_start) begin
		                cfg_16bits_ia_reg <= cfg_16bits_ia;
	                // 在收到 calc_start 时检查参数配置
	                config_error      <= check_config_valid();
	                error_type        <= get_error_type();
`ifndef SYNTHESIS
	                if (ctrl_trace_en) begin
	                    $display("Simulation time: %t", $time);
	                    $display("NPU Controller Start: lhs_base=%h, rhs_base=%h, dst_base=%h, bias_base=%h", lhs_base, rhs_base, dst_base, bias_base);
	                    $display("Dimensions: k=%d, n=%d, m=%d", k, n, m);
	                    $display("Strides: lhs_row_stride_b=%d, rhs_col_stride_b=%d, dst_row_stride_b=%d", lhs_row_stride_b, rhs_col_stride_b, dst_row_stride_b);
	                    $display("Quantization: q_mult_pt=%d, q_shift_pt=%d, use_per_channel=%b, cfg_16bits_ia=%b, cfg_dataflow_mode=%b", q_mult_pt, q_shift_pt, use_per_channel, cfg_16bits_ia, cfg_dataflow_mode);
	                end
`endif
		            end

	            if (current_state == INIT) begin
	                compute_tail_pending <= 1'b0;
	            end else begin
		                if (send_ia_trigger || (commit_now && ia_preissued)) begin
		                    compute_tail_pending <= 1'b1;
`ifndef SYNTHESIS
		                    if (ctrl_trace_en && send_ia_trigger) begin
		                        $display("[%0t] CTRL send_ia", $time);
		                    end
`endif
		                end else begin
		                    if (compute_tail_done) begin
		                        compute_tail_pending <= 1'b0;
`ifndef SYNTHESIS
		                        if (ctrl_trace_en) begin
		                            $display("[%0t] CTRL tail_done", $time);
		                        end
`endif
		                    end
		                end
	            end
	        end
	    end

`ifndef SYNTHESIS
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            util_active                   <= 1'b0;
            util_op_id                    <= '0;
            util_active_cycles            <= '0;
            util_weight_start_cycles      <= '0;
            util_weight_wait_cycles       <= '0;
            util_ia_start_cycles          <= '0;
            util_ia_wait_cycles           <= '0;
            util_wait_done_cycles           <= '0;
            util_stall_weight_tail_cycles <= '0;
            util_stall_weight_data_cycles <= '0;
            util_stall_weight_done_cycles <= '0;
            util_stall_ia_data_cycles     <= '0;
            util_stall_bias_cycles        <= '0;
            util_stall_quant_cycles       <= '0;
            util_stall_fifo_cycles        <= '0;
            util_stall_ia_done_cycles     <= '0;
            util_tail_pending_cycles      <= '0;
            util_tail_done_count          <= '0;
            util_weight_trigger_count     <= '0;
            util_ia_trigger_count         <= '0;
            util_sum_active_cycles            <= '0;
            util_sum_weight_start_cycles      <= '0;
            util_sum_weight_wait_cycles       <= '0;
            util_sum_ia_start_cycles          <= '0;
            util_sum_ia_wait_cycles           <= '0;
            util_sum_wait_done_cycles           <= '0;
            util_sum_stall_weight_tail_cycles <= '0;
            util_sum_stall_weight_data_cycles <= '0;
            util_sum_stall_weight_done_cycles <= '0;
            util_sum_stall_ia_data_cycles     <= '0;
            util_sum_stall_bias_cycles        <= '0;
            util_sum_stall_quant_cycles       <= '0;
            util_sum_stall_fifo_cycles        <= '0;
            util_sum_stall_ia_done_cycles     <= '0;
            util_sum_tail_pending_cycles      <= '0;
            util_sum_tail_done_count          <= '0;
            util_sum_weight_trigger_count     <= '0;
            util_sum_ia_trigger_count         <= '0;
        end else begin
            if (util_start_event) begin
                util_active                   <= 1'b1;
                util_op_id                    <= util_op_id + 1'b1;
                util_active_cycles            <= '0;
                util_weight_start_cycles      <= '0;
                util_weight_wait_cycles       <= '0;
                util_ia_start_cycles          <= '0;
                util_ia_wait_cycles           <= '0;
                util_wait_done_cycles           <= '0;
                util_stall_weight_tail_cycles <= '0;
                util_stall_weight_data_cycles <= '0;
                util_stall_weight_done_cycles <= '0;
                util_stall_ia_data_cycles     <= '0;
                util_stall_bias_cycles        <= '0;
                util_stall_quant_cycles       <= '0;
                util_stall_fifo_cycles        <= '0;
                util_stall_ia_done_cycles     <= '0;
                util_tail_pending_cycles      <= '0;
                util_tail_done_count          <= '0;
                util_weight_trigger_count     <= '0;
                util_ia_trigger_count         <= '0;
            end else if (util_active) begin
                util_active_cycles <= util_active_cycles + 1'b1;

                unique case (current_state)
                    WEIGHT_START: util_weight_start_cycles <= util_weight_start_cycles + 1'b1;
                    WEIGHT_WAIT:  util_weight_wait_cycles  <= util_weight_wait_cycles + 1'b1;
                    IA_START:     util_ia_start_cycles     <= util_ia_start_cycles + 1'b1;
                    IA_WAIT:      util_ia_wait_cycles      <= util_ia_wait_cycles + 1'b1;
                    WAIT_DONE:      util_wait_done_cycles      <= util_wait_done_cycles + 1'b1;
                    default: begin
                    end
                endcase

                if (current_state == WEIGHT_START && !oa_calc_over && !weight_safe_to_send) begin
                    util_stall_weight_tail_cycles <= util_stall_weight_tail_cycles + 1'b1;
                end
                if (current_state == WEIGHT_START && !oa_calc_over &&
                    weight_safe_to_send && !weight_data_valid) begin
                    util_stall_weight_data_cycles <= util_stall_weight_data_cycles + 1'b1;
                end
                if (current_state == WEIGHT_WAIT && !weight_sending_done) begin
                    util_stall_weight_done_cycles <= util_stall_weight_done_cycles + 1'b1;
                end
                if (current_state == IA_START && !ia_data_valid) begin
                    util_stall_ia_data_cycles <= util_stall_ia_data_cycles + 1'b1;
                end
                if (current_state == IA_START && ia_data_valid && !bias_ready_for_compute) begin
                    util_stall_bias_cycles <= util_stall_bias_cycles + 1'b1;
                end
                if (current_state == IA_START && ia_data_valid &&
                    bias_ready_for_compute && !quant_params_valid) begin
                    util_stall_quant_cycles <= util_stall_quant_cycles + 1'b1;
                end
                if (current_state == IA_START && ia_data_valid &&
                    bias_ready_for_compute && quant_params_valid && fifo_full_flag) begin
                    util_stall_fifo_cycles <= util_stall_fifo_cycles + 1'b1;
                end
                if (current_state == IA_WAIT && !ia_sending_done) begin
                    util_stall_ia_done_cycles <= util_stall_ia_done_cycles + 1'b1;
                end
                if (compute_tail_pending) begin
                    util_tail_pending_cycles <= util_tail_pending_cycles + 1'b1;
                end
                if (compute_tail_done) begin
                    util_tail_done_count <= util_tail_done_count + 1'b1;
                end
	                if (send_weight_trigger) begin
	                    util_weight_trigger_count <= util_weight_trigger_count + 1'b1;
	                end
	                if (send_ia_trigger) begin
	                    util_ia_trigger_count <= util_ia_trigger_count + 1'b1;
	                end
            end

            if (util_finish_event) begin
                util_sum_active_cycles            <= util_sum_active_cycles + util_active_cycles;
                util_sum_weight_start_cycles      <= util_sum_weight_start_cycles + util_weight_start_cycles;
                util_sum_weight_wait_cycles       <= util_sum_weight_wait_cycles + util_weight_wait_cycles;
                util_sum_ia_start_cycles          <= util_sum_ia_start_cycles + util_ia_start_cycles;
                util_sum_ia_wait_cycles           <= util_sum_ia_wait_cycles + util_ia_wait_cycles;
                util_sum_wait_done_cycles           <= util_sum_wait_done_cycles + util_wait_done_cycles;
                util_sum_stall_weight_tail_cycles <= util_sum_stall_weight_tail_cycles + util_stall_weight_tail_cycles;
                util_sum_stall_weight_data_cycles <= util_sum_stall_weight_data_cycles + util_stall_weight_data_cycles;
                util_sum_stall_weight_done_cycles <= util_sum_stall_weight_done_cycles + util_stall_weight_done_cycles;
                util_sum_stall_ia_data_cycles     <= util_sum_stall_ia_data_cycles + util_stall_ia_data_cycles;
                util_sum_stall_bias_cycles        <= util_sum_stall_bias_cycles + util_stall_bias_cycles;
                util_sum_stall_quant_cycles       <= util_sum_stall_quant_cycles + util_stall_quant_cycles;
                util_sum_stall_fifo_cycles        <= util_sum_stall_fifo_cycles + util_stall_fifo_cycles;
                util_sum_stall_ia_done_cycles     <= util_sum_stall_ia_done_cycles + util_stall_ia_done_cycles;
                util_sum_tail_pending_cycles      <= util_sum_tail_pending_cycles + util_tail_pending_cycles;
                util_sum_tail_done_count          <= util_sum_tail_done_count + util_tail_done_count;
                util_sum_weight_trigger_count     <= util_sum_weight_trigger_count + util_weight_trigger_count;
                util_sum_ia_trigger_count         <= util_sum_ia_trigger_count + util_ia_trigger_count;
                if (util_trace_en) begin
                    $display("[NPU_CTRL_UTIL] op=%0d active=%0d weight_start=%0d weight_wait=%0d ia_start=%0d ia_wait=%0d wait_done=%0d weight_tail_stall=%0d weight_data_stall=%0d weight_done_wait=%0d ia_data_stall=%0d bias_stall=%0d quant_stall=%0d fifo_stall=%0d ia_done_wait=%0d tail_pending=%0d tail_done=%0d weight_trig=%0d ia_trig=%0d",
                             util_op_id,
                             util_active_cycles,
                             util_weight_start_cycles,
                             util_weight_wait_cycles,
                             util_ia_start_cycles,
                             util_ia_wait_cycles,
                             util_wait_done_cycles,
                             util_stall_weight_tail_cycles,
                             util_stall_weight_data_cycles,
                             util_stall_weight_done_cycles,
                             util_stall_ia_data_cycles,
                             util_stall_bias_cycles,
                             util_stall_quant_cycles,
                             util_stall_fifo_cycles,
                             util_stall_ia_done_cycles,
                             util_tail_pending_cycles,
                             util_tail_done_count,
                             util_weight_trigger_count,
                             util_ia_trigger_count);
                end
                util_active <= 1'b0;
            end
	        end
	    end

    final begin
        if (util_summary_en) begin
            $display("[NPU_CTRL_UTIL_SUMMARY] ops=%0d active=%0d weight_start=%0d weight_wait=%0d ia_start=%0d ia_wait=%0d wait_done=%0d weight_tail_stall=%0d weight_data_stall=%0d weight_done_wait=%0d ia_data_stall=%0d bias_stall=%0d quant_stall=%0d fifo_stall=%0d ia_done_wait=%0d tail_pending=%0d tail_done=%0d weight_trig=%0d ia_trig=%0d",
                     util_op_id,
                     util_sum_active_cycles,
                     util_sum_weight_start_cycles,
                     util_sum_weight_wait_cycles,
                     util_sum_ia_start_cycles,
                     util_sum_ia_wait_cycles,
                     util_sum_wait_done_cycles,
                     util_sum_stall_weight_tail_cycles,
                     util_sum_stall_weight_data_cycles,
                     util_sum_stall_weight_done_cycles,
                     util_sum_stall_ia_data_cycles,
                     util_sum_stall_bias_cycles,
                     util_sum_stall_quant_cycles,
                     util_sum_stall_fifo_cycles,
                     util_sum_stall_ia_done_cycles,
                     util_sum_tail_pending_cycles,
                     util_sum_tail_done_count,
                     util_sum_weight_trigger_count,
                     util_sum_ia_trigger_count);
        end
    end
`endif


    // Load the NEXT weights into shadow registers while the current tall IA
    // stream computes. Commit only after the previous PS tail has drained.
    logic shadow_inflight, shadow_ready;
    logic ia_preissued;
    wire issue_ia_advance = current_state == WEIGHT_START && shadow_ready &&
        compute_tail_pending && partial_sum_advance_ready && issue_ia_now;
    wire commit_now = current_state==WEIGHT_START && shadow_ready &&
                      weight_safe_to_send && !oa_calc_over;
    wire prefetch_now = (current_state==WEIGHT_START || current_state==IA_WAIT) &&
                        !shadow_inflight && !shadow_ready &&
                        weight_data_valid && !weight_sending_done && !oa_calc_over;
    always_comb begin
        next_state=current_state;
        case(current_state)
            IDLE: if(calc_start) next_state=check_config_valid()?ERROR:INIT;
            INIT: next_state=WEIGHT_START;
            WEIGHT_START: begin
                if(oa_calc_over) next_state=done_ready?IDLE:WAIT_DONE;
                else if(commit_now) next_state=(ia_preissued || issue_ia_now) ? IA_WAIT : IA_START;
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
            shadow_inflight<=0; shadow_ready<=0; ia_preissued<=0; err_code<=0;
        end else begin
            init_cfg_ia<=0; init_cfg_weight<=0; init_cfg_bias<=0;
            init_cfg_requant<=0; init_cfg_oa<=0;
            send_weight_trigger<=prefetch_now;
            weight_commit<=commit_now;
            if(prefetch_now) shadow_inflight<=1;
            if(shadow_inflight && weight_sending_done) begin
                shadow_inflight<=0; shadow_ready<=1;
            end
            if(issue_ia_advance) ia_preissued<=1;
            if(commit_now) begin shadow_ready<=0; ia_preissued<=0; end
            if(current_state==IDLE) err_code<=0;
            if(current_state==ERROR) err_code<=error_type;
            if(current_state==INIT) begin
                init_cfg_ia<=1; init_cfg_weight<=1; init_cfg_bias<=1;
                init_cfg_requant<=1; init_cfg_oa<=1;
                use_16bits<=cfg_16bits_ia_reg;
                shadow_inflight<=0; shadow_ready<=0; ia_preissued<=0;
            end
        end
    end
    // The registered activation RAM can prepare its first read before commit
    // when the preceding sum and replay dependencies have been satisfied.
    assign send_ia_trigger = !ia_preissued && issue_ia_now &&
        (current_state==IA_START || commit_now || issue_ia_advance);
    assign sa_ready=current_state==IDLE;
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) done_valid<=0;
        else done_valid<=oa_calc_over || current_state==WAIT_DONE || current_state==ERROR;
    end
endmodule
