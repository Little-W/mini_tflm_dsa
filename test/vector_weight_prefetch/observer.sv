// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module vector_weight_prefetch_observer #(
    parameter int p_addr_width = 10,
    parameter int p_depth = 49,
    parameter int p_idle = 0,
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
    wire clear_context = (32'(vector_engine.state) == p_idle && vector_engine.start) ||
        32'(vector_engine.state) == p_output_init || 32'(vector_engine.state) == p_tile_init ||
        32'(vector_engine.state) == p_failed;

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
            if (clear_previous) assert(!vector_engine.g_shared_weights.saved_valid);

            assert(!(vector_engine.o_weight_read_en && vector_engine.o_weight_write_en &&
                (|vector_engine.o_weight_write_mask)));
            if (vector_engine.i_weight_read_valid) begin
                assert(request_valid);
                assert(vector_engine.g_shared_weights.return_tap == request_tap);
                assert(int'(request_tap) < p_depth);
                for (int lane = 0; lane < 16; lane++) begin
                    if (reference_mask[request_tap][lane]) begin
                        assert(vector_engine.i_weight_read_data[8*lane +: 8] ===
                            reference_weight[request_tap][8*lane +: 8]);
                    end
                end
                checked_returns <= checked_returns + 1;
            end
            if (vector_engine.g_shared_weights.saved_valid) begin
                assert(int'(vector_engine.g_shared_weights.saved_tap) < p_depth);
                for (int lane = 0; lane < 16; lane++) begin
                    if (reference_mask[vector_engine.g_shared_weights.saved_tap][lane]) begin
                        assert(vector_engine.g_shared_weights.saved_data[8*lane +: 8] ===
                            reference_weight[vector_engine.g_shared_weights.saved_tap][8*lane +: 8]);
                    end
                end
            end

            if (execute) begin
                assert(vector_engine.dw_in_bounds == vector_engine.in_bounds);
                if (!vector_engine.i_storage_error) assert(vector_engine.weight_data_ready);
                if (vector_engine.dw_in_bounds && !vector_engine.input_ready[vector_engine.read_bank])
                    stalled_cycles <= stalled_cycles + 1;
                if (!vector_engine.dw_in_bounds && vector_engine.dw_tap_advance)
                    skipped_taps <= skipped_taps + 1;
                if (vector_engine.dw_tap_advance) tap_advances <= tap_advances + 1;
            end
            if (vector_engine.dw_issue_fire) begin
                assert(vector_engine.weight_data_ready);
                assert(vector_engine.weight_data_tap == p_addr_width'(vector_engine.tap));
                if (vector_engine.g_shared_weights.return_matches)
                    returned_issues <= returned_issues + 1;
                else begin
                    assert(vector_engine.g_shared_weights.saved_matches);
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
    .p_idle(32'(IDLE)), .p_execute(32'(DW_EXECUTE)), .p_output_init(32'(OUTPUT_INIT)),
    .p_tile_init(32'(TILE_INIT)), .p_failed(32'(FAILED))
) tb_weight_prefetch_observer();
/* verilator lint_on DECLFILENAME */
`endif
