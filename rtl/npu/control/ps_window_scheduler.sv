// Schedule physical output frames while retaining each frame's K progress.
module ps_window_scheduler #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned FRAME_COUNT = 16,
    parameter int unsigned MAX_REUSE_TILES = 0
) (
    input logic clk, rst_n,
    input logic start,
    input logic [31:0] stream_rows, stationary_rows, reduction,
    input logic [31:0] reuse_rows, window_frames,
    input logic [31:0] slice_tiles = 32'd0,
    input logic [1:0] config_error,
    output logic ready,
    output logic done_valid,
    input logic done_ready,
    output logic [1:0] err_code,
    output logic command_valid,
    input logic command_ready,
    input logic command_pressure,
    input logic command_complete,
    output logic [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id,
    output logic [31:0] p0, q0, column0, rows, cols, count_k, reserve_rows,
    output logic frame_init, frame_final,
    output logic command_active,
    output logic lookahead_valid,
    output logic [31:0] lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k);
    localparam int unsigned ID_W = (FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1;
    localparam int unsigned SHIFT = $clog2(SIZE);
    localparam int unsigned TILE_W = 32 - SHIFT;
    localparam int unsigned ROW_PART_W = MAX_REUSE_TILES > 1 ? $clog2(MAX_REUSE_TILES) :
        MAX_REUSE_TILES == 1 ? 1 : TILE_W;
    localparam int unsigned ROW_COUNT_W = MAX_REUSE_TILES != 0 ? $clog2(MAX_REUSE_TILES * SIZE + 1) : 32;
    typedef enum logic [3:0] {IDLE, PREPARING, PREPARE_PARTS, PREPARE_CAPS,
                              PREPARE_PRODUCTS, PREPARE_TARGET, OPENING, SWEEPING, DRAINING, COMPLETE} phase_t;
    phase_t phase;
    logic [31:0] cfg_stream, cfg_reduction;
    logic [ROW_COUNT_W-1:0] cfg_rows, cfg_slice_rows;
    logic [ID_W:0] cfg_window;
    logic [31:0] final_q0, final_column0;
    logic [SHIFT:0] final_k_count, final_column_count;
    localparam int unsigned SLICE_SHIFT_W = ROW_COUNT_W > 2 ? $clog2(ROW_COUNT_W) : 1;
    logic [SLICE_SHIFT_W-1:0] slice_shift;
    logic sliced;
    logic next_part_is_last;
    logic [31:0] row_base;
    logic [TILE_W:0] next_column_tile;
    logic [ROW_PART_W:0] next_row_part;
    logic [ID_W:0] opened, target, cursor;
    logic [FRAME_COUNT-1:0] live;
    logic [TILE_W-1:0] frame_k [FRAME_COUNT];
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
    logic candidate_found;
    logic [ID_W-1:0] candidate_id, scanned_id, selected_id_q;
    logic selected_id_valid, selected_init_q;
    logic candidate_init;
    logic command_buffer_valid;
    logic [ID_W-1:0] command_buffer_id;
    logic command_buffer_init, command_buffer_final;
    logic [31:0] command_buffer_row, command_buffer_q, command_buffer_column;
    logic [ROW_COUNT_W-1:0] command_buffer_rows;
    logic [SHIFT:0] command_buffer_cols, command_buffer_k;
    logic [31:0] candidate_q, candidate_column;
    logic [SHIFT:0] candidate_cols, candidate_k;
    logic candidate_final;
    wire candidate_ready = candidate_found && selected_id_valid;
    logic [FRAME_COUNT-1:0] candidate_eligible, candidate_after_cursor, candidate_select;
    logic candidate_exists, candidate_after_exists;
    logic [ID_W-1:0] eligible_first_id, after_first_id;
    logic [TILE_W:0] column_tiles, remaining_columns;
    logic [TILE_W:0] incoming_column_tiles;
    logic [ROW_COUNT_W-1:0] current_rows;
    logic [ROW_PART_W:0] group_parts;
    logic [31:0] candidate_row, candidate_rows, initial_slice_rows;
    logic [SLICE_SHIFT_W-1:0] initial_slice_shift;
    wire [ROW_COUNT_W-1:0] next_slice_offset = ROW_COUNT_W'(next_row_part) << slice_shift;
    wire [ROW_COUNT_W-1:0] next_slice_remaining = current_rows - next_slice_offset;

    function automatic logic [31:0] minimum(input logic [31:0] a, b);
        return (a < b) ? a : b;
    endfunction

    // 零切片数由原有配置分支处理，其他值按幂次决定分块形状。
    logic [31:0] slice_shape_i_value;
    logic slice_shape_o_valid;
    assign slice_shape_i_value = slice_tiles;
    onehot_check #(.p_width(32), .p_allow_zero(1'b1)) u_slice_shape (
      .i_value(slice_shape_i_value),
      .o_valid(slice_shape_o_valid)
    );

    localparam int unsigned CAP_W = ID_W + 1;
    localparam int unsigned PRODUCT_W = 2 * CAP_W + 1;
    logic [ROW_COUNT_W-1:0] prepare_rows;
    logic [TILE_W:0] prepare_remaining_columns;
    logic [ROW_PART_W:0] prepare_parts;
    logic [CAP_W-1:0] parts_cap, window_cap, remaining_cap, tail_cap;
    logic [PRODUCT_W-1:0] window_product, available_product;
    logic [CAP_W-1:0] next_target;
    wire [ROW_PART_W:0] remaining_tail = prepare_parts - next_row_part;
    always_ff @(posedge clk) begin
        if (phase == PREPARING) begin
            prepare_rows <= ROW_COUNT_W'(minimum(32'(cfg_rows), cfg_stream - row_base));
            prepare_remaining_columns <= remaining_columns;
            if (!sliced) prepare_parts <= (ROW_PART_W+1)'(1);
        end
        if (phase == PREPARE_PARTS)
            prepare_parts <= sliced ? (ROW_PART_W+1)'(((prepare_rows - ROW_COUNT_W'(1)) >> slice_shift) + ROW_COUNT_W'(1)) : (ROW_PART_W+1)'(1);
        if (phase == PREPARE_CAPS) begin
            parts_cap <= prepare_parts >= 32'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) : CAP_W'(prepare_parts);
            window_cap <= cfg_window >= 32'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) : CAP_W'(cfg_window);
            remaining_cap <= prepare_remaining_columns > 32'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) :
                             CAP_W'(prepare_remaining_columns - 32'd1);
            tail_cap <= remaining_tail >= 32'(FRAME_COUNT) ? CAP_W'(FRAME_COUNT) : CAP_W'(remaining_tail);
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
        assign incoming_column_tiles = stationary_rows == 32'd0 ?
            ((TILE_W+1)'(1) << TILE_W) :
            (TILE_W+1)'(stationary_rows >> SHIFT) +
            (TILE_W+1)'(|stationary_rows[SHIFT-1:0]);
    end
    assign current_rows = prepare_rows;
    assign remaining_columns = column_tiles - next_column_tile;
    assign group_parts = prepare_parts;
    assign reserve_rows = minimum(cfg_slice_rows, current_rows);
    assign ready = phase == IDLE;
    assign done_valid = phase == COMPLETE;

    // 有效帧判断独立使用平衡归并树，保持命令写使能的组合层数。
    ps_scheduler_any #(.p_width(FRAME_COUNT)) u_candidate_exists (
        .i_value(candidate_eligible), .o_any(candidate_exists)
    );
    ps_scheduler_any #(.p_width(FRAME_COUNT)) u_candidate_after_exists (
        .i_value(candidate_after_cursor), .o_any(candidate_after_exists)
    );

    // 两段候选分别编码，最后选择游标之后的首个帧或循环回到首个有效帧。
    always_comb begin
        eligible_first_id = '0;
        after_first_id = '0;
        for (int i = FRAME_COUNT - 1; i >= 0; i--) begin
            if (candidate_eligible[i]) eligible_first_id = ID_W'(i);
            if (candidate_after_cursor[i]) after_first_id = ID_W'(i);
        end
    end

    always_comb begin
        initial_slice_shift = '0;
        for (int unsigned bit_index=0; bit_index<ROW_COUNT_W-SHIFT; bit_index++)
            if (slice_tiles[bit_index]) initial_slice_shift |= SLICE_SHIFT_W'(SHIFT+bit_index);
        if (slice_tiles == 0) initial_slice_shift = SLICE_SHIFT_W'(SHIFT);
        initial_slice_rows = (slice_tiles == 0) ? (reuse_rows << SHIFT) : (slice_tiles << SHIFT);
        candidate_found = 1'b0;
        candidate_eligible = '0;
        candidate_after_cursor = '0;
        candidate_select = '0;
        candidate_id = selected_id_q;
        scanned_id = '0;
        candidate_init = selected_init_q;
        if (phase == OPENING) begin
            candidate_found = opened < target;
            scanned_id = ID_W'(opened);
        end else if (phase == DRAINING && protected_valid) begin
            candidate_found = 1'b1;
            scanned_id = protected_id;
        end else if (phase == SWEEPING) begin
            for (int unsigned i = 0; i < FRAME_COUNT; i++) begin
                candidate_eligible[i] = live[i] && (i < opened);
                candidate_after_cursor[i] = candidate_eligible[i] && (i >= cursor);
            end
            candidate_select = candidate_after_exists ? candidate_after_cursor : candidate_eligible;
            candidate_found = candidate_exists;
            scanned_id = candidate_after_exists ? after_first_id : eligible_first_id;
        end
        candidate_row = candidate_init ? row_base + 32'(next_slice_offset) :
            row_base + (32'(selected_row_part) << SHIFT);
        candidate_rows = candidate_init ? minimum(32'(cfg_slice_rows),
            32'(next_slice_remaining)) : 32'(selected_rows);
        candidate_q = candidate_init ? 32'd0 : (32'(frame_k[candidate_id]) << SHIFT);
        candidate_column = candidate_init ? (32'(next_column_tile) << SHIFT) :
            (32'(selected_column) << SHIFT);
        candidate_final = candidate_q == final_q0;
        candidate_cols = candidate_column == final_column0 ? final_column_count : (SHIFT+1)'(SIZE);
        candidate_k = candidate_final ? final_k_count : (SHIFT+1)'(SIZE);
        command_valid = command_buffer_valid && !command_active;
        frame_id = command_active ? active_id : command_buffer_id;
        frame_init = command_active ? active_init : command_buffer_init;
        p0 = command_active ? active_row : command_buffer_row;
        rows = command_active ? active_rows : 32'(command_buffer_rows);
        q0 = command_active ? active_q0 : command_buffer_q;
        column0 = command_active ? active_column : command_buffer_column;
        cols = 32'(command_buffer_cols);
        count_k = 32'(command_buffer_k);
        frame_final = command_active ? active_final : command_buffer_final;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) command_buffer_valid <= 1'b0;
        else if (command_valid && (command_ready || command_pressure)) command_buffer_valid <= 1'b0;
        else if (!command_active && !command_buffer_valid && candidate_ready) command_buffer_valid <= 1'b1;
    end
    always_ff @(posedge clk) begin
        if (!command_active && !command_buffer_valid && candidate_ready) begin
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

    // The prediction is prepared while the accepted command executes.
    // Select a frame, read its metadata, and calculate the tail sizes in separate cycles.
    logic [3:0] prediction_valid;
    logic prediction_request, prediction_reads_frame;
    logic [ID_W-1:0] prediction_frame;
    logic [FRAME_COUNT-1:0] prediction_selection, prediction_selection_q;
    logic prediction_reads_frame_s0;
    logic [31:0] prediction_direct_q, prediction_direct_column;
    logic prediction_reads_frame_q, prediction_is_active_q;
    logic [ID_W-1:0] prediction_frame_q;
    logic [31:0] prediction_q_s0, prediction_column_s0, prediction_q_direct_s1, prediction_column_direct_s1;
    logic [31:0] prediction_q_s1, prediction_column_s1;
    always_comb begin : select_lookahead
        logic [FRAME_COUNT-1:0] future_live;
        logic [ID_W:0] search_start, search_count;
        logic [FRAME_COUNT-1:0] future_eligible, future_after_start, future_select;
        future_live = live;
        future_live[active_id] = !active_final;
        search_start = '0;
        search_count = opened;
        future_eligible = '0;
        future_after_start = '0;
        future_select = '0;
        prediction_request = 1'b0;
        prediction_reads_frame = 1'b0;
        prediction_selection = '0;
        prediction_direct_q = '0;
        prediction_direct_column = '0;
        if (command_active) begin
            if (phase == OPENING && opened + (ID_W+1)'(1) < target) begin
                prediction_request = 1'b1;
                prediction_direct_column = (32'(next_column_tile) +
                    (next_part_is_last ? 32'd1 : 32'd0)) << SHIFT;
            end else if (phase == DRAINING && !active_final) begin
                prediction_request = 1'b1;
                prediction_direct_q = active_q0 + 32'(SIZE);
                prediction_direct_column = active_column;
            end else begin
                prediction_reads_frame = 1'b1;
                if (phase == OPENING) search_count = opened + (ID_W+1)'(1);
                else if (phase == DRAINING) search_start = resume_valid ? (ID_W+1)'(resume_id) : '0;
                else search_start = ((ID_W+1)'(active_id) + (ID_W+1)'(1) == opened) ?
                    '0 : (ID_W+1)'(active_id) + (ID_W+1)'(1);
                for (int unsigned i = 0; i < FRAME_COUNT; i++) begin
                    future_eligible[i] = future_live[i] && (i < search_count);
                    future_after_start[i] = future_eligible[i] && (i >= search_start);
                end
                future_select = (|future_after_start) ? future_after_start : future_eligible;
                prediction_request = |future_eligible;
                prediction_selection = future_select;
            end
        end
    end
    always_comb begin
        prediction_frame = '0;
        for (int i = FRAME_COUNT - 1; i >= 0; i--)
            if (prediction_selection_q[i]) prediction_frame = ID_W'(i);
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) prediction_valid <= '0;
        else if (!command_active || command_complete) prediction_valid <= '0;
        else prediction_valid <= {prediction_valid[2:0], prediction_request};
    end
    assign lookahead_valid = prediction_valid[3] && command_active;
    always_ff @(posedge clk) begin
        if (prediction_request) begin
            prediction_selection_q <= prediction_selection;
            prediction_reads_frame_s0 <= prediction_reads_frame;
            prediction_q_s0 <= prediction_direct_q;
            prediction_column_s0 <= prediction_direct_column;
        end
        if (prediction_valid[0]) begin
            prediction_frame_q <= prediction_frame;
            prediction_reads_frame_q <= prediction_reads_frame_s0;
            prediction_is_active_q <= prediction_frame == active_id;
            prediction_q_direct_s1 <= prediction_q_s0;
            prediction_column_direct_s1 <= prediction_column_s0;
        end
        if (prediction_valid[1]) begin
            prediction_q_s1 <= prediction_reads_frame_q ?
                (prediction_is_active_q ? active_q0 + 32'(SIZE) :
                    32'(frame_k[prediction_frame_q]) << SHIFT) : prediction_q_direct_s1;
            prediction_column_s1 <= prediction_reads_frame_q ?
                (prediction_is_active_q ? active_column :
                    32'(predicted_column) << SHIFT) : prediction_column_direct_s1;
        end
        if (prediction_valid[2]) begin
            lookahead_q0 <= prediction_q_s1;
            lookahead_column <= prediction_column_s1;
            lookahead_cols <= prediction_column_s1 == final_column0 ? 32'(final_column_count) : 32'(SIZE);
            lookahead_count_k <= prediction_q_s1 == final_q0 ? 32'(final_k_count) : 32'(SIZE);
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
            final_q0 <= ((reduction - 32'd1) >> SHIFT) << SHIFT;
            final_column0 <= ((stationary_rows - 32'd1) >> SHIFT) << SHIFT;
            final_k_count <= (reduction & 32'(SIZE-1)) == '0 ? (SHIFT+1)'(SIZE) : (SHIFT+1)'(reduction & 32'(SIZE-1));
            final_column_count <= (stationary_rows & 32'(SIZE-1)) == '0 ? (SHIFT+1)'(SIZE) :
                (SHIFT+1)'(stationary_rows & 32'(SIZE-1));
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase <= IDLE;
            cfg_stream <= '0; cfg_reduction <= '0;
            column_tiles <= SHIFT == 0 ? '0 : ((TILE_W+1)'(1) << TILE_W);
            cfg_rows <= '0; cfg_window <= '0; cfg_slice_rows <= '0;
            slice_shift <= SLICE_SHIFT_W'(SHIFT); sliced <= 1'b0;
            row_base <= '0; next_column_tile <= '0; next_row_part <= '0;
            opened <= '0; target <= '0; cursor <= '0;
            live <= '0; protected_valid <= 1'b0; resume_valid <= 1'b0;
            protected_id <= '0; resume_id <= '0;
            command_active <= 1'b0; active_id <= '0;
            active_init <= 1'b0; active_final <= 1'b0;
            active_q0 <= '0; active_column <= '0; active_row <= '0; active_rows <= '0;
            err_code <= '0;

        end else begin
            if (phase == IDLE && start) begin
                cfg_stream <= stream_rows;
                column_tiles <= incoming_column_tiles;
                cfg_reduction <= reduction;
                cfg_rows <= ROW_COUNT_W'(reuse_rows << SHIFT);
                cfg_window <= (ID_W+1)'(window_frames);
                cfg_slice_rows <= ROW_COUNT_W'(initial_slice_rows);
                slice_shift <= initial_slice_shift;
                sliced <= slice_tiles != 0;
                row_base <= '0; next_column_tile <= '0; next_row_part <= '0;
                opened <= '0; cursor <= '0;
                target <= minimum(window_frames, 32'(incoming_column_tiles));
                live <= '0; protected_valid <= 1'b0; resume_valid <= 1'b0;
                command_active <= 1'b0;

                if (config_error != 0 || stream_rows == 0 || stationary_rows == 0 || reduction == 0 ||
                    reuse_rows == 0 || (reuse_rows >> (32-SHIFT)) != 0 ||
                    (MAX_REUSE_TILES != 0 && reuse_rows > MAX_REUSE_TILES) ||
                    window_frames == 0 || window_frames > 32'(FRAME_COUNT) ||
                    slice_tiles > reuse_rows || !slice_shape_o_valid) begin
                    err_code <= (config_error != 0) ? config_error : 2'b01;
                    phase <= COMPLETE;
                end else begin
                    err_code <= '0;
                    phase <= PREPARING;
                end
            end else if (phase == COMPLETE && done_ready) begin
                phase <= IDLE;
            end else if (command_valid && command_pressure) begin
                if (!frame_final && protected_valid && live[protected_id] && protected_id != command_buffer_id &&
                    (phase == OPENING || phase == SWEEPING)) begin

                    if (phase == OPENING) begin
                        target <= opened;
                        resume_valid <= 1'b0;
                        cursor <= '0;
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
            end else if (command_active && command_complete) begin
                command_active <= 1'b0;

                if (active_init) begin
                    opened <= opened + 1'b1;
                    if (next_row_part + (ROW_PART_W+1)'(1) == group_parts) begin
                        next_column_tile <= next_column_tile + (TILE_W+1)'(1);
                        next_row_part <= '0;
                    end else next_row_part <= next_row_part + (ROW_PART_W+1)'(1);
                end
                live[active_id] <= !active_final;
                if (active_final) begin
                    if (protected_valid && protected_id == active_id) protected_valid <= 1'b0;
                end else begin
                    protected_id <= active_id;
                    protected_valid <= 1'b1;
                end
                if (phase == OPENING && opened + (ID_W+1)'(1) == target) begin
                    phase <= SWEEPING;
                    cursor <= '0;
                end else if (phase == DRAINING && active_final) begin
                    phase <= SWEEPING;
                    cursor <= resume_valid ? (ID_W+1)'(resume_id) : '0;
                    resume_valid <= 1'b0;

                end else if (phase == SWEEPING) begin
                    cursor <= ((ID_W+1)'(active_id) + (ID_W+1)'(1) == opened) ? '0 : (ID_W+1)'(active_id) + (ID_W+1)'(1);
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
            end else if (phase == SWEEPING && !command_active && !candidate_found) begin
                opened <= '0; cursor <= '0;
                protected_valid <= 1'b0; resume_valid <= 1'b0;
                live <= '0;
                if (next_column_tile == column_tiles) begin
                    row_base <= row_base + current_rows;
                    next_column_tile <= '0;
                    next_row_part <= '0;
                    target <= minimum(cfg_window, column_tiles);
                    phase <= (row_base + current_rows == cfg_stream) ? COMPLETE : PREPARING;
                end else begin
                    target <= minimum(cfg_window, remaining_columns);
                    phase <= PREPARING;
                end
            end
        end
    end

    always_ff @(posedge clk) begin
        if (command_active && command_complete) begin
            frame_k[active_id] <= active_init ? TILE_W'(1) : frame_k[active_id] + 1'b1;
        end
    end

`ifdef NPU_SIM_ASSERT
    initial forever @(posedge clk) if (rst_n) begin
        if (command_complete) assert(command_active);
        if (command_valid && command_ready) begin
            assert(rows != 0 && cols != 0 && count_k != 0);
            assert(q0 < cfg_reduction && column0 < (final_column0 + 32'(final_column_count)) && p0 < cfg_stream);
        end
    end
`endif
endmodule

// 六输入归并树：每一级仅依赖前一级的六个结果。
module ps_scheduler_any #(
    parameter int p_width = 16,
    parameter bit p_use_lut =
`ifdef ASIC_SYNTHESIS
        1'b0
`elsif XILINX_FPGA
        1'b1
`elsif SYNTHESIS
        1'b1
`else
        1'b0
`endif
) (
    input  logic [p_width-1:0] i_value,
    output logic o_any
);
    localparam int p_groups = (p_width + 5) / 6;
    localparam int p_levels = $clog2(p_groups) + 1;

    for (genvar level = 0; level <= p_levels; level++) begin : g_level
        localparam int p_span = 6 ** level;
        localparam int p_nodes = (p_width + p_span - 1) / p_span;
        localparam int p_previous_span = level > 0 ? 6 ** (level - 1) : 1;
        localparam int p_previous_nodes = (p_width + p_previous_span - 1) / p_previous_span;

        for (genvar node = 0; node < p_width; node++) begin : g_node
            logic any_set;

            if (level == 0) begin : g_input
                assign any_set = i_value[node];
            end else if (node == 0 && p_previous_nodes == 1) begin : g_pass
                assign any_set = g_level[level-1].g_node[0].any_set;
            end else if (node < p_nodes) begin : g_reduce
                logic [5:0] any_i_value;
                logic any_o_value;

                for (genvar child = 0; child < 6; child++) begin : g_child
                    if (6 * node + child < p_previous_nodes) begin : g_present
                        assign any_i_value[child] = g_level[level-1].g_node[6*node+child].any_set;
                    end else begin : g_empty
                        assign any_i_value[child] = 1'b0;
                    end
                end
                assign any_o_value = |any_i_value;
                assign any_set = any_o_value;
            end else begin : g_unused
                assign any_set = 1'b0;
            end
        end
    end
    assign o_any = g_level[p_levels].g_node[0].any_set;
endmodule
