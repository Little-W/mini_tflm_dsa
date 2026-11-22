// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module vector_weight_prefetch_observer #(
    parameter int p_addr_width = 10,
    parameter int p_depth = 49,
    parameter int p_idle = 0,
    parameter int p_check = 0,
    parameter int p_execute = 0,
    parameter int p_output_init = 0,
    parameter int p_tile_init = 0,
    parameter int p_failed = 0
);
    logic [127:0] reference_weight [p_depth];
    logic [15:0] reference_mask [p_depth];
    logic [p_addr_width-1:0] request_tap;
    logic request_valid, clear_previous;
    longint unsigned cached_issues, returned_issues, stalled_cycles, skipped_taps;
    longint unsigned tap_advances, task_starts, failure_cycles, checked_returns;

    wire execute = 32'(vector_engine.state) == p_execute;
    wire clear_context = 32'(vector_engine.state) == p_check ||
        32'(vector_engine.state) == p_output_init || 32'(vector_engine.state) == p_tile_init ||
        32'(vector_engine.state) == p_failed;

`ifdef VECTOR_CHECK_REGISTERED_WRITE
    logic previous_write_valid, previous_write_last_row, previous_write_last_tap;
    logic previous_write_published;
    logic [p_addr_width-1:0] previous_write_address;
    logic [127:0] previous_write_data;
    logic [15:0] previous_write_mask;
    longint unsigned writes_captured, writes_published, writes_cancelled;
    longint unsigned writes_consecutive, last_rows_published, last_taps_published;
    wire write_cancel = vector_engine.i_storage_error ||
        32'(vector_engine.state) == p_failed;
    wire write_capture = vector_engine.u_operand_store.weights_i_wr_en &&
        (|vector_engine.u_operand_store.weights_i_wr_mask) && !write_cancel;

    // 从 DMA 接收端独立保存事务，检查共享 RAM 接口恰好延后一拍发布。
    // 逐拍比较全部负载，并分别统计连续写入、每行末拍和最后一个卷积核位置。
    always @(posedge vector_engine.clk) begin
        if (!vector_engine.rst_n) begin
            previous_write_valid <= 1'b0;
            previous_write_last_row <= 1'b0;
            previous_write_last_tap <= 1'b0;
            previous_write_published <= 1'b0;
            writes_captured <= 0;
            writes_published <= 0;
            writes_cancelled <= 0;
            writes_consecutive <= 0;
            last_rows_published <= 0;
            last_taps_published <= 0;
        end else begin
            assert(vector_engine.o_weight_write_en === (previous_write_valid && !write_cancel));
            if (vector_engine.o_weight_write_en) begin
                assert(vector_engine.o_weight_write_addr === previous_write_address);
                assert(vector_engine.o_weight_write_data === previous_write_data);
                assert(vector_engine.o_weight_write_mask === previous_write_mask);
                writes_published <= writes_published + 1;
                if (previous_write_published) writes_consecutive <= writes_consecutive + 1;
                if (previous_write_last_row) last_rows_published <= last_rows_published + 1;
                if (previous_write_last_tap) last_taps_published <= last_taps_published + 1;
            end
            if (previous_write_valid && write_cancel) writes_cancelled <= writes_cancelled + 1;
            if (vector_engine.ready || vector_engine.done_valid) assert(!previous_write_valid);
            previous_write_published <= vector_engine.o_weight_write_en;
            previous_write_valid <= write_capture;
            if (write_capture) begin
                previous_write_address <= p_addr_width'(vector_engine.u_operand_store.weights_i_wr_tap);
                previous_write_data <= 128'(vector_engine.u_operand_store.weights_i_wr_data);
                previous_write_mask <= 16'(vector_engine.u_operand_store.weights_i_wr_mask);
                previous_write_last_row <= vector_engine.weight_row_last_fire;
                previous_write_last_tap <= vector_engine.weight_row_last_fire &&
                    vector_engine.u_operand_store.weights_i_wr_tap + 32'd1 == 32'(vector_engine.taps);
                writes_captured <= writes_captured + 1;
            end
        end
    end
    final begin
        assert(writes_captured == writes_published + writes_cancelled);
        assert(writes_published != 0 && last_rows_published != 0 && last_taps_published != 0);
        $display("VECTOR_WEIGHT_WRITE_STAGE_PASS captured=%0d published=%0d cancelled=%0d consecutive=%0d last_rows=%0d last_taps=%0d",
            writes_captured, writes_published, writes_cancelled, writes_consecutive,
            last_rows_published, last_taps_published);
    end
`endif

    // 独立记录实际 RAM 端口请求以及写入内容，检查返回行与缓存行的数据来源。
    always @(posedge vector_engine.clk) begin
        if (!vector_engine.rst_n) begin
            request_valid <= 1'b0;
            clear_previous <= 1'b0;
            cached_issues <= 0;
            returned_issues <= 0;
            stalled_cycles <= 0;
            skipped_taps <= 0;
            tap_advances <= 0;
            task_starts <= 0;
            failure_cycles <= 0;
            checked_returns <= 0;
            for (int row = 0; row < p_depth; row++) reference_mask[row] <= '0;
        end else begin
            request_valid <= vector_engine.o_weight_read_en;
            if (vector_engine.o_weight_read_en) request_tap <= vector_engine.o_weight_read_addr;
            clear_previous <= clear_context;
            if (clear_previous) assert(!vector_engine.u_operand_store.g_shared_weights.saved_valid);

            assert(!(vector_engine.o_weight_read_en && vector_engine.o_weight_write_en &&
                (|vector_engine.o_weight_write_mask)));
            if (vector_engine.i_weight_read_valid) begin
                assert(request_valid);
                assert(vector_engine.u_operand_store.g_shared_weights.return_tap == request_tap);
                assert(int'(request_tap) < p_depth);
                for (int lane = 0; lane < 16; lane++) begin
                    if (reference_mask[request_tap][lane]) begin
                        assert(vector_engine.i_weight_read_data[8*lane +: 8] ===
                            reference_weight[request_tap][8*lane +: 8]);
                    end
                end
                checked_returns <= checked_returns + 1;
            end
            if (vector_engine.u_operand_store.g_shared_weights.saved_valid) begin
                assert(int'(vector_engine.u_operand_store.g_shared_weights.saved_tap) < p_depth);
                for (int lane = 0; lane < 16; lane++) begin
                    if (reference_mask[vector_engine.u_operand_store.g_shared_weights.saved_tap][lane]) begin
                        assert(vector_engine.u_operand_store.g_shared_weights.saved_data[8*lane +: 8] ===
                            reference_weight[vector_engine.u_operand_store.g_shared_weights.saved_tap][8*lane +: 8]);
                    end
                end
            end

            if (execute) begin
                assert(vector_engine.dw_in_bounds == (vector_engine.u_invariants.input_column_in_bounds && vector_engine.u_address.input_row_in_bounds));
                if (!vector_engine.i_storage_error) assert(vector_engine.weight_data_ready);
                if (vector_engine.dw_in_bounds && !vector_engine.input_ready[vector_engine.read_bank])
                    stalled_cycles <= stalled_cycles + 1;
                if (!vector_engine.dw_in_bounds && vector_engine.dw_tap_advance)
                    skipped_taps <= skipped_taps + 1;
                if (vector_engine.dw_tap_advance) tap_advances <= tap_advances + 1;
            end
            if (vector_engine.dw_issue_fire) begin
                assert(vector_engine.weight_data_ready);
                assert((vector_engine.u_operand_store.g_shared_weights.return_matches ?
                    vector_engine.u_operand_store.g_shared_weights.return_tap : vector_engine.u_operand_store.g_shared_weights.saved_tap) ==
                    p_addr_width'(vector_engine.tap));
                if (vector_engine.u_operand_store.g_shared_weights.return_matches)
                    returned_issues <= returned_issues + 1;
                else begin
                    assert(vector_engine.u_operand_store.g_shared_weights.saved_matches);
                    cached_issues <= cached_issues + 1;
                end
            end
            if (32'(vector_engine.state) == p_idle && vector_engine.start) task_starts <= task_starts + 1;
            if (32'(vector_engine.state) == p_failed) failure_cycles <= failure_cycles + 1;

            if (vector_engine.o_weight_write_en) begin
                assert(int'(vector_engine.o_weight_write_addr) < p_depth);
                for (int lane = 0; lane < 16; lane++) begin
                    if (vector_engine.o_weight_write_mask[lane]) begin
                        reference_weight[vector_engine.o_weight_write_addr][8*lane +: 8] <=
                            vector_engine.o_weight_write_data[8*lane +: 8];
                        reference_mask[vector_engine.o_weight_write_addr][lane] <= 1'b1;
                    end
                end
            end
        end
    end
    final begin
        assert(cached_issues != 0 && returned_issues != 0 && stalled_cycles != 0);
        assert(skipped_taps != 0 && tap_advances != 0 && task_starts > 1 && failure_cycles != 0);
        $display("VECTOR_WEIGHT_PREFETCH_PASS cached_issues=%0d returned_issues=%0d stalled_cycles=%0d skipped_taps=%0d tap_advances=%0d task_starts=%0d failure_cycles=%0d checked_returns=%0d",
            cached_issues, returned_issues, stalled_cycles, skipped_taps, tap_advances,
            task_starts, failure_cycles, checked_returns);
    end
endmodule

bind vector_engine vector_weight_prefetch_observer #(
    .p_addr_width(SHARED_STORAGE_ADDR_WIDTH), .p_depth(MAX_TAPS),
    .p_idle(32'(IDLE)), .p_check(32'(CHECK)), .p_execute(32'(DW_EXECUTE)), .p_output_init(32'(OUTPUT_INIT)),
    .p_tile_init(32'(TILE_INIT)), .p_failed(32'(FAILED))
) tb_weight_prefetch_observer();
/* verilator lint_on DECLFILENAME */
`endif
