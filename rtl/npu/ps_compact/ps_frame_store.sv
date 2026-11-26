// SPDX-License-Identifier: Apache-2.0
`default_nettype none

/* 按帧保存、编码及回放部分和，管理行目录、共享存储空间和容量限制。 */ module ps_frame_store #(
    parameter integer MAX_FRAME_ROWS = 47,
    parameter integer FRAME_COUNT = 16,
    parameter integer POOL_BYTES = 4096,
    parameter integer BANK_BYTES = 2048,
    parameter integer DECODE_FIFO_ROWS = 8,
    parameter integer EXTERNAL_RAM = 0,
    parameter bit p_fixed_ps_channels = 1'b0,
    parameter integer DIRECTORY_ROWS = FRAME_COUNT * MAX_FRAME_ROWS,
    parameter integer RAM_ADDR_BITS = EXTERNAL_RAM!=0 ? $clog2(POOL_BYTES/16) :
        ($clog2(POOL_BYTES/64)>0 ? $clog2(POOL_BYTES/64) : 1)
) (
    input  wire clk /* 工作时钟 */,
    input  wire rst_n /* 低有效复位 */,
    input  wire cfg_valid = 1'b0 /* 接收部分和存储空间及目录配置 */,
    input  wire [31:0] cfg_pool_bank_words = EXTERNAL_RAM!=0 ? BANK_BYTES/16 : POOL_BYTES/64 /* 每个物理部分和存储块的可用字数 */,
    input  wire [31:0] cfg_pool_bank_count = EXTERNAL_RAM!=0 ? POOL_BYTES/BANK_BYTES : 4 /* 当前分配给部分和的物理存储块数 */,
    input  wire [31:0] cfg_directory_stride = MAX_FRAME_ROWS /* 相邻帧在部分和行目录中的地址间隔 */,
    output wire [3:0] ram_read_en /* 四个部分和存储通道的读使能 */,
    output wire [RAM_ADDR_BITS-1:0] ram_read_addr [0:3] /* 四个部分和通道的存储字读取地址 */,
    input  wire [127:0] ram_read_data [0:3] = '{default:'0} /* 四个部分和通道同步返回的各128 位数据 */,
    output wire [3:0] ram_write_en /* 四个部分和存储通道的写使能 */,
    output wire [RAM_ADDR_BITS-1:0] ram_write_addr [0:3] /* 四个部分和通道的存储字写入地址 */,
    output wire [127:0] ram_write_data [0:3] /* 四个部分和通道的各128 位写数据 */,
    input  wire frame_request /* 当前帧命令请求检查存储资源 */,
    input  wire frame_accept /* 当前帧命令已被接收 */,
    input  wire [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id /* 当前部分和帧的物理槽号 */,
    input  wire [31:0] frame_rows /* 当前部分和帧的有效行数 */,
    input  wire [31:0] frame_reserve_rows /* 本次帧命令需要预留的部分和行数 */,
    input  wire [2:0] frame_word_cap = 3'd4 /* 每行部分和最多占用的128 位存储字数 */,
    input  wire frame_init /* 当前帧开始首次归约并初始化部分和 */,
    input  wire frame_final /* 当前帧执行最终归约并输出结果 */,
    input  wire force_raw_i /* 部分和始终使用原始32 位格式 */,
    output wire frame_ready /* 部分和存储可接收当前帧命令 */,
    output wire frame_pressure /* 剩余部分和存储需要提前结束当前切片 */,
    output reg  capacity_fault /* 容量配置或实际存储访问超出限制 */,
    output reg  frame_complete /* 当前部分和帧的读写处理完成 */,
    input  wire write_valid /* 当前完整部分和行可写入存储 */,
    input  wire [511:0] write_data /* 当前待编码并保存的16 个 32 位部分和元素 */,
    input  wire write_frame_end /* 当前写入行结束该帧的结果流 */,
    input  wire replay_trigger /* 启动当前已保存部分和帧的顺序回放 */,
    output wire [511:0] replay_data /* 解码后返回的完整部分和行 */,
    output reg  replay_valid /* 当前返回的部分和回放行有效 */
);
    localparam integer BANKS=EXTERNAL_RAM!=0 ? POOL_BYTES/BANK_BYTES : 4;
    localparam integer BANK_DEPTH=EXTERNAL_RAM!=0 ? BANK_BYTES/16 : POOL_BYTES/64;
    localparam integer BANK_ADDR_BITS=$clog2(BANK_DEPTH)>0 ? $clog2(BANK_DEPTH) : 1;
    localparam integer ROTATION_BITS=$clog2(BANKS)>0 ? $clog2(BANKS) : 1;
    localparam integer FRAME_ID_BITS=FRAME_COUNT>1 ? $clog2(FRAME_COUNT) : 1;
    localparam integer FIFO_PTR_BITS=$clog2(DECODE_FIFO_ROWS);
    localparam integer PREFETCH_CREDITS=DECODE_FIFO_ROWS-1;
    localparam integer LENGTH_BITS=$clog2(MAX_FRAME_ROWS+1);
    reg configuration_ready,configuration_pending;
    reg [BANK_ADDR_BITS:0] pool_bank_words_q;
    reg [ROTATION_BITS:0] pool_bank_count_q;
    reg [LENGTH_BITS-1:0] directory_stride_q;
    reg [FRAME_COUNT-1:0] frame_valid;
    logic frame_empty_q;
    logic [FRAME_COUNT-1:0] frame_valid_after_complete;
    reg [LENGTH_BITS-1:0] frame_lengths [FRAME_COUNT];
    reg command_present,command_accepted,input_ended,replay_armed,replay_active;
    logic replay_launch_q;
    reg [FRAME_ID_BITS-1:0] frame_id_q;
    reg [LENGTH_BITS-1:0] frame_rows_q,capture_count,commit_count,read_index,replay_index;
    logic frame_single_row_q, read_remaining_q, replay_complete_q;
    logic commit_complete_q, commit_next_complete_q;
    localparam int p_capture_width = LENGTH_BITS < 32 ? LENGTH_BITS + 1 : LENGTH_BITS;
    logic [p_capture_width-1:0] capture_end_i_a, capture_end_i_b, capture_end_i_target;
    logic capture_end_i_carry_in, capture_end_o_equal;
    logic capture_length_match;
    reg frame_init_q,frame_final_q;
    localparam int p_cursor_bits = (EXTERNAL_RAM != 0 && p_fixed_ps_channels) ? RAM_ADDR_BITS : BANK_ADDR_BITS+1;
    logic [p_cursor_bits-1:0] read_cursor, write_cursor;
    reg [ROTATION_BITS-1:0] read_rotation,write_rotation;
    wire configuration_valid=cfg_pool_bank_count>=4 && cfg_pool_bank_count<=BANKS &&
        cfg_pool_bank_words>0 && cfg_pool_bank_words<=BANK_DEPTH &&
        cfg_directory_stride>0 && cfg_directory_stride<=MAX_FRAME_ROWS;
    wire configure_start=cfg_valid && !command_present && frame_empty_q;
    wire clear_metadata=configure_start || configuration_pending;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            configuration_ready<=EXTERNAL_RAM==0;configuration_pending<=0;
            pool_bank_words_q<=(BANK_ADDR_BITS+1)'(EXTERNAL_RAM==0 ? BANK_DEPTH : 0);
            pool_bank_count_q<=(ROTATION_BITS+1)'(EXTERNAL_RAM==0 ? BANKS : 0);
            directory_stride_q<=LENGTH_BITS'(MAX_FRAME_ROWS);
        end else if(configure_start) begin
            configuration_ready<=EXTERNAL_RAM==0;configuration_pending<=EXTERNAL_RAM!=0;
        end else if(configuration_pending) begin
            configuration_pending<=0;configuration_ready<=configuration_valid;
            pool_bank_words_q<=(BANK_ADDR_BITS+1)'(cfg_pool_bank_words);
            pool_bank_count_q<=(ROTATION_BITS+1)'(cfg_pool_bank_count);
            directory_stride_q<=LENGTH_BITS'(cfg_directory_stride);
        end
    end
    localparam integer RAW_LINEAR_BITS=$clog2(FRAME_COUNT*MAX_FRAME_ROWS*4+1);
    typedef struct packed {
        logic [FRAME_ID_BITS-1:0] id;
        logic [31:0] rows;
        logic init;
        logic final_row;
        logic legal;
        logic [RAW_LINEAR_BITS-1:0] initial_linear;
    } request_context_t;
    request_context_t request_q;
    logic request_pending_q, pressure_q;
    logic request_fits_q;
    logic request_qualified_q, request_initial_or_other_q;

    logic request_released_q;
    wire request_capture = frame_request && configuration_ready &&
        (!command_present || (command_accepted && request_released_q)) &&
        !request_pending_q && !capacity_fault;
    wire cancel_prepared = !frame_request && !frame_accept && !command_accepted &&
        (request_pending_q || command_present);
    wire cancel_request = !frame_request && !frame_accept && request_pending_q;
    wire [RAW_LINEAR_BITS-1:0] initial_linear = request_q.initial_linear;
    (* keep = "true" *) logic request_rows_high_valid, request_rows_low_valid;
    (* keep = "true" *) logic request_frame_valid;
    (* keep = "true" *) logic [FRAME_COUNT-1:0] request_frame_match;
    localparam integer p_request_length_groups = (LENGTH_BITS+2)/3;
    (* keep = "true" *) logic [p_request_length_groups-1:0] request_length_equal [FRAME_COUNT];
    logic request_valid;

    // 高位范围与低位行数并行检查，范围结果不经过低位大小比较的进位逻辑。
    if (LENGTH_BITS < 32) begin : g_request_rows_bounded
        assign request_rows_high_valid = frame_rows[31:LENGTH_BITS] == '0;
    end else begin : g_request_rows_full
        assign request_rows_high_valid = 1'b1;
    end
    assign request_rows_low_valid = LENGTH_BITS'(frame_rows) > 0 &&
        LENGTH_BITS'(frame_rows) <= LENGTH_BITS'(MAX_FRAME_ROWS) &&
        LENGTH_BITS'(frame_rows) <= directory_stride_q;
    // 各帧的初始化与长度资格并行形成，帧编号只选择最终的一位结果。
    for (genvar frame = 0; frame < FRAME_COUNT; frame++) begin : g_request_frame_match
        // 三位长度片段独立比较，最终资格同时合并各片段与帧状态。
        for (genvar group = 0; group < p_request_length_groups; group++) begin : g_length_group
            localparam integer p_width = (LENGTH_BITS-3*group > 3) ? 3 : LENGTH_BITS-3*group;
            assign request_length_equal[frame][group] =
                frame_lengths[frame][3*group+:p_width] == frame_rows[3*group+:p_width];
        end
        assign request_frame_match[frame] = frame_init ? !frame_valid[frame] :
            frame_valid[frame] && (&request_length_equal[frame]);
    end
    // 后续命令按当前命令完成后的帧目录检查，
    // 输出尾部写入期间即可保存下一帧描述。
    wire request_uses_active_frame = command_present && command_accepted && frame_id == frame_id_q;
    assign request_frame_valid = 32'(frame_id) < FRAME_COUNT &&
        (request_uses_active_frame ?
            (frame_init ? frame_final_q : !frame_final_q && 32'(frame_rows_q) == frame_rows) :
            request_frame_match[frame_id]);
    // 未确定行数字段保留完整四态比较，已确定字段共享实际行宽的范围结果。
    always_comb begin
        case (^frame_rows)
            1'b0, 1'b1: request_valid = request_rows_high_valid && request_rows_low_valid && request_frame_valid;
            default: request_valid = 32'(frame_id) < FRAME_COUNT && frame_rows > 0 && frame_rows <= MAX_FRAME_ROWS &&
                frame_rows <= directory_stride_q && (frame_init ? !frame_valid[frame_id] :
                frame_valid[frame_id] && 32'(frame_lengths[frame_id]) == frame_rows);
        endcase
    end
    localparam int p_pool_words_width = BANK_ADDR_BITS + ROTATION_BITS + 2;
    localparam int p_capacity_rows_width = (RAW_LINEAR_BITS-2 > p_pool_words_width-2) ?
        RAW_LINEAR_BITS-2 : p_pool_words_width-2;
    logic [p_pool_words_width-1:0] configured_pool_words;
    logic [p_capacity_rows_width-1:0] configured_pool_rows;
    logic [p_capacity_rows_width:0] frame_available_rows_q [FRAME_COUNT];
    logic [FRAME_COUNT-1:0] frame_capacity_match;
    logic incoming_rows_bounded;
    logic incoming_request_fits;
    logic [p_capacity_rows_width:0] selected_available_rows;
    logic selected_capacity_match;
    logic [p_capacity_rows_width-1:0] pool_capacity_rows_q;
    logic [RAW_LINEAR_BITS-3:0] incoming_initial_row;
    logic [p_capacity_rows_width:0] selected_available_fast;
    logic selected_available_carry;

    // 配置保存总行数，请求使用同一个起始行计算当前帧的剩余容量。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pool_capacity_rows_q <= p_capacity_rows_width'(EXTERNAL_RAM == 0 ? BANK_DEPTH : 0);
        end else if (configuration_pending && !configure_start) begin
            pool_capacity_rows_q <= configured_pool_rows;
        end
    end
    assign incoming_initial_row = (RAW_LINEAR_BITS-2)'(frame_id) *
        (RAW_LINEAR_BITS-2)'(directory_stride_q);
    parallel_prefix_add #(.p_width(p_capacity_rows_width+1),
        .p_dsp_split_width((p_capacity_rows_width+1)/2), .p_preserve_groups(1'b1),
        .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0), .p_direct_subtract(1'b1)) u_request_capacity (
        .i_a({1'b0, pool_capacity_rows_q}),
        .i_b(~(p_capacity_rows_width+1)'(incoming_initial_row)), .i_carry(1'b1),
        .o_sum(selected_available_fast), .o_carry(selected_available_carry)
    );

    assign configured_pool_words = p_pool_words_width'((BANK_ADDR_BITS+1)'(cfg_pool_bank_words)) *
        p_pool_words_width'((ROTATION_BITS+1)'(cfg_pool_bank_count));
    assign configured_pool_rows = p_capacity_rows_width'(configured_pool_words >> 2);
    if (p_capacity_rows_width < 32) begin : g_capacity_rows_bounded
        assign incoming_rows_bounded = !(|frame_rows[31:p_capacity_rows_width]) &&
            !(|frame_reserve_rows[31:p_capacity_rows_width]);
    end else begin : g_capacity_rows_full
        assign incoming_rows_bounded = 1'b1;
    end

    // 各帧的容量表用于未确定配置或帧编号的四态选择。
    for (genvar frame = 0; frame < FRAME_COUNT; frame++) begin : g_frame_capacity
        logic [RAW_LINEAR_BITS-3:0] configured_initial_row;
        logic [p_capacity_rows_width:0] available_rows, available_rows_direct;
        logic unused_capacity_carry;
        logic [RAW_LINEAR_BITS-3:0] offset_sum [FRAME_ID_BITS+1];
        logic [RAW_LINEAR_BITS-3:0] offset_carry [FRAME_ID_BITS+1];
        logic unused_initial_carry;
        // 固定帧编号展开为移位项，先压缩部分和，再完成一次进位计算。
        assign offset_sum[0] = '0;
        assign offset_carry[0] = '0;
        for (genvar bit_index = 0; bit_index < FRAME_ID_BITS; bit_index++) begin : g_offset_term
            if (((frame >> bit_index) & 1) != 0) begin : g_active
                logic [RAW_LINEAR_BITS-3:0] shifted_stride;
                assign shifted_stride = (RAW_LINEAR_BITS-2)'(LENGTH_BITS'(cfg_directory_stride)) << bit_index;
                assign offset_sum[bit_index+1] = offset_sum[bit_index] ^ offset_carry[bit_index] ^ shifted_stride;
                assign offset_carry[bit_index+1] = ((offset_sum[bit_index] & offset_carry[bit_index]) |
                    ((offset_sum[bit_index] | offset_carry[bit_index]) & shifted_stride)) << 1;
            end else begin : g_zero
                assign offset_sum[bit_index+1] = offset_sum[bit_index];
                assign offset_carry[bit_index+1] = offset_carry[bit_index];
            end
        end
        parallel_prefix_add #(
            .p_width(RAW_LINEAR_BITS-2), .p_group_width(1), .p_preserve_groups(1'b0)
        ) u_initial_row (
            .i_a(offset_sum[FRAME_ID_BITS]), .i_b(offset_carry[FRAME_ID_BITS]), .i_carry(1'b0),
            .o_sum(configured_initial_row), .o_carry(unused_initial_carry)
        );
        parallel_prefix_add #(
            .p_width(p_capacity_rows_width+1), .p_group_width(1), .p_preserve_groups(1'b0)
        ) u_available_rows (
            .i_a({1'b0, configured_pool_rows}),
            .i_b(~(p_capacity_rows_width+1)'(configured_initial_row)), .i_carry(1'b1),
            .o_sum(available_rows_direct), .o_carry(unused_capacity_carry)
        );
        // 固定帧编号的负偏移与存储池行数共同压缩，只在末级传播一次进位。
        if (LENGTH_BITS < 63 && RAW_LINEAR_BITS-2 < 63 &&
            64'(frame)*((64'b1 << LENGTH_BITS)-1) < (64'b1 << (RAW_LINEAR_BITS-2))) begin : g_fused_capacity
            localparam int p_width = p_capacity_rows_width+1;
            logic [p_width-1:0] sum_terms [FRAME_ID_BITS+1];
            logic [p_width-1:0] carry_terms [FRAME_ID_BITS+1];
            logic [p_width-1:0] available_fast;
            logic unused_fused_carry;
            assign sum_terms[0] = {1'b0, configured_pool_rows};
            assign carry_terms[0] = p_width'($countones(frame));
            for (genvar bit_index=0; bit_index<FRAME_ID_BITS; bit_index++) begin : g_term
                if (((frame >> bit_index) & 1) != 0) begin : g_active
                    logic [p_width-1:0] negative_stride;
                    assign negative_stride = ~(p_width'(LENGTH_BITS'(cfg_directory_stride)) << bit_index);
                    assign sum_terms[bit_index+1] = sum_terms[bit_index] ^ carry_terms[bit_index] ^ negative_stride;
                    assign carry_terms[bit_index+1] = ((sum_terms[bit_index] & carry_terms[bit_index]) |
                        ((sum_terms[bit_index] | carry_terms[bit_index]) & negative_stride)) << 1;
                end else begin : g_zero
                    assign sum_terms[bit_index+1] = sum_terms[bit_index];
                    assign carry_terms[bit_index+1] = carry_terms[bit_index];
                end
            end
            parallel_prefix_add #(.p_width(p_width), .p_dsp_split_width(p_width/2),
                .p_preserve_groups(1'b0), .p_parallel_high_prefix(1'b0), .p_keep_carry(1'b0)) u_capacity (
                .i_a(sum_terms[FRAME_ID_BITS]), .i_b(carry_terms[FRAME_ID_BITS]), .i_carry(1'b0),
                .o_sum(available_fast), .o_carry(unused_fused_carry)
            );
            always_comb begin
                case (^{configured_pool_rows, cfg_directory_stride})
                    1'b0, 1'b1: available_rows = available_fast;
                    default: available_rows = available_rows_direct;
                endcase
            end
        end else begin : g_modular_capacity
            assign available_rows = available_rows_direct;
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                frame_available_rows_q[frame] <= (p_capacity_rows_width+1)'(
                    (EXTERNAL_RAM == 0 ? BANK_DEPTH : 0) - frame * MAX_FRAME_ROWS);
            end else if (configuration_pending && !configure_start) begin
                frame_available_rows_q[frame] <= available_rows;
            end
        end
        assign frame_capacity_match[frame] = incoming_rows_bounded &&
            !frame_available_rows_q[frame][p_capacity_rows_width] &&
            p_capacity_rows_width'(frame_rows) <= frame_available_rows_q[frame][p_capacity_rows_width-1:0] &&
            p_capacity_rows_width'(frame_reserve_rows) <= frame_available_rows_q[frame][p_capacity_rows_width-1:0];
    end
    // 确定的请求共享起始行计算，两个行数上限比较使用同一剩余容量。
    always_comb begin
        selected_available_rows = frame_available_rows_q[frame_id];
        case (^{frame_id, pool_capacity_rows_q, directory_stride_q})
            1'b0, 1'b1: begin
                if (32'(frame_id) < FRAME_COUNT)
                    selected_available_rows = selected_available_fast;
            end
            default: begin end
        endcase
    end
    logic rows_exceed_capacity, reserve_exceeds_capacity;
    logic rows_capacity_equal, reserve_capacity_equal;
    parallel_unsigned_compare #(.p_width(p_capacity_rows_width), .p_preserve_groups(1'b1)) u_rows_capacity (
        .i_a(selected_available_rows[p_capacity_rows_width-1:0]),
        .i_b(p_capacity_rows_width'(frame_rows)),
        .o_less(rows_exceed_capacity), .o_equal(rows_capacity_equal)
    );
    parallel_unsigned_compare #(.p_width(p_capacity_rows_width), .p_preserve_groups(1'b1)) u_reserve_capacity (
        .i_a(selected_available_rows[p_capacity_rows_width-1:0]),
        .i_b(p_capacity_rows_width'(frame_reserve_rows)),
        .o_less(reserve_exceeds_capacity), .o_equal(reserve_capacity_equal)
    );
    assign selected_capacity_match = incoming_rows_bounded &&
        !selected_available_rows[p_capacity_rows_width] &&
        !rows_exceed_capacity && !reserve_exceeds_capacity;
    always_comb begin
        case (^frame_id)
            1'b0, 1'b1: begin
                if (32'(frame_id) < FRAME_COUNT)
                    incoming_request_fits = (frame_init && frame_final) || selected_capacity_match;
                else
                    incoming_request_fits = (frame_init && frame_final) || frame_capacity_match[frame_id];
            end
            default: incoming_request_fits = (frame_init && frame_final) || frame_capacity_match[frame_id];
        endcase
    end
    logic complete_now;
    logic complete_eligible, prepare_eligible;
    (* keep = "true" *) logic prepare_state_eligible;
    logic prepare_start, prepare_state_selected, prepare_read_state_selected;
    always_comb begin
        frame_valid_after_complete = frame_valid;
        frame_valid_after_complete[frame_id_q] = !frame_final_q;
    end
    // 当前帧完成资格先独立形成，容量状态只在接收事件末端参与选择。
    always_comb begin
        prepare_state_eligible = configuration_ready && request_pending_q &&
            (!command_present || complete_eligible) && request_q.legal && request_fits_q;
        case (^{configuration_ready, request_pending_q, command_present, complete_eligible,
                request_q.legal, request_fits_q, request_qualified_q})
            1'b0, 1'b1: prepare_state_eligible = prepare_state_selected;
            default: begin end
        endcase
    end
    assign prepare_eligible = frame_request && prepare_state_eligible;
    always_comb begin
        case (capacity_fault)
            1'b0: prepare_start = prepare_eligible;
            1'b1: prepare_start = 1'b0;
            default: prepare_start = frame_request && configuration_ready && request_pending_q &&
                (!command_present || complete_now) && request_q.legal && request_fits_q && !capacity_fault;
        endcase
    end
    assign frame_pressure = pressure_q && frame_request && !capacity_fault;

    // 帧描述、容量资格和起始地址在同一接收边沿保存。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            request_pending_q <= 1'b0;
            request_fits_q <= 1'b0;
            request_qualified_q <= 1'b0;
            request_initial_or_other_q <= 1'b0;
            pressure_q <= 1'b0;
            request_released_q <= 1'b0;
        end else if (clear_metadata || cancel_prepared) begin
            request_pending_q <= 1'b0;
            request_fits_q <= 1'b0;
            request_qualified_q <= 1'b0;
            request_initial_or_other_q <= 1'b0;
            pressure_q <= 1'b0;
            request_released_q <= 1'b0;
        end else begin
            if (command_accepted && !frame_request) request_released_q <= 1'b1;
            if (request_capture) begin
                request_q.id <= frame_id;
                request_q.rows <= frame_rows;
                request_fits_q <= incoming_request_fits;
                // 请求等待期间当前帧编号不变，帧交接同时清除请求有效状态。
                request_qualified_q <= request_valid && incoming_request_fits;
                request_initial_or_other_q <= frame_init || frame_id != frame_id_q;
                request_q.init <= frame_init;
                request_q.final_row <= frame_final;
                request_q.legal <= request_valid;
                request_q.initial_linear <=
                    {incoming_initial_row, 2'b00};
                request_pending_q <= 1'b1;
            end
            if (request_pending_q) begin
                pressure_q <= frame_request && request_q.legal && !request_fits_q && !capacity_fault;
            end
            if (prepare_start) begin
                request_pending_q <= 1'b0;
                request_qualified_q <= 1'b0;
                pressure_q <= 1'b0;
                request_released_q <= 1'b0;
            end
            if (cancel_request) begin
                request_pending_q <= 1'b0;
                request_qualified_q <= 1'b0;
                pressure_q <= 1'b0;
            end
        end
    end
    logic [31:0] initial_row, initial_bank;
    if (EXTERNAL_RAM != 0 && p_fixed_ps_channels) begin : g_fixed_address
        // 固定通道中地址为完整部分和的行号，每次读写同时处理四个数据段。
        assign initial_row = 32'(initial_linear >> 2);
        assign initial_bank = 32'd0;
    end else begin : g_rotating_address
    wire [RAW_LINEAR_BITS-1:0] quotient_5,quotient_6,quotient_7;
    wire [2:0] remainder_5,remainder_6,remainder_7;
    ps_raw_address #(.WIDTH(RAW_LINEAR_BITS),.DIVISOR(5)) u_address_5
        (.linear(initial_linear),.quotient(quotient_5),.remainder(remainder_5));
    ps_raw_address #(.WIDTH(RAW_LINEAR_BITS),.DIVISOR(6)) u_address_6
        (.linear(initial_linear),.quotient(quotient_6),.remainder(remainder_6));
    ps_raw_address #(.WIDTH(RAW_LINEAR_BITS),.DIVISOR(7)) u_address_7
        (.linear(initial_linear),.quotient(quotient_7),.remainder(remainder_7));
    always @* begin
        initial_row=0;initial_bank=0;
        case(pool_bank_count_q)
            4:begin initial_row=32'(initial_linear>>2);initial_bank=32'(initial_linear&3);end
            5:begin initial_row=32'(quotient_5);initial_bank=32'(remainder_5);end
            6:begin initial_row=32'(quotient_6);initial_bank=32'(remainder_6);end
            7:begin initial_row=32'(quotient_7);initial_bank=32'(remainder_7);end
            8:begin initial_row=32'(initial_linear>>3);initial_bank=32'(initial_linear&7);end
            default:;
        endcase
    end
    end
    reg encoder_done;
    wire encoder_start=write_valid && command_accepted && !frame_final_q && !input_ended && !capacity_fault;
    // 已接收行数和本拍继续接收一行的结束条件并行比较，接收事件仅选择结果。
    // 额外一位保留窄计数器的加法进位，与完整表达式的数值范围一致。
    assign capture_end_i_a = p_capture_width'(capture_count);
    assign capture_end_i_b = '0;
    assign capture_end_i_target = p_capture_width'(frame_rows_q);
    assign capture_end_i_carry_in = 1'b1;
    add_equal #(.p_width(p_capture_width)) u_capture_end (
        .i_a(capture_end_i_a), .i_b(capture_end_i_b), .i_target(capture_end_i_target),
        .i_carry_in(capture_end_i_carry_in), .o_equal(capture_end_o_equal)
    );
    always_comb begin
        capture_length_match = capture_count + (encoder_start ? 1 : 0) == frame_rows_q;
        case (^{capture_count, frame_rows_q, encoder_start})
            1'b0, 1'b1: capture_length_match = encoder_start ?
                capture_end_o_equal : capture_count == frame_rows_q;
            default: ;
        endcase
    end
    reg [511:0] encode_commit_packet;
    wire encode_commit_valid=encoder_done && !capacity_fault;
    wire last_commit_now = encode_commit_valid && commit_next_complete_q;
    logic commit_following_equal;
    add_equal #(.p_width(LENGTH_BITS)) u_commit_following (
        .i_a(commit_count), .i_b(LENGTH_BITS'(2)), .i_target(frame_rows_q),
        .i_carry_in(1'b0), .o_equal(commit_following_equal)
    );
    // 提交计数更新时保存本行和下一行的结束条件，帧交接使用保存的状态。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            commit_complete_q <= 1'b1;
            commit_next_complete_q <= 1'b0;
        end else if (clear_metadata || cancel_prepared) begin
            commit_complete_q <= frame_rows_q == LENGTH_BITS'(0);
            commit_next_complete_q <= frame_rows_q == LENGTH_BITS'(1);
        end else if (prepare_start) begin
            commit_complete_q <= LENGTH_BITS'(request_q.rows) == LENGTH_BITS'(0);
            commit_next_complete_q <= LENGTH_BITS'(request_q.rows) == LENGTH_BITS'(1);
        end else if (encode_commit_valid) begin
            commit_complete_q <= commit_next_complete_q;
            commit_next_complete_q <= commit_following_equal;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin encoder_done<=0;encode_commit_packet<=0;end
        else begin
            encoder_done<=encoder_start && !clear_metadata;
            if(encoder_start) encode_commit_packet<=write_data;
        end
    end
    reg [FIFO_PTR_BITS-1:0] decoded_write_pointer,decoded_read_pointer;
    logic decoded_i_wr_en, decoded_i_rd_en, decoded_i_wr_mask;
    logic [FIFO_PTR_BITS-1:0] decoded_i_wr_addr, decoded_i_rd_addr;
    logic [511:0] decoded_i_wr_data, replay_row_data;
    reg [FIFO_PTR_BITS:0] decoded_count,decoder_inflight;
    logic prefetch_credit_available;
    if (DECODE_FIFO_ROWS == (1 << FIFO_PTR_BITS)) begin : g_prefetch_credit
        // 深度为二的幂时，低段取反直接给出允许的剩余行数，省去先求和再比较。
        always_comb begin
            case (^{decoded_count, decoder_inflight})
                1'b0, 1'b1: prefetch_credit_available =
                    !decoded_count[FIFO_PTR_BITS] && !decoder_inflight[FIFO_PTR_BITS] &&
                    decoder_inflight[FIFO_PTR_BITS-1:0] < ~decoded_count[FIFO_PTR_BITS-1:0];
                default: prefetch_credit_available =
                    32'(decoded_count)+32'(decoder_inflight)<PREFETCH_CREDITS;
            endcase
        end
    end else begin : g_prefetch_credit_general
        assign prefetch_credit_available =
            32'(decoded_count)+32'(decoder_inflight)<PREFETCH_CREDITS;
    end
    // 单行更新提交后才读取同一帧，避免同步 RAM 同拍读写同址。
    wire prepare_read_conflict = last_commit_now && request_q.id == frame_id_q && frame_single_row_q;
    logic prefetch_prepare, prefetch_fire;
    logic prepare_read_eligible;
    logic prefetch_eligible;
    (* keep = "true" *) logic prepare_read_state_eligible;
    (* keep = "true" *) logic prefetch_continue_eligible;
    logic prefetch_requested_eligible, prefetch_read_selected;
    // 同拍完成与首行冲突使用未屏蔽的局部条件，读端口末级统一检查容量状态。
    always_comb begin
        prepare_read_state_eligible = prepare_state_eligible && !request_q.init &&
            !(encoder_done && commit_next_complete_q && request_q.id == frame_id_q && frame_single_row_q);
        case (^{prepare_state_eligible, request_q.init, encoder_done, commit_next_complete_q,
                request_q.id, frame_id_q, frame_single_row_q, request_initial_or_other_q})
            1'b0, 1'b1: prepare_read_state_eligible = prepare_read_state_selected;
            default: begin end
        endcase
    end
    assign prepare_read_eligible = frame_request && prepare_read_state_eligible;
    // 首行和后续行的局部状态先并行准备，请求与接受脉冲仅选择末级读取资格。
    assign prefetch_continue_eligible = command_present && !frame_init_q && read_remaining_q &&
        prefetch_credit_available && !clear_metadata;
    assign prefetch_requested_eligible = prepare_read_state_eligible || prefetch_continue_eligible;
    ps_frame_read_enable u_prefetch_read_enable (
        .i_request(frame_request), .i_accept(frame_accept), .i_accepted(command_accepted),
        .i_first_ready(prepare_read_state_eligible), .i_continue_ready(prefetch_continue_eligible),
        .i_fault(capacity_fault), .o_read_enable(prefetch_read_selected)
    );
    always_comb begin
        prefetch_eligible = prepare_read_eligible ||
            (prefetch_continue_eligible && !cancel_prepared);
        case (^{frame_request, frame_accept, command_accepted, command_present})
            1'b0, 1'b1: prefetch_eligible =
                (frame_request && prefetch_requested_eligible) ||
                ((frame_accept || command_accepted) && prefetch_continue_eligible);
            default: ;
        endcase
    end
    always_comb begin
        case (capacity_fault)
            1'b0: begin
                prefetch_prepare = prepare_read_eligible;
                prefetch_fire = prefetch_eligible;
            end
            1'b1: begin
                prefetch_prepare = 1'b0;
                prefetch_fire = 1'b0;
            end
            default: begin
                prefetch_prepare = prepare_start && !request_q.init && !prepare_read_conflict;
                prefetch_fire = prefetch_prepare ||
                    (command_present && !frame_init_q && read_remaining_q &&
                     prefetch_credit_available &&
                     !capacity_fault && !clear_metadata && !cancel_prepared);
            end
        endcase
        // 已完成的首行、后续行状态与容量状态统一参与末级读取选择。
        case (^{capacity_fault, frame_request, frame_accept, command_accepted, command_present})
            1'b0, 1'b1: prefetch_fire = prefetch_read_selected;
            default: ;
        endcase
    end
    wire [p_cursor_bits-1:0] read_issue_cursor = prefetch_prepare ? p_cursor_bits'(initial_row) : read_cursor;
    // 首行与后续行的地址提前形成，实际读取由预取使能控制。
    wire memory_address_prepare = request_pending_q &&
        (!command_present || frame_init_q || replay_complete_q);
    wire [p_cursor_bits-1:0] memory_read_cursor = memory_address_prepare ?
        p_cursor_bits'(initial_row) : read_cursor;
    wire [ROTATION_BITS-1:0] read_issue_rotation = prefetch_prepare ? ROTATION_BITS'(initial_bank) : read_rotation;
    wire read_issue_wrap = 32'(read_issue_rotation) + 32'd4 >= 32'(pool_bank_count_q);
    logic [p_cursor_bits-1:0] read_next_cursor;
    if (EXTERNAL_RAM != 0 && p_fixed_ps_channels) begin : g_fixed_cursor_advance
        logic [p_cursor_bits-1:0] current_next_cursor, initial_next_cursor;
        // 两个地址各自完成递增，首行读取资格仅选择已经得到的地址。
        ps_frame_address_increment #(.p_width(p_cursor_bits)) u_current_next (
            .i_address(read_cursor), .o_next(current_next_cursor)
        );
        ps_frame_address_increment #(.p_width(p_cursor_bits)) u_initial_next (
            .i_address(p_cursor_bits'(initial_row)), .o_next(initial_next_cursor)
        );
        assign read_next_cursor = prefetch_prepare ? initial_next_cursor : current_next_cursor;
    end else begin : g_rotating_cursor_advance
        assign read_next_cursor = read_issue_cursor + p_cursor_bits'(read_issue_wrap);
    end
    wire [ROTATION_BITS-1:0] read_next_rotation = (EXTERNAL_RAM != 0 && p_fixed_ps_channels) ? '0 :
        ROTATION_BITS'(32'(read_issue_rotation) + 32'd4 - (read_issue_wrap ? 32'(pool_bank_count_q) : 32'd0));
    wire [BANKS-1:0] payload_ram_read_en,payload_ram_write_en;
    wire [127:0] payload_read_data [BANKS];
    wire [127:0] incoming_words [4];
    for(genvar word=0;word<4;word++) begin:g_port
        wire [ROTATION_BITS:0] rsum={1'b0,read_issue_rotation}+(ROTATION_BITS+1)'(word);
        wire [ROTATION_BITS:0] wsum={1'b0,write_rotation}+(ROTATION_BITS+1)'(word);
        wire rwrap=32'(rsum)>=pool_bank_count_q;
        wire wwrap=32'(wsum)>=pool_bank_count_q;
        wire [ROTATION_BITS-1:0] rb=ROTATION_BITS'(rwrap ? 32'(rsum)-32'(pool_bank_count_q) : 32'(rsum));
        wire [ROTATION_BITS-1:0] wb=ROTATION_BITS'(wwrap ? 32'(wsum)-32'(pool_bank_count_q) : 32'(wsum));
        assign ram_read_en[word]=prefetch_fire;
        assign ram_write_en[word]=encode_commit_valid;
        assign ram_read_addr[word] = EXTERNAL_RAM != 0 && p_fixed_ps_channels ?
            RAM_ADDR_BITS'(memory_read_cursor) : EXTERNAL_RAM != 0 ?
            RAM_ADDR_BITS'({rb,BANK_ADDR_BITS'(read_issue_cursor+rwrap)}) : RAM_ADDR_BITS'(read_issue_cursor);
        assign ram_write_addr[word] = EXTERNAL_RAM != 0 && !p_fixed_ps_channels ?
            RAM_ADDR_BITS'({wb,BANK_ADDR_BITS'(write_cursor+wwrap)}) : RAM_ADDR_BITS'(write_cursor);
        assign ram_write_data[word]=encode_commit_packet[word*128+:128];
        assign incoming_words[word]=EXTERNAL_RAM!=0 ? ram_read_data[word] : payload_read_data[word];
    end
    for(genvar bank=0;bank<BANKS;bank++) begin:g_payload
        wire [3:0] rselect,wselect;
        for(genvar port_index=0;port_index<4;port_index++)begin:g_select
            assign rselect[port_index]=ram_read_en[port_index] &&
                (EXTERNAL_RAM!=0 ? (32'(ram_read_addr[port_index])>>BANK_ADDR_BITS)==bank : port_index==bank);
            assign wselect[port_index]=ram_write_en[port_index] &&
                (EXTERNAL_RAM!=0 ? (32'(ram_write_addr[port_index])>>BANK_ADDR_BITS)==bank : port_index==bank);
        end
        assign payload_ram_read_en[bank]=|rselect;
        assign payload_ram_write_en[bank]=|wselect;
        if(EXTERNAL_RAM==0) begin:g_internal
            reg [127:0] payload_ram [BANK_DEPTH];
            reg [127:0] data_q;
            always @(posedge clk) begin
                if(prefetch_fire) data_q<=payload_ram[read_issue_cursor];
                if(encode_commit_valid) payload_ram[write_cursor]<=encode_commit_packet[bank*128+:128];
            end
            assign payload_read_data[bank]=data_q;
        end else begin:g_external
            assign payload_read_data[bank]=0;
        end
    end

    reg ram_read_valid, decoder_done;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ram_read_valid <= 1'b0;
            decoder_done <= 1'b0;
        end else if (clear_metadata || cancel_prepared) begin
            ram_read_valid <= 1'b0;
            decoder_done <= 1'b0;
        end else begin
            ram_read_valid <= prefetch_fire;
            decoder_done <= ram_read_valid;
        end
    end
    wire decoded_read_en=replay_active && decoded_count!=0 && !capacity_fault;
    wire replay_bypass=replay_active && decoded_count==0 && decoder_done && !capacity_fault;
    wire decoded_write_en=decoder_done && !replay_bypass && !capacity_fault;
    wire replay_consume=decoded_read_en || replay_bypass;
    assign replay_data = replay_valid ? replay_row_data : 512'd0;
    // 已发出的首行读请求可覆盖接受命令后的重放准备时间，
    // 接受与重放触发同拍时也保持同步读写顺序。
    (* keep = "true" *) logic complete_data_idle;
    (* keep = "true" *) logic complete_control_eligible;
    (* keep = "true" *) logic ready_existing, ready_prepare_idle, ready_prepare_complete;
    logic ready_prepare_context, ready_idle_selected, ready_complete_selected;
    logic ready_selected, ready_result;

    // 返回队列的空闲条件与帧控制状态并行形成，完成交接在末级合并。
    assign complete_data_idle = !ram_read_valid && !decoder_done &&
        decoded_count == 0 && decoder_inflight == 0;
    assign complete_control_eligible = command_present && command_accepted && input_ended &&
        !replay_armed && !replay_active && !replay_launch_q &&
        (!encoder_done || (encoder_done && commit_next_complete_q)) &&
        (frame_final_q || commit_complete_q || (encoder_done && commit_next_complete_q)) &&
        (frame_init_q || replay_complete_q);
    assign complete_eligible = complete_control_eligible && complete_data_idle;
    // 保存的请求资格与完成条件并行选择，不再经过帧编号比较。
    ps_frame_prepare_enable u_prepare_enable (
        .i_request_qualified(request_qualified_q), .i_command_present(command_present),
        .i_control_complete(complete_control_eligible), .i_data_idle(complete_data_idle),
        .o_eligible(prepare_state_selected)
    );
    ps_frame_prepare_branch u_prepare_read (
        .i_request_qualified(prepare_state_eligible), .i_initial_or_other(request_initial_or_other_q),
        .i_encoder_done(encoder_done), .i_commit_next_complete(commit_next_complete_q),
        .i_single_row(frame_single_row_q), .i_branch_enable(!request_q.init),
        .o_ready(prepare_read_state_selected)
    );
    // 已保存命令、空闲命令槽和本拍完成的命令分别形成接收资格。
    // 新帧的首行读取只检查同址提交冲突，直接参与帧接收的最终选择。
    assign ready_existing = command_present && !command_accepted &&
        (frame_init_q || read_index != 0);
    assign ready_prepare_context = configuration_ready && request_pending_q &&
        request_q.legal && request_fits_q &&
        (request_q.init || !(encoder_done && commit_next_complete_q &&
         request_q.id == frame_id_q && frame_single_row_q));
    // 接收边沿保存的请求资格与帧关系直接参与六输入分支选择。
    ps_frame_prepare_branch u_prepare_idle (
        .i_request_qualified(request_qualified_q), .i_initial_or_other(request_initial_or_other_q),
        .i_encoder_done(encoder_done), .i_commit_next_complete(commit_next_complete_q),
        .i_single_row(frame_single_row_q), .i_branch_enable(!command_present),
        .o_ready(ready_idle_selected)
    );
    ps_frame_prepare_branch u_prepare_complete (
        .i_request_qualified(request_qualified_q), .i_initial_or_other(request_initial_or_other_q),
        .i_encoder_done(encoder_done), .i_commit_next_complete(commit_next_complete_q),
        .i_single_row(frame_single_row_q), .i_branch_enable(complete_control_eligible),
        .o_ready(ready_complete_selected)
    );
    always_comb begin
        ready_prepare_idle = ready_prepare_context && !command_present;
        ready_prepare_complete = ready_prepare_context && complete_control_eligible;
        case (^{configuration_ready, request_pending_q, request_q.legal, request_fits_q,
                request_q.init, request_q.id, frame_id_q, encoder_done, commit_next_complete_q,
                frame_single_row_q, command_present, complete_control_eligible,
                request_qualified_q, request_initial_or_other_q})
            1'b0, 1'b1: begin
                ready_prepare_idle = ready_idle_selected;
                ready_prepare_complete = ready_complete_selected;
            end
            default: begin end
        endcase
    end
    ps_frame_ready_select u_frame_ready (
        .i_request(frame_request), .i_fault(capacity_fault),
        .i_existing(ready_existing), .i_idle(ready_prepare_idle),
        .i_completing(ready_prepare_complete), .i_data_idle(complete_data_idle),
        .o_ready(ready_selected)
    );
    always_comb begin
        ready_result = frame_request && !capacity_fault &&
            ((command_present && !command_accepted && (frame_init_q || read_index!=0)) ||
             (prepare_start && (request_q.init || prefetch_prepare)));
        case (^{frame_request, capacity_fault, command_present, command_accepted,
            frame_init_q, read_index, request_q.init, configuration_ready, request_pending_q,
            request_q.legal, request_fits_q, input_ended, replay_armed, replay_active,
            replay_launch_q, encoder_done, commit_next_complete_q, ram_read_valid, decoder_done,
            decoded_count, decoder_inflight, frame_final_q, commit_complete_q, replay_complete_q,
            request_q.id, frame_id_q, frame_single_row_q})
            1'b0, 1'b1: ready_result = ready_selected;
            default: ;
        endcase
    end
    assign frame_ready = ready_result;
    always_comb begin
        case (capacity_fault)
            1'b0: complete_now = complete_eligible;
            1'b1: complete_now = 1'b0;
            default: complete_now = command_present && command_accepted && input_ended && !capacity_fault &&
                !replay_armed && !replay_active && !replay_launch_q && (!encoder_done || last_commit_now) &&
                !ram_read_valid && !decoder_done && decoded_count==0 && decoder_inflight==0 &&
                (frame_final_q || commit_complete_q || last_commit_now) && (frame_init_q || replay_complete_q);
        endcase
    end
    // 存储返回行直接写入队列，完成指示仍经过原有控制流水级。
    // 重放接收边沿同步读取下一行，读取结果与 replay_valid 在同一周期输出。
    // 预取最多占用深度减一行，连续读取与写入使用不同物理位置。
    assign decoded_i_wr_en = ram_read_valid && !capacity_fault && !clear_metadata && !cancel_prepared;
    assign decoded_i_wr_addr = decoded_write_pointer;
    assign decoded_i_wr_data = {incoming_words[3], incoming_words[2], incoming_words[1], incoming_words[0]};
    assign decoded_i_wr_mask = 1'b1;
    assign decoded_i_rd_en = replay_consume;
    assign decoded_i_rd_addr = decoded_read_pointer;
    regfile #(
        .p_data_width(512), .p_depth(DECODE_FIFO_ROWS), .p_addr_width(FIFO_PTR_BITS),
        .p_write_unit(512), .p_sync_read(1'b1), .p_ram_style("block")
    ) u_decoded (
        .clk(clk), .i_wr_en(decoded_i_wr_en), .i_wr_addr(decoded_i_wr_addr),
        .i_wr_data(decoded_i_wr_data), .i_wr_mask(decoded_i_wr_mask),
        .i_rd_en(decoded_i_rd_en), .i_rd_addr(decoded_i_rd_addr), .o_rd_data(replay_row_data)
    );
    // 行数条件与各计数器同时更新，控制端直接读取已保存的结果。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            replay_complete_q <= 1'b1;
            read_remaining_q <= 1'b0;
        end else if (clear_metadata || cancel_prepared) begin
            replay_complete_q <= frame_rows_q == LENGTH_BITS'(0);
            read_remaining_q <= LENGTH_BITS'(0) < frame_rows_q;
        end else if (prepare_start) begin
            replay_complete_q <= LENGTH_BITS'(request_q.rows) == LENGTH_BITS'(0);
            read_remaining_q <= LENGTH_BITS'(prefetch_prepare) < LENGTH_BITS'(request_q.rows);
        end else begin
            if (replay_active && replay_consume) begin
                replay_complete_q <= LENGTH_BITS'(replay_index + LENGTH_BITS'(1)) == frame_rows_q;
            end
            if (prefetch_fire) begin
                read_remaining_q <= LENGTH_BITS'(read_index + LENGTH_BITS'(1)) < frame_rows_q;
            end
        end
    end
    logic capacity_set, capacity_accept_error, capacity_other_error, capacity_context_open;
    (* keep = "true" *) logic capacity_accept_set, capacity_wait_set;
    // 接受命令的错误资格和在途错误独立形成，接受脉冲只参与最终置位选择。
    assign capacity_accept_error = !frame_ready || !frame_request ||
        frame_id != (prepare_start ? request_q.id : frame_id_q);
    assign capacity_other_error =
        (frame_request && configuration_ready && request_pending_q && !request_q.legal) ||
        (write_frame_end && (!command_accepted || replay_armed || (!frame_final_q && !capture_length_match))) ||
        (replay_active && !replay_consume);
    assign capacity_context_open = frame_request || command_accepted ||
        !(request_pending_q || command_present);
    assign capacity_accept_set = capacity_accept_error || capacity_other_error;
    assign capacity_wait_set = capacity_context_open && capacity_other_error;
    always_comb begin
        case (^{frame_accept, capacity_accept_error, capacity_other_error,
                capacity_context_open, cancel_prepared})
            1'b0, 1'b1: capacity_set = (frame_accept && capacity_accept_set) || capacity_wait_set;
            default: begin
                capacity_set = 1'b0;
                if (cancel_prepared) begin
                end else begin
                    if (frame_request && configuration_ready && request_pending_q && !request_q.legal)
                        capacity_set = 1'b1;
                    if (frame_accept) begin
                        if (!frame_ready || !frame_request || frame_id != (prepare_start ? request_q.id : frame_id_q))
                            capacity_set = 1'b1;
                    end
                    if (write_frame_end) begin
                        if (!command_accepted || replay_armed || (!frame_final_q && !capture_length_match))
                            capacity_set = 1'b1;
                    end
                    if (replay_active) begin
                        if (!replay_consume) capacity_set = 1'b1;
                    end
                end
            end
        endcase
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) capacity_fault <= 1'b0;
        else if (clear_metadata) capacity_fault <= configuration_pending && !configuration_valid;
        else if (capacity_set) capacity_fault <= 1'b1;
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            frame_complete<=0;frame_valid<=0;frame_empty_q<=1;
            command_present<=0;command_accepted<=0;input_ended<=0;replay_armed<=0;replay_active<=0;
            replay_launch_q<=0;
            frame_id_q<=0;frame_rows_q<=0;frame_single_row_q<=0;frame_init_q<=0;frame_final_q<=0;
            capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
            read_cursor<=0;write_cursor<=0;read_rotation<=0;write_rotation<=0;
            decoded_count<=0;decoder_inflight<=0;decoded_write_pointer<=0;decoded_read_pointer<=0;replay_valid<=0;
            for(integer f=0;f<FRAME_COUNT;f++)frame_lengths[f]<=0;
        end else if(clear_metadata) begin
            frame_complete<=0;frame_valid<=0;frame_empty_q<=1;command_present<=0;command_accepted<=0;input_ended<=0;
            replay_armed<=0;replay_active<=0;capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
            replay_launch_q<=0;
            decoded_count<=0;decoder_inflight<=0;decoded_write_pointer<=0;decoded_read_pointer<=0;replay_valid<=0;
        end else if (cancel_prepared) begin
            // 未接受的请求只释放准备状态，已提交帧的目录与数据保持有效。
            frame_complete <= 1'b0;
            command_present <= 1'b0;
            command_accepted <= 1'b0;
            input_ended <= 1'b0;
            replay_armed <= 1'b0;
            replay_active <= 1'b0;
            replay_launch_q <= 1'b0;
            capture_count <= '0;
            commit_count <= '0;
            read_index <= '0;
            replay_index <= '0;
            decoded_count <= '0;
            decoder_inflight <= '0;
            decoded_write_pointer <= '0;
            decoded_read_pointer <= '0;
            replay_valid <= 1'b0;
        end else begin
            frame_complete<=0;replay_valid<=replay_consume;
            decoded_count<=decoded_count+(FIFO_PTR_BITS+1)'(decoded_write_en ? 1'b1 : 1'b0)-
                (FIFO_PTR_BITS+1)'(decoded_read_en ? 1'b1 : 1'b0);
            decoder_inflight<=decoder_inflight+(FIFO_PTR_BITS+1)'(prefetch_fire ? 1'b1 : 1'b0)-
                (FIFO_PTR_BITS+1)'(decoder_done ? 1'b1 : 1'b0);
            if(frame_accept)begin
                command_accepted<=1;
            end
            if(encoder_start)capture_count<=capture_count+1;
            if(encode_commit_valid)begin
                commit_count<=commit_count+1;
                if (EXTERNAL_RAM != 0 && p_fixed_ps_channels) begin
                    write_cursor <= write_cursor + p_cursor_bits'(1);
                end else if(32'(write_rotation)+4>=pool_bank_count_q)begin
                    write_cursor<=write_cursor+1;write_rotation<=ROTATION_BITS'(32'(write_rotation)+4-pool_bank_count_q);
                end else write_rotation<=write_rotation+ROTATION_BITS'(4);
            end
            if(prefetch_fire)begin
                read_index<=read_index+1;
                read_cursor<=read_next_cursor;
                read_rotation<=read_next_rotation;
            end
            if(write_frame_end)begin
                input_ended<=1;
            end
            if (decoded_i_wr_en) begin
                decoded_write_pointer <= decoded_write_pointer + 1'b1;
            end
            if (replay_consume) begin
                decoded_read_pointer <= decoded_read_pointer + 1'b1;
            end
            if(replay_trigger && replay_armed && (command_accepted || frame_accept))begin replay_active<=1;replay_armed<=0;end
            if(replay_launch_q)begin replay_active<=1;replay_launch_q<=0;end
            if (replay_active) begin
                if (!replay_consume) begin
                end else begin
                    replay_index<=replay_index+1;
                    if(replay_index+1==frame_rows_q)replay_active<=0;
                end
            end
            if(complete_now)begin
                frame_complete<=1;command_present<=0;command_accepted<=0;
                frame_valid[frame_id_q]<=!frame_final_q;frame_lengths[frame_id_q]<=frame_final_q ? 0 : frame_rows_q;
                frame_empty_q <= frame_valid_after_complete == '0;
            end
            // 完成拍使用当前写地址，随后命令从自身计数与地址开始。
            if(prepare_start)begin
                command_present<=1;command_accepted<=frame_accept;input_ended<=0;
                frame_id_q<=request_q.id;frame_rows_q<=LENGTH_BITS'(request_q.rows);
                frame_single_row_q <= LENGTH_BITS'(request_q.rows) == LENGTH_BITS'(1);
                frame_init_q<=request_q.init;frame_final_q<=request_q.final_row;
                replay_armed<=!request_q.init && !(frame_accept && replay_trigger);replay_active<=0;
                // 首读与接受同拍时，同拍重放触发延迟到同步读返回后启动。
                replay_launch_q<=!request_q.init && frame_accept && replay_trigger;
                capture_count<=0;commit_count<=0;read_index<=LENGTH_BITS'(prefetch_prepare);replay_index<=0;
                read_cursor <= prefetch_prepare ? read_next_cursor : p_cursor_bits'(initial_row);
                write_cursor <= p_cursor_bits'(initial_row);
                read_rotation<=prefetch_prepare ? read_next_rotation : ROTATION_BITS'(initial_bank);
                write_rotation<=ROTATION_BITS'(initial_bank);
            end
        end
    end
endmodule

`default_nettype wire
