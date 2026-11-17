// Schedule physical output frames while retaining each frame's K progress.
module ps_window_scheduler #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned FRAME_COUNT = 16
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
    typedef enum logic [2:0] {IDLE, PREPARING, OPENING, SWEEPING, DRAINING, COMPLETE} phase_t;
    phase_t phase;
    logic [31:0] cfg_stream, cfg_stationary, cfg_reduction, cfg_rows, cfg_window, cfg_slice_rows;
    logic [5:0] slice_shift;
    logic sliced;
    logic [31:0] row_base, next_column_tile, next_row_part, opened, target, cursor;
    logic [FRAME_COUNT-1:0] live;
    logic [31:0] frame_k [FRAME_COUNT];
    logic [31:0] frame_column [FRAME_COUNT];
    logic [31:0] frame_row [FRAME_COUNT];
    logic [31:0] frame_rows [FRAME_COUNT];
    logic protected_valid, resume_valid;
    logic [ID_W-1:0] protected_id, resume_id, active_id;
    logic active_init, active_final;
    logic [31:0] active_q0, active_column, active_row, active_rows;
    logic candidate_found;
    logic [ID_W-1:0] candidate_id;
    logic candidate_init;
    logic [31:0] column_tiles, current_rows, remaining_columns, group_parts;
    logic [31:0] candidate_row, candidate_rows, initial_slice_rows;
    logic [5:0] initial_slice_shift;

    function automatic logic [31:0] minimum(input logic [31:0] a, b);
        return (a < b) ? a : b;
    endfunction

    assign column_tiles = ((cfg_stationary - 32'd1) >> SHIFT) + 32'd1;
    assign current_rows = minimum(cfg_rows, cfg_stream - row_base);
    assign remaining_columns = column_tiles - next_column_tile;
    assign group_parts = sliced ? (((current_rows - 32'd1) >> slice_shift) + 32'd1) : 32'd1;
    assign reserve_rows = minimum(cfg_slice_rows, current_rows);
    assign ready = phase == IDLE;
    assign done_valid = phase == COMPLETE;

    always_comb begin
        initial_slice_shift = 6'(SHIFT);
        for (int unsigned bit_index=0; bit_index<32-SHIFT; bit_index++)
            if (slice_tiles[bit_index]) initial_slice_shift = 6'(SHIFT+bit_index);
        initial_slice_rows = (slice_tiles == 0) ? (reuse_rows << SHIFT) : (slice_tiles << SHIFT);
        candidate_found = 1'b0;
        candidate_id = '0;
        candidate_init = 1'b0;
        if (phase == OPENING && opened < target) begin
            candidate_found = 1'b1;
            candidate_id = ID_W'(opened);
            candidate_init = 1'b1;
        end else if (phase == DRAINING && protected_valid) begin
            candidate_found = 1'b1;
            candidate_id = protected_id;
        end else if (phase == SWEEPING) begin
            for (int unsigned offset = 0; offset < FRAME_COUNT; offset++) begin
                if (offset < opened) begin
                    if (cursor + offset < opened) begin
                        if (!candidate_found && live[ID_W'(cursor + offset)]) begin
                            candidate_found = 1'b1;
                            candidate_id = ID_W'(cursor + offset);
                        end
                    end else begin
                        if (!candidate_found && live[ID_W'(cursor + offset - opened)]) begin
                            candidate_found = 1'b1;
                            candidate_id = ID_W'(cursor + offset - opened);
                        end
                    end
                end
            end
        end
        command_valid = candidate_found && !command_active;
        frame_id = command_active ? active_id : candidate_id;
        frame_init = command_active ? active_init : candidate_init;
        candidate_row = candidate_init ? row_base + (next_row_part << slice_shift) : frame_row[candidate_id];
        candidate_rows = candidate_init ? minimum(cfg_slice_rows, current_rows - (next_row_part << slice_shift)) : frame_rows[candidate_id];
        p0 = command_active ? active_row : candidate_row;
        rows = command_active ? active_rows : candidate_rows;
        q0 = command_active ? active_q0 :
             candidate_init ? 32'd0 : (frame_k[candidate_id] << SHIFT);
        column0 = command_active ? active_column :
                  candidate_init ? (next_column_tile << SHIFT) : frame_column[candidate_id];
        cols = minimum(32'(SIZE), cfg_stationary - column0);
        count_k = minimum(32'(SIZE), cfg_reduction - q0);
        frame_final = command_active ? active_final : (cfg_reduction - q0 <= 32'(SIZE));
    end

    // Predict the next stationary tile without advancing a frame's K position.
    // The loader verifies the complete descriptor before consuming a prediction.
    always_comb begin : select_lookahead
        logic [FRAME_COUNT-1:0] future_live;
        logic [31:0] search_start, search_count, future_index;
        logic search_frames;
        future_live = live;
        future_live[active_id] = !active_final;
        search_start = 0;
        search_count = opened;
        future_index = 0;
        search_frames = 1'b0;
        lookahead_valid = 1'b0;
        lookahead_q0 = 0;
        lookahead_column = 0;
        lookahead_cols = 0;
        lookahead_count_k = 0;
        if (command_active) begin
            if (phase == OPENING && opened + 1 < target) begin
                lookahead_valid = 1'b1;
                lookahead_q0 = 0;
                lookahead_column = (next_column_tile +
                    ((next_row_part + 1 == group_parts) ? 32'd1 : 32'd0)) << SHIFT;
            end else if (phase == DRAINING && !active_final) begin
                lookahead_valid = 1'b1;
                lookahead_q0 = active_q0 + 32'(SIZE);
                lookahead_column = active_column;
            end else begin
                search_frames = 1'b1;
                if (phase == OPENING) search_count = opened + 1;
                else if (phase == DRAINING) search_start = resume_valid ? 32'(resume_id) : 0;
                else search_start = (32'(active_id) + 1 == opened) ? 0 : 32'(active_id) + 1;
            end
            if (search_frames) begin
                for (int unsigned offset = 0; offset < FRAME_COUNT; offset++) begin
                    future_index = search_start + offset;
                    if (future_index >= search_count) future_index = future_index - search_count;
                    if (offset < search_count && !lookahead_valid && future_live[ID_W'(future_index)]) begin
                        lookahead_valid = 1'b1;
                        lookahead_q0 = (ID_W'(future_index) == active_id) ?
                            active_q0 + 32'(SIZE) : frame_k[ID_W'(future_index)] << SHIFT;
                        lookahead_column = (ID_W'(future_index) == active_id) ?
                            active_column : frame_column[ID_W'(future_index)];
                    end
                end
            end
            if (lookahead_valid) begin
                lookahead_cols = minimum(32'(SIZE), cfg_stationary - lookahead_column);
                lookahead_count_k = minimum(32'(SIZE), cfg_reduction - lookahead_q0);
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase <= IDLE;
            cfg_stream <= '0; cfg_stationary <= '0; cfg_reduction <= '0;
            cfg_rows <= '0; cfg_window <= '0; cfg_slice_rows <= '0;
            slice_shift <= 6'(SHIFT); sliced <= 1'b0;
            row_base <= '0; next_column_tile <= '0; next_row_part <= '0;
            opened <= '0; target <= '0; cursor <= '0;
            live <= '0; protected_valid <= 1'b0; resume_valid <= 1'b0;
            protected_id <= '0; resume_id <= '0;
            command_active <= 1'b0; active_id <= '0;
            active_init <= 1'b0; active_final <= 1'b0;
            active_q0 <= '0; active_column <= '0; active_row <= '0; active_rows <= '0;
            err_code <= '0;

            for (int i = 0; i < FRAME_COUNT; i++) begin
                frame_k[i] <= '0;
                frame_column[i] <= '0;
                frame_row[i] <= '0;
                frame_rows[i] <= '0;
            end
        end else begin
            if (phase == IDLE && start) begin
                cfg_stream <= stream_rows;
                cfg_stationary <= stationary_rows;
                cfg_reduction <= reduction;
                cfg_rows <= reuse_rows << SHIFT;
                cfg_window <= window_frames;
                cfg_slice_rows <= initial_slice_rows;
                slice_shift <= initial_slice_shift;
                sliced <= slice_tiles != 0;
                row_base <= '0; next_column_tile <= '0; next_row_part <= '0;
                opened <= '0; cursor <= '0;
                target <= minimum(window_frames, ((stationary_rows - 32'd1) >> SHIFT) + 32'd1);
                live <= '0; protected_valid <= 1'b0; resume_valid <= 1'b0;
                command_active <= 1'b0;

                if (config_error != 0 || stream_rows == 0 || stationary_rows == 0 || reduction == 0 ||
                    reuse_rows == 0 || (reuse_rows >> (32-SHIFT)) != 0 ||
                    window_frames == 0 || window_frames > 32'(FRAME_COUNT) ||
                    slice_tiles > reuse_rows || (slice_tiles & (slice_tiles - 32'd1)) != 0) begin
                    err_code <= (config_error != 0) ? config_error : 2'b01;
                    phase <= COMPLETE;
                end else begin
                    err_code <= '0;
                    phase <= PREPARING;
                end
            end else if (phase == COMPLETE && done_ready) begin
                phase <= IDLE;
            end else if (command_valid && command_pressure) begin
                if (!frame_final && protected_valid && live[protected_id] && protected_id != candidate_id &&
                    (phase == OPENING || phase == SWEEPING)) begin

                    if (phase == OPENING) begin
                        target <= opened;
                        resume_valid <= 1'b0;
                        cursor <= '0;
                        phase <= SWEEPING;
                    end else begin
                        resume_id <= candidate_id;
                        resume_valid <= 1'b1;
                        phase <= DRAINING;
                    end
                end else begin
                    err_code <= 2'b10;
                    phase <= COMPLETE;
                end
            end else if (command_valid && command_ready) begin
                command_active <= 1'b1;
                active_id <= candidate_id;
                active_init <= candidate_init;
                active_final <= frame_final;
                active_q0 <= q0;
                active_column <= column0;
                active_row <= p0;
                active_rows <= rows;
            end else if (command_active && command_complete) begin
                command_active <= 1'b0;

                if (active_init) begin
                    frame_column[active_id] <= active_column;
                    frame_row[active_id] <= active_row;
                    frame_rows[active_id] <= active_rows;
                    frame_k[active_id] <= 32'd1;
                    opened <= opened + 32'd1;
                    if (next_row_part + 32'd1 == group_parts) begin
                        next_column_tile <= next_column_tile + 32'd1;
                        next_row_part <= '0;
                    end else next_row_part <= next_row_part + 32'd1;
                end else frame_k[active_id] <= frame_k[active_id] + 32'd1;
                live[active_id] <= !active_final;
                if (active_final) begin
                    if (protected_valid && protected_id == active_id) protected_valid <= 1'b0;
                end else begin
                    protected_id <= active_id;
                    protected_valid <= 1'b1;
                end
                if (phase == OPENING && opened + 32'd1 == target) begin
                    phase <= SWEEPING;
                    cursor <= '0;
                end else if (phase == DRAINING && active_final) begin
                    phase <= SWEEPING;
                    cursor <= resume_valid ? 32'(resume_id) : 32'd0;
                    resume_valid <= 1'b0;

                end else if (phase == SWEEPING) begin
                    cursor <= (32'(active_id) + 32'd1 == opened) ? 32'd0 : 32'(active_id) + 32'd1;
                end
            end else if (phase == PREPARING) begin
                target <= minimum(32'(FRAME_COUNT), minimum(cfg_window * group_parts,
                                                           remaining_columns * group_parts - next_row_part));
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

`ifdef NPU_SIM_ASSERT
    initial forever @(posedge clk) if (rst_n) begin
        if (command_complete) assert(command_active);
        if (command_valid && command_ready) begin
            assert(rows != 0 && cols != 0 && count_k != 0);
            assert(q0 < cfg_reduction && column0 < cfg_stationary && p0 < cfg_stream);
        end
    end
`endif
endmodule
