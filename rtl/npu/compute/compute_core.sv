`ifndef GEMMORA_PS_POOL_BYTES
`define GEMMORA_PS_POOL_BYTES 12288
`endif
// 协调脉动阵列、偏置及部分和缓存，按分块和帧输出矩阵累加结果。
module compute_core #(
    parameter int unsigned SIZE       = 16,
    parameter int unsigned DATA_WIDTH = 16,
    parameter int unsigned WEIGHT_WIDTH = 16,
    parameter int unsigned PS_FRAME_COUNT = SIZE,
    parameter int unsigned MAX_IA_REUSE = 2,
    parameter int unsigned PS_STORAGE_ROWS = 0,
    parameter int unsigned PS_EXTERNAL_RAM = 0,
    parameter bit p_fixed_ps_channels = 1'b0,
    parameter int unsigned PS_POOL_BYTES = `GEMMORA_PS_POOL_BYTES,
    parameter int unsigned PS_BANK_BYTES = 2048,
    parameter int unsigned PS_DIRECTORY_ROWS = PS_FRAME_COUNT * MAX_IA_REUSE * SIZE,
    parameter int unsigned PS_RAM_ADDR_BITS = PS_EXTERNAL_RAM!=0 ? $clog2(PS_POOL_BYTES/16) :
        ($clog2(PS_POOL_BYTES/64)>0 ? $clog2(PS_POOL_BYTES/64) : 1)
) (
    input  logic                         clk, // 模块工作时钟。
    input  logic                         rst_n, // 低有效复位输入。
    input  logic                         ps_store_cfg_valid = 1'b0, // 接收部分和存储容量配置。
    input  logic [31:0]                  ps_pool_bank_words = PS_EXTERNAL_RAM!=0 ? PS_BANK_BYTES/16 : PS_POOL_BYTES/64, // 每个部分和存储分组的可用数据字数。
    input  logic [31:0]                  ps_pool_bank_count = PS_EXTERNAL_RAM!=0 ? PS_POOL_BYTES/PS_BANK_BYTES : 4, // 部分和存储池的可用分组数。
    input  logic [31:0]                  ps_directory_stride = MAX_IA_REUSE*SIZE, // 相邻部分和帧在行目录中的间隔。
    output wire [3:0]                    ps_ram_read_en, // 部分和共享存储：各端口读取使能。
    output wire [PS_RAM_ADDR_BITS-1:0]    ps_ram_read_addr [0:3], // 部分和共享存储：各端口读取地址。
    input  wire [127:0]                  ps_ram_read_data [0:3] = '{default:'0}, // 部分和共享存储：各端口返回的读取数据。
    output wire [3:0]                    ps_ram_write_en, // 部分和共享存储：各端口写入使能。
    output wire [PS_RAM_ADDR_BITS-1:0]    ps_ram_write_addr [0:3], // 部分和共享存储：各端口写入地址。
    output wire [127:0]                  ps_ram_write_data [0:3], // 部分和共享存储：各端口写入数据。

    input  logic                         weight_commit, // 提交已装入的权重块供计算使用。
    input  logic                         store_weight_req, // 使能本周期的权重装载。
    input  logic signed [WEIGHT_WIDTH-1:0] weight_in [SIZE], // 本周期装入的逐列有符号权重。
    input  logic signed [DATA_WIDTH-1:0] ia_vec_in   [SIZE], // 本周期送入阵列的输入激活向量。
    input  logic                         ia_row_valid, // 本周期输入激活行有效。
    input  logic                         final_output_overlap = 1'b0, // 允许最终输出与后续部分和处理重叠。
    input  logic                         direct_final_stream = 1'b0, // 最终结果直接输出而不进入部分和存储。
    input  logic [$clog2(SIZE):0]         active_columns = ($clog2(SIZE)+1)'(SIZE), // 当前分块中有效的输出列数。
    input  logic                         ia_tile_start, // 启动当前输入分块的阵列计算。
    input  logic                         ia_calc_done, // 当前输入行属于最后一个归约分块。
    input  logic                         ia_is_init_data, // 当前输入行开始一次新的部分和累加。
    input  logic                         ia_l1_switch, // 输入加载器发出的一级分组切换标志。
    input  logic                         ia_sending_done, // 当前输入行是一组输入的最后一行。
    input  logic                         send_ia_trigger, // 接受帧描述符并开始发送输入数据。
    input  logic                         ps_frame_request = 1'b0, // 请求接收新的部分和帧描述符。
    input  logic [((PS_FRAME_COUNT > 1) ? $clog2(PS_FRAME_COUNT) : 1)-1:0] ps_frame_id = '0, // 待处理的部分和帧编号。
    input  logic [31:0]                  ps_frame_rows = 32'd0, // 本帧的有效输出行数。
    input  logic [31:0]                  ps_frame_reserve_rows = 32'd0, // 本帧需要预留的部分和行数。
    input  logic [2:0]                   ps_frame_word_cap = 3'd4, // 本帧每行允许占用的数据字上限。
    input  logic                         ps_frame_init = 1'b0, // 本帧执行首次部分和累加。
    input  logic                         ps_frame_final = 1'b0, // 本帧执行最后一次归约并产生最终结果。
    input  logic                         ps_force_raw = 1'b0, // 强制使用未压缩的部分和存储格式。
    output logic                         ps_frame_ready, // 部分和缓存能够接收当前帧。
    output logic                         ps_frame_pressure, // 部分和缓存当前存在容量压力。
    output logic                         ps_frame_complete, // 当前部分和帧处理完成。
    input  logic                         bias_sleep, // 置位时使用缓存部分和作为累加初值。
    input  logic signed [31:0]           bias_in     [SIZE], // 各计算通道的有符号偏置初值。

    output logic signed [31:0]           acc_data_out[SIZE], // 完成部分和处理后的逐通道累加结果。
    output logic                         acc_data_valid, // 输出累加结果有效。
    output logic                         partial_sum_calc_over, // 当前部分和计算阶段完成。
    output logic                         partial_sum_advance_ready, // 部分和缓存允许推进下一输入分块。
    output logic                         tile_calc_over, // 当前矩阵分块的计算结果已全部处理。
    output logic                         ps_capacity_fault // 部分和存储容量不足或访问越界。
);

    logic signed [31:0] bias_or_ps_sum [0:SIZE-1];
    logic signed [31:0] systolic_sum [0:SIZE-1];
    logic signed [31:0] ps_data_out [0:SIZE-1];
    logic signed [31:0] ps_acc_out [0:SIZE-1];
    logic ps_acc_data_valid, ps_tile_calc_over, ps_stream_calc_over;
    logic ps_replay_ready;
    logic [SIZE-1:0] row_valid_pipe, row_final_pipe, row_init_pipe, row_last_pipe;
    logic final_group_complete_q;
    logic final_output_complete;

    // A PE registers the input and the incoming sum in the same cycle.
    // After SIZE such stages, all output columns belong to one matrix row.
    // Metadata follows the same stages and never creates padding rows.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row_valid_pipe <= '0;
            row_final_pipe <= '0;
            row_init_pipe <= '0;
            row_last_pipe <= '0;
            final_group_complete_q <= 1'b0;
        end else begin
            final_group_complete_q <= row_last_pipe[SIZE-1] &&
                row_final_pipe[SIZE-1] && !final_output_overlap;
            row_valid_pipe[0] <= ia_row_valid;
            row_final_pipe[0] <= ia_row_valid && ia_calc_done;
            row_init_pipe[0] <= ia_row_valid && ia_is_init_data;
            row_last_pipe[0] <= ia_row_valid && ia_sending_done;
            for (int stage=1; stage<SIZE; stage++) begin
                row_valid_pipe[stage] <= row_valid_pipe[stage-1];
                row_final_pipe[stage] <= row_final_pipe[stage-1];
                row_init_pipe[stage] <= row_init_pipe[stage-1];
                row_last_pipe[stage] <= row_last_pipe[stage-1];
            end
        end
    end

    wire ps_stream_valid_d = row_valid_pipe[SIZE-1];
    wire ps_calc_done_d = row_final_pipe[SIZE-1];
    wire ps_is_init_data_d = row_init_pipe[SIZE-1];
    wire ps_group_switch_d = row_last_pipe[SIZE-1];
    localparam int unsigned PS_EFFECTIVE_FRAME_COUNT =
        (PS_FRAME_COUNT < 1) ? MAX_IA_REUSE : PS_FRAME_COUNT;

    bias_mux #(.SIZE(SIZE), .DATA_WIDTH(32)) u_bias_mux (
        .bias_sleep(bias_sleep), .bias_in(bias_in), .ps_in(ps_data_out),
        .sum_in(bias_or_ps_sum)
    );

    // 每块权重在提交前完成 SIZE 次装载，预取寄存器采用覆盖写入。
    ws_systolic_array #(
        .SIZE(SIZE), .DATA_IN_WIDTH(DATA_WIDTH), .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .ACC_WIDTH(32), .p_exchange_weights(1'b0)
    ) u_systolic_array (
        .clk(clk), .rst_n(rst_n),
        .store_weight_req(store_weight_req), .weight_commit(weight_commit),
        .weight_in(weight_in), .data_in(ia_vec_in), .sum_in(bias_or_ps_sum),
        .sum_out(systolic_sum)
    );

    ps_buffer #(
        .SIZE      (SIZE),
        .DATA_WIDTH(32),
        .FRAME_COUNT(PS_EFFECTIVE_FRAME_COUNT),
        .MAX_IA_REUSE(MAX_IA_REUSE),
        .STORAGE_ROWS(PS_STORAGE_ROWS),
        .PS_EXTERNAL_RAM(PS_EXTERNAL_RAM),
        .p_fixed_ps_channels(p_fixed_ps_channels),
        .PS_POOL_BYTES(PS_POOL_BYTES),
        .PS_BANK_BYTES(PS_BANK_BYTES),
        .PS_DIRECTORY_ROWS(PS_DIRECTORY_ROWS),
        .PS_RAM_ADDR_BITS(PS_RAM_ADDR_BITS)
    ) u_ps_buffer (
        .clk(clk), .rst_n(rst_n),
        .ps_store_cfg_valid(ps_store_cfg_valid), .ps_pool_bank_words(ps_pool_bank_words),
        .ps_pool_bank_count(ps_pool_bank_count), .ps_directory_stride(ps_directory_stride),
        .ps_ram_read_en(ps_ram_read_en), .ps_ram_read_addr(ps_ram_read_addr),
        .ps_ram_read_data(ps_ram_read_data), .ps_ram_write_en(ps_ram_write_en),
        .ps_ram_write_addr(ps_ram_write_addr), .ps_ram_write_data(ps_ram_write_data),
        .capacity_fault(ps_capacity_fault), .replay_ready(ps_replay_ready),
        .direct_final_stream(direct_final_stream),
        .frame_request(ps_frame_request),
        .frame_id(ps_frame_id), .frame_accept(send_ia_trigger),
        .frame_rows(ps_frame_rows), .frame_reserve_rows(ps_frame_reserve_rows),
        .frame_word_cap(ps_frame_word_cap), .frame_init(ps_frame_init),
        .frame_final(ps_frame_final), .force_raw(ps_force_raw),
        .frame_ready(ps_frame_ready), .frame_pressure(ps_frame_pressure),
        .frame_complete(ps_frame_complete),
        .data_in(systolic_sum), .ia_row_valid(ps_stream_valid_d),
        .ia_calc_done(ps_calc_done_d), .ia_tile_start(1'b0),
        .ia_l1_switch(ps_group_switch_d), .send_ia_trigger(ia_tile_start),
        .ia_is_init_data(ps_is_init_data_d), .replay_enable(bias_sleep),
        .data_out(ps_data_out), .acc_data_out(ps_acc_out),
        .acc_data_valid(ps_acc_data_valid), .tile_calc_over(ps_tile_calc_over),
        .stream_calc_over(ps_stream_calc_over)
    );

    // 最终结果先寄存再进入偏置加法，乘加与偏置加法分别位于两个时钟周期。
    // 数据寄存器不需要复位；有效标志清零后，复位期间的数值不会被接收。
    always_ff @(posedge clk) begin
        for (int lane = 0; lane < SIZE; lane++) begin
            acc_data_out[lane] <= ps_acc_out[lane];
        end
    end

    // 最终分组的完成事件随输出延迟一拍，保留重叠模式与参数切换的先后关系。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_data_valid <= 1'b0;
            tile_calc_over <= 1'b0;
            final_output_complete <= 1'b0;
        end else begin
            acc_data_valid <= ps_acc_data_valid;
            tile_calc_over <= ps_tile_calc_over;
            final_output_complete <= final_group_complete_q ||
                (ps_group_switch_d && ps_calc_done_d && final_output_overlap);
        end
    end

    // 中间部分和仍按 PS 存储的原有完成周期推进。
    assign partial_sum_calc_over = final_output_complete ||
        (ps_group_switch_d && !ps_calc_done_d);
    assign partial_sum_advance_ready = direct_final_stream;

`ifdef NPU_SIM_ASSERT
    initial forever @(posedge clk) if (rst_n) begin
        assert (!ia_sending_done || ia_row_valid)
            else $fatal(1, "DiP stream completion requires a valid input row");
    end
`endif
endmodule
