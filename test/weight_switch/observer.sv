`timescale 1ns/1ps

// Passive counters use the input and output row tags independently of PS commands.
module weight_switch_observer #(
    parameter integer SIZE = 16
) (
    input wire clk, rst_n, core_rst_n, new_job,
    input wire calc_start, sa_ready, done_valid,
    input wire [1:0] err_code,
    input wire [63:0] cycle,
    input wire weight_commit, store_weight_req, send_ia_trigger,
    input wire ia_row_valid, ia_sending_done, output_row_valid, output_group_end,
    input wire [SIZE-1:0] row_valid_pipe, row_weight_select,
    input wire direct_final_stream, fifo_full, final_output_pending,
    input wire [31:0] fifo_used_banks, fifo_banks, compute_tail_count,
    input wire partial_sum_calc_over, controller_init,
    input wire s8_valid, s8_blocked, s16_valid, s16_blocked,
    input wire awvalid, awready, wvalid, wready
);
    integer task_id = 0;
    bit active = 0, first_input_pending = 0;
    longint unsigned start_cycle = 0;
    integer commits = 0, commits_with_rows = 0, loads_with_rows = 0;
    integer groups = 0, input_ends = 0, output_ends = 0;
    integer input_rows = 0, output_rows = 0;
    integer trigger_overlap = 0, first_input_overlap = 0;
    integer max_pending_groups = 0, max_array_rows = 0;
    integer mixed_select_cycles = 0, direct_cycles = 0;
    integer fifo_wait_cycles = 0, max_fifo_banks = 0;
    integer aw_wait_cycles = 0, w_wait_cycles = 0;
    integer between_groups_cycles = 0;
    integer last_group_end = -1;
    integer expected_tail_count = 0, maximum_tail_count = 0;
    integer simultaneous_start_finish = 0, tail_count_checks = 0;
    integer event_file = 0;
    string event_path;

    initial if ($value$plusargs("WEIGHT_SWITCH_EVENTS=%s", event_path)) begin
        event_file = $fopen(event_path, "w");
        assert (event_file != 0) else $fatal(1, "Cannot open weight-switch events");
        $fdisplay(event_file, "H version=1 size=%0d fifo_banks=%0d", SIZE, fifo_banks);
    end

    always @(posedge clk) begin
        if (!rst_n || new_job) begin
            active = 0;
            first_input_pending = 0;
            commits = 0; commits_with_rows = 0; loads_with_rows = 0;
            groups = 0; input_ends = 0; output_ends = 0;
            input_rows = 0; output_rows = 0;
            trigger_overlap = 0; first_input_overlap = 0;
            max_pending_groups = 0; max_array_rows = 0;
            mixed_select_cycles = 0; direct_cycles = 0;
            fifo_wait_cycles = 0; max_fifo_banks = 0;
            aw_wait_cycles = 0; w_wait_cycles = 0;
            between_groups_cycles = 0; last_group_end = -1;
            expected_tail_count = 0; maximum_tail_count = 0;
            simultaneous_start_finish = 0; tail_count_checks = 0;
        end else begin
            if (calc_start && sa_ready) begin
                active = 1;
                start_cycle = cycle;
            end
            if (active && core_rst_n) begin
                assert (int'(compute_tail_count) == expected_tail_count)
                    else $fatal(1, "The controller must retain every outstanding output group");
                tail_count_checks++;
                if (int'(compute_tail_count) > maximum_tail_count)
                    maximum_tail_count = int'(compute_tail_count);
                if (send_ia_trigger && partial_sum_calc_over) simultaneous_start_finish++;
                if (controller_init) expected_tail_count = 0;
                else expected_tail_count += int'(send_ia_trigger) -
                    int'((compute_tail_count != 0) && partial_sum_calc_over);
                if (weight_commit) begin
                    commits++;
                    if (|row_valid_pipe) commits_with_rows++;
                    if (event_file) $fdisplay(event_file,
                        "C task=%0d cycle=%0d valid=%0h select=%0h", task_id,
                        cycle, row_valid_pipe, row_weight_select);
                end
                if (store_weight_req && |row_valid_pipe) loads_with_rows++;
                if (send_ia_trigger) begin
                    assert (!first_input_pending && groups == input_ends)
                        else $fatal(1, "An IA group starts before the preceding input group ends");
                    first_input_pending = 1;
                    groups++;
                    if (|row_valid_pipe) trigger_overlap++;
                    if (event_file) $fdisplay(event_file,
                        "S task=%0d cycle=%0d group=%0d valid=%0h direct=%0d", task_id,
                        cycle, groups, row_valid_pipe, direct_final_stream);
                end
                if (ia_row_valid) begin
                    input_rows++;
                    if (first_input_pending) begin
                        first_input_pending = 0;
                        if (|row_valid_pipe) begin
                            first_input_overlap++;
                            assert (direct_final_stream)
                                else $fatal(1, "IA overlaps an output group with dependent PS or parameters");
                        end
                        if (last_group_end >= 0)
                            between_groups_cycles += int'(cycle) - last_group_end - 1;
                        if (event_file) $fdisplay(event_file,
                            "I task=%0d cycle=%0d group=%0d valid=%0h", task_id,
                            cycle, groups, row_valid_pipe);
                    end
                end
                if (ia_sending_done) begin
                    assert (ia_row_valid) else $fatal(1, "Input end requires a valid row");
                    input_ends++;
                    last_group_end = int'(cycle);
                    if (event_file) $fdisplay(event_file,
                        "L task=%0d cycle=%0d group=%0d", task_id, cycle, input_ends);
                end
                if (output_row_valid) output_rows++;
                if (output_group_end) begin
                    assert (output_row_valid) else $fatal(1, "Output end requires a valid row");
                    output_ends++;
                    if (event_file) $fdisplay(event_file,
                        "E task=%0d cycle=%0d group=%0d", task_id, cycle, output_ends);
                end
                assert (groups >= input_ends && input_ends >= output_ends)
                    else $fatal(1, "Input and output group counts differ");
                if (groups - output_ends > max_pending_groups)
                    max_pending_groups = groups - output_ends;
                if ($countones(row_valid_pipe) > max_array_rows)
                    max_array_rows = $countones(row_valid_pipe);
                if ((|(row_valid_pipe & row_weight_select)) && (|(row_valid_pipe & ~row_weight_select)))
                    mixed_select_cycles++;
                if (direct_final_stream) direct_cycles++;
                if (fifo_full && final_output_pending) fifo_wait_cycles++;
                if (int'(fifo_used_banks) > max_fifo_banks)
                    max_fifo_banks = int'(fifo_used_banks);
                assert (!s8_valid || !s8_blocked)
                    else $fatal(1, "Every S8 output row requires a writable FIFO bank");
                assert (!s16_valid || !s16_blocked)
                    else $fatal(1, "Every S16 output row requires a writable FIFO bank");
                if (awvalid && !awready) aw_wait_cycles++;
                if (wvalid && !wready) w_wait_cycles++;
            end
            if (!core_rst_n) expected_tail_count = 0;
            if (active && done_valid) begin
                if (err_code == 0) assert (!first_input_pending && groups == input_ends &&
                        groups == output_ends && input_rows == output_rows)
                    else $fatal(1, "The completed task retains unfinished rows or groups");
                $display("WEIGHT_SWITCH_TASK task=%0d cycles=%0d commits=%0d commits_with_rows=%0d loads_with_rows=%0d groups=%0d input_rows=%0d output_rows=%0d trigger_overlap=%0d first_input_overlap=%0d max_pending_groups=%0d max_array_rows=%0d mixed_select_cycles=%0d direct_cycles=%0d fifo_wait_cycles=%0d max_fifo_banks=%0d aw_wait_cycles=%0d w_wait_cycles=%0d between_groups_cycles=%0d maximum_tail_count=%0d simultaneous_start_finish=%0d tail_count_checks=%0d",
                    task_id, cycle-start_cycle, commits, commits_with_rows,
                    loads_with_rows, groups, input_rows, output_rows, trigger_overlap,
                    first_input_overlap, max_pending_groups, max_array_rows,
                    mixed_select_cycles, direct_cycles, fifo_wait_cycles, max_fifo_banks,
                    aw_wait_cycles, w_wait_cycles, between_groups_cycles,
                    maximum_tail_count, simultaneous_start_finish, tail_count_checks);
                task_id++;
                active = 0;
            end
        end
    end

    final if (event_file) $fclose(event_file);
endmodule

bind tb_conv_npu weight_switch_observer #(
    .SIZE(SIZE)
) u_weight_switch_observer (
    .clk(clk), .rst_n(rst_n), .core_rst_n(u_dut.core_rst_n), .new_job(new_job),
    .calc_start(calc_start), .sa_ready(sa_ready), .done_valid(done_valid), .cycle(cycle),
    .err_code(err_code),
    .weight_commit(u_dut.weight_commit), .store_weight_req(u_dut.store_weight_req),
    .send_ia_trigger(u_dut.send_ia_trigger), .ia_row_valid(u_dut.ia_row_valid),
    .ia_sending_done(u_dut.ia_sending_done),
    .output_row_valid(u_dut.u_compute_core.ps_stream_valid_d),
    .output_group_end(u_dut.u_compute_core.ps_group_switch_d),
    .row_valid_pipe(u_dut.u_compute_core.row_valid_pipe),
`ifdef TB_WEIGHT_SELECT_WAVE
    .row_weight_select(u_dut.u_compute_core.u_systolic_array.row_weight_select),
    .direct_final_stream(u_dut.direct_final_stream),
    .compute_tail_count(32'(u_dut.u_npu_controller.compute_tail_count)),
`else
    .row_weight_select('0), .direct_final_stream(1'b0),
    .compute_tail_count(32'(u_dut.u_npu_controller.compute_tail_pending)),
`endif
    .partial_sum_calc_over(u_dut.partial_sum_calc_over),
    .controller_init(u_dut.u_npu_controller.current_state == 1),
    .fifo_full(u_dut.fifo_full_flag), .final_output_pending(u_dut.ia_output_pending),
    .fifo_banks(32'(u_dut.OA_FIFO_BANKS)),
    .fifo_used_banks(32'(u_dut.u_vec_s8_to_fifo.g_full.u_full.used_bank_count)),
    .s8_valid(u_dut.u_vec_s8_to_fifo.in_valid),
    .s8_blocked(u_dut.u_vec_s8_to_fifo.g_full.u_full.write_bank_blocked),
    .s16_valid(u_dut.u_vec_s16_to_fifo.in_valid),
    .s16_blocked(u_dut.u_vec_s16_to_fifo.write_bank_blocked),
    .awvalid(awvalid), .awready(awready), .wvalid(wvalid), .wready(wready)
);
