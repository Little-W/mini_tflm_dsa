// 调度物理输出帧，并保存每一帧沿归约维度的执行进度。
// 准备阶段保存切片取整值，互斥的候选行与下一组行共用地址计算。
`default_nettype none

module ps_window_scheduler #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned FRAME_COUNT = 16,
    parameter int unsigned MAX_REUSE_TILES = 0
) (
    input wire logic clk /* 工作时钟 */, rst_n /* 低有效复位 */,
    input wire logic start /* 接收当前矩阵任务并启动帧调度 */,
    input wire logic [31:0] stream_rows /* 流式操作数方向的总行数 */, stationary_rows /* 驻留操作数方向的总行数 */, reduction /* 矩阵任务的完整归约长度 */,
    input wire logic [31:0] reuse_rows /* 每个帧沿流式方向保留的矩阵块数 */, window_frames /* 窗口内允许同时保留的部分和帧数 */,
    input wire logic [31:0] slice_tiles = 32'd0 /* 单条帧命令沿流式行方向处理的矩阵块数 */,
    input wire logic [1:0] config_error /* 任务配置检查产生的错误码 */,
    output logic ready /* 调度器空闲并可接收新任务 */,
    output logic done_valid /* 任务完成状态有效 */,
    input wire logic done_ready /* 上层可接收任务完成状态 */,
    output logic [1:0] err_code /* 任务正常完成或配置错误的状态码 */,
    output logic command_valid /* 当前帧命令及其参数有效 */,
    input wire logic command_ready /* 执行通路可接收当前帧命令 */,
    input wire logic command_pressure /* 部分和存储要求提前结束当前帧命令 */,
    input wire logic command_complete /* 当前帧命令已完成数据处理 */,
    output logic [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id /* 当前帧命令使用的物理部分和槽号 */,
    output logic [31:0] p0 /* 当前帧沿流式方向的起始行位置 */, q0 /* 当前帧命令的归约起点 */, column0 /* 当前帧沿驻留方向的起始位置 */, rows /* 当前帧沿流式方向的有效行数 */, cols /* 当前帧沿驻留方向的有效行数 */, count_k /* 当前帧命令处理的归约元素数 */, reserve_rows /* 当前帧命令需要预留的部分和行数 */,
    output logic frame_init /* 当前命令开始该帧的首次归约 */, frame_final /* 当前命令完成该帧的最终归约 */,
    output logic command_active /* 当前帧命令已经接收且尚未完成 */,
    output logic lookahead_valid /* 下一帧预读参数有效 */,
    output logic [31:0] lookahead_q0 /* 下一帧预读的归约起点 */, lookahead_column /* 下一帧预读的驻留方向起始位置 */, lookahead_cols /* 下一帧预读的驻留方向有效行数 */, lookahead_count_k /* 下一帧预读需要处理的归约元素数 */);
    localparam int unsigned ID_W = (FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1;
    localparam int unsigned SHIFT = $clog2(SIZE);
    localparam int unsigned TILE_W = 32 - SHIFT;
    localparam int unsigned ROW_PART_W = MAX_REUSE_TILES > 1 ? $clog2(MAX_REUSE_TILES) :
        MAX_REUSE_TILES == 1 ? 1 : TILE_W;
    localparam int unsigned ROW_COUNT_W = MAX_REUSE_TILES != 0 ? $clog2(MAX_REUSE_TILES * SIZE + 1) : 32;
    typedef enum logic [3:0] {IDLE, PREPARING, PREPARE_PARTS, PREPARE_CAPS,
                              PREPARE_PRODUCTS, PREPARE_TARGET, OPENING, SWEEPING, DRAINING, COMPLETE} phase_t;
    phase_t phase;
    logic incoming_window_oversized, incoming_reuse_oversized, incoming_slice_oversized;
    logic unused_window_equal, unused_reuse_equal, unused_slice_equal;
    (* keep = "true" *) logic incoming_dimensions_invalid, incoming_window_invalid;
    (* keep = "true" *) logic incoming_reuse_invalid, incoming_slice_invalid;
    // 配置尺寸、窗口上界和切片范围并行检查，状态更新只合并单比特结果。
    unsigned_compare #(.p_width(32)) u_window_bound (
        .i_a(32'(FRAME_COUNT)), .i_b(window_frames),
        .o_less(incoming_window_oversized), .o_equal(unused_window_equal)
    );
    unsigned_compare #(.p_width(32)) u_reuse_bound (
        .i_a(32'(MAX_REUSE_TILES)), .i_b(reuse_rows),
        .o_less(incoming_reuse_oversized), .o_equal(unused_reuse_equal)
    );
    unsigned_compare #(.p_width(32)) u_slice_bound (
        .i_a(reuse_rows), .i_b(slice_tiles),
        .o_less(incoming_slice_oversized), .o_equal(unused_slice_equal)
    );
    assign incoming_dimensions_invalid = stream_rows == 0 || stationary_rows == 0 || reduction == 0;
    assign incoming_window_invalid = window_frames == 0 || incoming_window_oversized;
    assign incoming_reuse_invalid = reuse_rows == 0 || (reuse_rows >> (32-SHIFT)) != 0 ||
        (MAX_REUSE_TILES != 0 && incoming_reuse_oversized);
    logic [ROW_COUNT_W-1:0] cfg_rows, cfg_slice_rows;
    logic [ID_W:0] cfg_window;
    logic [31:0] final_q0, final_column0;
    logic [SHIFT:0] final_k_count, final_column_count;
    localparam int unsigned SLICE_SHIFT_W = ROW_COUNT_W > 2 ? $clog2(ROW_COUNT_W) : 1;
    logic [SLICE_SHIFT_W-1:0] slice_shift;
    logic sliced;
    logic next_part_is_last;
    logic [31:0] row_base;
    logic [31:0] stream_rows_remaining, next_stream_rows_remaining;
    logic row_group_complete;
    logic [31:0] row_advance_i_a, row_advance_i_b, row_advance_o_sum;
    logic row_advance_i_carry, row_advance_o_carry;
    logic [31:0] stream_remaining_i_a, stream_remaining_i_b, stream_remaining_o_sum;
    logic stream_remaining_i_carry, stream_remaining_o_carry;
    logic [31:0] stream_remaining_reference_sum, stream_remaining_fast;
    logic unused_stream_fast_carry;
    logic [31:0] selected_row_offset, shared_row_sum, row_update_sum;
    logic unused_shared_row_carry;

    logic [TILE_W:0] next_column_tile, column_after_part;
    logic [ROW_PART_W:0] next_row_part;
    logic [ID_W:0] opened, target;
    logic [FRAME_COUNT-1:0] cursor_mask;
    (* keep = "true" *) logic [ID_W:0] opened_after_init;
    logic [ID_W:0] active_after_frame;
    logic [FRAME_COUNT-1:0] live;
    logic [TILE_W-1:0] frame_k [FRAME_COUNT];
    logic [TILE_W-1:0] active_frame_k, frame_k_after_command;
    localparam int p_metadata_width = TILE_W + ROW_PART_W + ROW_COUNT_W;
    logic frame_metadata_i_wr_en, frame_metadata_i_wr_mask;
    logic [ID_W-1:0] frame_metadata_i_wr_addr;
    logic [p_metadata_width-1:0] frame_metadata_i_wr_data;
    logic [1:0] frame_metadata_i_rd_en;
    logic [1:0][ID_W-1:0] frame_metadata_i_rd_addr;
    logic [1:0][p_metadata_width-1:0] frame_metadata_o_rd_data;
    logic [TILE_W-1:0] selected_column, predicted_column;
    logic [ROW_PART_W-1:0] selected_row_part;
    logic [ROW_COUNT_W-1:0] selected_rows;
    logic protected_valid, resume_valid;
    logic [ID_W-1:0] protected_id, resume_id, active_id;
    logic active_init, active_final;
    logic [31:0] active_q0, active_column, active_row, active_rows;
     logic [31:0] active_q_next, reduction_last, stationary_rows_last;
    // 预测和终止位置共享完整模宽算术，状态选择仅选择已计算的结果。
    assign active_q_next = active_q0 + 32'(SIZE);
    assign reduction_last = reduction - 32'd1;
    assign stationary_rows_last = stationary_rows - 32'd1;
    // 帧资格、分组存在性和状态选择各自描述独立的组合关系。
    logic candidate_found;
    logic [ID_W-1:0] candidate_id, scanned_id, scanned_reference, selected_id_q;
    (* keep = 1 *) logic [ID_W-1:0] scan_open_candidate, scan_protected_candidate;
    (* keep = 1 *) logic [ID_W-1:0] scan_after_candidate, scan_wrap_candidate;
    logic selected_id_valid, selected_init_q;
    logic [ROW_COUNT_W-1:0] selected_initial_offset;
    logic [31:0] initial_row_i_a, initial_row_i_b, initial_row_o_sum;
    logic initial_row_i_carry, initial_row_o_carry;
    logic [31:0] stored_row_i_a, stored_row_i_b, stored_row_o_sum;
    logic stored_row_i_carry, stored_row_o_carry;
    logic candidate_init;
    logic command_buffer_valid;
    logic command_buffer_recoverable, command_buffer_opening;
    logic [ID_W-1:0] command_buffer_id;
    logic command_buffer_init, command_buffer_final;
    logic [31:0] command_buffer_row, command_buffer_q, command_buffer_column;
    logic [ROW_COUNT_W-1:0] command_buffer_rows;
    logic [SHIFT:0] command_buffer_cols, command_buffer_k;
    logic [31:0] candidate_q, candidate_column;
    logic [SHIFT:0] candidate_cols, candidate_k;
    logic candidate_final;
    logic candidate_final_match;
    logic [1:0] candidate_final_half;
    // 两个半字分别进行相等比较，结果同时供命令描述与恢复资格使用。
    for (genvar half_index = 0; half_index < 2; half_index++) begin : g_candidate_final
        parallel_equal #(.p_width(16)) u_compare (
            .i_a(candidate_q[16*half_index+:16]), .i_b(final_q0[16*half_index+:16]),
            .o_equal(candidate_final_half[half_index]));
    end
    assign candidate_final_match = &candidate_final_half;
    wire candidate_ready = candidate_found && selected_id_valid;
    logic [FRAME_COUNT-1:0] frame_open;
    logic [FRAME_COUNT-1:0] candidate_eligible, candidate_after_cursor;
    logic candidate_exists, candidate_after_exists;
    logic [FRAME_COUNT-1:0] candidate_live_after, candidate_open_after;
    logic [ID_W-1:0] eligible_first_id, after_first_id;
    logic [TILE_W:0] column_tiles, remaining_columns;
    logic [TILE_W:0] incoming_column_tiles;
    logic [TILE_W:0] remaining_columns_i_a, remaining_columns_i_b, remaining_columns_o_sum;
    logic remaining_columns_i_carry, remaining_columns_o_carry;
    logic [TILE_W:0] remaining_columns_reference_sum, remaining_columns_fast;
    logic unused_columns_fast_carry;
    logic [ROW_COUNT_W-1:0] current_rows;
    logic [ROW_PART_W:0] group_parts;
    logic [31:0] candidate_row, candidate_rows, initial_slice_rows;
    logic [SLICE_SHIFT_W-1:0] initial_slice_shift;
    wire [ROW_COUNT_W-1:0] next_slice_offset = ROW_COUNT_W'(next_row_part) << slice_shift;
    wire [ROW_COUNT_W-1:0] next_slice_remaining = current_rows - selected_initial_offset;

    // 行起点和剩余行数保持相同的模加关系，准备阶段直接比较已保存的余量。
    assign row_advance_i_a = row_base;
    assign row_advance_i_b = 32'(current_rows);
    assign row_advance_i_carry = 1'b0;
    parallel_prefix_add #(.p_width(32)) u_row_advance (
        .i_a(row_advance_i_a), .i_b(row_advance_i_b), .i_carry(row_advance_i_carry),
        .o_sum(row_advance_o_sum), .o_carry(row_advance_o_carry)
    );
    assign stream_remaining_i_a = stream_rows_remaining;
    assign stream_remaining_i_b = ~32'(current_rows);
    assign stream_remaining_i_carry = 1'b1;
    parallel_prefix_add #(.p_width(32)) u_stream_remaining (
        .i_a(stream_remaining_i_a), .i_b(stream_remaining_i_b), .i_carry(stream_remaining_i_carry),
        .o_sum(stream_remaining_reference_sum), .o_carry(stream_remaining_o_carry)
    );
    parallel_prefix_add #(
        .p_width(32), .p_preserve_groups(1'b1), .p_dsp_split_width(16),
        .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)
    ) u_stream_remaining_arithmetic (
        .i_a(stream_remaining_i_a), .i_b(stream_remaining_i_b), .i_carry(1'b1),
        .o_sum(stream_remaining_fast), .o_carry(unused_stream_fast_carry)
    );
    // 两段定宽算术共同形成剩余行数，未知输入使用完整分组加法的传播关系。
    always_comb begin
        stream_remaining_o_sum = stream_remaining_reference_sum;
        case (^{stream_remaining_i_a, stream_remaining_i_b})
            1'b0, 1'b1: stream_remaining_o_sum = stream_remaining_fast;
            default: ;
        endcase
    end

    function automatic logic [31:0] minimum(input logic [31:0] a, b);
        return (a < b) ? a : b;
    endfunction

    // 帧计数的各位进位并行求值，预测选择与状态更新共用同一结果。
    assign opened_after_init[0] = ~opened[0];
    for (genvar opened_bit = 1; opened_bit <= ID_W; opened_bit++) begin : g_opened_increment
        assign opened_after_init[opened_bit] = opened[opened_bit] ^ (&opened[opened_bit-1:0]);
    end

    assign active_after_frame[0] = ~active_id[0];
    for (genvar active_bit = 1; active_bit < ID_W; active_bit++) begin : g_active_increment
        assign active_after_frame[active_bit] = active_id[active_bit] ^ (&active_id[active_bit-1:0]);
    end
    assign active_after_frame[ID_W] = &active_id;

    // 各组并行形成低位传播条件，组内只执行至多 8 位的定宽增量。
    for (genvar column_group = 0; column_group < (TILE_W+8)/8; column_group++) begin : g_column_increment
        localparam int unsigned p_first = 8 * column_group;
        localparam int unsigned p_bits = (TILE_W+1-p_first < 8) ? TILE_W+1-p_first : 8;
        logic column_carry;

        if (column_group == 0) begin : g_first
            assign column_carry = 1'b1;
        end else begin : g_upper
            assign column_carry = &next_column_tile[p_first-1:0];
        end
        assign column_after_part[p_first +: p_bits] =
            next_column_tile[p_first +: p_bits] + p_bits'(column_carry);
    end

    assign active_frame_k = frame_k[active_id];
    // 帧位置从目录读出后分组递增，各组直接检查其低位传播条件。
    for (genvar k_group = 0; k_group < (TILE_W+7)/8; k_group++) begin : g_frame_k_increment
        localparam int unsigned p_first = 8 * k_group;
        localparam int unsigned p_bits = (TILE_W-p_first < 8) ? TILE_W-p_first : 8;
        logic k_carry;

        if (k_group == 0) begin : g_first
            assign k_carry = 1'b1;
        end else begin : g_upper
            assign k_carry = &active_frame_k[p_first-1:0];
        end
        assign frame_k_after_command[p_first +: p_bits] =
            active_frame_k[p_first +: p_bits] + p_bits'(k_carry);
    end

    // 初始切片偏移与帧索引同时保存，候选命令阶段只计算完整行地址。
    assign initial_row_i_a = row_base;
    assign initial_row_i_b = 32'(selected_initial_offset);
    assign initial_row_i_carry = 1'b0;
    parallel_prefix_add #(.p_width(32)) u_initial_row (
        .i_a(initial_row_i_a), .i_b(initial_row_i_b), .i_carry(initial_row_i_carry),
        .o_sum(initial_row_o_sum), .o_carry(initial_row_o_carry)
    );
    assign stored_row_i_a = row_base;
    assign stored_row_i_b = 32'(selected_row_part) << SHIFT;
    assign stored_row_i_carry = 1'b0;
    parallel_prefix_add #(.p_width(32)) u_stored_row (
        .i_a(stored_row_i_a), .i_b(stored_row_i_b), .i_carry(stored_row_i_carry),
        .o_sum(stored_row_o_sum), .o_carry(stored_row_o_carry)
    );
    // 扫描结束时更新下一组行；存在候选帧时计算该帧行地址，两者不会同时接收。
    assign selected_row_offset = (phase == SWEEPING && !candidate_exists) ?
        32'(current_rows) : (selected_init_q ? initial_row_i_b : stored_row_i_b);
    parallel_prefix_add #(
        .p_width(32), .p_preserve_groups(1'b1), .p_dsp_split_width(16),
        .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)
    ) u_shared_row_address (
        .i_a(row_base), .i_b(selected_row_offset), .i_carry(1'b0),
        .o_sum(shared_row_sum), .o_carry(unused_shared_row_carry)
    );
    always_comb begin
        row_update_sum = row_advance_o_sum;
        case (^{row_base, current_rows})
            1'b0, 1'b1: row_update_sum = shared_row_sum;
            default: ;
        endcase
    end

    // 零切片数由原有配置分支处理，其他值按幂次决定分块形状。
    logic [31:0] slice_shape_i_value;
    logic slice_shape_o_valid;
    if (MAX_REUSE_TILES > 0 && MAX_REUSE_TILES < 32'h80000000) begin : g_bounded_slice_check
        localparam int p_slice_bits = $clog2(MAX_REUSE_TILES + 1);
        localparam int p_high_groups = (32 - p_slice_bits + 5) / 6;
        (* keep = 1 *) logic [p_high_groups-1:0] high_zero_groups;
        logic low_shape_valid;
        logic low_exceeds_reuse;
        logic slice_invalid_binary;
        // 复用上限和切片资格共同检查任务；高位非零直接表示切片超出容量。
        for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high_zero
            localparam int p_first = p_slice_bits + 6 * group_index;
            localparam int p_bits = 32-p_first < 6 ? 32-p_first : 6;
            zero_reduce #(.p_width(p_bits)) u_zero (
                .i_value(slice_tiles[p_first +: p_bits]), .o_zero(high_zero_groups[group_index])
            );
        end
        (* keep_hierarchy = "yes" *) onehot_check #(
            .p_width(p_slice_bits), .p_allow_zero(1'b1)
        ) u_low_shape (
            .i_value(slice_tiles[p_slice_bits-1:0]), .o_valid(low_shape_valid)
        );
        assign low_exceeds_reuse = slice_tiles[p_slice_bits-1:0] > reuse_rows[p_slice_bits-1:0];
        assign slice_invalid_binary = !(&high_zero_groups) ||
            !low_shape_valid || low_exceeds_reuse;
        always_comb begin
            incoming_slice_invalid = incoming_slice_oversized || !slice_shape_o_valid;
            case (^{slice_tiles, reuse_rows})
                1'b0, 1'b1: incoming_slice_invalid = slice_invalid_binary;
                default: ;
            endcase
        end
    end else begin : g_full_slice_check
        assign incoming_slice_invalid = incoming_slice_oversized || !slice_shape_o_valid;
    end
    assign slice_shape_i_value = slice_tiles;
    onehot_check #(.p_width(32), .p_allow_zero(1'b1)) u_slice_shape (
      .i_value(slice_shape_i_value),
      .o_valid(slice_shape_o_valid)
    );

    localparam int unsigned CAP_W = ID_W + 1;
    localparam int unsigned PRODUCT_W = 2 * CAP_W + 1;
    logic [ROW_COUNT_W-1:0] prepare_rows;
    localparam int PART_MATH_W = ROW_COUNT_W > (ROW_PART_W+1) ? ROW_COUNT_W : (ROW_PART_W+1);
    logic [PART_MATH_W-1:0] prepare_rows_extended, prepare_rows_last, prepare_rows_last_binary;
    logic [PART_MATH_W-1:0] prepare_rows_lower_nonzero;
    logic [PART_MATH_W-1:0] prepare_rows_last_q;
    logic [PART_MATH_W-1:0] prepare_part_quotient, prepare_part_rounded;
    logic [TILE_W:0] prepare_remaining_columns;
    logic [ROW_PART_W:0] prepare_parts;
    logic [CAP_W-1:0] parts_cap, window_cap, remaining_cap, tail_cap;
    logic [PRODUCT_W-1:0] window_product, available_product;
    logic [CAP_W-1:0] next_target;
    wire [ROW_PART_W:0] remaining_tail = prepare_parts - next_row_part;
    // 切片取整的减一与加一按位计算，移位保持完整表达式宽度。
    // 减法必须在扩展后执行，以保留零输入在 PART_MATH_W 位上的回绕。
    assign prepare_rows_extended = PART_MATH_W'(prepare_rows);
    assign prepare_rows_lower_nonzero[0] = 1'b0;
    for (genvar part_bit = 1; part_bit < PART_MATH_W; part_bit++) begin : g_part_decrement
        assign prepare_rows_lower_nonzero[part_bit] = |prepare_rows_extended[part_bit-1:0];
    end
    assign prepare_rows_last_binary = prepare_rows_extended ^ ~prepare_rows_lower_nonzero;
    always_comb begin
        case (^prepare_rows_extended)
            1'b0, 1'b1: prepare_rows_last = prepare_rows_last_binary;
            default: prepare_rows_last = prepare_rows_extended - PART_MATH_W'(1);
        endcase
    end
    assign prepare_part_quotient = prepare_rows_last_q >> slice_shift;
    assign prepare_part_rounded[0] = ~prepare_part_quotient[0];
    for (genvar part_bit = 1; part_bit < PART_MATH_W; part_bit++) begin : g_part_increment
        assign prepare_part_rounded[part_bit] = prepare_part_quotient[part_bit] ^
            (&prepare_part_quotient[part_bit-1:0]);
    end

    always_ff @(posedge clk) begin
        if (phase == PREPARING) begin
            prepare_rows <= ROW_COUNT_W'(minimum(32'(cfg_rows), stream_rows_remaining));
            // 行数和减一结果在同一准备边沿保存，下一阶段只移位并向上取整。
            prepare_rows_last_q <= PART_MATH_W'(ROW_COUNT_W'(
                minimum(32'(cfg_rows), stream_rows_remaining))) - PART_MATH_W'(1);
            prepare_remaining_columns <= remaining_columns;
            if (!sliced) prepare_parts <= (ROW_PART_W+1)'(1);
        end
        if (phase == PREPARE_PARTS)
            prepare_parts <= sliced ? (ROW_PART_W+1)'(prepare_part_rounded) : (ROW_PART_W+1)'(1);
        if (phase == PREPARE_CAPS) begin
            // 分组结束时直接使用准备结果，完成判断独立于行地址加法。
            next_stream_rows_remaining <= stream_remaining_o_sum;
            row_group_complete <= stream_rows_remaining == 32'(current_rows);
            parts_cap <= 64'(prepare_parts) >= 64'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) : CAP_W'(prepare_parts);
            window_cap <= 64'(cfg_window) >= 64'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) : CAP_W'(cfg_window);
            remaining_cap <= 64'(prepare_remaining_columns) > 64'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) :
                             CAP_W'(prepare_remaining_columns - 32'd1);
            tail_cap <= 64'(remaining_tail) >= 64'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) : CAP_W'(remaining_tail);
        end
        if (phase == PREPARE_PRODUCTS) begin
            window_product <= PRODUCT_W'(window_cap) * PRODUCT_W'(parts_cap);
            available_product <= PRODUCT_W'(remaining_cap) * PRODUCT_W'(parts_cap) + PRODUCT_W'(tail_cap);
        end
    end
    always_comb begin
        next_target = CAP_W'(FRAME_COUNT);
        if (window_product < PRODUCT_W'(next_target)) next_target = CAP_W'(window_product);
        if (available_product < PRODUCT_W'(next_target)) next_target = CAP_W'(available_product);
    end

    // 配置接收时保存列分块数，后续调度直接使用已保存的结果。
    // 低位非零时向上取整，零输入保留完整位宽减法的回绕结果。
    if (SHIFT == 0) begin : g_single_column
        assign incoming_column_tiles = (TILE_W+1)'(stationary_rows);
    end else begin : g_column_tiles
        logic [TILE_W:0] column_quotient, column_rounded;
        logic column_round_up;
        assign column_quotient = (TILE_W+1)'(stationary_rows >> SHIFT);
        assign column_round_up = |stationary_rows[SHIFT-1:0];
        // 列数取整使用分组增量，保留最高位和零输入的回绕值。
        for (genvar group_i = 0; group_i < (TILE_W+8)/8; group_i++) begin : g_round_group
            localparam int unsigned p_first = 8 * group_i;
            localparam int unsigned p_bits = (TILE_W+1-p_first < 8) ? TILE_W+1-p_first : 8;
            logic round_carry;

            if (group_i == 0) begin : g_first
                assign round_carry = column_round_up;
            end else begin : g_upper
                assign round_carry = column_round_up && (&column_quotient[p_first-1:0]);
            end
            assign column_rounded[p_first +: p_bits] =
                column_quotient[p_first +: p_bits] + p_bits'(round_carry);
        end
        assign incoming_column_tiles = stationary_rows == 32'd0 ?
            ((TILE_W+1)'(1) << TILE_W) :
            column_rounded;
    end
    assign current_rows = prepare_rows;
    assign remaining_columns_i_a = column_tiles;
    assign remaining_columns_i_b = ~next_column_tile;
    assign remaining_columns_i_carry = 1'b1;
    // 剩余列数采用低、高段并行算术，保留全部列索引位和输入进位语义。
    parallel_prefix_add #(.p_width(TILE_W+1),
        .p_dsp_split_width(16), .p_parallel_high_prefix(1'b1),
        .p_keep_carry(1'b0), .p_preserve_grouped_unknowns(1'b1)) u_remaining_columns (
        .i_a(remaining_columns_i_a), .i_b(remaining_columns_i_b), .i_carry(remaining_columns_i_carry),
        .o_sum(remaining_columns_reference_sum), .o_carry(remaining_columns_o_carry)
    );
    parallel_prefix_add #(
        .p_width(TILE_W+1), .p_preserve_groups(1'b1), .p_dsp_split_width((TILE_W+2)/2),
        .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)
    ) u_remaining_columns_arithmetic (
        .i_a(remaining_columns_i_a), .i_b(remaining_columns_i_b), .i_carry(1'b1),
        .o_sum(remaining_columns_fast), .o_carry(unused_columns_fast_carry)
    );
    always_comb begin
        remaining_columns_o_sum = remaining_columns_reference_sum;
        case (^{remaining_columns_i_a, remaining_columns_i_b})
            1'b0, 1'b1: remaining_columns_o_sum = remaining_columns_fast;
            default: ;
        endcase
    end
    assign remaining_columns = remaining_columns_o_sum;
    assign group_parts = prepare_parts;
    assign reserve_rows = minimum(32'(cfg_slice_rows), 32'(current_rows));
    assign ready = phase == IDLE;
    assign done_valid = phase == COMPLETE;


    // 候选集合分别编码，状态和扫描起点在末端选择编号。
    // 完成事件先计算帧目录的后继状态，存在性资格与目录在同一边沿保存。
    always_comb begin
        candidate_live_after = live;
        candidate_live_after[active_id] = !active_final;
        candidate_open_after = frame_open;
        if (active_init) begin
            for (int unsigned frame_index = 0; frame_index < FRAME_COUNT; frame_index++)
                candidate_open_after[frame_index] = 32'(frame_index) < opened_after_init;
        end
    end
    assign candidate_after_exists = |candidate_after_cursor;
    ps_scheduler_priority #(.p_frames(FRAME_COUNT), .p_id_width(ID_W)) u_eligible_priority (
        .i_eligible(candidate_eligible), .o_id(eligible_first_id)
    );
    ps_scheduler_priority #(.p_frames(FRAME_COUNT), .p_id_width(ID_W)) u_after_priority (
        .i_eligible(candidate_after_cursor), .o_id(after_first_id)
    );

    // 扫描范围随游标同时保存，候选筛选直接合并帧资格与范围掩码。
    always_comb begin
        for (int unsigned i = 0; i < FRAME_COUNT; i++) begin
            candidate_eligible[i] = live[i] && frame_open[i];
            candidate_after_cursor[i] = candidate_eligible[i] && cursor_mask[i];
        end
    end

    // 开帧、保护帧和两个扫描范围并行生成编号，编码结果只经过一次归并。
    assign scan_open_candidate = ID_W'(opened) & {ID_W{phase == OPENING}};
    assign scan_protected_candidate = protected_id &
        {ID_W{phase == DRAINING && protected_valid}};
    assign scan_after_candidate = after_first_id &
        {ID_W{phase == SWEEPING && candidate_after_exists}};
    assign scan_wrap_candidate = eligible_first_id &
        {ID_W{phase == SWEEPING && !candidate_after_exists}};

    always_comb begin
        initial_slice_shift = '0;
        for (int unsigned bit_index=0; bit_index<ROW_COUNT_W-SHIFT; bit_index++)
            if (slice_tiles[bit_index]) initial_slice_shift |= SLICE_SHIFT_W'(SHIFT+bit_index);
        if (slice_tiles == 0) initial_slice_shift = SLICE_SHIFT_W'(SHIFT);
        initial_slice_rows = (slice_tiles == 0) ? (reuse_rows << SHIFT) : (slice_tiles << SHIFT);
        candidate_found = 1'b0;
        candidate_id = selected_id_q;
        scanned_reference = '0;
        candidate_init = selected_init_q;
        if (phase == OPENING) begin
            candidate_found = opened < target;
            scanned_reference = ID_W'(opened);
        end else if (phase == DRAINING && protected_valid) begin
            candidate_found = 1'b1;
            scanned_reference = protected_id;
        end else if (phase == SWEEPING) begin
            candidate_found = candidate_exists;
            scanned_reference = candidate_after_exists ? after_first_id : eligible_first_id;
        end
        scanned_id = scanned_reference;
        case (^{phase, protected_valid, candidate_after_exists, opened,
                protected_id, after_first_id, eligible_first_id})
            1'b0, 1'b1: scanned_id = scan_open_candidate | scan_protected_candidate |
                scan_after_candidate | scan_wrap_candidate;
            default: ;
        endcase
        candidate_row = candidate_init ? initial_row_o_sum : stored_row_o_sum;
        case (^{row_base, initial_row_i_b, stored_row_i_b, candidate_init})
            1'b0, 1'b1: candidate_row = shared_row_sum;
            default: ;
        endcase
        candidate_rows = candidate_init ? minimum(32'(cfg_slice_rows),
            32'(next_slice_remaining)) : 32'(selected_rows);
        candidate_q = candidate_init ? 32'd0 : (32'(frame_k[candidate_id]) << SHIFT);
        candidate_column = candidate_init ? (32'(next_column_tile) << SHIFT) :
            (32'(selected_column) << SHIFT);
        candidate_final = candidate_final_match;
        candidate_cols = candidate_column == final_column0 ? final_column_count : (SHIFT+1)'(SIZE);
        candidate_k = candidate_final ? final_k_count : (SHIFT+1)'(SIZE);
        command_valid = command_buffer_valid && !command_active;
        // 执行期间命令描述保持不变，接收状态独立于地址和尺寸输出。
        frame_id = command_buffer_id;
        frame_init = command_buffer_init;
        p0 = command_buffer_row;
        rows = 32'(command_buffer_rows);
        q0 = command_buffer_q;
        column0 = command_active ? active_column : command_buffer_column;
        cols = 32'(command_buffer_cols);
        count_k = 32'(command_buffer_k);
        frame_final = command_buffer_final;
`ifndef SYNTHESIS
        // 未知执行状态按四态条件选择各字段。
        if ((^command_active) === 1'bx) begin
            frame_id = command_active ? active_id : command_buffer_id;
            frame_init = command_active ? active_init : command_buffer_init;
            p0 = command_active ? active_row : command_buffer_row;
            rows = command_active ? active_rows : 32'(command_buffer_rows);
            q0 = command_active ? active_q0 : command_buffer_q;
            frame_final = command_active ? active_final : command_buffer_final;
        end
`endif
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) command_buffer_valid <= 1'b0;
        else if (command_valid && (command_ready || command_pressure)) command_buffer_valid <= 1'b0;
        else if (!command_active && !command_buffer_valid && candidate_ready) command_buffer_valid <= 1'b1;
    end
    always_ff @(posedge clk) begin
        if (!command_active && !command_buffer_valid && candidate_ready) begin
            // 压力恢复资格与命令描述同时保存，外部压力返回仅选择保存的动作。
            command_buffer_recoverable <= !candidate_final && protected_valid && live[protected_id] &&
                protected_id != candidate_id && (phase == OPENING || phase == SWEEPING);
            command_buffer_opening <= phase == OPENING;
            command_buffer_id <= candidate_id;
            command_buffer_init <= candidate_init;
            command_buffer_final <= candidate_final;
            command_buffer_row <= candidate_row;
            command_buffer_rows <= ROW_COUNT_W'(candidate_rows);
            command_buffer_q <= candidate_q;
            command_buffer_column <= candidate_column;
            command_buffer_cols <= candidate_cols;
            command_buffer_k <= candidate_k;
        end
    end

    // 命令执行期间依次选择预测帧、读取元数据并计算尾部尺寸。
    logic [3:0] prediction_valid;
    logic prediction_request, prediction_reads_frame;
    logic [ID_W-1:0] prediction_frame;
    logic [FRAME_COUNT-1:0] prediction_selection_q;
    logic [FRAME_COUNT-1:0] prediction_eligible, prediction_after_start;
    logic [FRAME_COUNT-1:0] prediction_eligible_q, prediction_after_start_q;
    (* keep = "true" *) logic [ID_W-1:0] prediction_eligible_frame, prediction_after_frame;
    (* keep = "true" *) logic prediction_eligible_is_active, prediction_after_is_active;
    logic prediction_is_active;
    // 帧元数据读取条件分别随请求接收和帧选择阶段保存。
    logic prediction_reads_frame_q [2];
    logic [31:0] prediction_direct_q, prediction_direct_column;
    logic prediction_is_active_q;
    logic [ID_W-1:0] prediction_frame_q;
    // 直接位置、选择准备和帧位置分别保存在三个已有流水阶段。
    logic [31:0] prediction_depth_q [3];
    logic [31:0] prediction_column_q [3];
    always_comb begin : select_lookahead
        logic [FRAME_COUNT-1:0] future_live;
        logic [FRAME_COUNT-1:0] future_eligible, future_after_start;
        for (int unsigned i = 0; i < FRAME_COUNT; i++) begin
            future_live[i] = (active_id == ID_W'(i)) ? !active_final : live[i];
        end
        future_eligible = '0;
        future_after_start = '0;
        prediction_request = 1'b0;
        prediction_reads_frame = 1'b0;
        prediction_eligible = '0;
        prediction_after_start = '0;
        prediction_direct_q = '0;
        prediction_direct_column = '0;
        if (command_active) begin
            if (phase == OPENING && opened_after_init < target) begin
                prediction_request = 1'b1;
                prediction_direct_column = 32'(next_part_is_last ? column_after_part : next_column_tile) << SHIFT;
            end else if (phase == DRAINING && !active_final) begin
                prediction_request = 1'b1;
                prediction_direct_q = active_q_next;
                prediction_direct_column = active_column;
            end else begin
                prediction_reads_frame = 1'b1;
                for (int unsigned i = 0; i < FRAME_COUNT; i++) begin
                    future_eligible[i] = future_live[i] &&
                        ((phase == OPENING) ? (i < opened_after_init) : (i < opened));
                    future_after_start[i] = future_eligible[i] &&
                        ((phase == OPENING) ||
                         ((phase == DRAINING) ? (!resume_valid || i >= resume_id) :
                          (active_after_frame == opened || i >= active_after_frame)));
                end
                prediction_request = |future_eligible;
                prediction_eligible = future_eligible;
                prediction_after_start = future_after_start;
            end
        end
    end
    // 两个集合并行编码，末端仅选择帧编号及活动帧匹配结果。
    assign prediction_selection_q = (|prediction_after_start_q) ?
        prediction_after_start_q : prediction_eligible_q;
    function automatic logic [ID_W-1:0] first_prediction_frame(
        input logic [FRAME_COUNT-1:0] selection
    );
        logic [FRAME_COUNT-1:0] first;
        begin
            first[0] = selection[0];
            for (int frame = 1; frame < FRAME_COUNT; frame++) begin
                first[frame] = selection[frame] && !(|(selection & ((FRAME_COUNT'(1) << frame) - 1'b1)));
            end
            first_prediction_frame = '0;
            for (int frame = 0; frame < FRAME_COUNT; frame++) begin
                first_prediction_frame |= ID_W'(frame) & {ID_W{first[frame]}};
            end
        end
    endfunction
    ps_scheduler_priority #(.p_frames(FRAME_COUNT), .p_id_width(ID_W)) u_prediction_eligible (
        .i_eligible(prediction_eligible_q), .o_id(prediction_eligible_frame)
    );
    ps_scheduler_priority #(.p_frames(FRAME_COUNT), .p_id_width(ID_W)) u_prediction_after (
        .i_eligible(prediction_after_start_q), .o_id(prediction_after_frame)
    );
    assign prediction_eligible_is_active = prediction_eligible_frame == active_id;
    assign prediction_after_is_active = prediction_after_frame == active_id;
    always_comb begin
        case (^{prediction_eligible_q, prediction_after_start_q})
            1'b0, 1'b1: begin
                prediction_frame = (|prediction_after_start_q) ?
                    prediction_after_frame : prediction_eligible_frame;
                prediction_is_active = (|prediction_after_start_q) ?
                    prediction_after_is_active : prediction_eligible_is_active;
            end
            default: begin
                prediction_frame = first_prediction_frame(prediction_selection_q);
                prediction_is_active = prediction_frame == active_id;
            end
        endcase
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) prediction_valid <= '0;
        else if (!command_active || command_complete) prediction_valid <= '0;
        else prediction_valid <= {prediction_valid[2:0], prediction_request};
    end
    assign lookahead_valid = prediction_valid[3] && command_active;
    always_ff @(posedge clk) begin
        if (prediction_request) begin
            prediction_eligible_q <= prediction_eligible;
            prediction_after_start_q <= prediction_after_start;
            prediction_reads_frame_q[0] <= prediction_reads_frame;
            prediction_depth_q[0] <= prediction_direct_q;
            prediction_column_q[0] <= prediction_direct_column;
        end
        if (prediction_valid[0]) begin
            prediction_frame_q <= prediction_frame;
            prediction_reads_frame_q[1] <= prediction_reads_frame_q[0];
            prediction_is_active_q <= prediction_is_active;
            prediction_depth_q[1] <= prediction_depth_q[0];
            prediction_column_q[1] <= prediction_column_q[0];
        end
        if (prediction_valid[1]) begin
            prediction_depth_q[2] <= prediction_reads_frame_q[1] ?
                (prediction_is_active_q ? active_q_next :
                    32'(frame_k[prediction_frame_q]) << SHIFT) : prediction_depth_q[1];
            prediction_column_q[2] <= prediction_reads_frame_q[1] ?
                (prediction_is_active_q ? active_column :
                    32'(predicted_column) << SHIFT) : prediction_column_q[1];
        end
        if (prediction_valid[2]) begin
            lookahead_q0 <= prediction_depth_q[2];
            lookahead_column <= prediction_column_q[2];
            lookahead_cols <= prediction_column_q[2] == final_column0 ? 32'(final_column_count) : 32'(SIZE);
            lookahead_count_k <= prediction_depth_q[2] == final_q0 ? 32'(final_k_count) : 32'(SIZE);
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            selected_id_valid <= 1'b0;
        end else if (!candidate_found || command_active ||
                     (command_valid && (command_ready || command_pressure))) begin
            selected_id_valid <= 1'b0;
        end else if (!selected_id_valid && candidate_found) begin
            selected_id_valid <= 1'b1;
        end
    end
    always_ff @(posedge clk) begin
        if (!command_active && !selected_id_valid && candidate_found) begin
            selected_id_q <= scanned_id;
            selected_init_q <= phase == OPENING;
            selected_initial_offset <= next_slice_offset;
        end
    end

    // 候选帧和预测帧在保存索引的同一边沿读取元数据，后续计算直接使用同步结果。
    assign frame_metadata_i_wr_en = command_active && command_complete && active_init;
    assign frame_metadata_i_wr_addr = active_id;
    assign frame_metadata_i_wr_mask = 1'b1;
    assign frame_metadata_i_wr_data = {TILE_W'(active_column >> SHIFT),
        ROW_PART_W'((active_row - row_base) >> SHIFT), ROW_COUNT_W'(active_rows)};
    assign frame_metadata_i_rd_en[0] = !command_active && !selected_id_valid && candidate_found;
    assign frame_metadata_i_rd_en[1] = prediction_valid[0];
    assign frame_metadata_i_rd_addr[0] = scanned_id;
    assign frame_metadata_i_rd_addr[1] = prediction_frame;
    assign {selected_column, selected_row_part, selected_rows} = frame_metadata_o_rd_data[0];
    assign predicted_column = frame_metadata_o_rd_data[1][p_metadata_width-1 -: TILE_W];

    regfile #(
        .p_data_width(p_metadata_width), .p_depth(FRAME_COUNT), .p_addr_width(ID_W),
        .p_write_unit(p_metadata_width), .p_read_ports(2), .p_sync_read(1'b1),
        .p_ram_style("block")
    ) u_frame_metadata (
        .clk(clk), .i_wr_en(frame_metadata_i_wr_en), .i_wr_addr(frame_metadata_i_wr_addr),
        .i_wr_data(frame_metadata_i_wr_data), .i_wr_mask(frame_metadata_i_wr_mask),
        .i_rd_en(frame_metadata_i_rd_en), .i_rd_addr(frame_metadata_i_rd_addr),
        .o_rd_data(frame_metadata_o_rd_data)
    );

    always_ff @(posedge clk) begin
        next_part_is_last <= next_row_part + (ROW_PART_W+1)'(1) == group_parts;
    end

    always_ff @(posedge clk) begin
        if (phase == IDLE && start) begin
            final_q0 <= ((reduction_last) >> SHIFT) << SHIFT;
            final_column0 <= ((stationary_rows_last) >> SHIFT) << SHIFT;
            final_k_count <= (reduction & 32'(SIZE-1)) == '0 ? (SHIFT+1)'(SIZE) : (SHIFT+1)'(reduction & 32'(SIZE-1));
            final_column_count <= (stationary_rows & 32'(SIZE-1)) == '0 ? (SHIFT+1)'(SIZE) :
                (SHIFT+1)'(stationary_rows & 32'(SIZE-1));
        end
    end

    // 完成与准备事件独立更新；等待中的命令在最后选择压力恢复或接收。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase <= IDLE;
            column_tiles <= SHIFT == 0 ? '0 : ((TILE_W+1)'(1) << TILE_W);
            cfg_rows <= '0; cfg_window <= '0; cfg_slice_rows <= '0;
            slice_shift <= SLICE_SHIFT_W'(SHIFT); sliced <= 1'b0;
            row_base <= '0; next_column_tile <= '0; next_row_part <= '0;
            stream_rows_remaining <= '0;
            opened <= '0; target <= '0;
            cursor_mask <= '1;
            frame_open <= '0;
            live <= '0; protected_valid <= 1'b0; resume_valid <= 1'b0;
            candidate_exists <= 1'b0;
            protected_id <= '0; resume_id <= '0;
            command_active <= 1'b0; active_id <= '0;
            active_init <= 1'b0; active_final <= 1'b0;
            active_q0 <= '0; active_column <= '0; active_row <= '0; active_rows <= '0;
            err_code <= '0;

        end else begin
            if (phase == IDLE && start) begin
                column_tiles <= incoming_column_tiles;
                cfg_rows <= ROW_COUNT_W'(reuse_rows << SHIFT);
                cfg_window <= (ID_W+1)'(window_frames);
                cfg_slice_rows <= ROW_COUNT_W'(initial_slice_rows);
                slice_shift <= initial_slice_shift;
                sliced <= slice_tiles != 0;
                row_base <= '0; next_column_tile <= '0; next_row_part <= '0;
                stream_rows_remaining <= stream_rows;
                opened <= '0;
                cursor_mask <= '1;
                frame_open <= '0;
                // 帧目标数量在 PREPARE_TARGET 保存后供所有命令和预测阶段使用。
                target <= '0;
                live <= '0; protected_valid <= 1'b0; resume_valid <= 1'b0;
                candidate_exists <= 1'b0;
                command_active <= 1'b0;

                if (config_error != 0 || incoming_dimensions_invalid || incoming_reuse_invalid ||
                    incoming_window_invalid || incoming_slice_invalid) begin
                    err_code <= (config_error != 0) ? config_error : 2'b01;
                    phase <= COMPLETE;
                end else begin
                    err_code <= '0;
                    phase <= PREPARING;
                end
            end else if (phase == COMPLETE) begin
                // 完成阶段保持全部任务状态，仅在接收通知后返回空闲。
                if (done_ready) begin
                    phase <= IDLE;
                end
            end else if (command_active && command_complete) begin
                command_active <= 1'b0;

                if (active_init) begin
                    opened <= opened_after_init;
                    // 开放掩码与帧计数同拍更新，候选资格直接读取对应状态。
                    for (int unsigned frame_index = 0; frame_index < FRAME_COUNT; frame_index++)
                        frame_open[frame_index] <= 32'(frame_index) < opened_after_init;
                    if (next_row_part + (ROW_PART_W+1)'(1) == group_parts) begin
                        next_column_tile <= column_after_part;
                        next_row_part <= '0;
                    end else next_row_part <= next_row_part + (ROW_PART_W+1)'(1);
                end
                live[active_id] <= !active_final;
                candidate_exists <= |(candidate_live_after & candidate_open_after);
                if (active_final) begin
                    if (protected_valid && protected_id == active_id) protected_valid <= 1'b0;
                end else begin
                    protected_id <= active_id;
                    protected_valid <= 1'b1;
                end
                if (phase == OPENING && opened_after_init == target) begin
                    phase <= SWEEPING;
                    cursor_mask <= '1;
                end else if (phase == DRAINING && active_final) begin
                    phase <= SWEEPING;
                    for (int unsigned frame_index = 0; frame_index < FRAME_COUNT; frame_index++)
                        cursor_mask[frame_index] <= frame_index >= (resume_valid ? 32'(resume_id) : 32'd0);
                    resume_valid <= 1'b0;

                end else if (phase == SWEEPING) begin
                    for (int unsigned frame_index = 0; frame_index < FRAME_COUNT; frame_index++)
                        cursor_mask[frame_index] <= frame_index >= ((active_after_frame == opened) ? 32'd0 : 32'(active_after_frame));
                end
            end else if (phase == PREPARING) begin
                phase <= sliced ? PREPARE_PARTS : PREPARE_CAPS;
            end else if (phase == PREPARE_PARTS) begin
                phase <= PREPARE_CAPS;
            end else if (phase == PREPARE_CAPS) begin
                phase <= PREPARE_PRODUCTS;
            end else if (phase == PREPARE_PRODUCTS) begin
                phase <= PREPARE_TARGET;
            end else if (phase == PREPARE_TARGET) begin
                target <= next_target;
                phase <= OPENING;
            end else if (phase == SWEEPING && !command_active && !candidate_exists) begin
                opened <= '0;
                cursor_mask <= '1;
                frame_open <= '0;
                protected_valid <= 1'b0; resume_valid <= 1'b0;
                live <= '0;
                candidate_exists <= 1'b0;
                if (next_column_tile == column_tiles) begin
                    row_base <= row_update_sum;
                    stream_rows_remaining <= next_stream_rows_remaining;
                    next_column_tile <= '0;
                    next_row_part <= '0;
                    target <= '0;
                    phase <= row_group_complete ? COMPLETE : PREPARING;
                end else begin
                    target <= '0;
                    phase <= PREPARING;
                end
            end else if (command_valid && command_pressure) begin
                if (command_buffer_recoverable) begin
                    if (command_buffer_opening) begin
                        target <= opened;
                        resume_valid <= 1'b0;
                        cursor_mask <= '1;
                        phase <= SWEEPING;
                    end else begin
                        resume_id <= command_buffer_id;
                        resume_valid <= 1'b1;
                        phase <= DRAINING;
                    end
                end else begin
                    err_code <= 2'b10;
                    phase <= COMPLETE;
                end
            end else if (command_valid && command_ready) begin
                command_active <= 1'b1;
                active_id <= command_buffer_id;
                active_init <= command_buffer_init;
                active_final <= frame_final;
                active_q0 <= q0;
                active_column <= column0;
                active_row <= p0;
                active_rows <= rows;

            end
        end
    end

    always_ff @(posedge clk) begin
        if (command_active && command_complete) begin
            frame_k[active_id] <= active_init ? TILE_W'(1) : frame_k_after_command;
        end
    end

`ifdef NPU_SIM_ASSERT
    logic [31:0] cfg_stream, cfg_reduction;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_stream <= '0;
            cfg_reduction <= '0;
        end else if (phase == IDLE && start) begin
            cfg_stream <= stream_rows;
            cfg_reduction <= reduction;
        end
    end
    initial forever @(posedge clk) if (rst_n) begin
        if (command_complete) assert(command_active);
        if (command_valid && command_ready) begin
            assert(rows != 0 && cols != 0 && count_k != 0);
            assert(q0 < cfg_reduction && column0 < (final_column0 + 32'(final_column_count)) && p0 < cfg_stream);
        end
    end
`endif
endmodule

`default_nettype wire
