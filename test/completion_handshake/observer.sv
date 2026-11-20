// SPDX-License-Identifier: Apache-2.0
module npu_completion_observer #(
    parameter int unsigned OPERAND_CACHE_ENABLE = 0
) (
    input logic clk,
    input logic rst_n,
    input logic calc_start,
    input logic sa_ready,
    input logic done_valid,
    input logic done_ready,
    input logic [1:0] err_code,
    input logic cfg_conv_enable,
    input logic run_vector,
    input logic frame_mode,
    input logic [3:0] controller_state,
    input logic dma_idle,
    input logic conv_busy,
    input logic operand_cache_idle,
    input logic frame_prefetch_idle
);
    localparam logic [3:0] WAIT_DONE = 4'b0111;
    int unsigned tasks_started, tasks_completed;
    int unsigned gemm_completed, conv_completed;
    int unsigned job_done_count, completion_backpressure_cycles;
    logic task_active, task_is_conv, wait_done_seen;
    logic held_valid;
    logic [1:0] held_error;

    initial begin
        assert (OPERAND_CACHE_ENABLE == 0)
            else $fatal(1, "completion test requires the default operand cache configuration");
    end

    // 每个任务独立记录一次完成接收，后续持续就绪周期不得产生新的完成。
    always @(posedge clk) begin
        if (!rst_n) begin
            tasks_started <= 0;
            tasks_completed <= 0;
            gemm_completed <= 0;
            conv_completed <= 0;
            job_done_count <= 0;
            completion_backpressure_cycles <= 0;
            task_active <= 1'b0;
            task_is_conv <= 1'b0;
            wait_done_seen <= 1'b0;
            held_valid <= 1'b0;
            held_error <= '0;
        end else begin
            if (held_valid) begin
                assert (done_valid && err_code == held_error)
                    else $fatal(1, "completion changed while its receiver was stalled");
            end
            held_valid <= done_valid && !done_ready;
            held_error <= err_code;

            if (calc_start && sa_ready) begin
                assert (!task_active)
                    else $fatal(1, "new task accepted before prior completion");
                tasks_started <= tasks_started + 1;
                task_active <= 1'b1;
                task_is_conv <= cfg_conv_enable;
                job_done_count <= 0;
                wait_done_seen <= 1'b0;
            end
            if (task_active && !frame_mode && controller_state == WAIT_DONE && !done_ready)
                wait_done_seen <= 1'b1;
            if (done_valid) begin
                assert (task_active && !run_vector && !frame_mode)
                    else $fatal(1, "completion has no active ordinary task");
                assert (dma_idle && !conv_busy && operand_cache_idle && frame_prefetch_idle)
                    else $fatal(1, "completion preceded physical transaction drain");
                if (!done_ready)
                    completion_backpressure_cycles <= completion_backpressure_cycles + 1;
                else begin
                    assert (wait_done_seen && controller_state == WAIT_DONE && job_done_count == 0)
                        else $fatal(1, "completion was duplicated or did not wait for the receiver");
                    assert (err_code == 0)
                        else $fatal(1, "ordinary completion test returned an error");
                    job_done_count <= job_done_count + 1;
                    tasks_completed <= tasks_completed + 1;
                    task_active <= 1'b0;
                    if (task_is_conv) conv_completed <= conv_completed + 1;
                    else gemm_completed <= gemm_completed + 1;
                end
            end
        end
    end
endmodule

bind npu_top npu_completion_observer #(
    .OPERAND_CACHE_ENABLE(OPERAND_CACHE_ENABLE)
) tb_completion (
    .clk, .rst_n, .calc_start, .sa_ready, .done_valid, .done_ready, .err_code,
    .cfg_conv_enable, .run_vector, .frame_mode(frame_mode_q),
    .controller_state(u_npu_controller.current_state),
    .dma_idle, .conv_busy, .operand_cache_idle, .frame_prefetch_idle
);
